#!/usr/bin/env python3
"""Regenerate the dataset-viewer index from the current local task files.

Usage: uv run python scripts/build_tasks_jsonl.py [DATA_ROOT] [-o OUTPUT]

Use --repair-index to update only IDs and fixture counts in an existing index.

Defaults to this checkout's data/ directory and DATA_ROOT/tasks.jsonl.
The downloaded data/scripts/ copy also works with the dataset root as default.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import tomllib
from pathlib import Path

FAMILIES = {"care_management", "marathon", "prior_auth_e2e", "prior_auth_provider", "prior_auth_um"}


def first_heading(md: str) -> str | None:
    for line in md.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return None


def first_paragraph(md: str, max_chars: int = 400) -> str:
    body = re.sub(r"^---\n.*?\n---\n", "", md, count=1, flags=re.DOTALL)
    body = re.sub(r"^#.*$", "", body, flags=re.MULTILINE).strip()
    paragraph = re.sub(r"\s+", " ", body.split("\n\n", 1)[0].strip())
    return paragraph[: max_chars - 1] + "…" if len(paragraph) > max_chars else paragraph


def family_from_path(task_dir: Path, repo_root: Path) -> str:
    return task_dir.relative_to(repo_root).parts[0]


def _task_identity(task_dir: Path, family: str, metadata: dict) -> str:
    if family == "marathon":
        manifest_path = task_dir / "fixtures" / "session_manifest.json"
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        )
        if not isinstance(manifest, dict):
            raise ValueError(f"Session manifest must be an object: {manifest_path}")
        # Session task.toml metadata can retain the seed child task's task_id.
        # The manifest identifies the entire Marathon run.
        task_id = manifest.get("session_id") or f"marathon_{task_dir.name}"
    else:
        task_id = metadata.get("task_id") or task_dir.name
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError(f"Invalid task identity under {task_dir}")
    return task_id


def build_row(task_toml: Path, repo_root: Path) -> dict | None:
    task_dir = task_toml.parent
    family = family_from_path(task_dir, repo_root)
    if family not in FAMILIES:
        return None
    with task_toml.open("rb") as stream:
        toml_data = tomllib.load(stream)
    task_id = _task_identity(task_dir, family, toml_data.get("metadata", {}))
    instruction_path = task_dir / "instruction.md"
    instruction_md = (
        instruction_path.read_text(encoding="utf-8") if instruction_path.exists() else ""
    )
    expectations_path = task_dir / "tests" / "expectations.json"
    expectations = (
        json.loads(expectations_path.read_text(encoding="utf-8"))
        if expectations_path.exists()
        else {}
    )
    fixtures_dir = task_dir / "fixtures"
    fixture_files = sorted(path for path in fixtures_dir.rglob("*") if path.is_file())
    pdf_inputs = [path for path in fixture_files if path.suffix.lower() == ".pdf"]
    relative = task_dir.relative_to(repo_root).as_posix()
    base_url = f"https://huggingface.co/datasets/actava/chi-bench/blob/main/{relative}"
    return {
        "family": family,
        "task_id": task_id,
        "task_kind": expectations.get("task_kind"),
        "task_actor": expectations.get("task_actor"),
        "title": first_heading(instruction_md) or task_id,
        "instruction_excerpt": first_paragraph(instruction_md),
        "expected_target_status": expectations.get("expected_target_status"),
        "expected_payer_route": expectations.get("expected_payer_route"),
        "verifier_contract": expectations.get("verifier_contract"),
        "agent_timeout_sec": toml_data.get("agent", {}).get("timeout_sec"),
        "num_fixture_files": len(fixture_files),
        "num_input_pdfs": len(pdf_inputs),
        "path": relative,
        "instruction_url": f"{base_url}/instruction.md",
        "task_toml_url": f"{base_url}/task.toml",
    }


def build_rows(data_root: Path) -> list[dict]:
    """Index top-level tasks and sessions, excluding packaged session children."""
    rows = []
    identities = {}
    for family in sorted(FAMILIES):
        pattern = "*/task.toml" if family == "marathon" else "tasks/*/task.toml"
        for task_toml in sorted((data_root / family).glob(pattern)):
            row = build_row(task_toml, data_root)
            if row["task_id"] in identities:
                raise ValueError(
                    f"Duplicate task_id {row['task_id']!r}: "
                    f"{identities[row['task_id']]} and {row['path']}"
                )
            identities[row["task_id"]] = row["path"]
            rows.append(row)
    return sorted(rows, key=lambda row: (row["family"], row["task_id"]))


def write_index(rows: list[dict], output: Path) -> None:
    """Replace the index atomically after all source rows validate."""
    output.parent.mkdir(parents=True, exist_ok=True)
    mode = output.stat().st_mode & 0o777 if output.exists() else 0o644
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        temporary.chmod(mode)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def repair_rows(generated: list[dict], existing: list[dict]) -> list[dict]:
    """Keep published metadata while correcting identities and file counts."""
    generated_by_path = {row["path"]: row for row in generated}
    existing_paths = [row.get("path") for row in existing]
    if len(set(existing_paths)) != len(existing_paths) or set(existing_paths) != set(
        generated_by_path
    ):
        raise ValueError("Index repair requires exactly the same task paths")
    return [
        {
            **row,
            "task_id": generated_by_path[row["path"]]["task_id"],
            "num_fixture_files": generated_by_path[row["path"]]["num_fixture_files"],
        }
        for row in existing
    ]


def default_data_root() -> Path:
    parent = Path(__file__).resolve().parents[1]
    return parent / "data" if (parent / "pyproject.toml").is_file() else parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", nargs="?", default=default_data_root(), type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument(
        "--repair-index", action="store_true", help="Only update task_id and num_fixture_files"
    )
    args = parser.parse_args(argv)
    data_root = args.data_root.resolve(strict=True)
    if not data_root.is_dir():
        raise ValueError(f"Dataset root must be a directory: {data_root}")
    rows = build_rows(data_root)
    if not rows:
        raise ValueError(f"No supported tasks found under {data_root}")
    output = args.output or data_root / "tasks.jsonl"
    if args.repair_index:
        existing = [
            json.loads(line)
            for line in output.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        rows = repair_rows(rows, existing)
    write_index(rows, output)
    print(f"Wrote {len(rows)} rows to {output}", file=sys.stderr)
    print(f"Families: {sorted({row['family'] for row in rows})}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
