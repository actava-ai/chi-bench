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

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts/preflight_frontier_models.py"
MATRIX_PATH = REPO_ROOT / "configs/experiments/frontier_models_smoke_2026_07.yaml"

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
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        headers={"x-request-id": request_id},
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
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = list(payloads)
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
        return _http_response(url, payload, request_id=f"req_{len(self.calls)}")


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


def test_anthropic_two_turn_probe_preserves_all_assistant_blocks(preflight: ModuleType) -> None:
    spec = _spec(preflight, "anthropic/claude-fable-5")
    first = _anthropic_tool_response("claude-fable-5")
    requester = SequenceRequester([first, _anthropic_text_response("claude-fable-5")])

    result = preflight.probe_model(spec, TEST_CREDENTIALS, requester)

    assert result["success"] is True
    assert result["tool_roundtrip"] is True
    assert result["reasoning_metadata"] is True
    assert result["request_ids"] == [
        "req_1",
        "msg_claude-fable-5_tool",
        "req_2",
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
    ("configured_model", "expected_url", "expected_model"),
    [
        ("openai/gpt-5.6-sol", "https://api.openai.com/v1/responses", "gpt-5.6-sol"),
        (
            "moonshotai/kimi-k3",
            "https://openrouter.ai/api/v1/responses",
            "moonshotai/kimi-k3",
        ),
    ],
)
def test_responses_probe_replays_full_output_with_function_result(
    preflight: ModuleType,
    configured_model: str,
    expected_url: str,
    expected_model: str,
) -> None:
    spec = _spec(preflight, configured_model)
    first = _responses_tool_response(expected_model)
    requester = SequenceRequester([first, _responses_text_response(expected_model)])

    result = preflight.probe_model(spec, TEST_CREDENTIALS, requester)

    assert result["success"] is True
    assert result["tool_roundtrip"] is True
    assert result["reasoning_metadata"] is True
    assert requester.calls[0]["url"] == expected_url
    assert requester.calls[0]["json"]["model"] == expected_model
    assert requester.calls[0]["json"]["tool_choice"] == {
        "type": "function",
        "name": "preflight_echo",
    }
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


def test_probe_requires_final_text_after_tool_result(preflight: ModuleType) -> None:
    model = "thinkingmachines/Inkling:peft:262144"
    empty_final = _chat_text_response(model)
    empty_final["choices"][0]["message"]["content"] = None
    requester = SequenceRequester([_chat_tool_response(model), empty_final])

    result = preflight.probe_model(_spec(preflight, model), TEST_CREDENTIALS, requester)

    assert result["success"] is False
    assert result["tool_roundtrip"] is True
    assert "final text" in result["error"]


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


def test_main_writes_structured_json_and_returns_zero_without_mutating_routing(
    preflight: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / ".env.test"
    output = tmp_path / "preflight.json"
    _write_env_file(env_file)
    ambient = {"OPENAI_BASE_URL": "https://ambient.invalid/v1"}
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
