import subprocess
from pathlib import Path


def _make_complete_data_tree(root: Path) -> None:
    """Create the minimum directory tree that `chi-bench data verify` accepts."""
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
    res = subprocess.run(
        ["uv", "run", "chi-bench", "data", "verify"], capture_output=True, text=True
    )
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
    res = subprocess.run(
        ["uv", "run", "chi-bench", "data", "verify"], capture_output=True, text=True
    )
    assert res.returncode != 0
    assert "marathon" in (res.stdout + res.stderr).lower()
