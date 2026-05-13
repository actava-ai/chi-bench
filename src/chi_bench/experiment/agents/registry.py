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

KNOWN_AGENTS: frozenset[str] = frozenset(IN_TREE_AGENT_IMPORT_PATHS) | HARBOR_BUILTIN_AGENTS

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
