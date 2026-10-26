"""Adversarial probes use synthetic private files, never benchmark answers."""

import threading

import pytest

from chi_bench.core.context import ServiceContext
from chi_bench.core.workspace_files import read_workspace_bytes, write_workspace_bytes


@pytest.mark.parametrize(
    "case_id,filename",
    [
        (None, "../../../private/canary"),
        ("../../private", "canary"),
        ("/private", "canary"),
        ("CASE-A", "../../../private/canary"),
    ],
)
@pytest.mark.parametrize("binary", [False, True])
def test_service_rejects_escape_before_mutation(tmp_path, case_id, filename, binary):
    root = tmp_path / "workspace"
    root.mkdir()
    private = tmp_path / "private"
    private.mkdir()
    canary = private / "canary"
    canary.write_bytes(b"private-canary")
    ctx = object.__new__(ServiceContext)
    ctx.workspace_root = root
    kwargs = dict(
        title="probe", artifact_type="note", owner="payer", case_id=case_id, filename=filename
    )
    with pytest.raises(ValueError):
        if binary:
            ctx.persist_workspace_artifact_bytes(file_bytes=b"overwrite", **kwargs)
        else:
            ctx.persist_workspace_artifact(content="overwrite", **kwargs)
    assert canary.read_bytes() == b"private-canary"


def test_concurrent_directory_symlink_swaps_cannot_read_private_files(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    public = root / "public"
    public.mkdir()
    (public / "note").write_bytes(b"public")
    private = tmp_path / "private"
    private.mkdir()
    (private / "note").write_bytes(b"private-canary")
    alias = root / "switch"
    alias.mkdir()
    (alias / "note").write_bytes(b"public")
    parked = root / "parked"
    done = threading.Event()

    def swap():
        while not done.is_set():
            alias.rename(parked)
            alias.symlink_to(private, target_is_directory=True)
            alias.unlink()
            parked.rename(alias)

    thread = threading.Thread(target=swap)
    thread.start()
    try:
        for _ in range(1000):
            try:
                assert read_workspace_bytes(root, "switch/note") == b"public"
            except (OSError, ValueError):
                pass
        assert (private / "note").read_bytes() == b"private-canary"
    finally:
        done.set()
        thread.join(timeout=5)
    assert not thread.is_alive()


def test_sparse_text_artifact_is_rejected_before_buffering(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    with (root / "huge").open("wb") as stream:
        stream.truncate(1024 * 1024 * 1024)
    with pytest.raises(ValueError, match="processing limit"):
        read_workspace_bytes(root, "huge")


def test_concurrent_file_symlink_swaps_cannot_read_or_overwrite_private_files(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    private = tmp_path / "private"
    private.write_bytes(b"private-canary")
    alias = root / "switch"
    alias.write_bytes(b"public")
    next_file = root / "next"
    done = threading.Event()
    failures = []

    def swap():
        try:
            while not done.is_set():
                next_file.symlink_to(private)
                next_file.replace(alias)
                next_file.write_bytes(b"public")
                next_file.replace(alias)
        except BaseException as error:
            failures.append(error)

    thread = threading.Thread(target=swap)
    thread.start()
    try:
        for _ in range(1000):
            try:
                assert read_workspace_bytes(root, "switch") in (b"public", b"")
            except (OSError, ValueError):
                pass
            try:
                write_workspace_bytes(root, "switch", b"public")
            except (OSError, ValueError):
                pass
        assert private.read_bytes() == b"private-canary"
    finally:
        done.set()
        thread.join(timeout=5)
    assert not failures
    assert not thread.is_alive()
