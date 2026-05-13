"""Tests for the unified agent registry."""

from __future__ import annotations

import importlib

import pytest

from chi_bench.experiment.agents.registry import (
    AGENT_ENV_VARS,
    HARBOR_BUILTIN_AGENTS,
    IN_TREE_AGENT_IMPORT_PATHS,
    KNOWN_AGENTS,
)


def test_known_agents_is_union_of_in_tree_and_harbor_builtin() -> None:
    """KNOWN_AGENTS must be exactly the union — drift between the two views
    is the bug class this refactor exists to prevent."""
    expected = frozenset(IN_TREE_AGENT_IMPORT_PATHS) | HARBOR_BUILTIN_AGENTS
    assert KNOWN_AGENTS == expected


def test_no_overlap_between_in_tree_and_harbor_builtin() -> None:
    """An agent name appearing in both registries would imply confusion
    about whether Harbor dispatches it via -a (built-in) or
    --agent-import-path (in-tree)."""
    overlap = set(IN_TREE_AGENT_IMPORT_PATHS) & HARBOR_BUILTIN_AGENTS
    assert not overlap, f"agent names in both registries: {sorted(overlap)}"


def test_in_tree_import_paths_are_well_formed() -> None:
    """Every value must be 'module.path:ClassName' — Harbor's
    --agent-import-path expects that exact form."""
    for name, path in IN_TREE_AGENT_IMPORT_PATHS.items():
        assert ":" in path, f"{name}: missing ':' in {path!r}"
        module_part, class_part = path.split(":", 1)
        assert module_part and class_part, f"{name}: malformed path {path!r}"


@pytest.mark.parametrize(
    "name,import_path",
    sorted(IN_TREE_AGENT_IMPORT_PATHS.items()),
)
def test_import_paths_resolve_to_base_installed_agent(name: str, import_path: str) -> None:
    """Each registered class must import cleanly and inherit from Harbor's
    BaseInstalledAgent. A typo or refactor that breaks this is what Harbor
    would otherwise surface as a confusing dispatch-time error."""
    from harbor.agents.installed.base import BaseInstalledAgent

    module_name, class_name = import_path.split(":", 1)
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)

    assert isinstance(cls, type), f"{import_path} is not a class"
    assert issubclass(cls, BaseInstalledAgent), (
        f"{import_path} is not a BaseInstalledAgent subclass"
    )


def test_agent_env_vars_keys_subset_of_known_agents() -> None:
    """AGENT_ENV_VARS is documentation aid only; we don't require every
    agent to appear there, but any key listed must be a real agent name."""
    unknown = set(AGENT_ENV_VARS) - set(KNOWN_AGENTS)
    assert not unknown, f"AGENT_ENV_VARS has entries for unknown agents: {sorted(unknown)}"
