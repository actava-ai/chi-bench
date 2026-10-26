import tarfile

import pytest


def synthetic_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    files = {
        "pyproject.toml": "[project]\nname='synthetic'\n",
        "uv.lock": "version = 1\n",
        "README.md": "public readme",
        "LICENSE": "public license",
        ".dockerignore": "**\n!src/**\n",
        "src/chi_bench/__init__.py": "public source",
        "docker/Dockerfile": "FROM scratch",
        "docker/entrypoint.sh": "#!/bin/sh\ntrue\n",
        "data/prior_auth_provider/shared/worlds/world.json": "backend world",
        "data/prior_auth_provider/tasks/task/fixtures/expectations.json": "backend fixture",
        "data/care_management/shared/tool_reference.md": "public tools",
        "data/skills/managed-care-operations-handbook/SKILL.md": "public skill",
    }
    for relative, contents in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
    (root / "docker/entrypoint.sh").chmod(0o755)
    return root


def archive_files(archive):
    with tarfile.open(archive) as stream:
        assert all(member.isfile() or member.isdir() for member in stream.getmembers())
        return {
            member.name: stream.extractfile(member).read() for member in stream if member.isfile()
        }


def test_build_context_archives_only_explicit_build_inputs(tmp_path):
    from chi_bench.experiment.build_context import create_build_context_archive

    root = synthetic_repo(tmp_path)
    denied = [
        ".env",
        "logs/trial/private.txt",
        ".git/config",
        "private-notes.txt",
        "src/chi_bench/.env.local",
        "src/chi_bench/__pycache__/private.pyc",
        "src/chi_bench/.cache/private.txt",
        "src/chi_bench/logs/private.txt",
        "docker/.git/config",
        "data/unreferenced-dataset/fixtures.json",
        "data/prior_auth_provider/tasks/task/.env",
        "data/skills/managed-care-operations-handbook/.cache/token",
    ]
    for relative in denied:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("PRIVATE_SENTINEL")

    archive = create_build_context_archive(root, tmp_path / "context.tar.gz")
    files = archive_files(archive)

    assert files["pyproject.toml"].startswith(b"[project]")
    assert files["README.md"] == b"public readme"
    assert files["docker/Dockerfile"] == b"FROM scratch"
    assert files["data/care_management/shared/tool_reference.md"] == b"public tools"
    assert "data/prior_auth_provider/tasks/task/fixtures/expectations.json" in files
    assert all(relative not in files for relative in denied)
    assert all(b"PRIVATE_SENTINEL" not in contents for contents in files.values())
    with tarfile.open(archive) as stream:
        assert stream.getmember("docker/entrypoint.sh").mode & 0o111


def test_build_context_resolves_only_the_known_root_data_symlink(tmp_path):
    from chi_bench.experiment.build_context import create_build_context_archive

    root = synthetic_repo(tmp_path)
    external_data = tmp_path / "downloaded-data"
    (root / "data").rename(external_data)
    (root / "data").symlink_to(external_data, target_is_directory=True)

    archive = create_build_context_archive(root, tmp_path / "context.tar.gz")
    files = archive_files(archive)

    assert "data/prior_auth_provider/tasks/task/fixtures/expectations.json" in files
    assert "data/skills/managed-care-operations-handbook/SKILL.md" in files


@pytest.mark.parametrize("linked_kind", ["file", "directory", "source_root"])
def test_build_context_excludes_other_symlinked_sources(tmp_path, linked_kind):
    from chi_bench.experiment.build_context import create_build_context_archive

    root = synthetic_repo(tmp_path)
    private = tmp_path / "private"
    private.mkdir()
    (private / "secrets.txt").write_text("PRIVATE_SENTINEL")
    if linked_kind == "file":
        (root / "src/chi_bench/linked.py").symlink_to(private / "secrets.txt")
    elif linked_kind == "directory":
        (root / "data/prior_auth_provider/tasks/linked").symlink_to(
            private, target_is_directory=True
        )
    else:
        (root / "src").rename(tmp_path / "original-src")
        (root / "src").symlink_to(private, target_is_directory=True)

    archive = create_build_context_archive(root, tmp_path / "context.tar.gz")
    files = archive_files(archive)
    assert all(b"PRIVATE_SENTINEL" not in contents for contents in files.values())
    assert not any("linked" in relative for relative in files)


def test_build_context_never_follows_a_symlink_in_an_allowed_ancestor(tmp_path):
    from chi_bench.experiment.build_context import create_build_context_archive

    root = synthetic_repo(tmp_path)
    private = tmp_path / "private-provider"
    (private / "tasks").mkdir(parents=True)
    (private / "tasks/secret.txt").write_text("PRIVATE_SENTINEL")
    provider = root / "data/prior_auth_provider"
    provider.rename(tmp_path / "original-provider")
    provider.symlink_to(private, target_is_directory=True)

    archive = create_build_context_archive(root, tmp_path / "context.tar.gz")
    assert all(b"PRIVATE_SENTINEL" not in contents for contents in archive_files(archive).values())
