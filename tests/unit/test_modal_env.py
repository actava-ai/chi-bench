import asyncio
import logging
import shutil
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from harbor.environments.base import ExecResult
from harbor.models.task.config import NetworkMode, NetworkPolicy, TaskConfig
from harbor.models.trial.paths import TrialPaths

import chi_bench.experiment.modal_env as modal_env
from chi_bench.experiment.modal_env import ChiBenchModalEnvironment
from chi_bench.experiment.docker_env import ChiBenchDockerEnvironment


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "allow_internet",
    [True, False],
)
async def test_create_sandbox_uses_harbor_migrated_network_policy(
    monkeypatch,
    tmp_path,
    allow_internet,
):
    with pytest.warns(DeprecationWarning, match="'allow_internet' field is deprecated"):
        task_config = TaskConfig.model_validate({"environment": {"allow_internet": allow_internet}})
    assert task_config.environment.allow_internet is None

    environment_dir = tmp_path / "environment"
    environment_dir.mkdir()
    (environment_dir / "docker-compose.yaml").touch()
    environment = ChiBenchModalEnvironment(
        environment_dir=environment_dir,
        environment_name="task",
        session_id="task__trial__env",
        trial_paths=TrialPaths(tmp_path / "trial"),
        task_env_config=task_config.environment,
        network_policy=task_config.environment.resolve_baseline(),
    )
    assert isinstance(environment, ChiBenchDockerEnvironment)
    assert environment._uses_host_network is True
    assert environment.capabilities.disable_internet is True
    assert environment.capabilities.network_allowlist is False
    assert environment.capabilities.dynamic_network_policy is False

    app = object()
    environment._app = app
    environment._image = object()

    create_kwargs = {}
    sandbox = object()

    class FakeCreate:
        @staticmethod
        async def aio(**kwargs):
            create_kwargs.update(kwargs)
            return sandbox

    class FakeSandbox:
        create = FakeCreate()

    monkeypatch.setattr(modal_env, "Sandbox", FakeSandbox)
    monkeypatch.setattr(modal_env, "_collect_forwarded_env", lambda: {})
    monkeypatch.setattr(modal_env, "_register_sandbox", lambda _sandbox: None)

    result = await environment._create_sandbox(
        gpu_config=None,
        secrets_config=[],
        volumes_config={},
    )

    assert result is sandbox
    assert create_kwargs["app"] is app
    # The trusted outer daemon needs registry access to build both images.
    # The inner server and agent enforce the requested Harbor network policy.
    assert create_kwargs["block_network"] is False
    assert create_kwargs["experimental_options"] == {"enable_docker": True}


def test_constructor_rejects_unsupported_network_allowlist(tmp_path):
    environment_dir = tmp_path / "environment"
    environment_dir.mkdir()
    (environment_dir / "docker-compose.yaml").touch()

    with pytest.raises(ValueError, match="network_mode='allowlist' is not supported"):
        ChiBenchModalEnvironment(
            environment_dir=environment_dir,
            environment_name="task",
            session_id="task__trial__env",
            trial_paths=TrialPaths(tmp_path / "trial"),
            task_env_config=TaskConfig().environment,
            network_policy=NetworkPolicy(
                network_mode=NetworkMode.ALLOWLIST,
                allowed_hosts=["api.anthropic.com"],
            ),
        )


@pytest.mark.asyncio
async def test_runtime_network_policy_change_fails_closed(tmp_path):
    environment_dir = tmp_path / "environment"
    environment_dir.mkdir()
    (environment_dir / "docker-compose.yaml").touch()
    environment = ChiBenchModalEnvironment(
        environment_dir=environment_dir,
        environment_name="task",
        session_id="task__trial__env",
        trial_paths=TrialPaths(tmp_path / "trial"),
        task_env_config=TaskConfig().environment,
        network_policy=NetworkPolicy(network_mode=NetworkMode.PUBLIC),
    )

    with pytest.raises(ValueError, match="cannot change network policy after start"):
        await environment.set_network_policy(NetworkPolicy(network_mode=NetworkMode.NO_NETWORK))


def make_environment(tmp_path, **kwargs):
    environment_dir = tmp_path / "environment"
    environment_dir.mkdir()
    return ChiBenchModalEnvironment(
        environment_dir=environment_dir,
        environment_name="task",
        session_id="task__trial__env",
        trial_paths=TrialPaths(tmp_path / "trial"),
        task_env_config=TaskConfig().environment,
        network_policy=NetworkPolicy(network_mode=NetworkMode.PUBLIC),
        host_env={},
        **kwargs,
    )


def fake_sandbox():
    return SimpleNamespace(
        terminate=SimpleNamespace(aio=AsyncMock()),
        filesystem=SimpleNamespace(
            copy_from_local=SimpleNamespace(aio=AsyncMock()),
            copy_to_local=SimpleNamespace(aio=AsyncMock()),
        ),
    )


def install_modal_fakes(monkeypatch, sandbox):
    image_calls = []
    image = SimpleNamespace()

    def run_commands(*commands):
        image_calls.extend(commands)
        return image

    image.run_commands = run_commands

    def from_registry(name):
        image_calls.append(name)
        return image

    monkeypatch.setattr(modal_env, "Image", SimpleNamespace(from_registry=from_registry))
    app = object()
    monkeypatch.setattr(
        modal_env, "App", SimpleNamespace(lookup=SimpleNamespace(aio=AsyncMock(return_value=app)))
    )
    create = AsyncMock(return_value=sandbox)
    monkeypatch.setattr(modal_env, "Sandbox", SimpleNamespace(create=SimpleNamespace(aio=create)))
    registered = []
    unregistered = []
    monkeypatch.setattr(modal_env, "_register_sandbox", registered.append)
    monkeypatch.setattr(modal_env, "_unregister_sandbox", unregistered.append)
    return create, image_calls, registered, unregistered


@pytest.mark.asyncio
async def test_start_inherits_dockerd_entrypoint_and_rebuilds_in_fresh_daemon(
    monkeypatch, tmp_path
):
    environment = make_environment(tmp_path)
    sandbox = fake_sandbox()
    create, image_calls, registered, _ = install_modal_fakes(monkeypatch, sandbox)
    base_start = AsyncMock()
    monkeypatch.setattr(ChiBenchDockerEnvironment, "start", base_start)
    environment._wait_for_docker_ready = AsyncMock()

    await environment.start(force_build=False)

    args, kwargs = create.call_args
    assert args == ()
    assert kwargs["timeout"] == 86400
    assert kwargs["block_network"] is False
    assert kwargs["experimental_options"] == {"enable_docker": True}
    assert not kwargs.get("env")
    assert "docker:28.3.3-dind" in image_calls
    assert "iptables" in " ".join(image_calls)
    assert '"bridge":"none"' in " ".join(image_calls)
    assert registered == [sandbox]
    environment._wait_for_docker_ready.assert_awaited_once()
    base_start.assert_awaited_once_with(force_build=True)


@pytest.mark.asyncio
async def test_start_honors_explicit_outer_sandbox_timeout(monkeypatch, tmp_path):
    environment = make_environment(tmp_path, sandbox_timeout_secs=7200)
    create, _, _, _ = install_modal_fakes(monkeypatch, fake_sandbox())
    monkeypatch.setattr(ChiBenchDockerEnvironment, "start", AsyncMock())
    environment._wait_for_docker_ready = AsyncMock()
    await environment.start(force_build=False)
    assert create.call_args.kwargs["timeout"] == 7200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [RuntimeError("inner startup failed"), asyncio.CancelledError()]
)
async def test_start_failure_terminates_outer_sandbox(monkeypatch, tmp_path, failure):
    environment = make_environment(tmp_path)
    sandbox = fake_sandbox()
    _, _, _, unregistered = install_modal_fakes(monkeypatch, sandbox)
    monkeypatch.setattr(ChiBenchDockerEnvironment, "start", AsyncMock(side_effect=failure))
    base_stop = AsyncMock()
    monkeypatch.setattr(ChiBenchDockerEnvironment, "stop", base_stop)
    environment._wait_for_docker_ready = AsyncMock()

    with pytest.raises(type(failure)):
        await environment.start(force_build=False)

    base_stop.assert_awaited_once_with(delete=True)
    sandbox.terminate.aio.assert_awaited_once()
    assert unregistered == [sandbox]
    assert environment._sandbox is None


@pytest.mark.asyncio
async def test_stop_terminates_outer_sandbox_even_if_inner_cleanup_fails(monkeypatch, tmp_path):
    environment = make_environment(tmp_path)
    sandbox = fake_sandbox()
    environment._sandbox = sandbox
    monkeypatch.setattr(
        ChiBenchDockerEnvironment, "stop", AsyncMock(side_effect=RuntimeError("inner"))
    )
    unregistered = []
    monkeypatch.setattr(modal_env, "_unregister_sandbox", unregistered.append)

    with pytest.raises(RuntimeError, match="inner"):
        await environment.stop(delete=True)

    sandbox.terminate.aio.assert_awaited_once()
    assert unregistered == [sandbox]
    assert environment._sandbox is None


@pytest.mark.asyncio
async def test_failed_outer_termination_keeps_orphan_cleanup_registration(monkeypatch, tmp_path):
    environment = make_environment(tmp_path)
    sandbox = fake_sandbox()
    sandbox.terminate.aio.side_effect = RuntimeError("outer termination failed")
    environment._sandbox = sandbox
    monkeypatch.setattr(ChiBenchDockerEnvironment, "stop", AsyncMock())
    unregister = Mock()
    monkeypatch.setattr(modal_env, "_unregister_sandbox", unregister)

    with pytest.raises(RuntimeError, match="outer termination failed"):
        await environment.stop(delete=True)

    unregister.assert_not_called()
    assert environment._sandbox is sandbox


@pytest.mark.asyncio
async def test_run_passes_credentials_through_sdk_environment_only(monkeypatch, tmp_path, caplog):
    environment = make_environment(tmp_path)
    process = SimpleNamespace(
        stdout=SimpleNamespace(read=SimpleNamespace(aio=AsyncMock(return_value="output"))),
        stderr=SimpleNamespace(read=SimpleNamespace(aio=AsyncMock(return_value="error"))),
        wait=SimpleNamespace(aio=AsyncMock(return_value=7)),
    )
    execute = AsyncMock(return_value=process)
    environment._sandbox = SimpleNamespace(exec=SimpleNamespace(aio=execute))
    secret = "synthetic-secret-do-not-log"

    with caplog.at_level(logging.DEBUG):
        result = await environment._run(
            ["docker", "exec", "agent", "true"], timeout_sec=13, env={"KEY": secret}
        )

    assert execute.call_args.args == ("docker", "exec", "agent", "true")
    assert execute.call_args.kwargs["env"] == {"KEY": secret}
    assert execute.call_args.kwargs["timeout"] == 13
    assert result == ExecResult(stdout="output", stderr="error", return_code=7)
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_run_reports_transport_timeout_without_exposing_argv(tmp_path):
    environment = make_environment(tmp_path)
    environment._sandbox = SimpleNamespace(
        exec=SimpleNamespace(aio=AsyncMock(side_effect=TimeoutError("sensitive command")))
    )
    result = await environment._run(["docker", "info"], timeout_sec=1)
    assert result.return_code == 124
    assert "sensitive command" not in result.stderr


@pytest.mark.asyncio
async def test_daemon_readiness_failure_fails_before_inner_start(monkeypatch, tmp_path):
    environment = make_environment(tmp_path)
    sandbox = fake_sandbox()
    install_modal_fakes(monkeypatch, sandbox)
    environment._wait_for_docker_ready = AsyncMock(side_effect=RuntimeError("daemon not ready"))
    base_start = AsyncMock()
    monkeypatch.setattr(ChiBenchDockerEnvironment, "start", base_start)
    monkeypatch.setattr(ChiBenchDockerEnvironment, "stop", AsyncMock())

    with pytest.raises(RuntimeError, match="daemon not ready"):
        await environment.start(force_build=False)

    base_start.assert_not_called()
    sandbox.terminate.aio.assert_awaited_once()


@pytest.mark.asyncio
async def test_file_upload_stages_in_outer_then_copies_to_selected_inner_container(tmp_path):
    environment = make_environment(tmp_path)
    sandbox = fake_sandbox()
    environment._sandbox = sandbox
    environment._run = AsyncMock(return_value=ExecResult(return_code=0))
    source = tmp_path / "public.txt"
    source.write_text("public contents")

    await environment._copy_to_container(source, "trusted-server", "/tasks/public.txt")

    sandbox.filesystem.copy_from_local.aio.assert_awaited_once()
    assert Path(sandbox.filesystem.copy_from_local.aio.call_args.args[0]) == source
    commands = [call.args[0] for call in environment._run.await_args_list]
    copies = [command for command in commands if command[:2] == ["docker", "cp"]]
    assert len(copies) == 1
    assert copies[0][-1] == "trusted-server:/tasks/public.txt"
    assert any(command[:2] == ["rm", "-rf"] for command in commands)


@pytest.mark.asyncio
async def test_file_download_copies_selected_inner_container_then_uses_sdk(tmp_path):
    environment = make_environment(tmp_path)
    sandbox = fake_sandbox()
    environment._sandbox = sandbox
    environment._run = AsyncMock(return_value=ExecResult(return_code=0))

    async def download(_source, target):
        Path(target).write_text("saved result")

    sandbox.filesystem.copy_to_local.aio.side_effect = download
    target = tmp_path / "result" / "score.json"
    await environment._copy_from_container("trusted-server", "/logs/verifier/score.json", target)

    assert target.read_text() == "saved result"
    commands = [call.args[0] for call in environment._run.await_args_list]
    copies = [command for command in commands if command[:2] == ["docker", "cp"]]
    assert len(copies) == 1
    assert copies[0][2] == "trusted-server:/logs/verifier/score.json"


@pytest.mark.asyncio
async def test_failed_file_transfer_cleans_outer_staging_directory(tmp_path):
    environment = make_environment(tmp_path)
    sandbox = fake_sandbox()
    sandbox.filesystem.copy_from_local.aio.side_effect = RuntimeError("upload failed")
    environment._sandbox = sandbox
    environment._run = AsyncMock(return_value=ExecResult(return_code=0))
    source = tmp_path / "public.txt"
    source.write_text("public")
    with pytest.raises(RuntimeError, match="upload failed"):
        await environment._copy_to_container(source, "agent", "/workspace/public.txt")
    assert any(call.args[0][:2] == ["rm", "-rf"] for call in environment._run.await_args_list)


@pytest.mark.asyncio
async def test_directory_upload_uses_a_single_archive_and_preserves_contents(tmp_path):
    environment = make_environment(tmp_path)
    sandbox = fake_sandbox()
    environment._sandbox = sandbox
    environment._run = AsyncMock(return_value=ExecResult(return_code=0))
    source = tmp_path / "task"
    (source / "fixtures").mkdir(parents=True)
    (source / "fixtures/synthetic.json").write_text("synthetic backend fixture")
    (source / "test.sh").write_text("#!/bin/sh\ntrue\n")
    (source / "test.sh").chmod(0o755)
    uploaded = []

    async def inspect_archive(archive, remote):
        with tarfile.open(archive) as stream:
            assert (
                stream.extractfile("./fixtures/synthetic.json").read()
                == b"synthetic backend fixture"
            )
            assert stream.getmember("./test.sh").mode & 0o111
        uploaded.append(remote)

    sandbox.filesystem.copy_from_local.aio.side_effect = inspect_archive
    await environment._copy_to_container(source, "trusted-server", "/tasks/task", directory=True)

    assert len(uploaded) == 1
    commands = [call.args[0] for call in environment._run.await_args_list]
    copies = [command for command in commands if command[:2] == ["docker", "cp"]]
    assert len(copies) == 1
    assert copies[0][2].endswith("/payload/.")
    assert copies[0][3] == "trusted-server:/tasks/task"


@pytest.mark.asyncio
async def test_directory_download_extracts_contents_without_an_extra_parent(tmp_path):
    environment = make_environment(tmp_path)
    sandbox = fake_sandbox()
    environment._sandbox = sandbox
    environment._run = AsyncMock(return_value=ExecResult(return_code=0))
    synthetic_logs = tmp_path / "synthetic-logs"
    (synthetic_logs / "nested").mkdir(parents=True)
    (synthetic_logs / "nested/log.txt").write_text("synthetic output")

    async def download_archive(_remote, local):
        with tarfile.open(local, "w:gz") as stream:
            stream.add(synthetic_logs, arcname=".")

    sandbox.filesystem.copy_to_local.aio.side_effect = download_archive
    target = tmp_path / "downloaded"
    await environment._copy_from_container("agent", "/logs/agent", target, directory=True)

    assert (target / "nested/log.txt").read_text() == "synthetic output"
    commands = [call.args[0] for call in environment._run.await_args_list]
    assert any(command[:3] == ["docker", "cp", "agent:/logs/agent/."] for command in commands)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["/logs/agent", "/logs/agent/", "/logs/verifier"])
async def test_verification_download_filters_only_agent_staging_caches(tmp_path, source):
    environment = make_environment(tmp_path)
    environment._verifying = True
    environment._sandbox = fake_sandbox()
    environment._server_exec = AsyncMock(return_value=ExecResult(return_code=0))
    environment._exec_in = AsyncMock(return_value=ExecResult(return_code=0))
    logs = tmp_path / "frozen-logs"
    contents = {
        "trajectory.json": "required trajectory",
        "sessions/raw.jsonl": "required raw session",
        ".tmp/keep.txt": "ordinary temporary log",
        "cache/keep.txt": "ordinary cached evidence",
        ".tmp/plugins/large.bin": "disposable plugin cache",
        "cache/codex_apps_tools/large.bin": "disposable tool cache",
    }
    for relative, content in contents.items():
        path = logs / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    commands = []

    async def run(argv, **kwargs):
        commands.append(argv)
        if argv[:2] == ["docker", "cp"]:
            assert argv[2] == f"{environment._download_container(source)}:{source.rstrip('/')}/."
            shutil.copytree(logs, argv[3], dirs_exist_ok=True, symlinks=True)
            return ExecResult(return_code=0)
        process = await asyncio.create_subprocess_exec(*argv)
        return ExecResult(return_code=await process.wait())

    async def download(remote, local):
        shutil.copyfile(remote, local)

    environment._run = run
    environment._sandbox.filesystem.copy_to_local.aio.side_effect = download
    target = tmp_path / "downloaded"
    await environment.download_dir(source, target)

    environment._server_exec.assert_not_awaited()
    environment._exec_in.assert_not_awaited()
    for relative, content in contents.items():
        cached = relative.startswith((".tmp/plugins/", "cache/codex_apps_tools/"))
        if source.rstrip("/") == "/logs/agent" and cached:
            assert not (target / relative).exists()
        else:
            assert (target / relative).read_text() == content
        assert (logs / relative).read_text() == content, "Frozen source logs must stay intact"
    staging = next(argv[-1] for argv in commands if argv[:2] == ["mkdir", "-p"])
    assert not Path(staging).exists()


@pytest.mark.asyncio
async def test_engine_build_context_is_filtered_before_sdk_upload_and_reused(monkeypatch, tmp_path):
    environment = make_environment(tmp_path)
    sandbox = fake_sandbox()
    environment._sandbox = sandbox
    environment._run = AsyncMock(return_value=ExecResult(return_code=0))
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "docker").mkdir()
    (root / "docker/Dockerfile").write_text("FROM scratch")
    (root / "src/module.py").write_text("public module")
    (root / "src/.env").write_text("PRIVATE_SENTINEL")
    (root / "private.txt").write_text("PRIVATE_SENTINEL")
    monkeypatch.setattr(modal_env, "_resolve_repo_root", lambda: root)
    uploads = []

    async def inspect_archive(archive, remote):
        with tarfile.open(archive) as stream:
            assert "src/module.py" in stream.getnames()
            assert "src/.env" not in stream.getnames()
            assert "private.txt" not in stream.getnames()
            assert all(
                b"PRIVATE_SENTINEL" not in stream.extractfile(member).read()
                for member in stream
                if member.isfile()
            )
        uploads.append(remote)

    sandbox.filesystem.copy_from_local.aio.side_effect = inspect_archive
    first = await environment._engine_build_context()
    second = await environment._engine_build_context()

    assert first == second
    assert first.startswith("/tmp/chi-bench-build-")
    assert first.endswith("/context")
    assert len(uploads) == 1
    assert any(
        call.args[0][:2] == ["tar", "-xzf"] and call.args[0][-1] == first
        for call in environment._run.await_args_list
    )


@pytest.mark.asyncio
async def test_failed_build_context_upload_cleans_staging_and_does_not_cache(monkeypatch, tmp_path):
    environment = make_environment(tmp_path)
    sandbox = fake_sandbox()
    sandbox.filesystem.copy_from_local.aio.side_effect = RuntimeError("upload failed")
    environment._sandbox = sandbox
    environment._run = AsyncMock(return_value=ExecResult(return_code=0))
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(modal_env, "_resolve_repo_root", lambda: root)

    with pytest.raises(RuntimeError, match="upload failed"):
        await environment._engine_build_context()

    assert environment._remote_build_context is None
    assert any(call.args[0][:2] == ["rm", "-rf"] for call in environment._run.await_args_list)


@pytest.mark.asyncio
async def test_daemon_readiness_retries_and_then_succeeds(tmp_path):
    environment = make_environment(tmp_path)
    environment._run = AsyncMock(side_effect=[ExecResult(return_code=1), ExecResult(return_code=0)])

    await environment._wait_for_docker_ready(attempts=3, poll_interval_s=0)

    assert environment._run.await_count == 2


@pytest.mark.asyncio
async def test_daemon_readiness_exhaustion_fails_closed(tmp_path):
    environment = make_environment(tmp_path)
    environment._run = AsyncMock(return_value=ExecResult(return_code=1))

    with pytest.raises(RuntimeError, match="daemon did not become ready"):
        await environment._wait_for_docker_ready(attempts=2, poll_interval_s=0)

    assert environment._run.await_count == 2


@pytest.mark.asyncio
async def test_cancellation_during_creation_recovers_and_terminates_the_sandbox(
    monkeypatch, tmp_path
):
    environment = make_environment(tmp_path)
    sandbox = fake_sandbox()
    create, _, registered, unregistered = install_modal_fakes(monkeypatch, sandbox)
    started = asyncio.Event()
    complete = asyncio.Event()

    async def delayed_create(**_kwargs):
        started.set()
        await complete.wait()
        return sandbox

    create.side_effect = delayed_create
    base_start = AsyncMock()
    monkeypatch.setattr(ChiBenchDockerEnvironment, "start", base_start)
    monkeypatch.setattr(ChiBenchDockerEnvironment, "stop", AsyncMock())
    task = asyncio.create_task(environment.start(force_build=False))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    complete.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)

    base_start.assert_not_called()
    assert registered == [sandbox]
    assert unregistered == [sandbox]
    sandbox.terminate.aio.assert_awaited_once()
