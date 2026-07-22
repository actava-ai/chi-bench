"""Provider routing and runner-control tests for the openai-agents harness."""

from __future__ import annotations

from typing import Any

import pytest
from harbor.models.agent.context import AgentContext
from harbor.models.task.config import MCPServerConfig

from chi_bench.experiment.agents.openai_agents_harness import OpenAIAgentsHarness


INKLING_MODEL = "thinkingmachines/Inkling:peft:262144"
NEMOTRON_MODEL = "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16:peft:262144"


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


def test_explicit_tinker_route_uses_tinker_for_non_thinkingmachines_model() -> None:
    env = OpenAIAgentsHarness._resolve_routing(
        NEMOTRON_MODEL,
        {
            "TINKER_API_KEY": "test-tinker-key",
            "OPENAI_API_KEY": "test-openai-key",
            "OPENAI_BASE_URL": "https://example.invalid/v1",
        },
        provider_route="tinker",
    )

    assert env == {
        "OPENAI_API_KEY": "test-tinker-key",
        "OPENAI_BASE_URL": OpenAIAgentsHarness.TINKER_BASE_URL,
        "OPENAI_AGENTS_MODEL": NEMOTRON_MODEL,
        "OPENAI_AGENTS_API_MODE": "chat_completions",
    }


def test_explicit_tinker_route_requires_tinker_api_key() -> None:
    with pytest.raises(RuntimeError, match="TINKER_API_KEY"):
        OpenAIAgentsHarness._resolve_routing(
            NEMOTRON_MODEL,
            {"OPENROUTER_API_KEY": "test-openrouter-key"},
            provider_route="tinker",
        )


def test_nemotron_without_explicit_route_still_uses_openrouter() -> None:
    env = OpenAIAgentsHarness._resolve_routing(
        NEMOTRON_MODEL,
        {
            "OPENROUTER_API_KEY": "test-openrouter-key",
            "TINKER_API_KEY": "test-tinker-key",
        },
    )

    assert env == {
        "OPENAI_API_KEY": "test-openrouter-key",
        "OPENAI_BASE_URL": OpenAIAgentsHarness.OPENROUTER_BASE_URL,
        "OPENAI_AGENTS_MODEL": NEMOTRON_MODEL,
    }


def test_provider_route_flag_is_exposed_to_cli_and_env() -> None:
    flags = {flag.kwarg: flag for flag in OpenAIAgentsHarness.CLI_FLAGS}

    assert "provider_route" in flags
    flag = flags["provider_route"]
    assert flag.cli == "--provider-route"
    assert flag.type == "enum"
    assert flag.choices == ["auto", "tinker"]
    assert flag.env_fallback == "OPENAI_AGENTS_PROVIDER_ROUTE"


@pytest.mark.asyncio
async def test_install_pins_compatible_openai_sdk(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = OpenAIAgentsHarness(logs_dir=tmp_path)
    captured: dict[str, Any] = {}

    async def fake_exec_as_root(environment, *, command: str):
        captured.update(environment=environment, command=command)

    monkeypatch.setattr(harness, "exec_as_root", fake_exec_as_root)
    environment = object()

    await harness.install(environment)

    assert captured == {
        "environment": environment,
        "command": (
            "uv pip install --no-cache-dir --python /workspace/.venv "
            "openai-agents==0.13.6 openai==2.36.0"
        ),
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
        api_mode="responses",
        reasoning_effort="high",
    )
    captured: dict[str, Any] = {}

    async def fake_exec_as_agent(environment, *, command: str, env: dict[str, str]):
        captured.update(environment=environment, command=command, env=env)

    monkeypatch.setattr(harness, "exec_as_agent", fake_exec_as_agent)

    environment = object()
    await harness.run("Complete the task", environment, AgentContext())

    assert captured["environment"] is environment
    assert captured["env"]["OPENAI_AGENTS_API_MODE"] == "responses"
    assert captured["env"]["OPENAI_AGENTS_REASONING_EFFORT"] == "high"


@pytest.mark.asyncio
async def test_provider_route_is_forwarded_to_routing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TINKER_API_KEY", "test-tinker-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    harness = OpenAIAgentsHarness(
        logs_dir=tmp_path,
        model_name=NEMOTRON_MODEL,
        mcp_servers=[
            MCPServerConfig(
                name="chi_bench",
                transport="streamable-http",
                url="http://chi-bench-server:8000/mcp",
            )
        ],
        provider_route="tinker",
        api_mode="chat_completions",
    )
    captured: dict[str, Any] = {}

    async def fake_exec_as_agent(environment, *, command: str, env: dict[str, str]):
        captured.update(environment=environment, command=command, env=env)

    monkeypatch.setattr(harness, "exec_as_agent", fake_exec_as_agent)

    await harness.run("Complete the task", object(), AgentContext())

    assert captured["env"]["OPENAI_API_KEY"] == "test-tinker-key"
    assert captured["env"]["OPENAI_BASE_URL"] == OpenAIAgentsHarness.TINKER_BASE_URL
    assert captured["env"]["OPENAI_AGENTS_MODEL"] == NEMOTRON_MODEL
    assert captured["env"]["OPENAI_AGENTS_API_MODE"] == "chat_completions"


@pytest.mark.asyncio
async def test_tinker_route_forces_chat_completions_over_api_mode_flag(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TINKER_API_KEY", "test-tinker-key")
    harness = OpenAIAgentsHarness(
        logs_dir=tmp_path,
        model_name=NEMOTRON_MODEL,
        mcp_servers=[
            MCPServerConfig(
                name="chi_bench",
                transport="streamable-http",
                url="http://chi-bench-server:8000/mcp",
            )
        ],
        provider_route="tinker",
        api_mode="responses",
    )
    captured: dict[str, Any] = {}

    async def fake_exec_as_agent(environment, *, command: str, env: dict[str, str]):
        captured.update(environment=environment, command=command, env=env)

    monkeypatch.setattr(harness, "exec_as_agent", fake_exec_as_agent)

    await harness.run("Complete the task", object(), AgentContext())

    assert captured["env"]["OPENAI_AGENTS_API_MODE"] == "chat_completions"


@pytest.mark.asyncio
async def test_tinker_route_ignores_api_mode_from_extra_env(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TINKER_API_KEY", "test-tinker-key")
    harness = OpenAIAgentsHarness(
        logs_dir=tmp_path,
        model_name=NEMOTRON_MODEL,
        mcp_servers=[
            MCPServerConfig(
                name="chi_bench",
                transport="streamable-http",
                url="http://chi-bench-server:8000/mcp",
            )
        ],
        provider_route="tinker",
    )
    saved_extra_env = {"OPENAI_AGENTS_API_MODE": "responses"}
    harness._extra_env = saved_extra_env
    captured: dict[str, Any] = {}

    async def fake_exec_as_agent(environment, *, command: str, env: dict[str, str]):
        captured["env"] = {**env, **harness._extra_env}

    monkeypatch.setattr(harness, "exec_as_agent", fake_exec_as_agent)

    await harness.run("Complete the task", object(), AgentContext())

    assert captured["env"]["OPENAI_AGENTS_API_MODE"] == "chat_completions"
    assert harness._extra_env is saved_extra_env
    assert saved_extra_env == {"OPENAI_AGENTS_API_MODE": "responses"}


@pytest.mark.asyncio
async def test_non_tinker_route_keeps_api_mode_from_extra_env(
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
    )
    saved_extra_env = {"OPENAI_AGENTS_API_MODE": "responses"}
    harness._extra_env = saved_extra_env
    captured: dict[str, Any] = {}

    async def fake_exec_as_agent(environment, *, command: str, env: dict[str, str]):
        captured["env"] = {**env, **harness._extra_env}

    monkeypatch.setattr(harness, "exec_as_agent", fake_exec_as_agent)

    await harness.run("Complete the task", object(), AgentContext())

    assert captured["env"]["OPENAI_AGENTS_API_MODE"] == "responses"
    assert harness._extra_env is saved_extra_env
    assert saved_extra_env == {"OPENAI_AGENTS_API_MODE": "responses"}
