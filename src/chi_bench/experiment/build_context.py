"""Explicit, link-free Docker build contexts for remote engine transports."""

from __future__ import annotations

import os
import tarfile
from pathlib import Path

_FILES = ("pyproject.toml", "uv.lock", "README.md", "LICENSE", ".dockerignore")
_TREES = (
    "src",
    "docker",
    "data/prior_auth_provider/shared/worlds",
    "data/prior_auth_provider/tasks",
    "data/prior_auth_um/tasks",
    "data/care_management/shared/worlds",
    "data/care_management/tasks",
    "data/prior_auth_e2e/worlds",
    "data/prior_auth_e2e/tasks",
    "data/marathon",
    "data/skills/managed-care-operations-handbook",
)
_DATA_FILES = ("data/care_management/shared/tool_reference.md",)
_EXCLUDED_NAMES = frozenset(
    {
        ".git",
        ".env",
        "logs",
        "__pycache__",
        ".cache",
        ".venv",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "node_modules",
        ".DS_Store",
    }
)


def _excluded(relative: Path) -> bool:
    return any(
        part in _EXCLUDED_NAMES or part.startswith(".env.") or part.endswith(".egg-info")
        for part in relative.parts
    ) or relative.suffix in {".pyc", ".pyo", ".pyd"}


def _physical_source(root: Path, relative: Path) -> Path | None:
    """Resolve only the checkout's known data link; reject all other links."""
    source = root
    for index, part in enumerate(relative.parts):
        source = source / part
        if source.is_symlink():
            if index == 0 and part == "data":
                source = source.resolve(strict=True)
            else:
                return None
    return source


def _members(root: Path) -> list[tuple[Path, Path]]:
    members: dict[Path, Path] = {}
    for name in (*_FILES, *_DATA_FILES):
        relative = Path(name)
        source = _physical_source(root, relative)
        if source is not None and source.is_file() and not _excluded(relative):
            members[relative] = source
    for name in _TREES:
        relative = Path(name)
        source = _physical_source(root, relative)
        if source is None or not source.is_dir():
            continue
        members[relative] = source
        for directory, dirs, files in os.walk(source, followlinks=False):
            parent = Path(directory)
            parent_relative = relative / parent.relative_to(source)
            dirs[:] = sorted(
                child
                for child in dirs
                if not (parent / child).is_symlink() and not _excluded(parent_relative / child)
            )
            for child in dirs:
                members[parent_relative / child] = parent / child
            for child in sorted(files):
                path = parent / child
                child_relative = parent_relative / child
                if not path.is_symlink() and path.is_file() and not _excluded(child_relative):
                    members[child_relative] = path
    return sorted(members.items())


def create_build_context_archive(repo_root: str | Path, target: str | Path) -> Path:
    """Archive Dockerfile inputs, excluding local logs, credentials and links.

    Dataset fixtures are trusted backend build inputs, admitted only beneath
    the exact data subtrees referenced by ``docker/Dockerfile``. A root
    ``data`` symlink is resolved for worktrees; nested links are excluded.
    Tar entries contain regular files or directories only.
    """
    root = Path(repo_root).resolve(strict=True)
    target = Path(target)
    members = _members(root)
    target.parent.mkdir(parents=True, exist_ok=True)

    def metadata(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if not info.isfile() and not info.isdir():
            return None
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        return info

    with tarfile.open(target, "w:gz", dereference=True) as archive:
        for relative, source in members:
            archive.add(source, arcname=relative.as_posix(), recursive=False, filter=metadata)
    return target
