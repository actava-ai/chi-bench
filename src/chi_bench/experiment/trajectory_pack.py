"""Pack agent trajectory.json files into streaming-friendly JSONL+zstd.

Input: a JSON file with the ATIF-v1.2 shape
    {"schema_version": ..., "session_id": ..., "agent": {...}, "steps": [...]}

Output: zstd-compressed JSONL where line 1 is a header object
    {"_atif_header": {schema_version, session_id, agent}}
and subsequent lines are individual step objects.

The format is optimized for streaming validation (line-by-line json.loads)
without buffering the full trajectory in memory.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import zstandard as zstd

_ZSTD_LEVEL = 19
_HEADER_KEYS = ("schema_version", "session_id", "agent")


def pack_trajectory_to_jsonl_zst(src: Path, dst: Path) -> None:
    """Re-serialize ``src`` (ATIF JSON) into ``dst`` (zstd-compressed JSONL).

    Header metadata (everything except ``steps``) lands on line 1 under the
    ``_atif_header`` key. Each entry of ``steps`` becomes a subsequent line.
    """
    payload: dict[str, Any] = json.loads(src.read_text(encoding="utf-8"))
    header = {k: payload[k] for k in _HEADER_KEYS if k in payload}
    steps: list[dict[str, Any]] = payload.get("steps", []) or []

    compressor = zstd.ZstdCompressor(level=_ZSTD_LEVEL)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("wb") as fh, compressor.stream_writer(fh) as writer:
        writer.write(
            (json.dumps({"_atif_header": header}, separators=(",", ":")) + "\n").encode("utf-8")
        )
        for step in steps:
            writer.write((json.dumps(step, separators=(",", ":")) + "\n").encode("utf-8"))


def iter_packed_messages(path: Path) -> Iterator[dict[str, Any]]:
    """Stream-decode a packed trajectory, yielding one dict per line.

    Used by both the validator (integrity check) and any consumer that wants
    to inspect a trajectory without writing the decompressed bytes.
    """
    decompressor = zstd.ZstdDecompressor()
    with path.open("rb") as fh, decompressor.stream_reader(fh) as reader:
        text_stream = io.TextIOWrapper(reader, encoding="utf-8")
        for line in text_stream:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)
