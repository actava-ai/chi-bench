"""Native exports bind source, fixtures, and handbook to explicit commits."""

import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import export_harbor_tasks as exporter


def pins(**overrides):
    values = {"source": "1" * 40, "dataset": "2" * 40, "handbook": "3" * 40}
    values.update(overrides)
    return exporter.BuildPins(**values)


@pytest.mark.parametrize("field", ["source", "dataset", "handbook"])
@pytest.mark.parametrize("bad", ["", "main", "chi-bench-v1.0.0", "a" * 12, "x" * 40])
def test_build_pins_require_full_immutable_commits(field, bad):
    with pytest.raises(ValueError, match=field):
        pins(**{field: bad})


def test_hub_dockerfile_has_no_moving_fallback():
    text = exporter.DOCKERFILE.read_text()
    assert "ARG CHI_BENCH_REF=main" not in text
    assert "ARG CHI_BENCH_DATASET_REV=chi-bench-v1.0.0" not in text
    assert "ARG CHI_BENCH_HANDBOOK_REV" in text
    assert '--revision "$CHI_BENCH_HANDBOOK_REV"' in text
    assert "rev-parse HEAD" in text


def test_exported_build_definitions_embed_the_same_explicit_pins(tmp_path):
    source = tmp_path / "task"
    source.mkdir()
    (source / "instruction.md").write_text("Synthetic public instruction")
    selected = pins()
    exporter.emit_task(
        source, tmp_path / "out", "example/task", "task", "task", "prior_auth_um", {}, pins=selected
    )
    task = tmp_path / "out/task"
    compose = yaml.safe_load((task / "environment/docker-compose.yaml").read_text())
    for service in ["main", "simulator"]:
        assert compose["services"][service]["build"]["args"] == selected.build_args()
    for relative in ["environment/Dockerfile", "tests/Dockerfile"]:
        text = (task / relative).read_text()
        for key, value in selected.build_args().items():
            assert f"ARG {key}={value}" in text


def git(root: Path, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def committed_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Synthetic")
    (root / "source.txt").write_text("committed source")
    git(root, "add", ".")
    git(root, "commit", "-m", "synthetic fixture")
    sha = git(root, "rev-parse", "HEAD")
    git(root, "remote", "add", "origin", exporter.SOURCE_REPO)
    return root, sha


def test_export_guard_rejects_clean_but_unpushed_source(tmp_path):
    root, sha = committed_repo(tmp_path)
    with pytest.raises(ValueError, match="remote|published|push"):
        exporter.validate_source_checkout(root, sha)


def test_export_guard_accepts_matching_clean_remote_reachable_commit(tmp_path):
    root, sha = committed_repo(tmp_path)
    git(root, "update-ref", "refs/remotes/origin/main", sha)
    exporter.validate_source_checkout(root, sha)
    (root / "source.txt").write_text("uncommitted source")
    with pytest.raises(ValueError, match="dirty|clean|uncommitted"):
        exporter.validate_source_checkout(root, sha)


def test_export_guard_rejects_a_different_source_revision(tmp_path):
    root, sha = committed_repo(tmp_path)
    git(root, "update-ref", "refs/remotes/origin/main", sha)
    with pytest.raises(ValueError, match="HEAD|checkout|revision"):
        exporter.validate_source_checkout(root, "a" * 40)
