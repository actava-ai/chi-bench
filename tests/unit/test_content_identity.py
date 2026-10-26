"""A declared dataset version never substitutes for an accepted byte identity."""

import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from chi_bench.experiment.submission import (
    SUBMISSION_SCHEMA_V1,
    SubmissionConfig,
    capture_provenance,
    preflight_dataset,
)


def identity_module():
    return importlib.import_module("chi_bench.experiment.content_identity")


def make_data(root: Path) -> Path:
    files = {
        ".chi-bench-version": "synthetic-v1\n",
        "prior_auth_provider/registry.json": "{}",
        "prior_auth_provider/tasks/task/instruction.md": "Synthetic instruction",
        "prior_auth_provider/tasks/task/task.toml": "schema_version = '1.2'",
        "prior_auth_provider/tasks/task/fixtures/expectations.json": '{"synthetic": true}',
        "prior_auth_provider/shared/worlds/world.json": '{"world": true}',
        "care_management/shared/tool_reference.md": "Synthetic common tool reference",
        "skills/managed-care-operations-handbook/SKILL.md": "Synthetic handbook",
    }
    for relative, body in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return root


def config(root: Path, expected: str | None) -> SubmissionConfig:
    dataset = {"version": "synthetic-v1", "domains": ["pa"]}
    if expected is not None:
        dataset["content_sha256"] = expected
    return SubmissionConfig.model_validate(
        {
            "schema": SUBMISSION_SCHEMA_V1,
            "submission": {
                "id": "synthetic",
                "team": "Synthetic",
                "contact": "test@example.invalid",
                "agent": "claude-code",
                "model": "anthropic/synthetic",
            },
            "dataset": dataset,
            "paths": {"data_root": root},
        }
    )


def accepted_config(root: Path) -> SubmissionConfig:
    digest = identity_module().compute_dataset_identity(root, ["pa_provider"]).content_sha256
    return config(root, digest)


def test_submission_requires_explicit_expected_identity(tmp_path):
    with pytest.raises(ValidationError, match="content_sha256"):
        config(tmp_path, None)


@pytest.mark.parametrize("digest", ["", "main", "a" * 40, "G" * 64, "A" * 64])
def test_submission_rejects_invalid_expected_identity(tmp_path, digest):
    with pytest.raises(ValidationError, match="content_sha256"):
        config(tmp_path, digest)


def test_known_content_identity_passes_preflight(tmp_path):
    root = make_data(tmp_path / "data")
    assert preflight_dataset(accepted_config(root)) == []


@pytest.mark.parametrize(
    "relative",
    [
        "prior_auth_provider/tasks/task/instruction.md",
        "prior_auth_provider/tasks/task/fixtures/expectations.json",
        "prior_auth_provider/shared/worlds/world.json",
        "care_management/shared/tool_reference.md",
        "skills/managed-care-operations-handbook/SKILL.md",
    ],
)
def test_same_version_changed_task_world_or_handbook_is_rejected(tmp_path, relative):
    root = make_data(tmp_path / "data")
    cfg = accepted_config(root)
    (root / relative).write_text("Different bytes under the same declared version")
    issues = preflight_dataset(cfg)
    assert any(i.code == "dataset.content_mismatch" and i.severity == "error" for i in issues)


@pytest.mark.parametrize("change", ["missing-file", "extra-file", "missing-tree"])
def test_missing_or_extra_assets_do_not_silently_refresh_expected_identity(tmp_path, change):
    root = make_data(tmp_path / "data")
    cfg = accepted_config(root)
    expected = cfg.dataset.content_sha256
    if change == "missing-file":
        (root / "prior_auth_provider/tasks/task/instruction.md").unlink()
    elif change == "extra-file":
        (root / "prior_auth_provider/tasks/task/extra.json").write_text("extra")
    else:
        shutil.rmtree(root / "skills/managed-care-operations-handbook")
    assert any(i.severity == "error" for i in preflight_dataset(cfg))
    assert cfg.dataset.content_sha256 == expected


def test_identity_is_portable_and_ignores_only_incidental_assets(tmp_path):
    root = make_data(tmp_path / "first")
    copied = tmp_path / "second"
    shutil.copytree(root, copied)
    for relative in [".DS_Store", ".cache/cache", ".git/HEAD", "__pycache__/module.pyc"]:
        path = copied / "prior_auth_provider/tasks/task" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("incidental")
    first = identity_module().compute_dataset_identity(root, ["pa_provider"])
    second = identity_module().compute_dataset_identity(copied, ["pa_provider"])
    assert first.content_sha256 == second.content_sha256
    assert first.file_count == second.file_count


def test_nested_symlink_is_rejected_instead_of_omitted(tmp_path):
    root = make_data(tmp_path / "data")
    outside = tmp_path / "outside"
    outside.write_text("linked asset")
    (root / "prior_auth_provider/tasks/task/link").symlink_to(outside)
    with pytest.raises(ValueError, match="[Ll]ink"):
        identity_module().compute_dataset_identity(root, ["pa_provider"])


def test_internal_relative_world_file_alias_binds_target_and_bytes(tmp_path):
    root = make_data(tmp_path / "data")
    worlds = root / "prior_auth_provider/shared/worlds"
    (worlds / "runtime-alias.json").symlink_to("world.json")
    first = identity_module().compute_dataset_identity(root, ["pa_provider"])
    (worlds / "world.json").write_text("changed resolved world")
    second = identity_module().compute_dataset_identity(root, ["pa_provider"])
    assert first.content_sha256 != second.content_sha256
    (worlds / "duplicate.json").write_text("changed resolved world")
    before_alias_change = identity_module().compute_dataset_identity(root, ["pa_provider"])
    (worlds / "runtime-alias.json").unlink()
    (worlds / "runtime-alias.json").symlink_to("duplicate.json")
    after_alias_change = identity_module().compute_dataset_identity(root, ["pa_provider"])
    assert before_alias_change.content_sha256 != after_alias_change.content_sha256


def test_um_identity_covers_provider_worlds_used_by_runtime(tmp_path):
    root = make_data(tmp_path / "data")
    shutil.copytree(root / "prior_auth_provider", root / "prior_auth_um")
    before = identity_module().compute_dataset_identity(root, ["pa_um"])
    (root / "prior_auth_provider/shared/worlds/world.json").write_text("runtime world drift")
    after = identity_module().compute_dataset_identity(root, ["pa_um"])
    assert before.content_sha256 != after.content_sha256


def test_provenance_records_verified_expected_and_actual_identity(tmp_path):
    root = make_data(tmp_path / "data")
    cfg = accepted_config(root)
    provenance = capture_provenance(cfg)
    assert provenance["dataset_content_sha256"] == cfg.dataset.content_sha256
    assert provenance["dataset_expected_content_sha256"] == cfg.dataset.content_sha256
    assert provenance["dataset_content_identity_schema"] == "chi-bench/dataset-content/v1"
    (root / "prior_auth_provider/shared/worlds/world.json").write_text("drift")
    with pytest.raises(ValueError, match="content.*(mismatch|changed)"):
        capture_provenance(cfg)


def test_provenance_records_effective_run_start_judge_and_unknown_modal_images(
    tmp_path, monkeypatch
):
    root = make_data(tmp_path / "data")
    cfg = accepted_config(root)
    env_file = tmp_path / "synthetic.env"
    env_file.write_text("CHI_BENCH_JUDGE_MODEL=synthetic-file-judge\n")
    cfg.run.env_file = str(env_file)
    monkeypatch.setenv("CHI_BENCH_JUDGE_MODEL", "synthetic-process-judge")
    provenance = capture_provenance(cfg)
    assert provenance["judge_model"] == "synthetic-file-judge"
    assert provenance["modal_runtime_image_digest"] is None
    assert provenance["modal_agent_image_digest"] is None


def test_identity_cli_prints_candidate_without_writing_into_data(tmp_path):
    root = make_data(tmp_path / "data")
    before = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    result = subprocess.run(
        [sys.executable, "scripts/dataset_identity.py", "--data-root", str(root), "--domain", "pa"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (
        json.loads(result.stdout)["content_sha256"] == accepted_config(root).dataset.content_sha256
    )
    assert sorted(str(p.relative_to(root)) for p in root.rglob("*")) == before


def test_identity_cli_rejects_output_inside_original_data(tmp_path):
    root = make_data(tmp_path / "data")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/dataset_identity.py",
            "--data-root",
            str(root),
            "--domain",
            "pa",
            "--out",
            str(root / "manifest.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "outside" in result.stderr and "data" in result.stderr
    assert not (root / "manifest.json").exists()
