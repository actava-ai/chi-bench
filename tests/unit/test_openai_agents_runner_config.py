"""OpenAI Agents SDK provider/model configuration tests."""

from __future__ import annotations

import os
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from chi_bench.experiment.agents import openai_agents_runner

NEMOTRON_MODEL = "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16:peft:262144"
TINKER_MODEL = "thinkingmachines/Inkling:peft:262144"
TINKER_BASE_URL = "https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1"


def _install_fake_agents_sdk(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    captured: dict[str, list[Any]] = {
        "agents": [],
        "chat_models": [],
        "clients": [],
        "model_settings": [],
        "nemotron_models": [],
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

    class CapturingAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.api_key = os.environ.get("OPENAI_API_KEY")
            self.base_url = os.environ.get("OPENAI_BASE_URL")
            self.closed = False
            captured["clients"].append(self)

        async def __aenter__(self) -> CapturingAsyncOpenAI:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            self.closed = True

    class CapturingOpenAIChatCompletionsModel:
        def __init__(
            self,
            model: str,
            openai_client: CapturingAsyncOpenAI,
            should_replay_reasoning_content: Any = None,
        ) -> None:
            self.model = model
            self.openai_client = openai_client
            self.should_replay_reasoning_content = should_replay_reasoning_content
            captured["chat_models"].append(self)

    class CapturingNemotronTinkerChatCompletionsModel(CapturingOpenAIChatCompletionsModel):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            captured["nemotron_models"].append(self)

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

    models_module = ModuleType("agents.models")
    chat_model_module = ModuleType("agents.models.openai_chatcompletions")
    chat_model_module.OpenAIChatCompletionsModel = CapturingOpenAIChatCompletionsModel

    openai_module = ModuleType("openai")
    openai_module.AsyncOpenAI = CapturingAsyncOpenAI

    local_tools_module = ModuleType("chi_bench.experiment.agents.openai_agents_local_tools")
    local_tools_module.build_local_tools = lambda _logs_dir: []

    nemotron_model_module = ModuleType("chi_bench.experiment.agents.nemotron_tinker_model")
    nemotron_model_module.NemotronTinkerChatCompletionsModel = (
        CapturingNemotronTinkerChatCompletionsModel
    )

    monkeypatch.setitem(sys.modules, "agents", agents_module)
    monkeypatch.setitem(sys.modules, "agents.mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "agents.models", models_module)
    monkeypatch.setitem(sys.modules, "agents.models.openai_chatcompletions", chat_model_module)
    monkeypatch.setitem(sys.modules, "openai", openai_module)
    monkeypatch.setitem(
        sys.modules,
        "chi_bench.experiment.agents.openai_agents_local_tools",
        local_tools_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "chi_bench.experiment.agents.nemotron_tinker_model",
        nemotron_model_module,
    )
    monkeypatch.setattr(openai_agents_runner, "_install_oversize_output_patch", lambda _path: None)
    monkeypatch.setattr(openai_agents_runner, "_install_mcp_tool_name_sanitizer", lambda: None)
    monkeypatch.setattr(openai_agents_runner, "_dump_trace", lambda **_kwargs: None)
    return captured


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "model",
        "api_mode",
        "base_url",
        "uses_responses",
        "uses_explicit_tinker_model",
        "uses_nemotron_adapter",
    ),
    [
        ("gpt-5.6-sol", None, None, True, False, False),
        ("moonshotai/kimi-k3", None, None, True, False, False),
        (TINKER_MODEL, "chat_completions", TINKER_BASE_URL, False, True, False),
        (NEMOTRON_MODEL, "chat_completions", TINKER_BASE_URL, False, True, True),
        (
            NEMOTRON_MODEL,
            "chat_completions",
            f"{TINKER_BASE_URL}/",
            False,
            True,
            True,
        ),
        (
            NEMOTRON_MODEL,
            "chat_completions",
            "https://example.invalid/v1",
            False,
            False,
            False,
        ),
        (NEMOTRON_MODEL, "responses", TINKER_BASE_URL, True, False, False),
        (
            TINKER_MODEL,
            "chat_completions",
            "https://example.invalid/v1",
            False,
            False,
            False,
        ),
        (TINKER_MODEL, "responses", TINKER_BASE_URL, True, False, False),
        (
            "custom-chat-model",
            "chat_completions",
            TINKER_BASE_URL,
            False,
            True,
            False,
        ),
        (
            "custom-chat-model",
            "chat_completions",
            "https://example.invalid/v1",
            False,
            False,
            False,
        ),
    ],
)
async def test_runner_selects_requested_sdk_api_without_changing_model_id(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    api_mode: str | None,
    base_url: str | None,
    uses_responses: bool,
    uses_explicit_tinker_model: bool,
    uses_nemotron_adapter: bool,
) -> None:
    captured = _install_fake_agents_sdk(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_AGENTS_MODEL", model)
    monkeypatch.delenv("OPENAI_AGENTS_API_MODE", raising=False)
    monkeypatch.delenv("OPENAI_AGENTS_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    if api_mode is not None:
        monkeypatch.setenv("OPENAI_AGENTS_API_MODE", api_mode)
    if base_url is not None:
        monkeypatch.setenv("OPENAI_BASE_URL", base_url)

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
    agent_model = captured["agents"][0]["model"]
    model_settings = captured["model_settings"][0]
    if uses_explicit_tinker_model:
        assert captured["chat_models"], (
            "expected an explicit Tinker Chat Completions model, "
            f"got agent_model={agent_model!r}, model_settings={model_settings!r}"
        )
        assert agent_model is captured["chat_models"][0]
        assert agent_model.model == model
        assert agent_model.openai_client is captured["clients"][0]
        assert agent_model.openai_client.kwargs == {}
        assert agent_model.openai_client.api_key == "test-openai-key"
        assert agent_model.openai_client.base_url.rstrip("/") == TINKER_BASE_URL
        assert agent_model.openai_client.closed is True
        hook = agent_model.should_replay_reasoning_content
        assert hook(
            SimpleNamespace(
                model=model,
                base_url=TINKER_BASE_URL,
                reasoning=SimpleNamespace(origin_model=model),
            )
        )
        assert not hook(
            SimpleNamespace(
                model=model,
                base_url=TINKER_BASE_URL,
                reasoning=SimpleNamespace(origin_model=f"{model}-other"),
            )
        )
        assert not hook(
            SimpleNamespace(
                model=model,
                base_url="https://example.invalid/v1",
                reasoning=SimpleNamespace(origin_model=model),
            )
        )
        assert not hook(
            SimpleNamespace(
                base_url=TINKER_BASE_URL,
                reasoning=SimpleNamespace(origin_model=model),
            )
        )
        assert not hook(
            SimpleNamespace(
                model=123,
                base_url=TINKER_BASE_URL,
                reasoning=SimpleNamespace(origin_model=123),
            )
        )
        assert model_settings["extra_body"] == {"separate_reasoning": True}
    else:
        assert agent_model == model
        assert captured["chat_models"] == []
        assert "extra_body" not in model_settings
    if uses_nemotron_adapter:
        assert captured["nemotron_models"] == [agent_model]
    else:
        assert captured["nemotron_models"] == []


@pytest.mark.parametrize(
    ("model", "reasoning_content"),
    [
        (TINKER_MODEL, "opaque-inkling-reasoning"),
        (NEMOTRON_MODEL, "opaque-nemotron-reasoning"),
    ],
)
def test_pinned_sdk_replays_tinker_reasoning_only_with_same_model_hook(
    model: str, reasoning_content: str
) -> None:
    pytest.importorskip("agents")
    from agents.models.chatcmpl_converter import Converter

    items = [
        {
            "id": "rs_tinker",
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": reasoning_content}],
            "provider_data": {"model": model},
        },
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "chart_get_patient",
            "arguments": "{}",
            "status": "completed",
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "{}",
        },
    ]

    default_messages = Converter.items_to_messages(items, model=model)
    hooked_messages = Converter.items_to_messages(
        items,
        model=model,
        base_url=TINKER_BASE_URL,
        should_replay_reasoning_content=(
            openai_agents_runner._should_replay_same_model_reasoning_content
        ),
    )
    cross_model_messages = Converter.items_to_messages(
        items,
        model=f"{model}-other",
        base_url=TINKER_BASE_URL,
        should_replay_reasoning_content=(
            openai_agents_runner._should_replay_same_model_reasoning_content
        ),
    )
    wrong_route_messages = Converter.items_to_messages(
        items,
        model=model,
        base_url="https://example.invalid/v1",
        should_replay_reasoning_content=(
            openai_agents_runner._should_replay_same_model_reasoning_content
        ),
    )

    assert "reasoning_content" not in default_messages[0]
    assert hooked_messages[0]["reasoning_content"] == reasoning_content
    assert "reasoning_content" not in cross_model_messages[0]
    assert "reasoning_content" not in wrong_route_messages[0]


@pytest.mark.asyncio
async def test_runner_adds_reasoning_effort_to_model_settings(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _install_fake_agents_sdk(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", TINKER_BASE_URL)
    monkeypatch.setenv("OPENAI_AGENTS_MODEL", TINKER_MODEL)
    monkeypatch.setenv("OPENAI_AGENTS_API_MODE", "chat_completions")
    monkeypatch.setenv("OPENAI_AGENTS_REASONING_EFFORT", "high")

    await openai_agents_runner.run_agent(
        "Complete the task",
        "http://chi-bench-server:8000/mcp",
        logs_dir=tmp_path,
    )

    assert captured["model_settings"][0]["reasoning"] == {"effort": "high"}
    assert captured["model_settings"][0]["extra_body"] == {"separate_reasoning": True}
