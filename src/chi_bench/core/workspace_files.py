"""Rooted file operations for the agent-writable shared workspace.

Directory descriptors pin every component while O_NOFOLLOW rejects links,
including links swapped concurrently by another container.
"""

from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from pathlib import Path


def workspace_relative(root: Path, path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        try:
            path = path.relative_to(root.absolute())
        except ValueError as exc:
            raise ValueError("Workspace path must stay inside the workspace") from exc
    if not path.parts or any(part in ("..", ".") for part in path.parts):
        raise ValueError("Invalid workspace path")
    return path


@contextmanager
def _parent(root: Path, path: str | Path, *, create: bool = False):
    relative = workspace_relative(root, path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(root, flags)
    try:
        for component in relative.parts[:-1]:
            if create:
                try:
                    os.mkdir(component, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor, relative.name
    finally:
        os.close(descriptor)


def _regular(descriptor: int) -> None:
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        raise ValueError("Workspace artifact must be a regular file")


def open_workspace_file(root: Path, path: str | Path):
    """Open a regular file beneath root; the caller owns the returned stream."""
    with _parent(root, path) as (parent, name):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            _regular(descriptor)
        except BaseException:
            os.close(descriptor)
            raise
        return os.fdopen(descriptor, "rb")


def read_workspace_bytes(root: Path, path: str | Path) -> bytes:
    # Text registration and internal copies must not buffer arbitrary sparse
    # files into the trusted process. Downloads use the streaming reader.
    maximum = 32 * 1024 * 1024
    with open_workspace_file(root, path) as stream:
        if os.fstat(stream.fileno()).st_size > maximum:
            raise ValueError("Workspace artifact exceeds the 32 MiB processing limit")
        content = stream.read(maximum + 1)
        if len(content) > maximum:
            raise ValueError("Workspace artifact exceeds the 32 MiB processing limit")
        return content


def write_workspace_bytes(root: Path, path: str | Path, content: bytes) -> None:
    with _parent(root, path, create=True) as (parent, name):
        descriptor = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o644, dir_fd=parent
        )
        with os.fdopen(descriptor, "wb") as stream:
            _regular(stream.fileno())
            stream.truncate(0)
            stream.write(content)


def validate_workspace_path(root: Path, path: str | Path) -> Path:
    """Validate metadata paths; use rooted reads/writes for actual I/O."""
    relative = workspace_relative(root, path)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Workspace paths must not contain symbolic links")
    return root / relative


def stat_workspace_file(root: Path, path: str | Path) -> os.stat_result:
    with _parent(root, path) as (parent, name):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            _regular(descriptor)
            return os.fstat(descriptor)
        finally:
            os.close(descriptor)


def remove_workspace_entry(root: Path, path: str | Path, *, directory: bool = False) -> None:
    with _parent(root, path) as (parent, name):
        if directory:
            os.rmdir(name, dir_fd=parent)
        else:
            os.unlink(name, dir_fd=parent)
