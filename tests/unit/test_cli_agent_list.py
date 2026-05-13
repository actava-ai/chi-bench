"""Tests for `cb agent list`."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from chi_bench.cli import app
from chi_bench.experiment.agents.registry import (
    HARBOR_BUILTIN_AGENTS,
    IN_TREE_AGENT_IMPORT_PATHS,
)


def test_agent_list_exit_zero() -> None:
    result = CliRunner().invoke(app, ["agent", "list"])
    assert result.exit_code == 0, result.stdout


def test_agent_list_includes_all_in_tree_agents() -> None:
    result = CliRunner().invoke(app, ["agent", "list"])
    assert result.exit_code == 0
    for name in IN_TREE_AGENT_IMPORT_PATHS:
        assert name in result.stdout, f"{name!r} missing from `cb agent list` output"


def test_agent_list_includes_all_harbor_builtin_agents() -> None:
    result = CliRunner().invoke(app, ["agent", "list"])
    assert result.exit_code == 0
    for name in HARBOR_BUILTIN_AGENTS:
        assert name in result.stdout, f"{name!r} missing from `cb agent list` output"


def test_agent_list_distinguishes_kind() -> None:
    """The output must show which dispatch path each agent uses, so a
    contributor can tell that adding a custom agent means editing
    IN_TREE_AGENT_IMPORT_PATHS, not HARBOR_BUILTIN_AGENTS."""
    result = CliRunner().invoke(app, ["agent", "list"])
    assert result.exit_code == 0
    assert "in-tree" in result.stdout
    assert "harbor-builtin" in result.stdout


def test_agent_list_json_shape() -> None:
    result = CliRunner().invoke(app, ["agent", "list", "--json"])
    assert result.exit_code == 0, result.stdout

    data = json.loads(result.stdout)
    assert isinstance(data, list)

    names = {row["name"] for row in data}
    assert set(IN_TREE_AGENT_IMPORT_PATHS) <= names
    assert HARBOR_BUILTIN_AGENTS <= names

    for row in data:
        assert set(row.keys()) == {"name", "kind", "import_path", "env_vars"}
        assert row["kind"] in {"in-tree", "harbor-builtin"}
        assert isinstance(row["env_vars"], list)
        if row["kind"] == "in-tree":
            assert ":" in row["import_path"]
        else:
            assert row["import_path"] is None


def test_agent_list_json_includes_env_vars_for_openai_agents() -> None:
    """Sanity-check the AGENT_ENV_VARS plumbing for one known agent."""
    result = CliRunner().invoke(app, ["agent", "list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    row = next(r for r in data if r["name"] == "openai-agents")
    assert "OPENAI_API_KEY" in row["env_vars"]
    assert "OPENROUTER_API_KEY" in row["env_vars"]
