"""Tests for judge-subprocess env isolation from the agent's .env.

The judge is pinned to ``claude-opus-4-7`` and must always talk to
api.anthropic.com so leaderboard scores stay comparable across
submissions. When a user sets ``ANTHROPIC_BASE_URL`` in their .env to
redirect their ``claude-code`` agent through a proxy, that value lands
in the trial container's ``os.environ`` and — without isolation —
silently redirects every judge call through the proxy too.
``_subprocess_env`` strips ``ANTHROPIC_BASE_URL`` unconditionally; there
is no opt-out because routing the judge would undermine the pin.
"""

from __future__ import annotations

import pytest

from chi_bench.verifier.judge.claude_runner import ClaudeAgentRunner


@pytest.fixture
def runner() -> ClaudeAgentRunner:
    return ClaudeAgentRunner(model="opus")


def test_subprocess_env_strips_anthropic_base_url(
    runner: ClaudeAgentRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Agent-level ANTHROPIC_BASE_URL must not leak into the judge subprocess."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://my-proxy.example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-proxy-key")

    env = runner._subprocess_env()
    assert env is not None
    assert "ANTHROPIC_BASE_URL" not in env, (
        "judge subprocess env must not inherit agent-level ANTHROPIC_BASE_URL — "
        "the judge is pinned to api.anthropic.com"
    )
    # ANTHROPIC_API_KEY is left alone: real Anthropic will use it.
    assert env.get("ANTHROPIC_API_KEY") == "sk-proxy-key"


def test_subprocess_env_no_anthropic_base_url_unset_path(
    runner: ClaudeAgentRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ANTHROPIC_BASE_URL is unset, the judge env has no key for it."""
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

    env = runner._subprocess_env()
    # env may be None (no overrides needed) or a dict — either way,
    # ANTHROPIC_BASE_URL must not appear.
    if env is not None:
        assert "ANTHROPIC_BASE_URL" not in env


# ─── ANTHROPIC_API_KEY as the default judge auth path ────────────────────────


@pytest.mark.parametrize("key_var", ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"])
def test_ensure_authenticated_prefers_api_key_without_probe(
    runner: ClaudeAgentRunner, monkeypatch: pytest.MonkeyPatch, key_var: str
) -> None:
    """A present ANTHROPIC_API_KEY/AUTH_TOKEN short-circuits auth: no CLI probe,
    no ClaudeAuthError, and the auth method is recorded as ``api_key`` so
    _subprocess_env keeps the key for the judge subprocess."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv(key_var, "sk-test-key")

    # The `claude auth status` probe must NOT run when a key is present.
    def _fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("claude auth status probe should be skipped when a key is set")

    monkeypatch.setattr("chi_bench.verifier.judge.claude_runner.subprocess.run", _fail_if_called)

    runner._ensure_authenticated()

    assert runner._auth_logged_in is True
    assert runner._auth_method == "api_key"


def test_api_key_survives_into_judge_env_after_auth(
    runner: ClaudeAgentRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end of the real flow: once auth marks api_key, the key is kept in
    the judge subprocess env (the OAuth-preference strip is skipped)."""
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-judge-key")
    monkeypatch.setattr(
        "chi_bench.verifier.judge.claude_runner.subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("probe must be skipped")),
    )

    runner._ensure_authenticated()
    env = runner._subprocess_env()

    assert env is not None
    assert env.get("ANTHROPIC_API_KEY") == "sk-judge-key"
