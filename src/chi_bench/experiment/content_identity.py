"""Read-only content identity for the source assets selected for a submission.

The digest binds sorted relative paths, directory entries, file sizes and file
SHA-256 values. Absolute checkout paths, mtimes, and file ownership are absent.
The expected digest comes from the operator's accepted bundle; computing a new
digest never accepts it or writes a pin into the source dataset.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

IDENTITY_SCHEMA = "chi-bench/dataset-content/v1"
DOMAIN_ROOTS = {
    "pa_provider": "prior_auth_provider",
    "pa_um": "prior_auth_um",
    "cm": "care_management",
}
_ALIASES = {
    "pa": "pa_provider",
    "pa-provider": "pa_provider",
    "prior_auth_provider": "pa_provider",
    "um": "pa_um",
    "pa-um": "pa_um",
    "prior_auth_um": "pa_um",
    "care_management": "cm",
    **{name: name for name in DOMAIN_ROOTS},
}
_INCIDENTAL = frozenset(
    {".cache", ".git", ".DS_Store", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
)


@dataclass(frozen=True)
class DatasetContentIdentity:
    content_sha256: str
    file_count: int
    domains: tuple[str, ...]
    schema: str = IDENTITY_SCHEMA


def validate_content_sha256(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("content_sha256 must be an explicit 64-character lowercase SHA-256")
    return value


def canonical_domains(domains: Iterable[str]) -> tuple[str, ...]:
    selected = set()
    for domain in domains:
        canonical = _ALIASES.get(str(domain).strip().lower())
        if canonical is None:
            raise ValueError(f"Unsupported content identity domain: {domain!r}")
        selected.add(canonical)
    if not selected:
        raise ValueError("Content identity requires at least one selected domain")
    return tuple(sorted(selected))


def _file_entry(path: Path, relative: str) -> dict[str, object]:
    before = path.stat(follow_symlinks=False)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat(follow_symlinks=False)
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ValueError(f"Dataset content changed while hashing: {relative}")
    return {"path": relative, "kind": "file", "size": after.st_size, "sha256": digest.hexdigest()}


def compute_dataset_identity(
    data_root: str | Path, domains: Iterable[str]
) -> DatasetContentIdentity:
    """Hash selected task families, runtime shared assets, and the handbook.

    Each selected family includes registry.json, every tasks/ entry, and every
    shared/ entry. All domains use care_management/shared/tool_reference.md.
    UM additionally binds Provider worlds because the source runtime image
    currently loads PA worlds from that tree. The handbook and version pin are
    always included. Incidental cache/VCS/macOS entries are excluded by name.
    Relative file aliases within the source root bind both their link text and
    resolved bytes (the CM world uses one). Directory, absolute, external and
    dangling links fail. The checkout's data-root symlink may resolve normally.
    """
    root = Path(data_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Dataset root must be a directory")
    selected = canonical_domains(domains)
    required_files = {".chi-bench-version", "care_management/shared/tool_reference.md"}
    required_trees = {"skills/managed-care-operations-handbook"}
    for domain in selected:
        family = DOMAIN_ROOTS[domain]
        required_files.add(f"{family}/registry.json")
        required_trees.update({f"{family}/tasks", f"{family}/shared", f"{family}/shared/worlds"})
    if "pa_um" in selected:
        required_trees.add("prior_auth_provider/shared/worlds")

    entries: dict[str, dict[str, object]] = {}

    def visit(path: Path) -> int:
        relative = path.relative_to(root).as_posix()
        if path.name in _INCIDENTAL:
            return 0
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise ValueError(f"Missing or unreadable dataset asset: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            target = path.readlink()
            try:
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise ValueError(f"Linked dataset asset cannot resolve: {relative}") from exc
            if target.is_absolute() or not resolved.is_relative_to(root) or not resolved.is_file():
                raise ValueError(
                    f"Linked dataset asset must be an internal relative file: {relative}"
                )
            entry = _file_entry(resolved, relative)
            entry.update(kind="file-alias", target=target.as_posix())
            if path.readlink() != target or path.resolve(strict=True) != resolved:
                raise ValueError(f"Linked dataset asset changed while hashing: {relative}")
            entries[relative] = entry
            return 1
        if stat.S_ISREG(metadata.st_mode):
            if relative not in entries:
                entries[relative] = _file_entry(path, relative)
            return 1
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"Non-regular dataset asset is not accepted: {relative}")
        entries[relative] = {"path": relative, "kind": "directory"}
        return sum(visit(child) for child in sorted(path.iterdir(), key=lambda item: item.name))

    def checked_path(relative: str) -> Path:
        current = root
        for part in Path(relative).parts:
            current /= part
            if current.is_symlink() and current != root / relative:
                raise ValueError(f"Linked dataset asset is not accepted: {relative}")
        return current

    for relative in sorted(required_files):
        path = checked_path(relative)
        if not path.is_file():
            raise ValueError(f"Missing required dataset file: {relative}")
        visit(path)
    for relative in sorted(required_trees):
        path = checked_path(relative)
        if not path.is_dir():
            raise ValueError(f"Missing required dataset directory: {relative}")
        if not visit(path):
            raise ValueError(f"Required dataset directory has no files: {relative}")

    document = {
        "schema": IDENTITY_SCHEMA,
        "domains": selected,
        "entries": [entries[name] for name in sorted(entries)],
    }
    encoded = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return DatasetContentIdentity(
        content_sha256=hashlib.sha256(encoded).hexdigest(),
        file_count=sum(entry["kind"] in {"file", "file-alias"} for entry in entries.values()),
        domains=selected,
    )


def require_dataset_identity(
    data_root: str | Path, domains: Iterable[str], expected: str
) -> DatasetContentIdentity:
    validate_content_sha256(expected)
    actual = compute_dataset_identity(data_root, domains)
    if actual.content_sha256 != expected:
        raise ValueError(
            f"dataset content mismatch: expected {expected}, observed {actual.content_sha256}; "
            "restore the accepted assets or explicitly select a separately reviewed bundle"
        )
    return actual
