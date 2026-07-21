"""OpenAI Agents SDK provider/model configuration tests."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from chi_bench.experiment.agents import openai_agents_runner


def _install_fake_agents_sdk(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    captured: dict[str, list[Any]] = {
        "agents": [],
        "model_settings": [],
        "providers": [],
        "run_configs": [],
    }
    agents_module = ModuleType("agents")

    class CapturingAgent:
        def __init__(self, **kwargs: Any) -> None:
            captured["agents"].append(kwargs)

    class CapturingModelSettings:
        def __init__(self, **kwargs: Any) -> None:
            captured["model_settings"].append(kwargs)

    class CapturingMultiProvider:
        def __init__(self, **kwargs: Any) -> None:
            captured["providers"].append(kwargs)

    class CapturingRunConfig:
        def __init__(self, **kwargs: Any) -> None:
            captured["run_configs"].append(kwargs)

    class FakeRunner:
        @staticmethod
        async def run(**_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(final_output=None, raw_responses=[], new_items=[])

    class RetryPolicies:
        @staticmethod
        def any(*policies: Any) -> tuple[Any, ...]:
            return policies

        @staticmethod
        def network_error() -> str:
            return "network_error"

        @staticmethod
        def http_status(statuses: list[int]) -> tuple[str, tuple[int, ...]]:
            return "http_status", tuple(statuses)

        @staticmethod
        def retry_after() -> str:
            return "retry_after"

        @staticmethod
        def provider_suggested() -> str:
            return "provider_suggested"

    agents_module.Agent = CapturingAgent
    agents_module.ModelRetryBackoffSettings = SimpleNamespace
    agents_module.ModelRetrySettings = SimpleNamespace
    agents_module.ModelSettings = CapturingModelSettings
    agents_module.MultiProvider = CapturingMultiProvider
    agents_module.RunConfig = CapturingRunConfig
    agents_module.Runner = FakeRunner
    agents_module.retry_policies = RetryPolicies
    agents_module.set_tracing_disabled = lambda _disabled: None

    mcp_module = ModuleType("agents.mcp")

    class FakeMCPServerStreamableHttp:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: Any) -> None:
            return None

    mcp_module.MCPServerStreamableHttp = FakeMCPServerStreamableHttp

    local_tools_module = ModuleType("chi_bench.experiment.agents.openai_agents_local_tools")
    local_tools_module.build_local_tools = lambda _logs_dir: []

    monkeypatch.setitem(sys.modules, "agents", agents_module)
    monkeypatch.setitem(sys.modules, "agents.mcp", mcp_module)
    monkeypatch.setitem(
        sys.modules,
        "chi_bench.experiment.agents.openai_agents_local_tools",
        local_tools_module,
    )
    monkeypatch.setattr(openai_agents_runner, "_install_oversize_output_patch", lambda _path: None)
    monkeypatch.setattr(openai_agents_runner, "_install_mcp_tool_name_sanitizer", lambda: None)
    monkeypatch.setattr(openai_agents_runner, "_dump_trace", lambda **_kwargs: None)
    return captured


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "api_mode", "uses_responses"),
    [
        ("gpt-5.6-sol", None, True),
        ("moonshotai/kimi-k3", None, True),
        ("thinkingmachines/Inkling:peft:262144", "chat_completions", False),
    ],
)
async def test_runner_selects_requested_sdk_api_without_changing_model_id(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    api_mode: str | None,
    uses_responses: bool,
) -> None:
    captured = _install_fake_agents_sdk(monkeypatch)
    monkeypatch.setenv("OPENAI_AGENTS_MODEL", model)
    monkeypatch.delenv("OPENAI_AGENTS_API_MODE", raising=False)
    monkeypatch.delenv("OPENAI_AGENTS_REASONING_EFFORT", raising=False)
    if api_mode is not None:
        monkeypatch.setenv("OPENAI_AGENTS_API_MODE", api_mode)

    await openai_agents_runner.run_agent(
        "Complete the task",
        "http://chi-bench-server:8000/mcp",
        logs_dir=tmp_path,
    )

    assert captured["providers"] == [
        {
            "unknown_prefix_mode": "model_id",
            "openai_use_responses": uses_responses,
        }
    ]
    assert captured["agents"][0]["model"] == model


@pytest.mark.asyncio
async def test_runner_adds_reasoning_effort_to_model_settings(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _install_fake_agents_sdk(monkeypatch)
    monkeypatch.setenv("OPENAI_AGENTS_MODEL", "thinkingmachines/Inkling:peft:262144")
    monkeypatch.setenv("OPENAI_AGENTS_API_MODE", "chat_completions")
    monkeypatch.setenv("OPENAI_AGENTS_REASONING_EFFORT", "high")

    await openai_agents_runner.run_agent(
        "Complete the task",
        "http://chi-bench-server:8000/mcp",
        logs_dir=tmp_path,
    )

    assert captured["model_settings"][0]["reasoning"] == {"effort": "high"}
