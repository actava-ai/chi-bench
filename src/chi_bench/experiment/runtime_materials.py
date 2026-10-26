"""Bind trusted runtime inputs to source bytes before the simulator bootstraps.

This module uses only the standard library so the host can upload and execute
it against an existing image, including images built before this guard existed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCHEMA = "chi-bench/runtime-materials/v1"
_INCIDENTAL = frozenset(
    {".cache", ".git", ".DS_Store", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
)


def infer_data_root(path: Path) -> Path | None:
    """Recognize a source dataset before task mirroring changes its location."""
    path = path.resolve()
    for candidate in (path, *path.parents):
        if (candidate / "skills/managed-care-operations-handbook").is_dir() and any(
            (candidate / family).is_dir()
            for family in (
                "prior_auth_provider",
                "prior_auth_um",
                "care_management",
                "prior_auth_e2e",
                "marathon",
            )
        ):
            return candidate
    return None


def _file_digest(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"Missing regular runtime material: {path}")
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ValueError(f"Runtime material changed while hashing: {path}")
    return digest.hexdigest()


def _tree_digest(root: Path) -> str:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"Missing regular runtime material directory: {root}")
    entries = []

    def visit(directory: Path) -> None:
        for path in sorted(directory.iterdir()):
            if path.name in _INCIDENTAL:
                continue
            relative = path.relative_to(root).as_posix()
            if path.is_dir() and not path.is_symlink():
                # Harbor adds an empty environment/ discovery stub. Runtime
                # input identity binds file names and bytes, not empty dirs.
                visit(path)
            else:
                # File aliases and regular copies identify the same runtime
                # input bytes. Directory aliases cannot add hidden subtrees.
                entries.append([relative, "file", _file_digest(path)])

    visit(root)
    return hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()


def _world_sources(task_dir: Path, data_root: Path) -> dict[str, Path]:
    fixtures = task_dir / "fixtures"
    session = fixtures / "session_manifest.json"
    if session.is_file():
        record = json.loads(session.read_text())
        children = [fixtures / "tasks" / row["task_id"] for row in record["tasks"]]
        first = json.loads((children[0] / "manifest.json").read_text())
        if first.get("task_actor") != "care_manager":
            if Path(record["world_id"]).name != record["world_id"] or record["world_id"] in {
                ".",
                "..",
            }:
                raise ValueError("Invalid governing world identity")
            return {
                record["world_id"]: data_root
                / "prior_auth_provider/shared/worlds"
                / (record["world_id"] + ".json")
            }
    else:
        children = [fixtures]
    worlds = {}
    for child in children:
        if (child / "world.json").is_file() or (child / "scenario.json").is_file():
            continue
        manifest = child / "manifest.json"
        if not manifest.is_file():
            continue
        record = json.loads(manifest.read_text())
        world_id = record["world_id"]
        if Path(world_id).name != world_id or world_id in {".", ".."}:
            raise ValueError("Invalid governing world identity")
        family = (
            "prior_auth_e2e/worlds"
            if record.get("task_kind") == "provider_to_payer_e2e"
            else "care_management/shared/worlds"
            if record.get("task_actor") == "care_manager"
            else "prior_auth_provider/shared/worlds"
        )
        worlds[world_id] = data_root / family / (world_id + ".json")
    return worlds


def source_task_path(data_root: Path, task_id: str) -> Path:
    """Find the selected task in the independently accepted source bundle."""
    candidates = (
        [data_root / task_id]
        if task_id.startswith("marathon/")
        else [
            data_root / family / "tasks" / task_id
            for family in (
                "prior_auth_provider",
                "prior_auth_um",
                "care_management",
                "prior_auth_e2e",
            )
        ]
    )
    matches = [path for path in candidates if (path / "fixtures").is_dir()]
    if len(matches) != 1:
        raise ValueError("Cannot identify one selected task in the accepted data root")
    return matches[0]


def build_runtime_material_manifest(
    data_root: Path,
    task_dir: Path,
    task_id: str,
    *,
    worlds_root: str = "/opt/chi-bench/worlds",
    tasks_root: str = "/opt/chi-bench/tasks",
) -> dict:
    """Describe selected task, governing worlds, handbook and tool-reference bytes."""
    data_root, task_dir = Path(data_root).resolve(strict=True), Path(task_dir).resolve(strict=True)
    trees = {
        str(Path(tasks_root) / task_id): _tree_digest(task_dir),
        "/workspace/skills/managed-care-operations-handbook": _tree_digest(
            data_root / "skills/managed-care-operations-handbook"
        ),
    }
    files = {
        str(Path(worlds_root) / (world_id + ".json")): _file_digest(source)
        for world_id, source in _world_sources(task_dir, data_root).items()
    }
    # The entrypoint later makes the task's reference into a proxy and may
    # rewrite separators. Check that source through the task hash, before
    # either transformation. Only tasks without it use the baked CM default.
    if not (task_dir / "tool_reference.md").is_file():
        files["/opt/chi-bench-task-assets/tool_reference.md"] = _file_digest(
            data_root / "care_management/shared/tool_reference.md"
        )
    return {"schema": SCHEMA, "trees": trees, "files": files}


def verify_runtime_material_manifest(manifest: dict, *, filesystem_root: Path = Path("/")) -> None:
    if manifest.get("schema") != SCHEMA or not manifest.get("trees"):
        raise ValueError("Invalid runtime material manifest")
    for kind, digest in (("trees", _tree_digest), ("files", _file_digest)):
        for absolute, expected in manifest[kind].items():
            path = Path(absolute)
            if not path.is_absolute() or ".." in path.parts:
                raise ValueError("Invalid runtime material path")
            try:
                observed = digest(filesystem_root / path.relative_to("/"))
            except (OSError, ValueError) as exc:
                raise ValueError(
                    f"Runtime material mismatch: {absolute}; rebuild from the accepted data root"
                ) from exc
            if observed != expected:
                raise ValueError(
                    f"Runtime material mismatch: {absolute}; rebuild from the accepted data root"
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--filesystem-root", type=Path, default=Path("/"))
    args = parser.parse_args()
    verify_runtime_material_manifest(
        json.loads(args.manifest.read_text()), filesystem_root=args.filesystem_root
    )


if __name__ == "__main__":
    main()
