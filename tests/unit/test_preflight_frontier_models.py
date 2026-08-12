"""Tests for the redacted frontier-model live preflight."""

from __future__ import annotations

import copy
import importlib.util
import json
from collections import defaultdict
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

from chi_bench.experiment.agents.nemotron_tool_protocol import (
    NEMOTRON_ULTRA_256K_MODEL as NEMOTRON_MODEL,
    parse_nemotron_tool_calls,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts/preflight_frontier_models.py"
MATRIX_PATH = REPO_ROOT / "configs/experiments/frontier_models_smoke_2026_07.yaml"
NEMOTRON_TOOL_XML = (
    "<tool_call>\n"
    "<function=preflight_echo>\n"
    "<parameter=value>\n"
    "ping\n"
    "</parameter>\n"
    "</function>\n"
    "</tool_call>"
)

TEST_CREDENTIALS = {
    "ANTHROPIC_API_KEY": "anthropic-test-secret-123456",
    "OPENAI_API_KEY": "openai-test-secret-123456",
    "OPENROUTER_API_KEY": "openrouter-test-secret-123456",
    "TINKER_API_KEY": "tinker-test-secret-123456",
}


@pytest.fixture(scope="module")
def preflight() -> ModuleType:
    assert SCRIPT_PATH.is_file(), f"missing preflight script: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("preflight_frontier_models", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _http_response(
    url: str,
    payload: dict[str, Any],
    *,
    request_id: str,
    status_code: int = 200,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    headers = {"x-request-id": request_id}
    headers.update(extra_headers or {})
    return httpx.Response(
        status_code,
        json=payload,
        headers=headers,
        request=httpx.Request("POST", url),
    )


def _anthropic_tool_response(model: str) -> dict[str, Any]:
    return {
        "id": f"msg_{model}_tool",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [
            {
                "type": "thinking",
                "thinking": "private-anthropic-reasoning",
                "signature": "signed-thinking-state",
            },
            {
                "type": "tool_use",
                "id": "toolu_echo",
                "name": "preflight_echo",
                "input": {"value": "ping"},
            },
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 4,
            "cache_creation_input_tokens": 2,
            "cache_read_input_tokens": 3,
        },
    }


def _anthropic_text_response(model: str, suffix: str = "final") -> dict[str, Any]:
    return {
        "id": f"msg_{model}_{suffix}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "PREFLIGHT_OK"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 8, "output_tokens": 3},
    }


def _responses_tool_response(model: str) -> dict[str, Any]:
    return {
        "id": f"resp_{model}_tool",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "model": model,
        "output": [
            {
                "id": "rs_echo",
                "type": "reasoning",
                "encrypted_content": "opaque-responses-reasoning-state",
                "summary": [],
            },
            {
                "id": "fc_echo",
                "type": "function_call",
                "call_id": "call_echo",
                "name": "preflight_echo",
                "arguments": '{"value":"ping"}',
                "status": "completed",
            },
        ],
        "parallel_tool_calls": False,
        "error": None,
        "incomplete_details": None,
        "usage": {
            "input_tokens": 12,
            "input_tokens_details": {"cached_tokens": 2},
            "output_tokens": 4,
            "output_tokens_details": {"reasoning_tokens": 3},
            "total_tokens": 16,
        },
    }


def _responses_text_response(model: str) -> dict[str, Any]:
    return {
        "id": f"resp_{model}_final",
        "object": "response",
        "created_at": 2,
        "status": "completed",
        "model": model,
        "output": [
            {
                "id": "msg_echo",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "annotations": [],
                        "logprobs": [],
                        "text": "PREFLIGHT_OK",
                    }
                ],
            }
        ],
        "parallel_tool_calls": False,
        "error": None,
        "incomplete_details": None,
        "usage": {
            "input_tokens": 20,
            "input_tokens_details": {"cached_tokens": 1},
            "output_tokens": 3,
            "output_tokens_details": {"reasoning_tokens": 1},
            "total_tokens": 23,
        },
    }


def _chat_tool_response(model: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl_{model}_tool",
        "object": "chat.completion",
        "created": 1,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": "opaque-tinker-reasoning-state",
                    "tool_calls": [
                        {
                            "id": "call_echo",
                            "type": "function",
                            "function": {
                                "name": "preflight_echo",
                                "arguments": '{"value":"ping"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
                "logprobs": None,
            }
        ],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 5,
            "total_tokens": 16,
            "prompt_tokens_details": {"cached_tokens": 2},
            "completion_tokens_details": {"reasoning_tokens": 4},
        },
    }


def _nemotron_xml_tool_response(
    content: str = NEMOTRON_TOOL_XML,
    *,
    model: str = NEMOTRON_MODEL,
) -> dict[str, Any]:
    return {
        "id": f"chatcmpl_{model}_tool",
        "object": "chat.completion",
        "created": 1,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "reasoning_content": "opaque-nemotron-reasoning-state",
                    "reasoning_details": [{"type": "opaque", "id": "reasoning_state_1"}],
                },
                "finish_reason": "stop",
                "logprobs": None,
            }
        ],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 5,
            "total_tokens": 16,
            "prompt_tokens_details": {"cached_tokens": 2},
            "completion_tokens_details": {"reasoning_tokens": 4},
        },
    }


def _chat_text_response(model: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl_{model}_final",
        "object": "chat.completion",
        "created": 2,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "PREFLIGHT_OK"},
                "finish_reason": "stop",
                "logprobs": None,
            }
        ],
        "usage": {"prompt_tokens": 18, "completion_tokens": 3, "total_tokens": 21},
    }


class SequenceRequester:
    def __init__(
        self,
        payloads: list[dict[str, Any]],
        *,
        status_codes: list[int] | None = None,
    ) -> None:
        self.payloads = list(payloads)
        self.status_codes = list(status_codes or [200] * len(payloads))
        if len(self.status_codes) != len(self.payloads):
            raise ValueError("status_codes must match payloads")
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: Any,
    ) -> httpx.Response:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "json": copy.deepcopy(json),
                "timeout": timeout,
            }
        )
        payload = self.payloads.pop(0)
        status_code = self.status_codes.pop(0)
        return _http_response(
            url,
            payload,
            request_id=f"req_{len(self.calls)}",
            status_code=status_code,
        )


class StaticResponseRequester:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.call_count = 0

    def __call__(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: Any,
    ) -> httpx.Response:
        del method, url, headers, json, timeout
        self.call_count += 1
        return self.response


class FailingTransportRequester:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def __call__(self, *args: Any, **kwargs: Any) -> httpx.Response:
        del args, kwargs
        raise self.error


class ProviderRouter:
    """Realistic provider response double at the HTTP boundary."""

    def __init__(self, *, fail_model: str | None = None, leaked_secret: str = "") -> None:
        self.fail_model = fail_model
        self.leaked_secret = leaked_secret
        self.turns: defaultdict[tuple[str, str], int] = defaultdict(int)
        self.seen_models: list[str] = []

    def __call__(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: Any,
    ) -> httpx.Response:
        del method, headers, timeout
        model = json["model"]
        self.seen_models.append(model)
        key = (url, model)
        self.turns[key] += 1
        turn = self.turns[key]

        if model == self.fail_model:
            raise RuntimeError(
                f"provider rejected Bearer {self.leaked_secret}; "
                "also leaked sk-live-unlistedtoken123456; request prompt was "
                "You must call the preflight_echo tool exactly once with value='ping'. "
                "Do not answer before calling it. After receiving the tool result, reply with "
                "final text.; raw response was private-provider-body-fragment"
            )

        if url.endswith("/messages"):
            if "tools" not in json:
                payload = _anthropic_text_response(model, suffix="support")
            elif turn == 1:
                payload = _anthropic_tool_response(model)
            else:
                payload = _anthropic_text_response(model)
        elif url.endswith("/responses"):
            payload = (
                _responses_tool_response(model) if turn == 1 else _responses_text_response(model)
            )
        elif url.endswith("/chat/completions"):
            payload = _chat_tool_response(model) if turn == 1 else _chat_text_response(model)
        else:  # pragma: no cover - makes unexpected dispatch fail loudly
            raise AssertionError(f"unexpected URL: {url}")
        return _http_response(url, payload, request_id=f"req_{model}_{turn}")


def _spec(preflight: ModuleType, model: str) -> Any:
    return next(spec for spec in preflight.load_probe_specs(MATRIX_PATH) if spec.model == model)


def _write_env_file(path: Path) -> None:
    path.write_text("".join(f"{key}={value}\n" for key, value in TEST_CREDENTIALS.items()))


def _write_nemotron_config(path: Path) -> None:
    path.write_text(
        f"""rows:
  - agent: openai-agents
    model: {NEMOTRON_MODEL}
    agent_kwargs:
      provider_route: tinker
      api_mode: chat_completions
""",
        encoding="utf-8",
    )


def test_loads_six_exact_matrix_rows_and_dispatches_provider_modes(preflight: ModuleType) -> None:
    specs = preflight.load_probe_specs(MATRIX_PATH)

    assert [
        (spec.provider, spec.model, spec.resolved_model, spec.endpoint_mode, spec.api_key_env)
        for spec in specs
    ] == [
        (
            "anthropic",
            "anthropic/claude-fable-5",
            "claude-fable-5",
            "messages",
            "ANTHROPIC_API_KEY",
        ),
        ("openai", "openai/gpt-5.6-sol", "gpt-5.6-sol", "responses", "OPENAI_API_KEY"),
        ("openai", "openai/gpt-5.6-terra", "gpt-5.6-terra", "responses", "OPENAI_API_KEY"),
        ("openai", "openai/gpt-5.6-luna", "gpt-5.6-luna", "responses", "OPENAI_API_KEY"),
        (
            "openrouter",
            "moonshotai/kimi-k3",
            "moonshotai/kimi-k3",
            "responses",
            "OPENROUTER_API_KEY",
        ),
        (
            "tinker",
            "thinkingmachines/Inkling:peft:262144",
            "thinkingmachines/Inkling:peft:262144",
            "chat_completions",
            "TINKER_API_KEY",
        ),
    ]


def test_loads_explicit_tinker_route_for_one_row_nemotron_config(
    preflight: ModuleType, tmp_path: Path
) -> None:
    config = tmp_path / "nemotron.yaml"
    _write_nemotron_config(config)

    specs = preflight.load_probe_specs(config)

    assert specs == [
        preflight.ProbeSpec(
            provider="tinker",
            model=NEMOTRON_MODEL,
            resolved_model=NEMOTRON_MODEL,
            endpoint_mode="chat_completions",
            api_key_env="TINKER_API_KEY",
            endpoint=preflight.TINKER_CHAT_URL,
            agent_kwargs={
                "provider_route": "tinker",
                "api_mode": "chat_completions",
            },
        )
    ]


def test_explicit_tinker_nemotron_probe_converts_xml_tool_call_for_replay(
    preflight: ModuleType, tmp_path: Path
) -> None:
    config = tmp_path / "nemotron.yaml"
    _write_nemotron_config(config)
    spec = preflight.load_probe_specs(config)[0]
    first = _nemotron_xml_tool_response()
    original_assistant = copy.deepcopy(first["choices"][0]["message"])
    requester = SequenceRequester([first, _chat_text_response(NEMOTRON_MODEL)])

    result = preflight.probe_model(spec, TEST_CREDENTIALS, requester)

    assert result["success"] is True
    assert result["tool_roundtrip"] is True
    assert result["reasoning_metadata"] is True
    assert all("reasoning_effort" not in call["json"] for call in requester.calls)
    assert all(call["json"]["separate_reasoning"] is True for call in requester.calls)
    parsed_calls = parse_nemotron_tool_calls(NEMOTRON_TOOL_XML)
    assert parsed_calls is not None
    assert len(parsed_calls) == 1
    expected_call = parsed_calls[0]
    second_messages = requester.calls[1]["json"]["messages"]
    assert second_messages[1] == {
        "role": "assistant",
        "content": None,
        "reasoning_content": "opaque-nemotron-reasoning-state",
        "reasoning_details": [{"type": "opaque", "id": "reasoning_state_1"}],
        "tool_calls": [
            {
                "id": expected_call.call_id,
                "type": "function",
                "function": {
                    "name": "preflight_echo",
                    "arguments": {"value": "ping"},
                },
            }
        ],
    }
    assert second_messages[2] == {
        "role": "tool",
        "tool_call_id": expected_call.call_id,
        "content": '{"echo":"ping","ok":true}',
    }
    assert first["choices"][0]["message"] == original_assistant
    assert NEMOTRON_TOOL_XML not in json.dumps(requester.calls[1]["json"])
    serialized_result = json.dumps(result)
    assert NEMOTRON_TOOL_XML not in serialized_result
    assert "opaque-nemotron-reasoning-state" not in serialized_result


def test_explicit_tinker_nemotron_second_turn_error_redacts_dynamic_reasoning(
    preflight: ModuleType,
    tmp_path: Path,
) -> None:
    config = tmp_path / "nemotron.yaml"
    _write_nemotron_config(config)
    spec = preflight.load_probe_specs(config)[0]
    direct_reasoning = "unique dynamic reasoning content 5802d9c1"
    nested_reasoning = "unique nested reasoning detail 919ab736"
    first = _nemotron_xml_tool_response()
    assistant = first["choices"][0]["message"]
    assistant["reasoning_content"] = direct_reasoning
    assistant["reasoning_details"] = [
        {
            "type": "opaque",
            "detail": {"segments": [{"text": nested_reasoning}]},
        }
    ]
    error_payload = {
        "error": {
            "type": "invalid_request_error",
            "code": "replay_rejected",
            "message": f"replay rejected: {direct_reasoning}; nested: {nested_reasoning}",
        }
    }
    requester = SequenceRequester([first, error_payload], status_codes=[200, 400])

    result = preflight.probe_model(spec, TEST_CREDENTIALS, requester)

    assert result["success"] is False
    assert result["tool_roundtrip"] is True
    assert result["error"] == {
        "kind": "http",
        "message": "replay rejected: [REDACTED]; nested: [REDACTED]",
        "status_code": 400,
        "provider_type": "invalid_request_error",
        "provider_code": "replay_rejected",
    }
    assert result["request_ids"] == ["req_1", "req_2"]
    assert len(requester.calls) == 2
    replayed_assistant = requester.calls[1]["json"]["messages"][1]
    assert replayed_assistant["reasoning_content"] == direct_reasoning
    assert replayed_assistant["reasoning_details"] == assistant["reasoning_details"]
    serialized_result = json.dumps(result)
    assert direct_reasoning not in serialized_result
    assert nested_reasoning not in serialized_result
    assert NEMOTRON_TOOL_XML not in serialized_result


@pytest.mark.parametrize(
    "content",
    [
        NEMOTRON_TOOL_XML.removesuffix("</tool_call>"),
        f"{NEMOTRON_TOOL_XML}\ntrailing response text",
        NEMOTRON_TOOL_XML.replace("preflight_echo", "other_tool"),
        NEMOTRON_TOOL_XML.replace("\nping\n", "\npong\n"),
        f"{NEMOTRON_TOOL_XML}\n{NEMOTRON_TOOL_XML}",
    ],
    ids=["malformed", "trailing-text", "wrong-tool", "wrong-arguments", "multiple-calls"],
)
def test_explicit_tinker_nemotron_probe_rejects_invalid_xml_without_replay(
    preflight: ModuleType,
    tmp_path: Path,
    content: str,
) -> None:
    config = tmp_path / "nemotron.yaml"
    _write_nemotron_config(config)
    spec = preflight.load_probe_specs(config)[0]
    first = _nemotron_xml_tool_response(content)
    requester = SequenceRequester([first])

    result = preflight.probe_model(spec, TEST_CREDENTIALS, requester)

    assert result["success"] is False
    assert result["tool_roundtrip"] is False
    assert result["error"] == {
        "kind": "validation",
        "message": "chat model did not make exactly one preflight_echo function call",
    }
    assert len(requester.calls) == 1
    serialized_result = json.dumps(result)
    assert content not in serialized_result
    assert "opaque-nemotron-reasoning-state" not in serialized_result


@pytest.mark.parametrize(
    "tool_calls",
    [{}, "", 0],
    ids=["empty-mapping", "empty-string", "zero"],
)
def test_explicit_tinker_nemotron_probe_rejects_falsey_malformed_tool_calls(
    preflight: ModuleType,
    tmp_path: Path,
    tool_calls: object,
) -> None:
    config = tmp_path / "nemotron.yaml"
    _write_nemotron_config(config)
    spec = preflight.load_probe_specs(config)[0]
    first = _nemotron_xml_tool_response()
    first["choices"][0]["message"]["tool_calls"] = tool_calls
    requester = SequenceRequester([first])

    result = preflight.probe_model(spec, TEST_CREDENTIALS, requester)

    assert result["success"] is False
    assert result["tool_roundtrip"] is False
    assert result["error"] == {
        "kind": "validation",
        "message": "chat model did not make exactly one preflight_echo function call",
    }
    assert len(requester.calls) == 1
    serialized_result = json.dumps(result)
    assert NEMOTRON_TOOL_XML not in serialized_result
    assert "opaque-nemotron-reasoning-state" not in serialized_result


@pytest.mark.parametrize("rows_yaml", ["[]", "{}"])
def test_load_probe_specs_requires_at_least_one_row(
    preflight: ModuleType, tmp_path: Path, rows_yaml: str
) -> None:
    config = tmp_path / "invalid-rows.yaml"
    config.write_text(f"rows: {rows_yaml}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="requires at least one row"):
        preflight.load_probe_specs(config)


def test_load_probe_specs_rejects_malformed_row(preflight: ModuleType, tmp_path: Path) -> None:
    config = tmp_path / "malformed-row.yaml"
    config.write_text("rows:\n  - malformed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="every frontier preflight row must be a mapping"):
        preflight.load_probe_specs(config)


def test_anthropic_two_turn_probe_preserves_all_assistant_blocks(preflight: ModuleType) -> None:
    spec = _spec(preflight, "anthropic/claude-fable-5")
    first = _anthropic_tool_response("claude-fable-5")
    requester = SequenceRequester([first, _anthropic_text_response("claude-fable-5")])

    result = preflight.probe_model(spec, TEST_CREDENTIALS, requester)

    assert result["success"] is True
    assert result["tool_roundtrip"] is True
    assert result["reasoning_metadata"] is True
    assert result["request_ids"] == ["req_1", "req_2"]
    assert result["response_ids"] == [
        "msg_claude-fable-5_tool",
        "msg_claude-fable-5_final",
    ]
    assert result["usage"] == {
        "input_tokens": 18,
        "output_tokens": 7,
        "total_tokens": 25,
        "cached_tokens": 5,
        "reasoning_tokens": 0,
    }
    assert requester.calls[0]["url"] == "https://api.anthropic.com/v1/messages"
    assert requester.calls[0]["json"]["model"] == "claude-fable-5"
    assert requester.calls[0]["json"]["thinking"] == {"type": "adaptive"}
    assert requester.calls[0]["json"]["output_config"] == {"effort": "high"}
    assert requester.calls[0]["json"]["tool_choice"] == {
        "type": "auto",
        "disable_parallel_tool_use": True,
    }
    second_messages = requester.calls[1]["json"]["messages"]
    assert second_messages[1] == {"role": "assistant", "content": first["content"]}
    assert second_messages[2]["content"][0]["tool_use_id"] == "toolu_echo"


@pytest.mark.parametrize(
    ("configured_model", "expected_url", "expected_model", "expected_tool_choice"),
    [
        (
            "openai/gpt-5.6-sol",
            "https://api.openai.com/v1/responses",
            "gpt-5.6-sol",
            {"type": "function", "name": "preflight_echo"},
        ),
        (
            "moonshotai/kimi-k3",
            "https://openrouter.ai/api/v1/responses",
            "moonshotai/kimi-k3",
            "auto",
        ),
    ],
)
def test_responses_probe_replays_full_output_with_function_result(
    preflight: ModuleType,
    configured_model: str,
    expected_url: str,
    expected_model: str,
    expected_tool_choice: str | dict[str, str],
) -> None:
    spec = _spec(preflight, configured_model)
    first = _responses_tool_response(expected_model)
    requester = SequenceRequester([first, _responses_text_response(expected_model)])

    result = preflight.probe_model(spec, TEST_CREDENTIALS, requester)

    assert result["success"] is True
    assert result["tool_roundtrip"] is True
    assert result["reasoning_metadata"] is True
    assert result["request_ids"] == ["req_1", "req_2"]
    assert result["response_ids"] == [
        f"resp_{expected_model}_tool",
        f"resp_{expected_model}_final",
    ]
    assert requester.calls[0]["url"] == expected_url
    assert requester.calls[0]["json"]["model"] == expected_model
    assert requester.calls[0]["json"]["tool_choice"] == expected_tool_choice
    assert requester.calls[1]["json"]["tool_choice"] == "none"
    second_input = requester.calls[1]["json"]["input"]
    assert second_input[1:3] == first["output"]
    assert second_input[1]["encrypted_content"] == "opaque-responses-reasoning-state"
    assert second_input[3] == {
        "type": "function_call_output",
        "call_id": "call_echo",
        "output": '{"echo":"ping","ok":true}',
    }
    assert result["usage"] == {
        "input_tokens": 32,
        "output_tokens": 7,
        "total_tokens": 39,
        "cached_tokens": 3,
        "reasoning_tokens": 4,
    }


def test_tinker_chat_probe_replays_full_assistant_message(preflight: ModuleType) -> None:
    model = "thinkingmachines/Inkling:peft:262144"
    spec = _spec(preflight, model)
    first = _chat_tool_response(model)
    requester = SequenceRequester([first, _chat_text_response(model)])

    result = preflight.probe_model(spec, TEST_CREDENTIALS, requester)

    assert result["success"] is True
    assert result["tool_roundtrip"] is True
    assert result["reasoning_metadata"] is True
    assert requester.calls[0]["url"] == (
        "https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1/chat/completions"
    )
    assert requester.calls[0]["json"]["model"] == model
    assert requester.calls[0]["json"]["reasoning_effort"] == "high"
    assert requester.calls[0]["json"]["separate_reasoning"] is True
    second_messages = requester.calls[1]["json"]["messages"]
    assert second_messages[1] == first["choices"][0]["message"]
    assert second_messages[2] == {
        "role": "tool",
        "tool_call_id": "call_echo",
        "content": '{"echo":"ping","ok":true}',
    }


def test_tinker_inkling_probe_still_requires_tool_calls_finish_reason(
    preflight: ModuleType,
) -> None:
    model = "thinkingmachines/Inkling:peft:262144"
    first = _chat_tool_response(model)
    first["choices"][0]["finish_reason"] = "stop"
    requester = SequenceRequester([first])

    result = preflight.probe_model(_spec(preflight, model), TEST_CREDENTIALS, requester)

    assert result["success"] is False
    assert result["tool_roundtrip"] is False
    assert result["error"] == {
        "kind": "validation",
        "message": "chat model did not make exactly one preflight_echo function call",
    }
    assert len(requester.calls) == 1


def test_probe_requires_final_text_after_tool_result(preflight: ModuleType) -> None:
    model = "thinkingmachines/Inkling:peft:262144"
    empty_final = _chat_text_response(model)
    empty_final["choices"][0]["message"]["content"] = None
    requester = SequenceRequester([_chat_tool_response(model), empty_final])

    result = preflight.probe_model(_spec(preflight, model), TEST_CREDENTIALS, requester)

    assert result["success"] is False
    assert result["tool_roundtrip"] is True
    assert result["error"] == {
        "kind": "validation",
        "message": "provider did not return final text after the tool result",
    }


def test_transport_failure_keeps_only_exception_class(preflight: ModuleType) -> None:
    secret = TEST_CREDENTIALS["OPENAI_API_KEY"]
    error_detail = f"{secret}; {preflight.PREFLIGHT_PROMPT}; private-transport-detail"
    requester = FailingTransportRequester(httpx.ConnectTimeout(error_detail))

    result = preflight.probe_model(
        _spec(preflight, "openai/gpt-5.6-sol"), TEST_CREDENTIALS, requester
    )

    assert result["success"] is False
    assert result["error"] == {
        "kind": "transport",
        "exception_class": "ConnectTimeout",
    }
    serialized = json.dumps(result["error"])
    assert secret not in serialized
    assert preflight.PREFLIGHT_PROMPT not in serialized
    assert "private-transport-detail" not in serialized


@pytest.mark.parametrize(
    ("model", "status_code", "payload", "expected_error"),
    [
        (
            "anthropic/claude-fable-5",
            400,
            {
                "type": "error",
                "error": {
                    "type": "model_not_available",
                    "message": "data retention is required: {secret}; {prompt_fragment}",
                },
            },
            {
                "provider_type": "model_not_available",
                "message_fragment": "data retention is required",
            },
        ),
        (
            "openai/gpt-5.6-sol",
            401,
            {
                "error": {
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                    "message": "bad credential {secret}; {prompt_fragment}",
                }
            },
            {
                "provider_type": "invalid_request_error",
                "provider_code": "invalid_api_key",
                "message_fragment": "bad credential",
            },
        ),
        (
            "openai/gpt-5.6-terra",
            404,
            {
                "error": {
                    "type": "invalid_request_error",
                    "code": "model_not_found",
                    "message": "bad model id; {secret}; {prompt_fragment}",
                }
            },
            {
                "provider_type": "invalid_request_error",
                "provider_code": "model_not_found",
                "message_fragment": "bad model id",
            },
        ),
        (
            "thinkingmachines/Inkling:peft:262144",
            422,
            {
                "detail": {
                    "error": {
                        "type": "invalid_request_error",
                        "code": "unsupported_parameter",
                        "message": "separate_reasoning unsupported; {secret}; {prompt_fragment}",
                    }
                }
            },
            {
                "provider_type": "invalid_request_error",
                "provider_code": "unsupported_parameter",
                "message_fragment": "separate_reasoning unsupported",
            },
        ),
        (
            "moonshotai/kimi-k3",
            400,
            {
                "error_type": "provider_error",
                "error": {
                    "code": 400,
                    "message": "upstream rejected request; {secret}; {prompt_fragment}",
                },
            },
            {
                "provider_type": "provider_error",
                "provider_code": "400",
                "message_fragment": "upstream rejected request",
            },
        ),
    ],
)
def test_http_failures_keep_safe_structured_provider_diagnostics(
    preflight: ModuleType,
    model: str,
    status_code: int,
    payload: dict[str, Any],
    expected_error: dict[str, str],
) -> None:
    secret = TEST_CREDENTIALS[_spec(preflight, model).api_key_env]
    prompt_fragment = "You must call the preflight_echo tool exactly once"
    rendered_payload = copy.deepcopy(payload)
    error_node = rendered_payload.get("error")
    if isinstance(rendered_payload.get("detail"), dict):
        error_node = rendered_payload["detail"].get("error")
    assert isinstance(error_node, dict)
    message = error_node["message"]
    assert isinstance(message, str)
    error_node["message"] = (
        message.replace("{secret}", secret).replace("{prompt_fragment}", prompt_fragment)
        + " "
        + "x" * 800
        + " tail-provider-fragment"
    )
    url = _spec(preflight, model).endpoint
    requester = StaticResponseRequester(
        _http_response(
            url,
            rendered_payload,
            request_id="req_safe_error",
            status_code=status_code,
            extra_headers={"x-private-debug": f"raw-header-{secret}"},
        )
    )

    result = preflight.probe_model(_spec(preflight, model), TEST_CREDENTIALS, requester)

    assert result["success"] is False
    assert result["error"]["kind"] == "http"
    assert result["error"]["status_code"] == status_code
    assert result["error"]["provider_type"] == expected_error["provider_type"]
    if provider_code := expected_error.get("provider_code"):
        assert result["error"]["provider_code"] == provider_code
    assert expected_error["message_fragment"] in result["error"]["message"]
    assert result["request_ids"] == ["req_safe_error"]
    assert result["response_ids"] == []
    serialized = json.dumps(result["error"])
    assert secret not in serialized
    assert prompt_fragment not in serialized
    assert "x-private-debug" not in serialized
    assert "raw-header" not in serialized
    assert "tail-provider-fragment" not in serialized
    assert len(result["error"]["message"]) <= 300


def test_openrouter_error_extracts_safe_nested_upstream_diagnostics(
    preflight: ModuleType,
) -> None:
    model = "moonshotai/kimi-k3"
    secret = TEST_CREDENTIALS["OPENROUTER_API_KEY"]
    prompt_fragment = "You must call the preflight_echo tool exactly once"
    upstream_message = (
        "tool_choice 'specified' is incompatible with thinking enabled; "
        f"{secret}; {prompt_fragment}; " + "x" * 800 + " tail-upstream-fragment"
    )
    payload = {
        "error": {
            "code": 400,
            "message": "Provider returned error",
            "metadata": {
                "provider_name": "Moonshot AI",
                "raw": json.dumps(
                    {
                        "type": "error",
                        "error": {
                            "type": "invalid_request_error",
                            "message": upstream_message,
                        },
                        "private": "private-raw-body-field",
                    }
                ),
                "private": "private-outer-metadata-field",
            },
        }
    }
    spec = _spec(preflight, model)
    requester = StaticResponseRequester(
        _http_response(
            spec.endpoint,
            payload,
            request_id="req_openrouter_upstream",
            status_code=400,
        )
    )

    result = preflight.probe_model(spec, TEST_CREDENTIALS, requester)

    assert result["success"] is False
    assert result["error"]["kind"] == "http"
    assert result["error"]["status_code"] == 400
    assert result["error"]["provider_type"] == "invalid_request_error"
    assert result["error"]["provider_code"] == "400"
    assert (
        "tool_choice 'specified' is incompatible with thinking enabled"
        in result["error"]["message"]
    )
    assert result["request_ids"] == ["req_openrouter_upstream"]
    serialized = json.dumps(result)
    assert secret not in serialized
    assert prompt_fragment not in serialized
    assert "tail-upstream-fragment" not in serialized
    assert "private-raw-body-field" not in serialized
    assert "private-outer-metadata-field" not in serialized
    assert len(result["error"]["message"]) <= 300


def test_sanitize_text_redacts_known_bearer_and_token_like_values(preflight: ModuleType) -> None:
    known = "known-secret-value-123456"
    sanitized = preflight.sanitize_text(
        f"key={known}; Authorization: Bearer bearer-secret-123456; "
        "upstream=sk-live-unlistedtoken123456",
        [known],
    )

    assert known not in sanitized
    assert "bearer-secret-123456" not in sanitized
    assert "sk-live-unlistedtoken123456" not in sanitized
    assert preflight.PREFLIGHT_PROMPT not in preflight.sanitize_text(
        f"request body contained: {preflight.PREFLIGHT_PROMPT}",
        [],
    )
    assert sanitized.count("[REDACTED]") >= 3


def test_run_preflight_continues_after_failure_and_checks_support_models(
    preflight: ModuleType,
) -> None:
    router = ProviderRouter(
        fail_model="gpt-5.6-terra",
        leaked_secret=TEST_CREDENTIALS["OPENAI_API_KEY"],
    )

    report = preflight.run_preflight(MATRIX_PATH, TEST_CREDENTIALS, router)

    assert report["success"] is False
    assert len(report["evaluated"]) == 6
    assert len(report["support_checks"]) == 2
    assert report["summary"] == {"total": 8, "passed": 7, "failed": 1}
    assert (
        next(item for item in report["evaluated"] if item["resolved_model"] == "gpt-5.6-terra")[
            "success"
        ]
        is False
    )
    assert "gpt-5.6-luna" in router.seen_models
    assert "moonshotai/kimi-k3" in router.seen_models
    assert [item["resolved_model"] for item in report["support_checks"]] == [
        "claude-opus-4-7",
        "claude-sonnet-5",
    ]
    serialized = json.dumps(report)
    assert TEST_CREDENTIALS["OPENAI_API_KEY"] not in serialized
    assert "sk-live-unlistedtoken123456" not in serialized
    assert preflight.PREFLIGHT_PROMPT not in serialized
    assert "private-provider-body-fragment" not in serialized


def test_env_file_values_override_ambient_without_mutating_it(
    preflight: ModuleType, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env.test"
    file_key = "file-openai-secret-123456"
    env_file.write_text(
        f"OPENAI_API_KEY={file_key}\nOPENAI_BASE_URL=\n",
        encoding="utf-8",
    )
    ambient = {
        "OPENAI_API_KEY": "ambient-openai-secret-123456",
        "OPENAI_BASE_URL": "https://ambient-proxy.invalid/v1",
    }
    before = dict(ambient)

    credentials = preflight.load_credentials(env_file, ambient)

    assert credentials["OPENAI_API_KEY"] == file_key
    assert ambient == before


@pytest.mark.parametrize("base_var", ["OPENAI_BASE_URL", "ANTHROPIC_BASE_URL"])
@pytest.mark.parametrize("source", ["ambient", "env_file"])
def test_main_rejects_effective_endpoint_overrides_without_exposing_values(
    preflight: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    base_var: str,
    source: str,
) -> None:
    env_file = tmp_path / f".{base_var}.{source}.env"
    output = tmp_path / f"{base_var}.{source}.json"
    override = f"https://private-{base_var.lower()}.invalid/{source}/secret-route"
    lines = [f"{key}={value}" for key, value in TEST_CREDENTIALS.items()]
    ambient: dict[str, str] = {}
    if source == "env_file":
        lines.append(f"{base_var}={override}")
    else:
        ambient[base_var] = override
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    requester = ProviderRouter()

    exit_code = preflight.main(
        ["--config", str(MATRIX_PATH), "--env-file", str(env_file), "--output", str(output)],
        environ=ambient,
        request_fn=requester,
    )

    assert exit_code == 1
    assert requester.seen_models == []
    rendered = output.read_text() + capsys.readouterr().out
    assert base_var in rendered
    assert "official provider endpoints" in rendered
    assert override not in rendered


def test_main_writes_structured_json_and_returns_zero_without_mutating_environment(
    preflight: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / ".env.test"
    output = tmp_path / "preflight.json"
    _write_env_file(env_file)
    ambient = {"UNRELATED_PARENT_VALUE": "unchanged"}
    before = dict(ambient)

    exit_code = preflight.main(
        ["--config", str(MATRIX_PATH), "--env-file", str(env_file), "--output", str(output)],
        environ=ambient,
        request_fn=ProviderRouter(),
    )

    assert exit_code == 0
    assert ambient == before
    report = json.loads(output.read_text())
    assert report["schema_version"] == 1
    assert report["success"] is True
    assert report["summary"] == {"total": 8, "passed": 8, "failed": 0}
    assert len(report["evaluated"]) == 6
    assert len(report["support_checks"]) == 2
    assert set(report["evaluated"][0]) == {
        "provider",
        "model",
        "resolved_model",
        "endpoint_mode",
        "success",
        "tool_roundtrip",
        "reasoning_metadata",
        "request_ids",
        "response_ids",
        "usage",
        "latency_ms",
        "error",
    }
    rendered = output.read_text() + capsys.readouterr().out + capsys.readouterr().err
    for secret in TEST_CREDENTIALS.values():
        assert secret not in rendered


def test_main_returns_nonzero_and_serializes_only_sanitized_errors(
    preflight: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / ".env.test"
    output = tmp_path / "preflight.json"
    _write_env_file(env_file)
    leaked = TEST_CREDENTIALS["TINKER_API_KEY"]

    exit_code = preflight.main(
        ["--config", str(MATRIX_PATH), "--env-file", str(env_file), "--output", str(output)],
        environ={},
        request_fn=ProviderRouter(
            fail_model="thinkingmachines/Inkling:peft:262144", leaked_secret=leaked
        ),
    )

    assert exit_code == 1
    report_text = output.read_text()
    report = json.loads(report_text)
    assert report["success"] is False
    assert report["summary"]["failed"] == 1
    assert leaked not in report_text
    assert "sk-live-unlistedtoken123456" not in report_text
    terminal = capsys.readouterr()
    assert leaked not in terminal.out + terminal.err
    assert "sk-live-unlistedtoken123456" not in terminal.out + terminal.err
