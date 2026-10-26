from pathlib import Path

import pytest
from harbor.environments.base import ExecResult
from harbor.models.task.config import TaskConfig
from harbor.models.trial.paths import TrialPaths

from chi_bench.experiment.docker_env import ChiBenchDockerEnvironment


def make_environment(tmp_path, monkeypatch):
    task = tmp_path / "task"
    (task / "fixtures").mkdir(parents=True)
    (task / "environment").mkdir()
    (task / "task.toml").write_text('[task]\nname="org/task"\n')
    config = TaskConfig.model_validate({"environment": {"network_mode": "public"}})
    env = ChiBenchDockerEnvironment(
        environment_dir=task / "environment",
        environment_name="org/task",
        session_id="task__isolation",
        trial_paths=TrialPaths(tmp_path / "trial"),
        task_env_config=config.environment,
        network_policy=config.environment.resolve_baseline(),
        host_env={"ANTHROPIC_API_KEY": "private-server-key"},
    )
    calls = []

    async def run(argv, *, timeout_sec=None, env=None):
        calls.append((argv, env or {}))
        return ExecResult(return_code=0, stdout="", stderr="")

    async def ready(**kwargs):
        pass

    monkeypatch.setattr(env, "_run", run, raising=False)
    monkeypatch.setattr("chi_bench.experiment.docker_env._run_subprocess", run)
    monkeypatch.setattr("chi_bench.experiment.docker_env._register_container", lambda name: None)
    monkeypatch.setattr("chi_bench.experiment.docker_env._unregister_container", lambda name: None)
    monkeypatch.setattr(env, "_wait_for_server_ready", ready)
    return env, calls


@pytest.mark.asyncio
async def test_agent_container_has_no_private_mounts_or_server_credentials(tmp_path, monkeypatch):
    env, calls = make_environment(tmp_path, monkeypatch)
    await env.start(False)
    create = [(a, e) for a, e in calls if a[:2] == ["docker", "create"]]
    assert len(create) == 2
    server, agent = create
    assert server[1]["CHI_BENCH_CONTROL_TOKEN"]
    assert "private-server-key" not in " ".join(server[0])
    assert "CHI_BENCH_CONTROL_TOKEN" not in agent[1]
    assert "ANTHROPIC_API_KEY" not in agent[1]
    assert agent[0][agent[0].index("--cap-drop") + 1] == "NET_RAW"
    assert "no-new-privileges" in " ".join(agent[0])
    assert "/opt/chi-bench/tasks" not in " ".join(agent[0])
    assert "/var/run/docker.sock" not in " ".join(agent[0])
    assert any("/agent-assets:ro" in a for a in agent[0])
    assert any(a.endswith(":/agent-raw/artifacts:ro") for a in agent[0])
    assert not any(a.endswith(":/agent-raw:ro") for a in agent[0])


@pytest.mark.asyncio
async def test_tests_upload_stops_agent_and_routes_verifier_to_trusted_container(
    tmp_path, monkeypatch
):
    env, calls = make_environment(tmp_path, monkeypatch)
    await env.start(False)
    calls.clear()
    tests = tmp_path / "tests"
    tests.mkdir()
    await env.upload_dir(tests, "/tests")
    await env.exec("verify")
    stop = next(i for i, (a, _) in enumerate(calls) if a[:2] == ["docker", "stop"])
    drain = next(i for i, (a, _) in enumerate(calls) if "/_admin/agent_role" in " ".join(a))
    preparations = [
        i
        for i, (a, _) in enumerate(calls)
        if a[:2] == ["docker", "exec"] and a[-1] == "mkdir -p /logs/verifier"
    ]
    assert preparations, "Trusted verifier needs its output directory before running tests"
    prepare = preparations[0]
    copy = next(i for i, (a, _) in enumerate(calls) if a[:2] == ["docker", "cp"])
    assert stop < drain < prepare < copy
    assert env.server_container_name in calls[prepare][0]
    assert calls[copy][0][-1].startswith(env.server_container_name + ":")
    verify = calls[-1][0]
    assert env.server_container_name in verify
    assert env.container_name not in verify


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["stop", "drain", "prepare"])
async def test_verification_failure_never_uploads_tests_or_enters_verifier(
    tmp_path, monkeypatch, failure
):
    env, calls = make_environment(tmp_path, monkeypatch)
    await env.start(False)
    normal_run = env._run

    async def fail_boundary(argv, **kwargs):
        is_stop = argv[:2] == ["docker", "stop"]
        is_drain = "/_admin/agent_role" in " ".join(argv)
        is_prepare = argv[-1] == "mkdir -p /logs/verifier"
        if (
            (failure == "stop" and is_stop)
            or (failure == "drain" and is_drain)
            or (failure == "prepare" and is_prepare)
        ):
            calls.append((argv, {}))
            return ExecResult(return_code=1, stdout="", stderr="boundary failed")
        return await normal_run(argv, **kwargs)

    monkeypatch.setattr(env, "_run", fail_boundary)
    calls.clear()
    tests = tmp_path / "tests"
    tests.mkdir()
    with pytest.raises(RuntimeError):
        await env.upload_dir(tests, "/tests")
    assert not env._verifying
    assert not any(a[:2] == ["docker", "cp"] for a, _ in calls)
    if failure == "stop":
        assert not any("/_admin/agent_role" in " ".join(a) for a, _ in calls)


@pytest.mark.asyncio
async def test_control_request_does_not_execute_in_agent(tmp_path, monkeypatch):
    env, calls = make_environment(tmp_path, monkeypatch)
    await env.start(False)
    calls.clear()
    await env.exec_control("trusted-operation")
    assert env.server_container_name in calls[-1][0]
    assert env.container_name not in calls[-1][0]
    assert not any("CHI_BENCH_CONTROL_TOKEN=" in arg for arg in calls[-1][0])


@pytest.mark.asyncio
async def test_failed_start_cleans_up_all_owned_resources(tmp_path, monkeypatch):
    env, calls = make_environment(tmp_path, monkeypatch)
    normal_run = env._run

    async def fail_agent(argv, **kwargs):
        if argv[:2] == ["docker", "start"] and argv[-1] == env.container_name:
            return ExecResult(return_code=1, stdout="", stderr="failed")
        return await normal_run(argv, **kwargs)

    monkeypatch.setattr(env, "_run", fail_agent)
    with pytest.raises(RuntimeError):
        await env.start(False)
    assert any(a[:3] == ["docker", "volume", "rm"] for a, _ in calls)
    assert any(a[:3] == ["docker", "network", "rm"] for a, _ in calls)


@pytest.mark.asyncio
async def test_agent_exec_does_not_inherit_private_task_environment(tmp_path, monkeypatch):
    env, calls = make_environment(tmp_path, monkeypatch)
    env._persistent_env.update(
        {
            "HF_TOKEN": "private-download-key",
            "PRIVATE_POLICY": "secret",
            "CHI_BENCH_TOOL_MODE": "cli",
        }
    )
    await env.exec("agent", env={"OPENAI_API_KEY": "agent-key"})
    assert calls[-1][1] == {"CHI_BENCH_TOOL_MODE": "cli", "OPENAI_API_KEY": "agent-key"}


@pytest.mark.asyncio
async def test_remote_builds_use_host_network(tmp_path, monkeypatch):
    env, calls = make_environment(tmp_path, monkeypatch)
    env._uses_host_network = True
    await env._build_image()
    builds = [a for a, _ in calls if a[:2] == ["docker", "build"]]
    assert len(builds) == 2
    assert all(("--network", "host") in zip(a, a[1:]) for a in builds)


@pytest.mark.asyncio
async def test_harbor_agent_scoped_env_is_preserved_without_private_task_env(tmp_path, monkeypatch):
    env, calls = make_environment(tmp_path, monkeypatch)
    env._persistent_env["HF_TOKEN"] = "download-key"
    with env.scoped_exec_env(
        {"OPENAI_API_KEY": "agent-key", "CHI_BENCH_CONTROL_TOKEN": "forbidden"}
    ):
        await env.exec("agent", env={"OPENAI_API_KEY": "command-default"})
    assert calls[-1][1] == {"OPENAI_API_KEY": "agent-key"}
    await env.exec("outside-agent-scope")
    assert calls[-1][1] == {}


def test_modal_task_mirror_preserves_original_task_checksum(tmp_path):
    from dirhash import dirhash
    from chi_bench.experiment.runner import _prepare_modal_dataset

    task = tmp_path / "task"
    (task / "fixtures").mkdir(parents=True)
    (task / "task.toml").write_text('[metadata]\ntask_id="task"\n')
    (task / "instruction.md").write_text("Synthetic public task")
    (task / "fixtures/expectations.json").write_text('{"private":"synthetic"}')
    before = dirhash(task, "sha256")
    with _prepare_modal_dataset(str(task)) as mirrored:
        assert dirhash(mirrored, "sha256") == before
        assert (Path(mirrored) / "environment").is_dir()
        assert not (Path(mirrored) / "instruction.md").is_symlink()
        assert not (Path(mirrored) / "fixtures/expectations.json").is_symlink()
    assert dirhash(task, "sha256") == before


def test_mirrored_modal_task_can_publish_only_public_assets(tmp_path):
    from chi_bench.experiment.runner import _prepare_modal_dataset
    from chi_bench.experiment.runtime_assets import publish_agent_assets

    task = tmp_path / "task"
    (task / "fixtures").mkdir(parents=True)
    (task / "task.toml").write_text('[metadata]\ntask_id="task"\n')
    (task / "instruction.md").write_text("Synthetic public instruction")
    (task / "fixtures/expectations.json").write_text("private-canary")
    handbook = tmp_path / "handbook"
    handbook.mkdir()
    (handbook / "SKILL.md").write_text("Public handbook")
    reference = tmp_path / "reference.md"
    reference.write_text("Public tools")
    output = tmp_path / "published"

    with _prepare_modal_dataset(str(task)) as mirrored:
        publish_agent_assets(Path(mirrored).resolve(), handbook, reference, output)

    assert (output / "tools/instruction.md").read_text() == "Synthetic public instruction"
    assert all(
        "private-canary" not in path.read_text() for path in output.rglob("*") if path.is_file()
    )
