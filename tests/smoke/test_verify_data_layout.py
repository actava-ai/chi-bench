import subprocess
from pathlib import Path


def _make_complete_data_tree(root: Path) -> None:
    """Create the minimum directory tree that `cb data verify` accepts."""
    for domain, n in [
        ("prior_auth_provider", 25),
        ("prior_auth_um", 25),
        ("care_management", 25),
    ]:
        (root / domain / "shared" / "worlds").mkdir(parents=True, exist_ok=True)
        (root / domain / "registry.json").write_text("{}")
        for i in range(n):
            tdir = root / domain / "tasks" / f"task_{i:03d}"
            tdir.mkdir(parents=True, exist_ok=True)
            (tdir / "task.toml").write_text('version = "1.0"\n')
    for i in range(23):
        tdir = root / "prior_auth_e2e" / "tasks" / f"e2e_task_{i:03d}"
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "task.toml").write_text("")
    (root / "prior_auth_e2e" / "worlds").mkdir(parents=True, exist_ok=True)
    for dom in ("prior_auth_provider", "prior_auth_um", "care_management"):
        (root / "marathon" / dom).mkdir(parents=True, exist_ok=True)
        (root / "marathon" / dom / "task.toml").write_text("")
    (root / "skills" / "managed-care-operations-handbook" / "references" / "platform").mkdir(
        parents=True, exist_ok=True
    )
    (root / "skills" / "managed-care-operations-handbook" / "SKILL.md").write_text("# handbook")


def test_data_verify_succeeds_on_complete_tree(tmp_path, monkeypatch):
    tree_root = tmp_path / "tree"
    tree_root.mkdir()
    _make_complete_data_tree(tree_root)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    # data/ in current dir
    (cwd / "data").symlink_to(tree_root)
    res = subprocess.run(["uv", "run", "cb", "data", "verify"], capture_output=True, text=True)
    assert res.returncode == 0, f"stderr: {res.stderr}"
    assert "OK" in (res.stdout + res.stderr)


def test_data_verify_fails_on_missing_marathon(tmp_path, monkeypatch):
    tree_root = tmp_path / "tree"
    tree_root.mkdir()
    _make_complete_data_tree(tree_root)
    # Remove marathon to break the layout
    import shutil

    shutil.rmtree(tree_root / "marathon")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    (cwd / "data").symlink_to(tree_root)
    res = subprocess.run(["uv", "run", "cb", "data", "verify"], capture_output=True, text=True)
    assert res.returncode != 0
    assert "marathon" in (res.stdout + res.stderr).lower()


def _make_baked_image_tree(root: Path) -> None:
    """Create the flat layout used inside the runtime Docker image.

    Mirrors what docker/Dockerfile produces at /opt/chi-bench: all four
    task families flattened under tasks/, with a marathon/ subdir and a
    sibling worlds/ dir.
    """
    tasks_dir = root / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    counts = {
        "prior_auth_provider": 25,
        "prior_auth_um": 25,
        "care_management": 25,
        "prior_auth_e2e": 23,
    }
    idx = 0
    for domain, n in counts.items():
        for i in range(n):
            tdir = tasks_dir / f"{domain[:3]}_{idx:03d}_task"
            tdir.mkdir(parents=True, exist_ok=True)
            (tdir / "task.toml").write_text("")
            idx += 1
    for dom in ("prior_auth_provider", "prior_auth_um", "care_management"):
        (tasks_dir / "marathon" / dom).mkdir(parents=True, exist_ok=True)
        (tasks_dir / "marathon" / dom / "task.toml").write_text("")
    (root / "worlds").mkdir(parents=True, exist_ok=True)
    (root / "worlds" / "stub.json").write_text("{}")


def test_data_verify_succeeds_on_baked_layout(tmp_path, monkeypatch):
    """In the baked-image layout, the verifier counts the flat tasks/ dir.

    The handbook check inside the baked-layout branch points at the absolute
    runtime path (/workspace/skills/...), which won't exist on the host. We
    stage that path under tmp_path and patch Path resolution via a
    symlink-style trick: monkeypatch the verifier to look at our test
    handbook by chdir-ing then symlinking — instead, the simplest robust
    check is to assert the verifier emits a single failure that's _only_
    the handbook, proving the flat-tasks/marathon/worlds branches pass.
    """
    root = tmp_path / "baked"
    root.mkdir()
    _make_baked_image_tree(root)
    res = subprocess.run(
        ["uv", "run", "cb", "data", "verify", "--data-dir", str(root)],
        capture_output=True,
        text=True,
    )
    out = res.stdout + res.stderr
    # On the host, /workspace/skills/... won't exist, so verify is expected
    # to fail with ONLY that single missing entry. That proves the baked
    # layout branch is reached and tasks/marathon/worlds all validated.
    if res.returncode == 0:
        assert "OK" in out
    else:
        assert "managed-care-operations-handbook" in out
        # Make sure no other path is flagged
        assert "expected" not in out, f"unexpected count mismatch: {out}"
        assert "tasks" not in out.replace("managed-care-operations-handbook", ""), (
            f"unexpected tasks-related miss: {out}"
        )
