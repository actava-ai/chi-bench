"""Tests for prepare_packet()."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chi_bench.experiment.submission import (
    SUBMISSION_SCHEMA_V1,
    SubmissionConfig,
    prepare_packet,
)
from chi_bench.experiment.trajectory_pack import iter_packed_messages


def _write_yaml(path: Path, sub_id: str = "test-sub") -> Path:
    path.write_text(
        f"""schema: {SUBMISSION_SCHEMA_V1}
submission:
  id: {sub_id}
  team: Test Team
  contact: t@example.com
  agent: claude-code
  model: anthropic/claude-opus-4-6
dataset:
  version: chi-bench-v1.0.0
  domains: [pa_provider]
run:
  environment: docker
"""
    )
    return path


def _seed_trial_tree(
    output_root: Path,
    domain: str = "pa_provider",
    trial_id: str = "trial1",
) -> Path:
    """Create a minimal trial directory that prepare_packet can curate.

    Seeds the aggregator-friendly result.json shape (with verifier_result),
    plus sub.yaml and provenance.json at output_root.
    """
    trial = output_root / domain / "sub" / trial_id
    trial.mkdir(parents=True)
    (trial / "result.json").write_text(
        json.dumps(
            {
                "verifier_result": {"reward": 1.0, "rewards": {"reward": 1.0}},
                "agent_result": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "n_cache_tokens": 0,
                    "wall_clock_seconds": 12.5,
                },
                "agent_info": {
                    "agent": "claude-code",
                    "model_info": {
                        "provider": "anthropic",
                        "name": "claude-opus-4-6",
                    },
                },
                "task": {"path": f"data/{domain}/tasks/{trial_id}"},
            }
        )
    )
    (trial / "verifier").mkdir()
    (trial / "verifier" / "scorecard.json").write_text(json.dumps({"checks": []}))
    (trial / "verifier" / "reward.json").write_text(json.dumps({"reward": 1.0}))
    (trial / "agent").mkdir()
    (trial / "agent" / "trajectory.json").write_text(
        json.dumps(
            {
                "schema_version": "ATIF-v1.2",
                "session_id": "s1",
                "agent": {"name": "claude-code", "model_name": "claude-opus-4-6"},
                "steps": [{"step_id": 1, "source": "user", "message": "hi"}],
            }
        )
    )
    (output_root / "sub.yaml").write_text(
        f"schema: {SUBMISSION_SCHEMA_V1}\nsubmission:\n  id: x\n"
    )
    (output_root / "provenance.json").write_text(
        json.dumps(
            {
                "chi_bench_git_sha": "abc123",
                "image_digest": "sha256:def",
                "judge_model": "claude-opus-4-7",
                "harness_version": "1.0.0",
            }
        )
    )
    return trial


def test_prepare_packet_writes_directory(tmp_path: Path) -> None:
    yaml_path = _write_yaml(tmp_path / "sub.yaml", sub_id="my-team-x")
    output_root = tmp_path / "out"
    output_root.mkdir()
    _seed_trial_tree(output_root)

    cfg = SubmissionConfig.from_yaml(yaml_path)
    cfg.paths.output_root = output_root

    packet_dir = prepare_packet(cfg, out_dir=tmp_path / "packet", date="2026-05-12")

    expected = tmp_path / "packet" / "2026-05-12-my-team-x"
    assert packet_dir == expected
    assert (expected / "submission.json").is_file()
    assert (expected / "results.csv").is_file()
    assert (expected / "sub.yaml").is_file()
    assert (expected / "provenance.json").is_file()
    assert (expected / "README.md").is_file()
    assert not list(expected.glob("*.zip"))


def test_prepare_packet_manifest_has_nested_results(tmp_path: Path) -> None:
    yaml_path = _write_yaml(tmp_path / "sub.yaml", sub_id="x")
    output_root = tmp_path / "out"
    output_root.mkdir()
    _seed_trial_tree(output_root)
    cfg = SubmissionConfig.from_yaml(yaml_path)
    cfg.paths.output_root = output_root

    packet_dir = prepare_packet(cfg, out_dir=tmp_path / "p", date="2026-05-12")

    manifest = json.loads((packet_dir / "submission.json").read_text())
    assert manifest["schema"] == "chi-bench/submission/v1"
    assert manifest["submission"]["id"] == "x"
    assert "submitted_at" in manifest["submission"]
    assert manifest["dataset"]["name"] == "chi-bench"
    assert "overall" in manifest["results"]
    assert "per_domain" in manifest["results"]
    assert "pa_provider" in manifest["results"]["per_domain"]
    assert manifest["results"]["per_domain"]["pa_provider"]["pass_at_1"] == 1.0
    # provenance copied from output_root
    assert manifest["provenance"]["chi_bench_git_sha"] == "abc123"


def test_prepare_packet_results_csv_has_per_domain_rows(tmp_path: Path) -> None:
    import csv as _csv

    yaml_path = _write_yaml(tmp_path / "sub.yaml", sub_id="y")
    output_root = tmp_path / "out"
    output_root.mkdir()
    _seed_trial_tree(output_root)
    cfg = SubmissionConfig.from_yaml(yaml_path)
    cfg.paths.output_root = output_root

    packet_dir = prepare_packet(cfg, out_dir=tmp_path / "p", date="2026-05-12")

    with (packet_dir / "results.csv").open() as fh:
        rows = list(_csv.DictReader(fh))
    assert {r["domain"] for r in rows} == {"overall", "pa_provider"}
    for r in rows:
        assert r["benchmark"] == "chi-bench"
        assert r["dataset_version"] == "chi-bench-v1.0.0"
        assert r["submission_id"] == "y"


def test_prepare_packet_recodes_trajectories(tmp_path: Path) -> None:
    yaml_path = _write_yaml(tmp_path / "sub.yaml", sub_id="t")
    output_root = tmp_path / "out"
    output_root.mkdir()
    _seed_trial_tree(output_root, trial_id="trialA")

    cfg = SubmissionConfig.from_yaml(yaml_path)
    cfg.paths.output_root = output_root
    packet_dir = prepare_packet(cfg, out_dir=tmp_path / "p", date="2026-05-12")

    packed = packet_dir / "trials" / "pa_provider" / "trialA" / "agent" / "trajectory.jsonl.zst"
    assert packed.is_file()
    assert not (
        packet_dir / "trials" / "pa_provider" / "trialA" / "agent" / "trajectory.json"
    ).exists()
    messages = list(iter_packed_messages(packed))
    assert len(messages) == 2  # header + 1 step
    assert "_atif_header" in messages[0]


def test_prepare_packet_refuses_to_overwrite(tmp_path: Path) -> None:
    yaml_path = _write_yaml(tmp_path / "sub.yaml", sub_id="z")
    output_root = tmp_path / "out"
    output_root.mkdir()
    _seed_trial_tree(output_root)
    cfg = SubmissionConfig.from_yaml(yaml_path)
    cfg.paths.output_root = output_root

    prepare_packet(cfg, out_dir=tmp_path / "p", date="2026-05-12")
    with pytest.raises(FileExistsError):
        prepare_packet(cfg, out_dir=tmp_path / "p", date="2026-05-12")
    # --force allows it
    prepare_packet(cfg, out_dir=tmp_path / "p", date="2026-05-12", force=True)
