"""Provider routing and runner-control tests for the openai-agents harness."""

from __future__ import annotations

from typing import Any

import pytest
from harbor.models.agent.context import AgentContext
from harbor.models.task.config import MCPServerConfig

from chi_bench.experiment.agents.openai_agents_harness import OpenAIAgentsHarness


INKLING_MODEL = "thinkingmachines/Inkling:peft:262144"


def test_thinkingmachines_model_routes_to_tinker_chat_completions() -> None:
    env = OpenAIAgentsHarness._resolve_routing(
        INKLING_MODEL,
        {"TINKER_API_KEY": "test-tinker-key"},
    )

    assert env == {
        "OPENAI_API_KEY": "test-tinker-key",
        "OPENAI_BASE_URL": "https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1",
        "OPENAI_AGENTS_MODEL": INKLING_MODEL,
        "OPENAI_AGENTS_API_MODE": "chat_completions",
    }


def test_thinkingmachines_model_requires_tinker_api_key() -> None:
    with pytest.raises(RuntimeError, match="TINKER_API_KEY"):
        OpenAIAgentsHarness._resolve_routing(INKLING_MODEL, {})


def test_thinkingmachines_route_ignores_generic_openai_base_url() -> None:
    env = OpenAIAgentsHarness._resolve_routing(
        INKLING_MODEL,
        {
            "TINKER_API_KEY": "test-tinker-key",
            "OPENAI_API_KEY": "test-openai-key",
            "OPENAI_BASE_URL": "https://example.invalid/v1",
        },
    )

    assert env["OPENAI_API_KEY"] == "test-tinker-key"
    assert env["OPENAI_BASE_URL"] == OpenAIAgentsHarness.TINKER_BASE_URL
    assert env["OPENAI_AGENTS_API_MODE"] == "chat_completions"


def test_existing_openai_and_openrouter_routes_are_unchanged() -> None:
    assert OpenAIAgentsHarness._resolve_routing(
        "openai/gpt-5.6-sol",
        {"OPENAI_API_KEY": "test-openai-key"},
    ) == {
        "OPENAI_API_KEY": "test-openai-key",
        "OPENAI_BASE_URL": OpenAIAgentsHarness.OPENAI_DIRECT_BASE_URL,
        "OPENAI_AGENTS_MODEL": "gpt-5.6-sol",
    }
    assert OpenAIAgentsHarness._resolve_routing(
        "moonshotai/kimi-k3",
        {"OPENROUTER_API_KEY": "test-openrouter-key"},
    ) == {
        "OPENAI_API_KEY": "test-openrouter-key",
        "OPENAI_BASE_URL": OpenAIAgentsHarness.OPENROUTER_BASE_URL,
        "OPENAI_AGENTS_MODEL": "moonshotai/kimi-k3",
    }


@pytest.mark.asyncio
async def test_api_mode_and_reasoning_effort_are_forwarded_to_runner(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    harness = OpenAIAgentsHarness(
        logs_dir=tmp_path,
        model_name="openai/gpt-5.6-sol",
        mcp_servers=[
            MCPServerConfig(
                name="chi_bench",
                transport="streamable-http",
                url="http://chi-bench-server:8000/mcp",
            )
        ],
        api_mode="chat_completions",
        reasoning_effort="high",
    )
    captured: dict[str, Any] = {}

    async def fake_exec_as_agent(environment, *, command: str, env: dict[str, str]):
        captured.update(environment=environment, command=command, env=env)

    monkeypatch.setattr(harness, "exec_as_agent", fake_exec_as_agent)

    environment = object()
    await harness.run("Complete the task", environment, AgentContext())

    assert captured["environment"] is environment
    assert captured["env"]["OPENAI_AGENTS_API_MODE"] == "chat_completions"
    assert captured["env"]["OPENAI_AGENTS_REASONING_EFFORT"] == "high"
