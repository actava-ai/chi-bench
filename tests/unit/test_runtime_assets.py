import ast
import shlex
from pathlib import Path

import pytest


def test_agent_assets_are_an_allowlist_and_regular_copies(tmp_path):
    from chi_bench.experiment.runtime_assets import publish_agent_assets

    task = tmp_path / "task"
    (task / "fixtures" / "judge").mkdir(parents=True)
    (task / "fixtures" / "expectations.json").write_text("PRIVATE")
    (task / "fixtures" / "judge" / "rubrics.json").write_text("PRIVATE")
    (task / "tool_reference.md").write_text("public tools")
    (task / "instruction.md").write_text("public task")
    handbook = tmp_path / "handbook"
    handbook.mkdir()
    (handbook / "SKILL.md").write_text("public handbook")
    output = tmp_path / "public"
    publish_agent_assets(task, handbook, task / "tool_reference.md", output)
    assert (output / "tools" / "tool_reference.md").read_text() == "public tools"
    assert (output / "tools" / "instruction.md").read_text() == "public task"
    assert not (output / "tools" / "tool_reference.md").is_symlink()
    assert (output / "skills" / "managed-care-operations-handbook" / "SKILL.md").exists()
    assert not any("PRIVATE" in p.read_text() for p in output.rglob("*") if p.is_file())
    assert not (output / "fixtures").exists()


def public_sources(tmp_path):
    task = tmp_path / "task"
    task.mkdir()
    (task / "instruction.md").write_text("public task")
    (task / "tool_reference.md").write_text("original tools")
    handbook = tmp_path / "handbook"
    (handbook / "references").mkdir(parents=True)
    (handbook / "SKILL.md").write_text("public handbook")
    (handbook / "references" / "workflow.md").write_text("public workflow")
    return task, handbook


def test_publisher_preserves_the_selected_rewritten_reference(tmp_path):
    from chi_bench.experiment.runtime_assets import publish_agent_assets

    task, handbook = public_sources(tmp_path)
    rewritten = tmp_path / "selected-reference.md"
    rewritten.write_text("chart__get_patient\nreport.v1.pdf\n")
    output = tmp_path / "public"

    publish_agent_assets(task, handbook, rewritten, output)

    assert (output / "tools" / "tool_reference.md").read_bytes() == rewritten.read_bytes()
    assert (output / "tools" / "instruction.md").read_bytes() == (
        task / "instruction.md"
    ).read_bytes()
    assert sorted(p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()) == [
        "skills/managed-care-operations-handbook/SKILL.md",
        "skills/managed-care-operations-handbook/references/workflow.md",
        "tools/instruction.md",
        "tools/tool_reference.md",
    ]
    assert all(not p.is_symlink() for p in output.rglob("*"))


@pytest.mark.parametrize(
    "source", ["instruction", "tool_reference", "handbook_file", "handbook_dir"]
)
def test_symlinks_in_each_public_source_are_rejected_before_publication(tmp_path, source):
    from chi_bench.experiment.runtime_assets import publish_agent_assets

    task, handbook = public_sources(tmp_path)
    private = tmp_path / "expectations.json"
    private.write_text("PRIVATE")
    if source == "instruction":
        linked = task / "instruction.md"
    elif source == "tool_reference":
        linked = task / "tool_reference.md"
    elif source == "handbook_file":
        linked = handbook / "references" / "workflow.md"
    else:
        linked = handbook / "linked-directory"
        private = tmp_path / "private-directory"
        private.mkdir()
        (private / "expectations.json").write_text("PRIVATE")
    linked.unlink(missing_ok=True)
    linked.symlink_to(private)
    output = tmp_path / "public"

    with pytest.raises(ValueError, match="symlink"):
        publish_agent_assets(task, handbook, task / "tool_reference.md", output)

    assert not output.exists()


def test_symlinked_source_ancestor_is_rejected(tmp_path):
    from chi_bench.experiment.runtime_assets import publish_agent_assets

    task, handbook = public_sources(tmp_path)
    linked_parent = tmp_path / "linked-task"
    linked_parent.symlink_to(task, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        publish_agent_assets(
            task, handbook, linked_parent / "tool_reference.md", tmp_path / "public"
        )


def test_nonempty_publication_destination_is_rejected(tmp_path):
    from chi_bench.experiment.runtime_assets import publish_agent_assets

    task, handbook = public_sources(tmp_path)
    output = tmp_path / "public"
    output.mkdir()
    (output / "stale-private-state.json").write_text("PRIVATE")
    with pytest.raises(ValueError, match="empty"):
        publish_agent_assets(task, handbook, task / "tool_reference.md", output)


def test_symlinked_publication_destination_is_rejected(tmp_path):
    from chi_bench.experiment.runtime_assets import publish_agent_assets

    task, handbook = public_sources(tmp_path)
    target = tmp_path / "destination"
    target.mkdir()
    output = tmp_path / "public"
    output.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        publish_agent_assets(task, handbook, task / "tool_reference.md", output)
    assert list(target.iterdir()) == []


def test_public_asset_symlinks_are_rejected(tmp_path):
    from chi_bench.experiment.runtime_assets import publish_agent_assets

    task = tmp_path / "task"
    task.mkdir()
    handbook = tmp_path / "handbook"
    handbook.mkdir()
    private = tmp_path / "expectations.json"
    private.write_text("PRIVATE")
    (handbook / "SKILL.md").symlink_to(private)
    (task / "tool_reference.md").write_text("tools")
    with pytest.raises(ValueError, match="symlink"):
        publish_agent_assets(task, handbook, task / "tool_reference.md", tmp_path / "public")


def test_agent_target_does_not_inherit_application_source_or_task_layers():
    dockerfile = Path(__file__).resolve().parents[2] / "docker" / "Dockerfile"
    text = dockerfile.read_text()
    assert "FROM base AS agent" in text
    agent = text.split("FROM base AS agent", 1)[1].split("\nFROM ", 1)[0]
    assert "COPY data" not in agent
    assert "COPY src/ /workspace/src/" not in agent
    assert "openai_agents_runner.py" in agent
    assert "/var/run/docker.sock" not in agent


def test_build_context_excludes_local_private_artifacts():
    ignore = Path(__file__).resolve().parents[2] / ".dockerignore"
    assert ignore.exists()
    rules = ignore.read_text().splitlines()
    assert "**" in rules
    assert not any(line.startswith("!logs") or line.startswith("!.env") for line in rules)


def docker_stage(name):
    text = (Path(__file__).resolve().parents[2] / "docker" / "Dockerfile").read_text()
    return text.split(f" AS {name}\n", 1)[1].split("\nFROM ", 1)[0]


def test_agent_source_copy_is_closed_over_its_benchmark_imports():
    root = Path(__file__).resolve().parents[2]
    expected = {
        "src/chi_bench/__init__.py",
        "src/chi_bench/experiment/__init__.py",
        "src/chi_bench/experiment/agents/__init__.py",
        "src/chi_bench/experiment/agents/openai_agents_runner.py",
        "src/chi_bench/experiment/agents/openai_agents_local_tools.py",
        "src/chi_bench/experiment/agents/nemotron_tinker_model.py",
        "src/chi_bench/experiment/agents/nemotron_tool_protocol.py",
    }
    stage = docker_stage("agent").replace("\\\n", " ")
    copied = set()
    for line in stage.splitlines():
        if line.startswith("COPY src/"):
            copied.update(shlex.split(line)[1:-1])
    assert copied == expected
    assert "COPY --from=application /workspace/.venv /workspace/.venv" in stage
    assert "healthverse" not in docker_stage("application")
    assert "COPY src/" not in docker_stage("base")
    allowed_modules = {p.removeprefix("src/").removesuffix(".py").replace("/", ".") for p in copied}
    for path in copied:
        for node in ast.walk(ast.parse((root / path).read_text())):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("chi_bench")
            ):
                if node.module == "chi_bench.experiment.agents":
                    imports = [f"{node.module}.{alias.name}" for alias in node.names]
                else:
                    imports = [node.module]
                assert all(module in allowed_modules for module in imports), (path, imports)


def test_agent_image_links_only_public_runtime_mounts():
    stage = docker_stage("agent")
    for link in (
        "ln -s /agent-assets/skills /workspace/skills",
        "ln -s /agent-assets/tools /opt/chi-bench-task-assets",
        "ln -s /opt/chi-bench-task-assets /opt/healthverse-task-assets",
        "ln -s /agent-raw /workspace/raw",
    ):
        assert link in stage


def test_docker_build_inputs_are_explicitly_allowlisted():
    root = Path(__file__).resolve().parents[2]
    rules = (root / ".dockerignore").read_text().splitlines()
    positive = {line[1:] for line in rules if line.startswith("!")}
    assert {"pyproject.toml", "uv.lock", "src/", "src/**", "docker/", "docker/**"} <= positive
    assert "data/**" not in positive
    for path in (
        "data/prior_auth_provider/shared/worlds",
        "data/prior_auth_provider/tasks",
        "data/prior_auth_um/tasks",
        "data/care_management/shared/worlds",
        "data/care_management/tasks",
        "data/prior_auth_e2e/worlds",
        "data/prior_auth_e2e/tasks",
        "data/marathon",
        "data/skills/managed-care-operations-handbook",
    ):
        assert f"{path}/**" in positive
    assert "data/care_management/shared/tool_reference.md" in positive
    assert {"**/.git", "**/.env", "**/.env.*", "**/logs", "**/__pycache__", "**/.venv"} <= set(
        rules
    )


def test_official_claude_cli_default_is_pinned_in_the_shared_base():
    stage = docker_stage("base")
    assert "ARG CLAUDE_CODE_VERSION=2.1.219" in stage
    assert '@anthropic-ai/claude-code@"${CLAUDE_CODE_VERSION}"' in stage
    assert "claude-code@latest" not in stage
