"""Tests for chi_bench.experiment.trajectory_pack."""

from __future__ import annotations

import io
import json
from pathlib import Path

import zstandard as zstd

from chi_bench.experiment.trajectory_pack import (
    iter_packed_messages,
    pack_trajectory_to_jsonl_zst,
)


def _sample_trajectory() -> dict:
    return {
        "schema_version": "ATIF-v1.2",
        "session_id": "abc-123",
        "agent": {"name": "claude-code", "model_name": "claude-opus-4-7"},
        "steps": [
            {"step_id": 1, "source": "user", "message": "hello"},
            {"step_id": 2, "source": "assistant", "message": "hi back"},
        ],
    }


def test_pack_writes_zstd_jsonl(tmp_path: Path) -> None:
    src = tmp_path / "trajectory.json"
    src.write_text(json.dumps(_sample_trajectory()))
    dst = tmp_path / "trajectory.jsonl.zst"

    pack_trajectory_to_jsonl_zst(src, dst)

    assert dst.exists()
    decompressor = zstd.ZstdDecompressor()
    with dst.open("rb") as fh, decompressor.stream_reader(fh) as reader:
        text = io.TextIOWrapper(reader, encoding="utf-8").read()
    lines = text.strip().split("\n")
    assert len(lines) == 3  # header + 2 steps
    header = json.loads(lines[0])
    assert header == {
        "_atif_header": {
            "schema_version": "ATIF-v1.2",
            "session_id": "abc-123",
            "agent": {"name": "claude-code", "model_name": "claude-opus-4-7"},
        }
    }
    step1 = json.loads(lines[1])
    assert step1["step_id"] == 1


def test_iter_packed_messages_streams(tmp_path: Path) -> None:
    src = tmp_path / "trajectory.json"
    src.write_text(json.dumps(_sample_trajectory()))
    dst = tmp_path / "trajectory.jsonl.zst"
    pack_trajectory_to_jsonl_zst(src, dst)

    messages = list(iter_packed_messages(dst))
    assert len(messages) == 3
    assert "_atif_header" in messages[0]
    assert messages[1]["step_id"] == 1
    assert messages[2]["step_id"] == 2


def test_pack_handles_missing_steps_key(tmp_path: Path) -> None:
    """Some agents may emit trajectories with no 'steps' key — produce header only."""
    src = tmp_path / "trajectory.json"
    src.write_text(json.dumps({"schema_version": "ATIF-v1.2"}))
    dst = tmp_path / "trajectory.jsonl.zst"

    pack_trajectory_to_jsonl_zst(src, dst)

    messages = list(iter_packed_messages(dst))
    assert len(messages) == 1
    assert "_atif_header" in messages[0]
