"""Hub tasks separate agent execution, trusted collection, and frozen-state scoring."""

import io
import json
import logging
import shlex
import subprocess
import sys
import tomllib
import warnings
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from harbor.models.task.config import TaskConfig, VerifierEnvironmentMode
from harbor.models.trial.paths import EnvironmentPaths, TrialPaths
from harbor.trial.artifact_handler import ArtifactHandler
from harbor.trial.trial import Trial

from scripts import export_harbor_tasks as exporter


def emit_synthetic(tmp_path, *, domain="prior_auth_um", task_id="synthetic-task", session=False):
    source = tmp_path / "source"
    (source / "fixtures").mkdir(parents=True)
    (source / "solution").mkdir()
    (source / "instruction.md").write_text("# Public synthetic task\nUse the approved tools.\n")
    (source / "fixtures/expectations.json").write_text("PRIVATE_SENTINEL")
    (source / "solution/solve.sh").write_text("PRIVATE_SENTINEL")
    (source / "task.toml").write_text(
        "[verifier]\ntimeout_sec = 1234\n[agent]\ntimeout_sec = 2345\n"
    )
    cb_task_id = f"marathon/{domain}" if session else task_id
    exporter.emit_task(
        source,
        tmp_path / "exported",
        "example/" + task_id,
        task_id,
        cb_task_id,
        "marathon" if session else domain,
        {},
        pins=exporter.BuildPins(source="1" * 40, dataset="2" * 40, handbook="3" * 40),
        session=session,
    )
    return tmp_path / "exported" / task_id


def read_config(task):
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Artifact sources overlap")
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        return TaskConfig.model_validate(tomllib.loads((task / "task.toml").read_text()))


def volume_target(volume):
    return volume["target"] if isinstance(volume, dict) else volume.split(":", 2)[1]


@pytest.mark.parametrize("domain", ["prior_auth_um", "prior_auth_provider", "care_management"])
@pytest.mark.parametrize("session", [False, True])
def test_generated_config_preserves_timeouts_and_uses_native_separate_verifier(
    tmp_path, domain, session
):
    task = emit_synthetic(tmp_path, domain=domain, session=session)
    config = read_config(task)

    assert config.schema_version == "1.2"
    assert config.metadata["domain"] == ("marathon" if session else domain)
    assert config.agent.timeout_sec == 2345
    assert config.verifier.timeout_sec == 1234
    assert config.verifier.environment_mode == VerifierEnvironmentMode.SEPARATE
    assert config.verifier.environment is not None
    assert config.verifier.collect
    assert {hook.service for hook in config.verifier.collect} == {"simulator"}
    assert "HF_TOKEN" not in config.environment.env
    assert not any("KEY" in key or "TOKEN" in key for key in config.environment.env)
    assert "HF_TOKEN" in config.verifier.env
    artifacts = [artifact for artifact in config.artifacts if not isinstance(artifact, str)]
    assert any(
        item.service == "simulator" and item.source == "/logs/artifacts/final-state.json"
        for item in artifacts
    )
    assert any(
        item.service == "simulator" and item.source == "/logs/artifacts/workspaces"
        for item in artifacts
    )
    assert any(
        item.service == "simulator"
        and item.source == "/workspace/skills/managed-care-operations-handbook"
        for item in artifacts
    )
    main = next(
        item for item in artifacts if item.source == "/logs/artifacts" and item.service == "main"
    )
    assert {"workspaces", "final-state.json"} <= set(main.exclude)


@pytest.mark.parametrize(
    "domain,role",
    [("prior_auth_um", "payer"), ("prior_auth_provider", "provider"), ("care_management", "cm")],
)
def test_compose_main_uses_clean_image_and_only_public_shared_paths(tmp_path, domain, role):
    task = emit_synthetic(tmp_path, domain=domain)
    compose = yaml.safe_load((task / "environment/docker-compose.yaml").read_text())
    main = compose["services"]["main"]
    simulator = compose["services"]["simulator"]

    assert main["build"]["target"] == "agent"
    assert simulator["build"]["target"] == "simulator"
    assert main["network_mode"] == "service:simulator"
    assert main["depends_on"]["simulator"]["condition"] == "service_healthy"
    assert main["cap_drop"] == ["NET_RAW"]
    assert "no-new-privileges:true" in main["security_opt"]
    assert simulator["environment"]["CHI_BENCH_AGENT_ROLE"] == role
    assert simulator["environment"]["CHI_BENCH_PUBLISH_AGENT_ASSETS"] == "1"
    assert simulator["environment"]["CHI_BENCH_COMPOSE_PROJECT"].startswith(
        "${COMPOSE_PROJECT_NAME:?"
    )
    assert "CHI_BENCH_COMPOSE_PROJECT" not in main.get("environment", {})
    assert not any("KEY" in key or "TOKEN" in key for key in main.get("environment", {}))
    assert any(volume_target(volume) == "/agent-assets" for volume in main["volumes"])
    assert any(
        isinstance(volume, str) and volume.endswith(":/agent-raw/artifacts:ro")
        for volume in main["volumes"]
    )
    assert any(
        volume_target(volume) == "/srv/chi-bench/raw/artifacts" for volume in simulator["volumes"]
    )
    assert not any(volume_target(volume) == "/srv/chi-bench/raw" for volume in simulator["volumes"])
    assert not any(
        "/var/run/docker.sock" in volume_target(volume) or "/run/chi-bench" in volume_target(volume)
        for volume in main["volumes"]
    )
    assert ".ready" in " ".join(simulator["healthcheck"]["test"])


def test_provider_new_referral_does_not_mount_raw_artifacts_into_main(tmp_path):
    task = emit_synthetic(
        tmp_path, domain="prior_auth_provider", task_id="synthetic_new_referral_provider"
    )
    main = yaml.safe_load((task / "environment/docker-compose.yaml").read_text())["services"][
        "main"
    ]
    assert not any("agent-raw" in volume_target(volume) for volume in main["volumes"])


def test_agent_asset_mount_cannot_seed_the_simulator_publication_volume(tmp_path):
    task = emit_synthetic(tmp_path)
    compose = yaml.safe_load((task / "environment/docker-compose.yaml").read_text())
    main = compose["services"]["main"]
    simulator = compose["services"]["simulator"]

    # Compose may create main before starting simulator. Its pre-created skills/
    # and tools/ directories must not copy into the publisher's empty volume.
    assets = next(
        volume
        for volume in main["volumes"]
        if (volume.get("source") if isinstance(volume, dict) else volume.split(":")[0])
        == "agent-assets"
    )
    assert assets == {
        "type": "volume",
        "source": "agent-assets",
        "target": "/agent-assets",
        "read_only": True,
        "volume": {"nocopy": True},
    }
    assert "agent-assets:/agent-assets" in simulator["volumes"]


@pytest.mark.parametrize("session", [False, True])
def test_verifier_build_context_has_its_own_tests_and_does_not_boot_a_server(tmp_path, session):
    task = emit_synthetic(tmp_path, session=session)
    dockerfile = (task / "tests/Dockerfile").read_text()
    script = (task / "tests/test.sh").read_text()

    assert "FROM verifier AS evaluation" in dockerfile
    assert "COPY test.sh /tests/test.sh" in dockerfile
    assert "ENTRYPOINT []" in dockerfile.split("FROM verifier AS evaluation", 1)[1]
    assert "--exported-state-input" in script
    assert "/logs/artifacts/final-state.json" in script
    assert "--verifier-host" not in script
    assert "cb serve" not in script
    assert "bootstrap" not in script
    assert "ensure-handbook" in script
    if session:
        assert "chi_bench.verifier.session_verifier" in script
    else:
        assert "chi_bench.verifier.task_runtime verify" in script
    assert not any(path.name in {"fixtures", "solution", ".env"} for path in task.rglob("*"))
    assert all(
        b"PRIVATE_SENTINEL" not in path.read_bytes() for path in task.rglob("*") if path.is_file()
    )


def test_agent_target_never_inherits_trusted_source_or_fixture_layers():
    text = exporter.DOCKERFILE.read_text()
    assert "ARG CLAUDE_CODE_VERSION=2.1.219" in text
    assert "FROM base AS agent" in text
    stage = text.split("FROM base AS agent", 1)[1].split("\nFROM ", 1)[0]
    assert "COPY --from=application /workspace/.venv /workspace/.venv" in stage
    assert "openai_agents_runner.py" in stage
    assert "verifier" not in stage
    assert "fixtures" not in stage
    assert "git clone" not in stage
    assert "COPY --from=application /workspace/src/ /workspace/src/" not in stage


def test_missing_frozen_snapshot_fails_before_handbook_or_judge_calls(tmp_path):
    task = emit_synthetic(tmp_path)
    script = (
        (task / "tests/test.sh")
        .read_text()
        .replace("/logs/artifacts/final-state.json", str(tmp_path / "missing-state.json"))
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode != 0
    assert "frozen" in result.stderr.lower()


@pytest.mark.parametrize(
    "state",
    [
        "invalid-json",
        "{}",
        '{"_evaluation_boundary":{"version":1,"main_stopped":false,"main_container_id":"x"}}',
        '{"_evaluation_boundary":{"version":1,"main_stopped":true}}',
    ],
)
def test_unconfirmed_snapshot_fails_before_handbook_or_judge_calls(tmp_path, state):
    snapshot = tmp_path / "state.json"
    snapshot.write_text(state)
    script = (
        exporter._VERIFIER_PRELUDE.replace("/logs/artifacts/final-state.json", str(snapshot))
        .replace(". /workspace/.venv/bin/activate", "")
        .replace("python -c", shlex.quote(sys.executable) + " -c")
        .replace("/usr/local/bin/ensure-handbook", "echo INVALID_CONTINUATION")
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode != 0
    assert "INVALID_CONTINUATION" not in result.stdout


@pytest.mark.asyncio
async def test_harbor_rematerializes_trusted_artifacts_at_canonical_source_paths(tmp_path):
    task = emit_synthetic(tmp_path)
    config = read_config(task)
    host = tmp_path / "collected"
    for artifact in config.artifacts:
        if isinstance(artifact, str):
            continue
        target = host / (artifact.destination or artifact.source.lstrip("/"))
        if artifact.source.endswith("final-state.json"):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('{"workspace_root":"/logs/artifacts/workspaces"}')
        else:
            target.mkdir(parents=True, exist_ok=True)
    environment = SimpleNamespace(
        empty_dirs=AsyncMock(),
        ensure_dirs=AsyncMock(),
        upload_file=AsyncMock(),
        upload_dir=AsyncMock(),
    )
    handler = ArtifactHandler(artifacts=config.artifacts, logger=logging.getLogger(__name__))

    await handler.upload_artifacts(
        environment,
        host,
        source_artifacts_dir="/logs/artifacts",
        target_artifacts_dir="/logs/artifacts",
    )

    uploads = environment.upload_file.await_args_list
    assert any(call.kwargs["target_path"] == "/logs/artifacts/final-state.json" for call in uploads)
    assert any(
        call.kwargs["target_dir"] == "/logs/artifacts/workspaces"
        for call in environment.upload_dir.await_args_list
    )


def test_shared_agent_toolchain_includes_mcporter():
    base = exporter.DOCKERFILE.read_text().split("FROM base AS application", 1)[0]
    assert "npm install -g" in base
    assert "mcporter" in base


def test_collect_hook_authenticates_and_writes_only_frozen_state(tmp_path, monkeypatch):
    from chi_bench.experiment import frozen_state

    monkeypatch.setattr(frozen_state, "require_stopped_main", lambda path: "synthetic-main")

    token = tmp_path / "control-token"
    token.write_text("synthetic-private-control-token")
    output = tmp_path / "private-evidence/final-state.json"
    state = {"workspace_root": "/logs/artifacts/workspaces", "synthetic": True}
    requests = []

    def urlopen(request, timeout):
        assert request.get_header("Authorization") == "Bearer synthetic-private-control-token"
        requests.append(request)
        return io.BytesIO(
            json.dumps(state if request.full_url.endswith("/export") else {"ok": True}).encode()
        )

    monkeypatch.setattr(frozen_state, "urlopen", urlopen)
    script = exporter.COLLECT_SCRIPT.replace("/run/chi-bench/control-token", str(token)).replace(
        "/logs/artifacts/final-state.json", str(output)
    )

    exec(compile(script, "synthetic-collect-hook", "exec"), {})

    assert [request.full_url for request in requests] == [
        "http://localhost:8023/_admin/agent_role",
        "http://localhost:8023/export",
    ]
    assert json.loads(requests[0].data) == {"role": "closed"}
    expected = {
        **state,
        "_evaluation_boundary": {
            "version": 1,
            "main_stopped": True,
            "main_container_id": "synthetic-main",
        },
    }
    assert json.loads(output.read_text()) == expected
    assert "synthetic-private-control-token" not in output.read_text()
    assert output.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_actual_harbor_collection_order_stops_main_before_simulator_hook(tmp_path):
    task = emit_synthetic(tmp_path)
    config = read_config(task)
    events = []

    async def download(_environment, _artifacts_dir, **kwargs):
        events.append("download:" + ",".join(sorted(kwargs["services"])))

    async def hooks(items):
        events.extend("hook:" + item.service for item in items)

    async def stop(service):
        events.append("stop:" + service)

    trial = SimpleNamespace(
        _collect_hooks_for=lambda _step: config.verifier.collect,
        _run_collect_hooks=hooks,
        _artifact_handler=SimpleNamespace(
            begin_collection=lambda: events.append("begin"),
            download_artifacts=download,
            sidecar_services=lambda _artifacts: {"simulator"},
        ),
        agent_environment=SimpleNamespace(stop_service=stop),
        agent_env_paths=EnvironmentPaths.for_os(config.environment.os),
        logger=logging.getLogger(__name__),
    )

    await Trial._collect_artifacts_phased(
        trial, artifacts_dir=tmp_path / "artifacts", stop_main_before_sidecars=True
    )

    assert events == ["begin", "download:main", "stop:main", "hook:simulator", "download:simulator"]


def test_actual_harbor_startup_env_keeps_host_credentials_out_of_main(tmp_path, monkeypatch):
    from harbor.environments.docker.docker import DockerEnvironment

    task = emit_synthetic(tmp_path)
    config = read_config(task)
    monkeypatch.setenv("HF_TOKEN", "synthetic-private-hf-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-private-judge-key")
    environment = DockerEnvironment(
        environment_dir=task / "environment",
        environment_name="synthetic",
        session_id="synthetic-hub-trial",
        trial_paths=TrialPaths(tmp_path / "trial"),
        task_env_config=config.environment,
        network_policy=config.environment.resolve_baseline(),
    )

    startup = environment._startup_env()
    compose = environment._compose_env_vars()

    assert "HF_TOKEN" not in startup
    assert "ANTHROPIC_API_KEY" not in startup
    assert compose["HF_TOKEN"] == "synthetic-private-hf-token"
    assert compose["ANTHROPIC_API_KEY"] == "synthetic-private-judge-key"


def test_metadata_toml_preserves_unicode_and_quotes():
    text = exporter.render_task_toml(
        "example/synthetic",
        "synthetic",
        "prior_auth_um",
        {"title": "Clinical 🩺 review", "instruction_excerpt": 'Keep the "quoted" request.'},
        verifier_timeout=1200,
        agent_timeout=900,
    )
    config = tomllib.loads(text)
    assert 'Clinical 🩺 review. Keep the "quoted" request.' in config["task"]["description"]


def test_only_trusted_simulator_receives_agent_stop_inspection_socket(tmp_path):
    task = emit_synthetic(tmp_path)
    compose = yaml.safe_load((task / "environment/docker-compose.yaml").read_text())
    assert not any(
        volume_target(v) == "/var/run/docker.sock" for v in compose["services"]["main"]["volumes"]
    )
    sockets = [
        v
        for v in compose["services"]["simulator"]["volumes"]
        if volume_target(v) == "/var/run/docker.sock"
    ]
    assert len(sockets) == 1 and sockets[0]["read_only"] is True
    script = (task / "tests/test.sh").read_text()
    assert "_evaluation_boundary" in script and "main_stopped" in script
