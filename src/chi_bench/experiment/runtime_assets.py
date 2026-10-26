"""Publish the public files an isolated agent needs for one trial."""

from __future__ import annotations

import shutil
from pathlib import Path


def _reject_symlink_components(path: Path) -> None:
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError("Public asset paths must not contain a symlink")


def _require_regular_file(path: Path) -> None:
    _reject_symlink_components(path)
    if not path.is_file():
        raise ValueError("Public asset source must be a regular file")


def publish_agent_assets(
    task_dir: str | Path,
    handbook_dir: str | Path,
    tool_reference_path: str | Path,
    output_dir: str | Path,
) -> None:
    """Copy selected task documents and the handbook into an empty public mount.

    ``tool_reference_path`` is the selected, already-rewritten regular file;
    it can live outside ``task_dir``. No task fixtures, worlds, or other task
    files are traversed or copied. Source paths, handbook entries, and the
    destination must not contain symlinks. A nonempty destination is rejected
    so stale files cannot survive publication into a reused mount.
    """
    task_dir = Path(task_dir).absolute()
    handbook_dir = Path(handbook_dir).absolute()
    tool_reference_path = Path(tool_reference_path).absolute()
    output_dir = Path(output_dir).absolute()
    for directory in (task_dir, handbook_dir):
        _reject_symlink_components(directory)
        if not directory.is_dir():
            raise ValueError("Public asset source must be a directory")

    handbook_entries = sorted(handbook_dir.rglob("*"))
    for source in handbook_entries:
        _reject_symlink_components(source)
        if not source.is_dir() and not source.is_file():
            raise ValueError("Handbook assets must be regular files or directories")
    instruction = task_dir / "instruction.md"
    _require_regular_file(instruction)
    _require_regular_file(tool_reference_path)

    _reject_symlink_components(output_dir)
    if output_dir.is_relative_to(task_dir) or output_dir.is_relative_to(handbook_dir):
        raise ValueError("Public asset destination must be outside the source directories")
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise ValueError("Public asset destination must be an empty directory")

    tools = output_dir / "tools"
    handbook = output_dir / "skills" / "managed-care-operations-handbook"
    tools.mkdir(parents=True)
    handbook.mkdir(parents=True)
    shutil.copyfile(instruction, tools / "instruction.md")
    shutil.copyfile(tool_reference_path, tools / "tool_reference.md")
    for source in handbook_entries:
        destination = handbook / source.relative_to(handbook_dir)
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            shutil.copyfile(source, destination)
