"""Accepted source bytes must identify the materials actually used by a trial."""

import importlib
import json
import shutil
import subprocess
import sys

import pytest


def materials():
    return importlib.import_module("chi_bench.experiment.runtime_materials")


def source_data(tmp_path, *, per_task_reference=True):
    root = tmp_path / "accepted"
    task = root / "prior_auth_um/tasks/task"
    files = {
        "prior_auth_um/tasks/task/instruction.md": "Public task",
        "prior_auth_um/tasks/task/task.toml": "schema_version='1.2'",
        "prior_auth_um/tasks/task/fixtures/manifest.json": json.dumps(
            {"world_id": "world", "task_actor": "payer_staff"}
        ),
        "prior_auth_um/tasks/task/fixtures/expectations.json": '{"private":"expected"}',
        "prior_auth_provider/shared/worlds/world.json": '{"world":"accepted"}',
        "skills/managed-care-operations-handbook/SKILL.md": "Accepted handbook",
        "care_management/shared/tool_reference.md": "Accepted default reference",
    }
    if per_task_reference:
        files["prior_auth_um/tasks/task/tool_reference.md"] = "Accepted task reference"
    for relative, body in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return root, task


def runtime_data(tmp_path, source, task):
    root = tmp_path / "container"
    mappings = {
        task: root / "opt/chi-bench/tasks/task",
        source / "prior_auth_provider/shared/worlds": root / "opt/chi-bench/worlds",
        source / "skills/managed-care-operations-handbook": root
        / "workspace/skills/managed-care-operations-handbook",
    }
    for src, target in mappings.items():
        shutil.copytree(src, target)
    reference = root / "opt/chi-bench-task-assets/tool_reference.md"
    reference.parent.mkdir(parents=True)
    shutil.copyfile(source / "care_management/shared/tool_reference.md", reference)
    return root


@pytest.mark.parametrize("per_task_reference", [True, False])
def test_exact_materials_accept_custom_source_root(tmp_path, per_task_reference):
    source, task = source_data(tmp_path, per_task_reference=per_task_reference)
    runtime = runtime_data(tmp_path, source, task)
    manifest = materials().build_runtime_material_manifest(source, task, "task")
    materials().verify_runtime_material_manifest(manifest, filesystem_root=runtime)


@pytest.mark.parametrize(
    "relative",
    [
        "opt/chi-bench/tasks/task/fixtures/expectations.json",
        "opt/chi-bench/worlds/world.json",
        "workspace/skills/managed-care-operations-handbook/SKILL.md",
        "opt/chi-bench-task-assets/tool_reference.md",
    ],
)
def test_stale_baked_materials_fail_before_bootstrap(tmp_path, relative):
    source, task = source_data(tmp_path, per_task_reference=False)
    runtime = runtime_data(tmp_path, source, task)
    manifest = materials().build_runtime_material_manifest(source, task, "task")
    (runtime / relative).write_text("Stale image content")
    with pytest.raises(ValueError, match="Runtime material mismatch"):
        materials().verify_runtime_material_manifest(manifest, filesystem_root=runtime)


def test_task_reference_selects_original_task_bytes_before_runtime_proxy_rewrite(tmp_path):
    source, task = source_data(tmp_path)
    runtime = runtime_data(tmp_path, source, task)
    selected = runtime / "opt/chi-bench-task-assets/tool_reference.md"
    selected.unlink()
    selected.symlink_to(runtime / "opt/chi-bench/tasks/task/tool_reference.md")
    manifest = materials().build_runtime_material_manifest(source, task, "task")
    materials().verify_runtime_material_manifest(manifest, filesystem_root=runtime)
    (runtime / "opt/chi-bench/tasks/task/tool_reference.md").write_text("Unaccepted task tools")
    with pytest.raises(ValueError, match="Runtime material mismatch"):
        materials().verify_runtime_material_manifest(manifest, filesystem_root=runtime)


@pytest.mark.parametrize(
    "tree", ["opt/chi-bench/tasks/task", "workspace/skills/managed-care-operations-handbook"]
)
def test_extra_stale_files_in_selected_task_or_handbook_fail(tmp_path, tree):
    source, task = source_data(tmp_path)
    runtime = runtime_data(tmp_path, source, task)
    manifest = materials().build_runtime_material_manifest(source, task, "task")
    (runtime / tree / "stale.txt").write_text("Old material")
    with pytest.raises(ValueError, match="Runtime material mismatch"):
        materials().verify_runtime_material_manifest(manifest, filesystem_root=runtime)


def test_runner_added_empty_environment_stub_does_not_change_material_bytes(tmp_path):
    source, task = source_data(tmp_path)
    runtime = runtime_data(tmp_path, source, task)
    (runtime / "opt/chi-bench/tasks/task/environment").mkdir()
    manifest = materials().build_runtime_material_manifest(source, task, "task")
    materials().verify_runtime_material_manifest(manifest, filesystem_root=runtime)


def test_session_guard_covers_the_session_governing_world(tmp_path):
    source, task = source_data(tmp_path)
    fixtures = task / "fixtures"
    (fixtures / "session_manifest.json").write_text(
        json.dumps({"world_id": "world", "tasks": [{"task_id": "nested"}]})
    )
    nested = fixtures / "tasks/nested"
    nested.mkdir(parents=True)
    shutil.copyfile(fixtures / "manifest.json", nested / "manifest.json")
    manifest = materials().build_runtime_material_manifest(source, task, "task")
    assert "/opt/chi-bench/worlds/world.json" in manifest["files"]


def test_per_task_cm_world_does_not_require_unused_shared_alias(tmp_path):
    source, task = source_data(tmp_path)
    (task / "fixtures/world.json").write_text('{"cm":"per-task-world"}')
    manifest = materials().build_runtime_material_manifest(source, task, "task")
    assert not any(path.startswith("/opt/chi-bench/worlds/") for path in manifest["files"])


def test_guard_is_a_standalone_script_for_prebuilt_images(tmp_path):
    source, task = source_data(tmp_path)
    runtime = runtime_data(tmp_path, source, task)
    manifest = materials().build_runtime_material_manifest(source, task, "task")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            materials().__file__,
            str(manifest_path),
            "--filesystem-root",
            str(runtime),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    (runtime / "opt/chi-bench/worlds/world.json").write_text("Stale world")
    failed = subprocess.run(
        [
            sys.executable,
            "-I",
            materials().__file__,
            str(manifest_path),
            "--filesystem-root",
            str(runtime),
        ],
        capture_output=True,
        text=True,
    )
    assert failed.returncode != 0
    assert "Runtime material mismatch" in failed.stderr


def test_submission_slice_and_harbor_kwargs_preserve_the_accepted_source(tmp_path):
    from harbor.cli.utils import parse_kwargs
    from chi_bench.experiment.config import ExperimentConfig
    from chi_bench.experiment.runner import _build_harbor_command
    from chi_bench.experiment.submission import SubmissionConfig, _build_slice_yaml

    config = SubmissionConfig.model_validate(
        {
            "schema": "chi-bench/submission/v1",
            "submission": {
                "id": "synthetic",
                "team": "Synthetic",
                "contact": "test@example.invalid",
                "agent": "claude-code",
                "model": "anthropic/synthetic",
            },
            "dataset": {"version": "synthetic", "content_sha256": "1" * 64, "domains": ["pa_um"]},
            "paths": {"data_root": tmp_path / "custom-data"},
        }
    )
    experiment = ExperimentConfig(**_build_slice_yaml(config, "pa_um"))
    command = _build_harbor_command(experiment, env={})
    kwargs = parse_kwargs(
        [command[i + 1] for i, value in enumerate(command) if value == "--environment-kwarg"]
    )
    assert kwargs["data_root"] == str(config.paths.data_root.resolve())
    assert kwargs["dataset_content_sha256"] == "1" * 64
    assert kwargs["dataset_domains"] == ["pa_um"]


def accepted_environment(tmp_path, monkeypatch):
    from harbor.environments.base import ExecResult
    from harbor.models.task.config import TaskConfig
    from harbor.models.trial.paths import TrialPaths
    from unittest.mock import AsyncMock

    from chi_bench.experiment.content_identity import compute_dataset_identity
    from chi_bench.experiment.docker_env import ChiBenchDockerEnvironment

    source, task = source_data(tmp_path)
    for relative, body in {
        ".chi-bench-version": "synthetic",
        "prior_auth_um/registry.json": "{}",
        "prior_auth_um/shared/worlds/world.json": '{"world":"accepted"}',
    }.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    identity = compute_dataset_identity(source, ["pa_um"])
    mirror = tmp_path / "mirrored/task"
    shutil.copytree(task, mirror)
    (mirror / "environment").mkdir()
    config = TaskConfig.model_validate({"environment": {"network_mode": "public"}})
    environment = ChiBenchDockerEnvironment(
        environment_dir=mirror / "environment",
        environment_name="org/task",
        session_id="task__materials",
        trial_paths=TrialPaths(tmp_path / "trial"),
        task_env_config=config.environment,
        network_policy=config.environment.resolve_baseline(),
        data_root=source,
        dataset_content_sha256=identity.content_sha256,
        dataset_domains=["pa_um"],
        host_env={},
    )
    calls = []

    async def run(argv, **kwargs):
        calls.append(argv)
        return ExecResult(return_code=0, stdout="", stderr="")

    monkeypatch.setattr(environment, "_run", run)
    monkeypatch.setattr(environment, "_wait_for_server_ready", AsyncMock())
    monkeypatch.setattr("chi_bench.experiment.docker_env._register_container", lambda name: None)
    return environment, calls, source, mirror


@pytest.mark.asyncio
async def test_real_lifecycle_stages_guard_before_starting_prebuilt_runtime(tmp_path, monkeypatch):
    environment, calls, source, mirror = accepted_environment(tmp_path, monkeypatch)
    await environment.start(False)
    create = next(command for command in calls if command[:2] == ["docker", "create"])
    assert create[create.index("--entrypoint") + 1] == "/bin/sh"
    assert "chi-bench-material-guard.py" in create[-1]
    assert " && exec /usr/bin/tini -- /usr/local/bin/entrypoint.sh" in create[-1]
    start = next(i for i, command in enumerate(calls) if command[:2] == ["docker", "start"])
    staged = [command[-1] for command in calls[:start] if command[:2] == ["docker", "cp"]]
    assert environment.server_container_name + ":/tmp/chi-bench-material-guard.py" in staged
    assert environment.server_container_name + ":/tmp/chi-bench-materials.json" in staged


@pytest.mark.asyncio
async def test_accepted_root_drift_is_rechecked_before_creating_any_runtime(tmp_path, monkeypatch):
    environment, calls, source, mirror = accepted_environment(tmp_path, monkeypatch)
    (source / "prior_auth_provider/shared/worlds/world.json").write_text("Unaccepted drift")
    with pytest.raises(ValueError, match="dataset content mismatch"):
        await environment.start(False)
    assert not calls


def test_accepted_source_task_hash_does_not_trust_a_changed_modal_mirror(tmp_path, monkeypatch):
    environment, calls, source, mirror = accepted_environment(tmp_path, monkeypatch)
    (mirror / "fixtures/expectations.json").write_text("Changed transport copy")
    manifest = environment._runtime_material_manifest()
    runtime = runtime_data(tmp_path, source, mirror)
    with pytest.raises(ValueError, match="Runtime material mismatch"):
        materials().verify_runtime_material_manifest(manifest, filesystem_root=runtime)


def test_direct_experiment_preserves_known_source_root_without_submission_pin(tmp_path):
    source, task = source_data(tmp_path)
    assert materials().infer_data_root(task) == source.resolve()


def test_unrelated_synthetic_task_does_not_adopt_checkout_dataset(tmp_path, monkeypatch):
    environment, calls, source, mirror = accepted_environment(tmp_path, monkeypatch)
    environment._data_root = None
    environment._dataset_content_sha256 = None
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "data").symlink_to(source, target_is_directory=True)
    monkeypatch.setattr("chi_bench.experiment.docker_env._resolve_repo_root", lambda: repository)
    assert environment._runtime_material_manifest() is None


def test_accepted_submission_cannot_skip_guard_when_source_root_is_absent(tmp_path, monkeypatch):
    environment, calls, source, mirror = accepted_environment(tmp_path, monkeypatch)
    environment._data_root = None
    with pytest.raises(ValueError, match="requires data_root"):
        environment._runtime_material_manifest()


def test_accepted_task_must_belong_to_the_hashed_domain_scope(tmp_path, monkeypatch):
    environment, calls, source, mirror = accepted_environment(tmp_path, monkeypatch)
    provider_task = source / "prior_auth_provider/tasks/other"
    shutil.copytree(source / "prior_auth_um/tasks/task", provider_task)
    environment._persistent_env["CHI_BENCH_TASK_ID"] = "other"
    with pytest.raises(ValueError, match="outside the accepted dataset domain scope"):
        environment._runtime_material_manifest()
