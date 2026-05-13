"""Tests for judge-subprocess env isolation from the agent's .env.

The judge is pinned to ``claude-opus-4-7`` and expected to talk to real
Anthropic. When a user sets ``ANTHROPIC_BASE_URL`` in their .env to
redirect their ``claude-code`` agent through a proxy, that value lands
in the trial container's ``os.environ`` and — without isolation —
silently redirects every judge call through the proxy too.
``_subprocess_env`` must strip ``ANTHROPIC_BASE_URL`` so the judge
keeps hitting api.anthropic.com.

Opt-out: ``CHI_BENCH_JUDGE_BASE_URL`` is the explicit knob for the rare
case where the user actually wants to route the judge somewhere else.
"""

from __future__ import annotations

import pytest

from chi_bench.verifier.judge.claude_runner import ClaudeAgentRunner


@pytest.fixture
def runner() -> ClaudeAgentRunner:
    return ClaudeAgentRunner(model="opus")


def test_subprocess_env_strips_anthropic_base_url_by_default(
    runner: ClaudeAgentRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Agent-level ANTHROPIC_BASE_URL must not leak into the judge subprocess."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://my-proxy.example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-proxy-key")
    monkeypatch.delenv("CHI_BENCH_JUDGE_BASE_URL", raising=False)

    env = runner._subprocess_env()
    assert env is not None
    assert "ANTHROPIC_BASE_URL" not in env, (
        "judge subprocess env must not inherit agent-level ANTHROPIC_BASE_URL — "
        "the judge is pinned to api.anthropic.com"
    )
    # ANTHROPIC_API_KEY is left alone: real Anthropic will use it.
    assert env.get("ANTHROPIC_API_KEY") == "sk-proxy-key"


def test_subprocess_env_respects_judge_base_url_override(
    runner: ClaudeAgentRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CHI_BENCH_JUDGE_BASE_URL is the explicit opt-in for redirecting the judge."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://my-proxy.example.com")
    monkeypatch.setenv("CHI_BENCH_JUDGE_BASE_URL", "https://judge-proxy.example.com")

    env = runner._subprocess_env()
    assert env is not None
    assert env.get("ANTHROPIC_BASE_URL") == "https://judge-proxy.example.com", (
        "CHI_BENCH_JUDGE_BASE_URL must win — it's the explicit opt-in"
    )


def test_subprocess_env_no_anthropic_base_url_unset_path(
    runner: ClaudeAgentRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When neither var is set, the judge env has no ANTHROPIC_BASE_URL key."""
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("CHI_BENCH_JUDGE_BASE_URL", raising=False)

    env = runner._subprocess_env()
    # env may be None (no overrides needed) or a dict — either way,
    # ANTHROPIC_BASE_URL must not appear with a non-empty value.
    if env is not None:
        assert "ANTHROPIC_BASE_URL" not in env
