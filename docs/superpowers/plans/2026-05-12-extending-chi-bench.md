# Extending chi-bench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `docs/extending.md` (the canonical "bring your own agent / model" recipe) plus a unified agent registry, `cb agent list`, and an improved unknown-agent warning, so leaderboard submitters can extend chi-bench without forking or guessing.

**Architecture:** A new `chi_bench.experiment.agents.registry` module becomes the single source of truth for agent names, replacing the drifting `_AGENT_IMPORT_PATHS` (runner.py) and `KNOWN_AGENTS` (submission.py). The `cb` CLI grows an `agent list` subcommand for introspection. The submission soft-warning rewrites to point at the new doc + command. `docs/extending.md` captures the three extension paths (new model / new harness / both) anchored to existing harness reference implementations.

**Tech Stack:** Python 3.12, Typer (CLI), Pydantic (existing schema), pytest (TDD), Harbor (harness base class — external dep). All Python work runs through `uv`.

**Spec:** [`docs/superpowers/specs/2026-05-12-extending-chi-bench-design.md`](../specs/2026-05-12-extending-chi-bench-design.md) (commit `c03d029`).

---

## File structure

**New files:**

- `src/chi_bench/experiment/agents/registry.py` — exports `IN_TREE_AGENT_IMPORT_PATHS`, `HARBOR_BUILTIN_AGENTS`, `KNOWN_AGENTS`, `AGENT_ENV_VARS`.
- `tests/unit/test_agent_registry.py` — validates the registry's invariants and that every import path resolves to a `BaseInstalledAgent` subclass.
- `tests/unit/test_cli_agent_list.py` — exercises `cb agent list` (text + `--json`).
- `docs/extending.md` — the deliverable doc.

**Modified files:**

- `src/chi_bench/experiment/runner.py` — replace the local `_AGENT_IMPORT_PATHS` literal with an import from `registry`.
- `src/chi_bench/experiment/submission.py` — replace the local `KNOWN_AGENTS` literal with an import; rewrite the `agent.unknown` warning copy to reference `docs/extending.md` and `cb agent list`.
- `src/chi_bench/cli.py` — register a new `agent` Typer subcommand group with `list` (and `--json`).
- `tests/unit/test_submission_config.py` — extend `test_preflight_agent_unknown_warns` to assert the new message content.
- `README.md` — cross-link `docs/extending.md` from §"Submit your agent" and §"Supported agents".
- `docs/cli.md` — append a section for `cb agent list`.

Each file has one clear responsibility. The registry module is the only place that owns the truth about which agent names chi-bench accepts; everything else imports from it.

---

## Task 1: Create the unified agent registry (TDD)

**Files:**
- Create: `src/chi_bench/experiment/agents/registry.py`
- Test: `tests/unit/test_agent_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_agent_registry.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_agent_registry.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'chi_bench.experiment.agents.registry'`.

- [ ] **Step 3: Create the registry module**

Create `src/chi_bench/experiment/agents/registry.py`:

```python
"""Single source of truth for which agent names chi-bench accepts.

Two-tier registry:

* ``IN_TREE_AGENT_IMPORT_PATHS`` — harness classes shipped in this repo.
  Each value is the ``module.path:ClassName`` string Harbor consumes via
  the ``--agent-import-path`` flag. Adding a custom harness means adding
  exactly one entry here (plus, if it needs new provider env vars,
  appending to ``AGENT_ENV_ALLOWLIST`` at ``runner.py:37``).

* ``HARBOR_BUILTIN_AGENTS`` — agent names Harbor knows about natively
  and dispatches via ``-a <name>``. These ship with Harbor, not
  chi-bench; do **not** add custom agents here.

``KNOWN_AGENTS`` is the union and is what ``cb submission validate``
checks against. Unknown values produce a soft warning rather than an
error so custom (out-of-tree) harnesses still work — see
``docs/extending.md`` § 3.

``AGENT_ENV_VARS`` is a documentation aid consumed by ``cb agent list``:
it lists the env vars each harness's model routing reads. It is *not*
the authoritative env allowlist — that remains
``AGENT_ENV_ALLOWLIST`` in ``runner.py``. Entries here are best-effort
and may lag the harness source; PRs welcome.
"""

from __future__ import annotations

IN_TREE_AGENT_IMPORT_PATHS: dict[str, str] = {
    "openai-agents": "chi_bench.experiment.agents.openai_agents_harness:OpenAIAgentsHarness",
    "deepagents": "chi_bench.experiment.agents.deepagents_harness:DeepAgentsHarness",
    "dual-pa-e2e": "chi_bench.experiment.agents.dual_pa_e2e_harness:DualPaE2EHarness",
    "openclaw": "chi_bench.experiment.agents.openclaw_harness:OpenClawHarness",
    "gemini-cli": "chi_bench.experiment.agents.gemini_cli_harness:GeminiCliHarness",
    "hermes": "chi_bench.experiment.agents.hermes_harness:HermesHarness",
    "codex-cli": "chi_bench.experiment.agents.codex_cli_harness:CodexCLIHarness",
    "claude-code-cli": "chi_bench.experiment.agents.claude_code_cli_harness:ClaudeCodeCLIHarness",
}

HARBOR_BUILTIN_AGENTS: frozenset[str] = frozenset({"claude-code", "codex"})

KNOWN_AGENTS: frozenset[str] = (
    frozenset(IN_TREE_AGENT_IMPORT_PATHS) | HARBOR_BUILTIN_AGENTS
)

# Best-effort per-agent env-var hints for `cb agent list`. Not a runtime
# contract — the runtime allowlist is AGENT_ENV_ALLOWLIST in runner.py.
AGENT_ENV_VARS: dict[str, tuple[str, ...]] = {
    "openai-agents": ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_BASE_URL"),
    "deepagents": (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY",
        "TOGETHER_API_KEY",
    ),
    "dual-pa-e2e": ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"),
    "openclaw": ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"),
    "gemini-cli": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_CLI_TRUST_WORKSPACE"),
    "hermes": ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"),
    "codex-cli": ("OPENAI_API_KEY",),
    "claude-code-cli": ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"),
    "claude-code": ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL"),
    "codex": ("OPENAI_API_KEY",),
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_agent_registry.py -v
```

Expected: PASS. All four named tests plus one parametrized case per agent (8 in-tree + 0 Harbor = 8) → 12 PASSED.

- [ ] **Step 5: Lint**

```bash
uv run ruff check src/chi_bench/experiment/agents/registry.py tests/unit/test_agent_registry.py
uv run ruff format --check src/chi_bench/experiment/agents/registry.py tests/unit/test_agent_registry.py
```

Expected: both clean. If format reports diffs, drop `--check` and re-run to apply.

- [ ] **Step 6: Commit**

```bash
git add src/chi_bench/experiment/agents/registry.py tests/unit/test_agent_registry.py
git commit -m "$(cat <<'EOF'
feat(agents): add unified registry as single source of truth for agent names

Introduces chi_bench.experiment.agents.registry with IN_TREE_AGENT_IMPORT_PATHS
+ HARBOR_BUILTIN_AGENTS + derived KNOWN_AGENTS + per-agent env var hints.
Tests assert no overlap between the two tiers and that every in-tree
import path resolves to a BaseInstalledAgent subclass.

Existing _AGENT_IMPORT_PATHS / KNOWN_AGENTS literals will be replaced
by imports from this module in follow-up commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Wire `runner.py` to the registry

**Files:**
- Modify: `src/chi_bench/experiment/runner.py:26-35` (replace `_AGENT_IMPORT_PATHS` literal) and `:455` (call site).

- [ ] **Step 1: Replace the literal with an import**

Open `src/chi_bench/experiment/runner.py`. Replace lines 25–35 (the `# Agent name → import path mapping for custom harnesses` comment + the `_AGENT_IMPORT_PATHS` dict literal) with a single import.

**Before (current `runner.py:25-35`):**

```python
# Agent name → import path mapping for custom harnesses
_AGENT_IMPORT_PATHS: dict[str, str] = {
    "openai-agents": "chi_bench.experiment.agents.openai_agents_harness:OpenAIAgentsHarness",
    "deepagents": "chi_bench.experiment.agents.deepagents_harness:DeepAgentsHarness",
    "dual-pa-e2e": "chi_bench.experiment.agents.dual_pa_e2e_harness:DualPaE2EHarness",
    "openclaw": "chi_bench.experiment.agents.openclaw_harness:OpenClawHarness",
    "gemini-cli": "chi_bench.experiment.agents.gemini_cli_harness:GeminiCliHarness",
    "hermes": "chi_bench.experiment.agents.hermes_harness:HermesHarness",
    "codex-cli": "chi_bench.experiment.agents.codex_cli_harness:CodexCLIHarness",
    "claude-code-cli": "chi_bench.experiment.agents.claude_code_cli_harness:ClaudeCodeCLIHarness",
}
```

**After:**

```python
# Agent name → import path mapping for custom harnesses.
# The dict itself lives in chi_bench.experiment.agents.registry so that
# submission.py's KNOWN_AGENTS allowlist is derived from the same source
# of truth (avoids the two-registries-drift bug the unified registry exists
# to prevent).
from chi_bench.experiment.agents.registry import IN_TREE_AGENT_IMPORT_PATHS
```

- [ ] **Step 2: Update the call site**

In the same file at line 455 (now shifted by the edit above; search for `_AGENT_IMPORT_PATHS.get(cfg.agent)`):

**Before:**

```python
import_path = _AGENT_IMPORT_PATHS.get(cfg.agent)
```

**After:**

```python
import_path = IN_TREE_AGENT_IMPORT_PATHS.get(cfg.agent)
```

That's the only call site — verify with grep below.

- [ ] **Step 3: Confirm there are no remaining references to the old name**

```bash
grep -n "_AGENT_IMPORT_PATHS" src/chi_bench/experiment/runner.py
```

Expected: no output. If anything matches, replace it with `IN_TREE_AGENT_IMPORT_PATHS`.

- [ ] **Step 4: Run the runner's existing tests**

```bash
uv run pytest tests/unit -v -k "runner or harbor or experiment"
```

Expected: all pre-existing tests pass (the refactor is a literal-for-import swap).

- [ ] **Step 5: Lint**

```bash
uv run ruff check src/chi_bench/experiment/runner.py
uv run ruff format --check src/chi_bench/experiment/runner.py
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chi_bench/experiment/runner.py
git commit -m "$(cat <<'EOF'
refactor(runner): consume IN_TREE_AGENT_IMPORT_PATHS from agents.registry

Replaces the local _AGENT_IMPORT_PATHS dict literal with an import from
the unified registry. Behavior unchanged; this is the runner side of the
DRY-up that prevents drift with submission.py's KNOWN_AGENTS allowlist.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Wire `submission.py` to the registry

**Files:**
- Modify: `src/chi_bench/experiment/submission.py:66-81` (replace `KNOWN_AGENTS` literal).

- [ ] **Step 1: Replace the literal with an import**

Open `src/chi_bench/experiment/submission.py`. Replace lines 66–81 (the `# Built-in harness names...` comment + `KNOWN_AGENTS` frozenset literal) with an import from the registry.

**Before (current `submission.py:66-81`):**

```python
# Built-in harness names. Unknown values produce a soft warning rather than an
# error so custom harnesses (registered out-of-tree) still work.
KNOWN_AGENTS: frozenset[str] = frozenset(
    {
        "claude-code",
        "codex",
        "gemini-cli",
        "openclaw",
        "hermes",
        "openai-agents",
        "deepagents",
        "claude-code-cli",
        "codex-cli",
        "dual-pa-e2e",
    }
)
```

**After:**

```python
# Built-in harness allowlist. The set itself is derived in
# chi_bench.experiment.agents.registry from IN_TREE_AGENT_IMPORT_PATHS
# (chi-bench harnesses dispatched via --agent-import-path) plus
# HARBOR_BUILTIN_AGENTS (claude-code, codex — dispatched via Harbor's -a).
# Unknown values produce a soft warning rather than an error so custom
# (out-of-tree) harnesses still work; see docs/extending.md § 3.
from chi_bench.experiment.agents.registry import KNOWN_AGENTS  # noqa: E402,F401  (re-exported)
```

The `noqa` is needed because the import sits mid-file (after the domain registry constants) by design — keeping it next to where it's used is more readable than hoisting to the top. The `F401` silences the "re-exported import" warning since downstream code (and tests) imports `KNOWN_AGENTS` from `submission`.

- [ ] **Step 2: Run the submission test suite**

```bash
uv run pytest tests/unit/test_submission_config.py -v
```

Expected: all existing tests pass — including `test_preflight_agent_known` and `test_preflight_agent_unknown_warns`. The behavior is unchanged at this step.

- [ ] **Step 3: Lint**

```bash
uv run ruff check src/chi_bench/experiment/submission.py
uv run ruff format --check src/chi_bench/experiment/submission.py
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add src/chi_bench/experiment/submission.py
git commit -m "$(cat <<'EOF'
refactor(submission): import KNOWN_AGENTS from agents.registry

Removes the local frozenset literal and re-exports KNOWN_AGENTS from the
unified registry, so registering a new in-tree harness no longer requires
edits in two files. Behavior and downstream import path
(chi_bench.experiment.submission.KNOWN_AGENTS) are unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add `cb agent list` subcommand (TDD)

**Files:**
- Modify: `src/chi_bench/cli.py` (register new `agent_app` group + `list` command).
- Test: `tests/unit/test_cli_agent_list.py`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_cli_agent_list.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_cli_agent_list.py -v
```

Expected: FAIL. Most cases will fail with `No such command 'agent'` (Typer exit code 2) — the subcommand group doesn't exist yet.

- [ ] **Step 3: Add the `agent` subcommand group to the CLI**

Open `src/chi_bench/cli.py`. In the "Subcommand groups" block (currently registers `experiment_app`, `data_app`, `submission_app` around lines 40–51), append a new group registration. Then append a new section near the end of the file for the `list` command.

**In the subcommand-groups block (after `submission_app` registration around line 51):**

```python
agent_app = typer.Typer(
    help="Inspect agent harness registry (which names cb submission accepts).",
    no_args_is_help=True,
)
app.add_typer(agent_app, name="agent")
```

**Add the command implementation near the bottom of the file** (before `if __name__ == "__main__":` if present, otherwise at end). Include the imports it needs at the top of the file if not already imported (`json` likely already is — verify with grep before adding a duplicate import).

```python
@agent_app.command("list")
def agent_list(
    as_json: bool = typer.Option(
        False, "--json", help="Emit JSON instead of a human-readable table."
    ),
) -> None:
    """List agent names chi-bench accepts in submission YAML / --agent.

    Two kinds appear:

    * ``in-tree`` — harness classes shipped in this repo. Dispatched via
      Harbor's ``--agent-import-path``. To register a new one, see
      ``docs/extending.md`` § 3.
    * ``harbor-builtin`` — names Harbor knows about natively. Dispatched
      via ``-a <name>``. Not added by chi-bench.
    """
    import json as _json

    from chi_bench.experiment.agents.registry import (
        AGENT_ENV_VARS,
        HARBOR_BUILTIN_AGENTS,
        IN_TREE_AGENT_IMPORT_PATHS,
    )

    rows: list[dict[str, object]] = []
    for name in sorted(IN_TREE_AGENT_IMPORT_PATHS):
        rows.append(
            {
                "name": name,
                "kind": "in-tree",
                "import_path": IN_TREE_AGENT_IMPORT_PATHS[name],
                "env_vars": list(AGENT_ENV_VARS.get(name, ())),
            }
        )
    for name in sorted(HARBOR_BUILTIN_AGENTS):
        rows.append(
            {
                "name": name,
                "kind": "harbor-builtin",
                "import_path": None,
                "env_vars": list(AGENT_ENV_VARS.get(name, ())),
            }
        )

    if as_json:
        typer.echo(_json.dumps(rows, indent=2))
        return

    name_w = max((len(r["name"]) for r in rows), default=4)
    kind_w = max(len("harbor-builtin"), len("in-tree"))
    typer.echo(f"{'NAME':<{name_w}}  {'KIND':<{kind_w}}  IMPORT PATH / ENV VARS")
    typer.echo(f"{'-' * name_w}  {'-' * kind_w}  ---------------------------------")
    for row in rows:
        import_path = row["import_path"] or "(dispatched by Harbor via -a)"
        env_vars = ", ".join(row["env_vars"]) or "—"
        typer.echo(
            f"{row['name']:<{name_w}}  {row['kind']:<{kind_w}}  {import_path}"
        )
        typer.echo(f"{' ' * name_w}  {' ' * kind_w}    env: {env_vars}")
```

The import lives inside the command body (not at module top) to keep cold-import cost for `cb --help` low — same pattern used by other `cb` subcommands.

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_cli_agent_list.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Smoke-test by eye**

```bash
uv run cb agent list
uv run cb agent list --json
```

Expected output for `cb agent list`: a table with all 10 known agents (8 in-tree + 2 Harbor builtin), each with kind and import path / env-vars line. JSON output: an array of 10 objects, each with `name`, `kind`, `import_path`, `env_vars`.

- [ ] **Step 6: Lint**

```bash
uv run ruff check src/chi_bench/cli.py tests/unit/test_cli_agent_list.py
uv run ruff format --check src/chi_bench/cli.py tests/unit/test_cli_agent_list.py
```

Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/chi_bench/cli.py tests/unit/test_cli_agent_list.py
git commit -m "$(cat <<'EOF'
feat(cli): add `cb agent list` subcommand for registry introspection

Prints registered agent names with their kind (in-tree | harbor-builtin),
import path, and the env vars their model routing reads. Supports --json
for scripting (cb agent list --json | jq ...).

This is the introspection counterpart to the unified agents.registry
module — a contributor adding a custom harness can verify their
registration without spelunking source.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Rewrite the unknown-agent soft warning (TDD)

**Files:**
- Modify: `src/chi_bench/experiment/submission.py` (the `preflight_agent` function — currently around lines 358–372).
- Test: `tests/unit/test_submission_config.py` (extend the existing `test_preflight_agent_unknown_warns`).

- [ ] **Step 1: Write the failing test**

Open `tests/unit/test_submission_config.py`. Find `test_preflight_agent_unknown_warns` (around line 210) and replace it with the expanded version below (which keeps the original assertions and adds new ones):

```python
def test_preflight_agent_unknown_warns(tmp_path: Path) -> None:
    p = _write(tmp_path / "sub.yaml", _valid_yaml(agent="my-custom-harness"))
    cfg = SubmissionConfig.from_yaml(p)
    issues = preflight_agent(cfg)
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].code == "agent.unknown"
    # The message must direct the user to the extension recipe and the
    # introspection command. Drift here is a UX regression — the soft
    # warning is most users' first hint that they need to register.
    assert "docs/extending.md" in issues[0].message
    assert "cb agent list" in issues[0].message
    assert "my-custom-harness" in issues[0].message
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_submission_config.py::test_preflight_agent_unknown_warns -v
```

Expected: FAIL on the `"docs/extending.md" in issues[0].message` assertion (the current message doesn't mention the doc).

- [ ] **Step 3: Rewrite the warning copy**

In `src/chi_bench/experiment/submission.py`, find `preflight_agent` (around line 358 after Task 3's edits — search for `def preflight_agent`). Replace the function body's `PreflightIssue` construction with a more directive message.

**Before:**

```python
def preflight_agent(cfg: SubmissionConfig) -> list[PreflightIssue]:
    """Soft check that the agent name is recognised; custom harnesses pass."""
    if cfg.submission.agent in KNOWN_AGENTS:
        return []
    return [
        PreflightIssue(
            severity="warning",
            code="agent.unknown",
            message=(
                f"agent '{cfg.submission.agent}' is not a built-in harness "
                f"(known: {sorted(KNOWN_AGENTS)}). If you registered a custom "
                "harness this is fine; otherwise check spelling."
            ),
        )
    ]
```

**After:**

```python
def preflight_agent(cfg: SubmissionConfig) -> list[PreflightIssue]:
    """Soft check that the agent name is recognised; custom harnesses pass."""
    if cfg.submission.agent in KNOWN_AGENTS:
        return []
    return [
        PreflightIssue(
            severity="warning",
            code="agent.unknown",
            message=(
                f"agent '{cfg.submission.agent}' is not registered in chi-bench. "
                "If you're bringing a custom harness, see docs/extending.md § 3 "
                "for the recipe, or run `cb agent list` to inspect what's "
                "registered today. Continuing — Harbor will fail at dispatch "
                "time if the name doesn't resolve."
            ),
        )
    ]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_submission_config.py::test_preflight_agent_unknown_warns -v
```

Expected: PASS.

- [ ] **Step 5: Run the full submission test file**

```bash
uv run pytest tests/unit/test_submission_config.py -v
```

Expected: all tests in the file pass (the rewrite doesn't touch any other behavior).

- [ ] **Step 6: Lint**

```bash
uv run ruff check src/chi_bench/experiment/submission.py tests/unit/test_submission_config.py
uv run ruff format --check src/chi_bench/experiment/submission.py tests/unit/test_submission_config.py
```

Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/chi_bench/experiment/submission.py tests/unit/test_submission_config.py
git commit -m "$(cat <<'EOF'
feat(submission): direct unknown-agent warning at docs/extending.md

The previous message ('if you registered a custom harness this is fine')
gave users no path forward. New copy points at docs/extending.md § 3
(the extension recipe) and `cb agent list` (the introspection command).
The test asserts the message contains both pointers + the offending
agent name so the UX can't regress silently.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Write `docs/extending.md`

**Files:**
- Create: `docs/extending.md`

This task is a single large file write. The content below is the doc verbatim — paste it into `docs/extending.md` exactly. The structure follows the approved spec § Part 1.

- [ ] **Step 1: Create the doc**

Create `docs/extending.md` with this exact content:

````markdown
# Extending chi-bench

chi-bench is a leaderboard benchmark. To climb it you change one of two
things — the **model** running behind an agent, the **agent harness**
driving the model, or both — and then run the standard 5-command
submission flow (`validate → run → status → prepare → upload`) to
produce a packet.

You **do not need to open a PR to chi-bench** to submit to the
leaderboard. The packet at `logs/submissions/<id>/packet/...` is
self-contained. Upstreaming your harness is encouraged (§ 6) so others
can reproduce your run, but it is not a leaderboard requirement.

| Want to… | Read | Time |
|---|---|---|
| Try a different model on an existing harness | § 2 (Path A) | ~5 min |
| Plug in your own agent loop / scaffolding | § 3 (Path B) | ~1 hr (thin) – ½ day (heavy) |
| Both | § 4 (Path C) | combine the above |
| Sanity-check what's registered today | `cb agent list` | 1 cmd |

## § 2 — Path A: new model on an existing harness

Most leaderboard model swaps are configuration-only. Three sub-cases.

### § 2.1 OpenAI-compatible endpoint (vLLM, OpenRouter, Together, self-hosted)

The `openai-agents` harness auto-routes on the model id prefix
(`src/chi_bench/experiment/agents/openai_agents_harness.py:84-150`):

| `submission.model:` | Routes to | Reads from `.env` |
|---|---|---|
| `openai/<id>` or bare `<id>` | OpenAI directly | `OPENAI_API_KEY` |
| `<vendor>/<id>` (vendor ≠ `openai`) | OpenRouter | `OPENROUTER_API_KEY` |
| anything, when `OPENAI_BASE_URL` is set | that URL verbatim | `OPENAI_API_KEY` |

The `OPENAI_BASE_URL` escape hatch is how you point at a self-hosted
vLLM / fine-tune / proxy.

**Example: point `openai-agents` at a self-hosted vLLM.**

`.env`:

```
OPENAI_BASE_URL=https://vllm.my-org.com/v1
OPENAI_API_KEY=sk-vllm-...
ANTHROPIC_API_KEY=sk-ant-...   # still required for the judge
```

`configs/submissions/my-finetune.yaml`:

```yaml
schema: chi-bench/submission/v1
submission:
  id: my-team-my-finetune
  team: My Team
  contact: you@example.com
  agent: openai-agents
  model: my-org/my-finetune
run:
  environment: modal
  env_file: .env
dataset:
  version: chi-bench-v1.0.0
  domains: [pa_provider, pa_um, cm]
```

Then `uv run cb submission validate -f configs/submissions/my-finetune.yaml`
and continue with the standard 5-command flow.

### § 2.2 Anthropic-compatible endpoint

For Anthropic-style proxies (e.g. Bedrock-fronted, internal gateway),
use the `claude-code` harness with `ANTHROPIC_BASE_URL`.

`.env`:

```
ANTHROPIC_BASE_URL=https://anthropic.my-proxy.com
ANTHROPIC_API_KEY=sk-ant-proxy-...
```

`submission.model: anthropic/<your-id>`.

### § 2.3 Just a new model id on an existing provider

Not really "extending" — but worth saying: if Anthropic or OpenAI ships
a new model and the existing harness already routes its provider,
just update `submission.model:`. No env changes, no rebuild.

### § 2.4 Compatibility matrix

| Harness | OpenAI-direct | OpenRouter | OpenAI-compat (custom `BASE_URL`) | Anthropic-direct | Anthropic-compat | Notes |
|---|:---:|:---:|:---:|:---:|:---:|---|
| `openai-agents` | ✅ | ✅ | ✅ | via OpenRouter | — | Auto-routes on model prefix; `OPENAI_BASE_URL` overrides |
| `deepagents` | ✅ | ✅ | ✅ | ✅ | ✅ | Per-provider env-var table inside the harness |
| `claude-code` | — | — | — | ✅ | ✅ | `ANTHROPIC_BASE_URL` for proxies |
| `codex-cli` | ✅ | ✅ | ✅ | — | — | |
| `gemini-cli` | — | — | — | — | — | Gemini API only |
| `hermes` | ✅ | ✅ | ✅ | ✅ | — | |
| `openclaw` | ✅ | ✅ | ✅ | ✅ | — | |

Where your provider isn't supported on any harness, write your own —
see § 3.

### § 2.5 Common gotchas

- `data/.chi-bench-version` must equal your submission's
  `dataset.version`. `cb submission validate` rejects mismatches.
- `ANTHROPIC_API_KEY` is **always** required, even when the agent is
  non-Anthropic — the judge is pinned to `claude-opus-4-7`.
- Env-only changes do not require a Docker rebuild. Only rebuild
  (`uv run cb docker build`) when you change Python source.

## § 3 — Path B: new agent harness

A chi-bench harness is a Python class that subclasses Harbor's
`BaseInstalledAgent` and runs **inside** the chi-bench Docker image.
The canonical reference implementation is `openai-agents` — the first
non-built-in agent we shipped. The file pointers in this section refer
to it.

### § 3.1 The contract

| Member | Purpose | Reference |
|---|---|---|
| `@staticmethod name() -> str` | Canonical agent name used in submission YAML | `src/chi_bench/experiment/agents/openai_agents_harness.py:77-79` |
| `SUPPORTS_ATIF: bool = True` | Declare ATIF v1.2 trajectory support so downstream analysis tooling treats your harness like the built-ins | `src/chi_bench/experiment/agents/openai_agents_harness.py:51` |
| `CLI_FLAGS: list[CliFlag]` | Tunable knobs (e.g. `max_turns`) with type, default, env fallback | `src/chi_bench/experiment/agents/openai_agents_harness.py:53-75` |
| `get_version_command() -> str \| None` | Shell command to print the agent package version inside the container | `src/chi_bench/experiment/agents/openai_agents_harness.py:152` |
| `async install(self, environment)` | Install deps in the container (`uv pip install …`); runs as root | `src/chi_bench/experiment/agents/openai_agents_harness.py:155-159` |
| `@with_prompt_template async run(self, instruction, environment, context)` | Execute the agent; reads MCP URL from `self.mcp_servers`; writes logs to `self.logs_dir` | `src/chi_bench/experiment/agents/openai_agents_harness.py:161-233` |
| `populate_context_post_run(self, context)` | Read metrics + emit ATIF trajectory; populates `context.{n_input_tokens, cost_usd, …}` | `src/chi_bench/experiment/agents/openai_agents_harness.py:240-282` |

Harbor owns `BaseInstalledAgent`; consult Harbor's docs for the
upstream contract. This page covers chi-bench-specific patterns.

### § 3.2 The two-file pattern

Recommended layout for any non-trivial harness:

- **Harness file** `src/chi_bench/experiment/agents/<my_agent>.py` —
  Harbor-facing glue. Install, run, post-run trajectory translation.
- **Runner file** `src/chi_bench/experiment/agents/<my_agent>_runner.py` —
  the actual agent loop, executed inside the container as
  `python -m chi_bench.experiment.agents.<my_agent>_runner`. Reads the
  instruction from a temp file, connects to MCP, drives the model,
  writes `run_result.json` + `trace.jsonl` to `/logs/agent/`.

`openai_agents_harness.py` (465 lines) + `openai_agents_runner.py`
(687 lines) is the reference pair. Single-file harnesses are fine for
thin CLI wrappers — see `claude_code_cli_harness.py` (82 lines) — but
the two-file pattern is what scales.

### § 3.3 Step-by-step

1. **Drop the harness file** at
   `src/chi_bench/experiment/agents/<my_agent>.py`. Easiest start: copy
   `openai_agents_harness.py`, rename the class, change the value
   returned by `name()`, strip OpenAI-specific routing if not relevant.
2. **Drop the runner file** (if using the two-file pattern) at
   `src/chi_bench/experiment/agents/<my_agent>_runner.py`.
3. **Register in the unified registry** —
   `src/chi_bench/experiment/agents/registry.py`. One line:

   ```python
   IN_TREE_AGENT_IMPORT_PATHS["my-agent"] = (
       "chi_bench.experiment.agents.my_agent:MyAgentHarness"
   )
   ```

   That single edit makes the name resolvable for both Harbor dispatch
   (`runner.py`) and submission validation (`submission.py`).

4. **Allowlist new provider env vars** at
   `src/chi_bench/experiment/runner.py:37` (`AGENT_ENV_ALLOWLIST`) if
   your harness needs API keys not already on the list. Only allowlisted
   keys are forwarded into trial containers via Harbor's `--ae` flag.
   Skip this step if your harness only reads keys already present.

5. **Rebuild the image** so the new files are baked in:

   ```
   uv run cb docker build
   ```

6. **Sanity-check the registration:**

   ```
   uv run cb agent list
   ```

   Your agent should appear with `kind: in-tree`.

7. **Smoke-test against one task** before committing to a full
   submission:

   ```
   uv run cb experiment run \
       --dataset data/prior_auth_provider/tasks/<one-task-dir> \
       --agent my-agent --model <model-id>
   ```

### § 3.4 Plumbing checklist (subtle things easy to miss)

These come from the `openai-agents` and `hermes` harnesses. Skipping any
of them tends to manifest as a confusing failure mid-trial:

- **MCP URL discovery.** `self.mcp_servers` is set from `task.toml`.
  Iterate and pick the first non-empty `server.url`. Raise on miss;
  do not silently default
  (`src/chi_bench/experiment/agents/openai_agents_harness.py:168-177`).
- **Provider env preflight.** Mirror provider API keys from
  `self._extra_env` (populated by Harbor's `--ae`) into `os.environ`
  at `run()` entry. Routing decisions often read `os.environ` directly;
  per-row overrides via `--ae` only land in `_extra_env`. Pattern at
  `openai_agents_harness.py:191-194`.
- **Save/restore `_extra_env` around `exec_as_agent`.** Harbor merges
  `_extra_env` over the env you pass. To make your routing decisions
  win (not a stale host key), strip the conflicting keys before exec
  and restore in `finally`
  (`openai_agents_harness.py:204-233`).
- **Quote the instruction.** Use `shlex.quote(instruction)` before
  shell-interpolating into the exec command — the instruction often
  contains shell metacharacters.
- **Tee a `run_log.txt`.** Pipe the runner's stdout to
  `/logs/agent/run_log.txt` (`openai_agents_harness.py:228`). When
  post-run parsing fails on Modal, this is your only signal.
- **Use the container venv.** The chi-bench image installs Python deps
  into `/workspace/.venv` (`docker/Dockerfile:18-21`). In `install()`,
  prefix `uv pip` invocations with `--python /workspace/.venv` so your
  package lands where the venv-on-PATH actually looks.

### § 3.5 Trajectory normalization (optional but recommended)

If your harness emits a custom log format (most do), translate it to
**ATIF v1.2** in `populate_context_post_run`. Writing the result to
`self.logs_dir / "trajectory.json"` makes your trial show up uniformly
in cost rollups and per-step inspection.

Reference: `openai_agents_harness.py:285-465` (`_build_atif_trajectory`
and `_read_trace`). The Harbor types live at
`harbor.models.trajectories.*` — `Trajectory`, `Step`, `Agent`,
`ToolCall`, `Observation`, `ObservationResult`, `Metrics`,
`FinalMetrics`.

If you skip ATIF, your trial still scores correctly (the verifier reads
the workspace, not the trajectory), but cost reporting and trace
analysis on the leaderboard side won't work for your submission.

## § 4 — Path C: both new harness and new model

Cross-references §§ 2 and 3. The only working tip: **write the harness
first** (§ 3), pin a known public model as your dev model, get the
harness working end-to-end on a single task, **then** swap in your
endpoint via § 2. Debugging two unknowns simultaneously is much harder
than debugging them in sequence.

## § 5 — Submitting with a custom agent / model

The point of this section: **nothing changes** vs. the README §
"Submit your agent" flow. The packet shape is identical.

```bash
uv run cb submission validate -f configs/submissions/<your-id>.yaml
uv run cb submission run      -f configs/submissions/<your-id>.yaml
uv run cb submission status   -f configs/submissions/<your-id>.yaml
uv run cb submission prepare  -f configs/submissions/<your-id>.yaml
```

Two custom-agent-specific notes:

- `cb submission validate` emits only a soft warning for custom agent
  names, not a hard error. Hard errors are still reserved for malformed
  YAML, dataset-version mismatch, or missing env files.
- `provenance.json` in the packet records the resolved image digest +
  git SHA. A custom-agent run is reproducible from *your* checkout;
  others can only reproduce it if your harness source is available
  (which is what § 6 is about).

## § 6 — Contributing upstream (optional)

If you want others to reproduce your run, open a PR to chi-bench with:

1. Your harness file(s) under `src/chi_bench/experiment/agents/`.
2. A line in `src/chi_bench/experiment/agents/registry.py`'s
   `IN_TREE_AGENT_IMPORT_PATHS`.
3. A unit test in `tests/unit/test_agent_registry.py` is automatic —
   your import path will be picked up by the parametrized
   `test_import_paths_resolve_to_base_installed_agent`.
4. A row added to the § 2.4 compatibility matrix in this file.

This is **not** a leaderboard requirement.

## § 7 — Reference appendix

- **Unified registry:**
  `src/chi_bench/experiment/agents/registry.py`.
- **Env allowlist** (runtime contract for what's forwarded into trial
  containers): `AGENT_ENV_ALLOWLIST` at
  `src/chi_bench/experiment/runner.py:37`.
- **CLI:** `cb agent list` (registry introspection),
  `cb experiment run --agent <name> --model <id>` (single-task
  smoke), `cb submission {validate,run,status,prepare}` (submission
  flow). See [`docs/cli.md`](cli.md) for full flag reference.
- **Harbor's harness contract:** see Harbor's upstream documentation
  for the `BaseInstalledAgent` base class.
- **ATIF v1.2 types:** `harbor.models.trajectories.*`.
- **Known limitation: per-trial agent kwargs.** The submission YAML
  does not expose per-trial harness kwargs today (those flow through
  `ExperimentConfig.agent_kwargs` in
  `src/chi_bench/experiment/config.py`). For a harness that needs a
  runtime knob, see `dual_pa_e2e_harness.py` for a precedent —
  it uses `agent_kwargs` heavily. Exposing them in submission YAML
  is on the roadmap.
````

- [ ] **Step 2: Sanity-check the file links**

```bash
grep -n "src/chi_bench/experiment/agents/openai_agents_harness.py:" docs/extending.md | head -20
```

Expected: 8+ references, each citing a real line range. Spot-check two of them — open the referenced file and confirm the lines match what the doc claims (e.g. `:77-79` for `name()`).

- [ ] **Step 3: Render-check (optional but recommended)**

If you have a markdown previewer (or `mdcat`, `glow`, etc.), render the
doc and skim it. The compatibility matrix and the contract table should
both render as tables. The triple-backtick blocks should syntax-highlight
as `bash`, `yaml`, `python`, or plain text as labeled.

- [ ] **Step 4: Commit**

```bash
git add docs/extending.md
git commit -m "$(cat <<'EOF'
docs: add extending.md — bring your own agent / model recipe

Single canonical doc covering the three leaderboard-submitter extension
paths: new model on an existing harness (Path A, config-only), new
agent harness (Path B, in-tree edit), and both (Path C). Uses the
openai-agents harness as the canonical reference implementation
throughout, with file:line pointers for every non-trivial pattern.

Closes the gap between the existing 5-command submission flow and what
a new submitter needs to know to extend chi-bench. Spec:
docs/superpowers/specs/2026-05-12-extending-chi-bench-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Cross-link from README + docs/cli.md

**Files:**
- Modify: `README.md` (§ "Submit your agent" intro paragraph + § "Supported agents" trailing line).
- Modify: `docs/cli.md` (append `cb agent` section).

- [ ] **Step 1: Add the README §4 cross-link**

Open `README.md`. Find the line `## Submit your agent` (line 122 in the current `main`). The first non-blank line after it is the intro paragraph starting with `Submitting to the [leaderboard]...`. **Insert** a new paragraph immediately before that intro paragraph:

```markdown
> **Bringing your own agent harness or model endpoint?** The end-to-end
> recipe lives in [`docs/extending.md`](docs/extending.md). The rest of
> this section is identical regardless of whether you submit a built-in
> agent or a custom one — the packet shape is unchanged.
```

The result is: heading → new blockquote → existing intro paragraph → existing 4-command code block.

- [ ] **Step 2: Add the README "Supported agents" cross-link**

Find `## Supported agents` (line 193 in current `main`). Append a single line at the end of the section (just before the next `## Architecture` heading):

```markdown

See [`docs/extending.md`](docs/extending.md) to plug in your own.
```

(The leading blank line is intentional — it produces a separate paragraph in the rendered output.)

- [ ] **Step 3: Add the `cb agent` section to docs/cli.md**

Open `docs/cli.md`. Find the natural insertion point — `cb agent` slots alphabetically between `cb` global flags and the other subcommand groups. If `docs/cli.md` is organized by subcommand (`cb data`, `cb experiment`, `cb submission`, `cb serve`, …), insert `cb agent` ahead of `cb data`.

Append the new section:

```markdown

## `cb agent`

Inspect the agent registry that backs `submission.agent:` and the
`--agent` flag.

### `cb agent list`

```
uv run cb agent list           # human-readable table
uv run cb agent list --json    # array of {name, kind, import_path, env_vars}
```

Two kinds of agent appear:

- `in-tree` — harness classes shipped under
  `src/chi_bench/experiment/agents/`. Dispatched by Harbor via
  `--agent-import-path`. To add one, see
  [`docs/extending.md` § 3](extending.md#-3--path-b-new-agent-harness).
- `harbor-builtin` — names Harbor knows about natively (`claude-code`,
  `codex`). Dispatched via `-a <name>`. Not added by chi-bench.

The `env_vars` column is a best-effort list of provider keys each
harness's model routing reads — it is *not* the authoritative env
allowlist (that's `AGENT_ENV_ALLOWLIST` in
`src/chi_bench/experiment/runner.py`).
```

- [ ] **Step 4: Verify the cross-links resolve**

```bash
# README links to the doc
grep -n "docs/extending.md" README.md
# docs/cli.md links back to the doc
grep -n "extending.md" docs/cli.md
# extending.md links to docs/cli.md
grep -n "docs/cli.md\|cli.md" docs/extending.md
```

Expected: each grep returns ≥ 1 line.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/cli.md
git commit -m "$(cat <<'EOF'
docs: cross-link extending.md from README §4 + docs/cli.md

Two-line README addition pointing first-time submitters at the new
extension recipe before the 5-command flow, plus a docs/cli.md section
documenting `cb agent list` (the introspection counterpart to the
unified agents.registry module).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

After all seven tasks are committed:

- [ ] **Run the full default test suite**

```bash
uv run pytest
```

Expected: all tests pass with the default `pyproject.toml` markers
(skips `requires_anthropic_key` and `slow`).

- [ ] **Lint and format the whole touched surface**

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

Expected: both clean.

- [ ] **Walk through `cb agent list` once more**

```bash
uv run cb agent list
uv run cb agent list --json | head -20
```

Expected: the table shows 8 in-tree + 2 harbor-builtin agents; the JSON
output parses and has the documented shape.

- [ ] **Confirm the warning copy is right by running validate on a deliberately bogus agent name**

Create a throwaway YAML using one of the existing submissions as a
template (e.g. `configs/submissions/example.yaml` if present, or hand-roll
one) but set `submission.agent: not-a-real-agent`. Run:

```bash
uv run cb submission validate -f /tmp/bogus.yaml
```

Expected: a warning containing `docs/extending.md` and `cb agent list`,
exit code 0 (warnings are non-fatal).

- [ ] **`git log --oneline -7` shows seven commits with the messages from this plan**

Each task is one commit. Verify the order: registry → runner → submission
→ cli → warning → extending.md → cross-links.

---

## Self-review notes

Spec coverage — every spec section maps to at least one task:

| Spec section | Task(s) |
|---|---|
| § Part 1 — `docs/extending.md` | Task 6 |
| § Part 2.1 — Unified registry | Tasks 1, 2, 3 |
| § Part 2.2 — `cb agent list` | Task 4 |
| § Part 2.3 — Improved soft warning | Task 5 |
| § Part 3 — README + docs/cli.md updates | Task 7 |
| Reference implementation callouts | embedded in Task 6 (doc) |
| Validation / testing | Tasks 1, 4, 5 (TDD tests); final verification block |
| Open questions / risks | documented in spec; nothing requires plan action |
| Out of scope (deferred) | not implemented (correct) |
| File-by-file inventory | matches "File structure" header above |

Type consistency — `IN_TREE_AGENT_IMPORT_PATHS` is `dict[str, str]`
everywhere it's referenced; `HARBOR_BUILTIN_AGENTS` and `KNOWN_AGENTS`
are `frozenset[str]`; `AGENT_ENV_VARS` is `dict[str, tuple[str, ...]]`.
The CLI command emits `env_vars` as a JSON `list` (the tuple is
serialized as a list — JSON has no tuple type) and the test asserts
`isinstance(row["env_vars"], list)`. ✓
