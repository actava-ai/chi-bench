from pathlib import Path

import pytest

from chi_bench.core.workspace_files import read_workspace_bytes, write_workspace_bytes


@pytest.mark.parametrize("root_kind", ["symlink_ancestor", "relative"])
def test_normal_workspace_roots_can_persist_and_register_artifacts(
    tmp_path, monkeypatch, root_kind
):
    from datetime import UTC, datetime

    from chi_bench.core.context import ServiceContext, WorldClock

    monkeypatch.delenv("CHI_BENCH_WORKSPACE_ROOT", raising=False)
    physical = tmp_path / "physical"
    physical.mkdir()
    if root_kind == "symlink_ancestor":
        alias = tmp_path / "alias"
        alias.symlink_to(physical, target_is_directory=True)
        runtime = alias / "runtime"
    else:
        monkeypatch.chdir(physical)
        runtime = Path("runtime")
    ctx = ServiceContext(runtime_dir=runtime)
    ctx.workspace_root.mkdir(parents=True)
    ctx._clock = WorldClock(datetime(2026, 1, 1, tzinfo=UTC))
    artifact = ctx.persist_workspace_artifact(
        title="Normal note",
        content="public note",
        artifact_type="note",
        owner="payer",
        scope="shared",
        filename="notes/note.txt",
    )
    assert artifact.relative_path == "shared/notes/note.txt"
    assert read_workspace_bytes(ctx.workspace_root, artifact.relative_path) == b"public note"


def test_workspace_read_and_write_are_rooted(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    write_workspace_bytes(root, "CASE-A/payer/note.txt", b"note")
    assert read_workspace_bytes(root, "CASE-A/payer/note.txt") == b"note"
    for path in ("../private", "/run/chi-bench/control-token", "CASE-A/../../private"):
        with pytest.raises(ValueError):
            write_workspace_bytes(root, path, b"overwrite")
        with pytest.raises(ValueError):
            read_workspace_bytes(root, path)


@pytest.mark.parametrize("directory", [False, True])
def test_workspace_symlinks_cannot_read_or_overwrite_private_files(tmp_path, directory):
    root = tmp_path / "workspace"
    root.mkdir()
    private = tmp_path / "private"
    private.mkdir()
    token = private / "token"
    token.write_bytes(b"canary-private-token")
    if directory:
        (root / "link").symlink_to(private, target_is_directory=True)
        relative = "link/token"
    else:
        (root / "link").symlink_to(token)
        relative = "link"
    with pytest.raises((OSError, ValueError)):
        read_workspace_bytes(root, relative)
    with pytest.raises((OSError, ValueError)):
        write_workspace_bytes(root, relative, b"changed")
    assert token.read_bytes() == b"canary-private-token"


def test_workspace_rejects_fifo_without_blocking(tmp_path):
    import os

    root = tmp_path / "workspace"
    root.mkdir()
    os.mkfifo(root / "pipe")
    with pytest.raises(ValueError):
        read_workspace_bytes(root, "pipe")


def test_workspace_reset_preserves_root_mountpoint(tmp_path, monkeypatch):
    from chi_bench.core.context import ServiceContext
    import chi_bench.core.context as context

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "stale").write_text("old")
    ctx = object.__new__(ServiceContext)
    ctx.workspace_root = root
    real_rmtree = context.shutil.rmtree

    def reject_root(path, *args, **kwargs):
        if Path(path) == root:
            raise OSError("cannot remove mount point")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(context.shutil, "rmtree", reject_root)
    ctx._reset_workspace_root()
    assert root.is_dir() and list(root.iterdir()) == []


def test_opened_workspace_file_stays_pinned_when_path_changes(tmp_path):
    from chi_bench.core.workspace_files import open_workspace_file

    root = tmp_path / "workspace"
    root.mkdir()
    path = root / "note"
    path.write_bytes(b"public")
    private = tmp_path / "private"
    private.write_bytes(b"private")
    with open_workspace_file(root, "note") as stream:
        path.unlink()
        path.symlink_to(private)
        assert stream.read() == b"public"


def test_raw_workspace_cleanup_preserves_nested_mount(tmp_path, monkeypatch):
    from chi_bench.core.context import ServiceContext
    import chi_bench.core.context as context

    raw = tmp_path / "raw"
    artifacts = raw / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "old").write_text("old")
    ctx = object.__new__(ServiceContext)
    ctx._raw_workspace_root_override = raw
    real_mount = Path.is_mount
    monkeypatch.setattr(Path, "is_mount", lambda path: path == artifacts or real_mount(path))
    real_rmtree = context.shutil.rmtree

    def reject_mount(path, *args, **kwargs):
        if path == artifacts:
            raise OSError("mounted directory")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(context.shutil, "rmtree", reject_mount)
    ctx._remove_raw_workspace_root()
    assert artifacts.is_dir() and list(artifacts.iterdir()) == []
