"""Redacted live provider preflight for the frontier-model smoke matrix.

This script intentionally uses raw HTTP APIs so it runs with the repository's
base dependencies. It stores only operational metadata; prompts, responses,
reasoning bodies, and credentials never enter the report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

import httpx
import yaml
from dotenv import dotenv_values

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENROUTER_RESPONSES_URL = "https://openrouter.ai/api/v1/responses"
TINKER_CHAT_URL = (
    "https://tinker.thinkingmachines.dev/services/tinker-prod/oai/api/v1/chat/completions"
)

API_KEY_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "TINKER_API_KEY",
)
ROUTING_ENV_VARS = ("OPENAI_BASE_URL", "ANTHROPIC_BASE_URL")
SUPPORT_MODELS = ("claude-opus-4-7", "claude-sonnet-5")
MAX_OUTPUT_TOKENS = 4096
SUPPORT_MAX_TOKENS = 64
MAX_ERROR_MESSAGE_CHARS = 300
MAX_ERROR_FIELD_CHARS = 100
MAX_IDENTIFIER_CHARS = 200
REQUEST_TIMEOUT = httpx.Timeout(130.0, connect=10.0, write=10.0, pool=10.0)

PREFLIGHT_PROMPT = (
    "You must call the preflight_echo tool exactly once with value='ping'. "
    "Do not answer before calling it. After receiving the tool result, reply with final text."
)
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {"value": {"type": "string", "enum": ["ping"]}},
    "required": ["value"],
    "additionalProperties": False,
}
TOOL_RESULT = '{"echo":"ping","ok":true}'
_SENSITIVE_PAYLOAD_TEXTS = (
    PREFLIGHT_PROMPT,
    "You must call the preflight_echo tool exactly once",
    "Do not answer before calling it",
    "After receiving the tool result, reply with final text",
    "Reply with OK.",
    TOOL_RESULT,
)

RequestFn = Callable[..., httpx.Response]


class ProbeSpec(NamedTuple):
    provider: str
    model: str
    resolved_model: str
    endpoint_mode: str
    api_key_env: str
    endpoint: str
    agent_kwargs: dict[str, str]


class ProbeFailure(RuntimeError):
    """Safe, allowlisted failure text that may be persisted in the report."""

    def __init__(
        self,
        message: str | None,
        *,
        kind: str = "validation",
        details: Mapping[str, Any] | None = None,
        request_ids: Sequence[str] = (),
        response_ids: Sequence[str] = (),
    ) -> None:
        super().__init__(message or "")
        self.message = message
        self.kind = kind
        self.details = dict(details or {})
        self.request_ids = list(request_ids)
        self.response_ids = list(response_ids)


_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:sk|rk|pk|ghp|gho|github_pat|xox[a-z]*|api|token|key)"
    r"[-_][A-Za-z0-9._~+/=-]{8,}",
    re.IGNORECASE,
)


def sanitize_text(value: object, known_secrets: Sequence[str] = ()) -> str:
    """Redact known credentials plus common bearer/token-shaped strings."""

    text = str(value)
    for payload_text in _SENSITIVE_PAYLOAD_TEXTS:
        text = text.replace(payload_text, "[REDACTED PAYLOAD]")
    for secret in sorted({item for item in known_secrets if item}, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    return _TOKEN_RE.sub("[REDACTED]", text)


def _sanitize_value(value: Any, known_secrets: Sequence[str]) -> Any:
    if isinstance(value, str):
        return sanitize_text(value, known_secrets)
    if isinstance(value, list):
        return [_sanitize_value(item, known_secrets) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item, known_secrets) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_value(item, known_secrets) for key, item in value.items()}
    return value


def _known_secrets(credentials: Mapping[str, str]) -> list[str]:
    return [credentials[key] for key in API_KEY_ENV_VARS if credentials.get(key)]


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _safe_error_value(
    value: object,
    known_secrets: Sequence[str],
    *,
    limit: int,
) -> str:
    return _truncate(sanitize_text(value, known_secrets), limit)


def _safe_exception_class(exc: Exception) -> str:
    name = type(exc).__name__
    return _truncate(re.sub(r"[^A-Za-z0-9_.-]", "_", name), MAX_ERROR_FIELD_CHARS)


def _failure_metadata(
    failure: ProbeFailure,
    known_secrets: Sequence[str],
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"kind": failure.kind}
    if failure.message:
        metadata["message"] = _safe_error_value(
            failure.message,
            known_secrets,
            limit=MAX_ERROR_MESSAGE_CHARS,
        )
    for key in (
        "status_code",
        "exception_class",
        "provider_type",
        "provider_code",
    ):
        value = failure.details.get(key)
        if value is None:
            continue
        if key == "status_code" and isinstance(value, int):
            metadata[key] = value
        else:
            metadata[key] = _safe_error_value(
                value,
                known_secrets,
                limit=MAX_ERROR_FIELD_CHARS,
            )
    return metadata


def _internal_error(exc: Exception) -> dict[str, str]:
    return {"kind": "internal", "exception_class": _safe_exception_class(exc)}


def _record_ids(
    result: dict[str, Any],
    request_ids: Sequence[str],
    response_ids: Sequence[str],
) -> None:
    for key, values in (("request_ids", request_ids), ("response_ids", response_ids)):
        for value in values:
            if value not in result[key]:
                result[key].append(value)


def _provider_spec(row: Mapping[str, Any]) -> ProbeSpec:
    model = row.get("model")
    if not isinstance(model, str) or not model:
        raise ValueError("every frontier preflight row must have a non-empty model")
    raw_kwargs = row.get("agent_kwargs") or {}
    if not isinstance(raw_kwargs, dict):
        raise ValueError(f"agent_kwargs for {model!r} must be a mapping")
    agent_kwargs = {str(key): str(value) for key, value in raw_kwargs.items()}

    if model.startswith("anthropic/"):
        return ProbeSpec(
            "anthropic",
            model,
            model.removeprefix("anthropic/"),
            "messages",
            "ANTHROPIC_API_KEY",
            ANTHROPIC_MESSAGES_URL,
            agent_kwargs,
        )
    if model.startswith("openai/"):
        return ProbeSpec(
            "openai",
            model,
            model.removeprefix("openai/"),
            "responses",
            "OPENAI_API_KEY",
            OPENAI_RESPONSES_URL,
            agent_kwargs,
        )
    if model.startswith("thinkingmachines/"):
        return ProbeSpec(
            "tinker",
            model,
            model,
            "chat_completions",
            "TINKER_API_KEY",
            TINKER_CHAT_URL,
            agent_kwargs,
        )
    return ProbeSpec(
        "openrouter",
        model,
        model,
        "responses",
        "OPENROUTER_API_KEY",
        OPENROUTER_RESPONSES_URL,
        agent_kwargs,
    )


def load_probe_specs(config_path: str | Path) -> list[ProbeSpec]:
    """Load the six evaluated rows in their reviewed matrix order."""

    data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("frontier preflight config must be a YAML mapping")
    rows = data.get("rows")
    if not isinstance(rows, list) or len(rows) != 6:
        count = len(rows) if isinstance(rows, list) else 0
        raise ValueError(f"frontier preflight requires exactly six rows; found {count}")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("every frontier preflight row must be a mapping")
    return [_provider_spec(row) for row in rows]


def _base_result(spec: ProbeSpec) -> dict[str, Any]:
    return {
        "provider": spec.provider,
        "model": spec.model,
        "resolved_model": spec.resolved_model,
        "endpoint_mode": spec.endpoint_mode,
        "success": False,
        "tool_roundtrip": False,
        "reasoning_metadata": False,
        "request_ids": [],
        "response_ids": [],
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "reasoning_tokens": 0,
        },
        "latency_ms": 0,
        "error": None,
    }


def _add_usage(total: dict[str, int], update: Mapping[str, int]) -> None:
    for key in total:
        total[key] += int(update.get(key, 0) or 0)


def _anthropic_usage(data: Mapping[str, Any]) -> dict[str, int]:
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cached_tokens": int(usage.get("cache_creation_input_tokens", 0) or 0)
        + int(usage.get("cache_read_input_tokens", 0) or 0),
        "reasoning_tokens": 0,
    }


def _responses_usage(data: Mapping[str, Any]) -> dict[str, int]:
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    input_details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    if not isinstance(input_details, dict):
        input_details = {}
    if not isinstance(output_details, dict):
        output_details = {}
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": int(usage.get("total_tokens", input_tokens + output_tokens) or 0),
        "cached_tokens": int(input_details.get("cached_tokens", 0) or 0),
        "reasoning_tokens": int(output_details.get("reasoning_tokens", 0) or 0),
    }


def _chat_usage(data: Mapping[str, Any]) -> dict[str, int]:
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    completion_details = usage.get("completion_tokens_details") or {}
    if not isinstance(prompt_details, dict):
        prompt_details = {}
    if not isinstance(completion_details, dict):
        completion_details = {}
    input_tokens = int(usage.get("prompt_tokens", 0) or 0)
    output_tokens = int(usage.get("completion_tokens", 0) or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": int(usage.get("total_tokens", input_tokens + output_tokens) or 0),
        "cached_tokens": int(prompt_details.get("cached_tokens", 0) or 0),
        "reasoning_tokens": int(completion_details.get("reasoning_tokens", 0) or 0),
    }


def _safe_identifier(value: object, known_secrets: Sequence[str]) -> str:
    sanitized = _safe_error_value(value, known_secrets, limit=MAX_IDENTIFIER_CHARS)
    return re.sub(r"[^A-Za-z0-9._:/=-]", "_", sanitized)


def _request_ids(
    response: httpx.Response,
    known_secrets: Sequence[str],
    data: Mapping[str, Any] | None = None,
) -> list[str]:
    request_ids: list[str] = []
    for header in ("request-id", "x-request-id"):
        value = response.headers.get(header)
        if value:
            request_ids.append(_safe_identifier(value, known_secrets))
    if data is not None and isinstance(data.get("request_id"), str):
        request_ids.append(_safe_identifier(data["request_id"], known_secrets))
    return list(dict.fromkeys(request_ids))


def _provider_error_fields(
    data: Mapping[str, Any],
    known_secrets: Sequence[str],
) -> tuple[str | None, str | None, str | None]:
    detail = data.get("detail")
    error = data.get("error")
    if isinstance(detail, dict):
        nested = detail.get("error")
        error = nested if isinstance(nested, dict) else detail

    error_mapping = error if isinstance(error, dict) else {}
    raw_type = data.get("error_type") or error_mapping.get("type")
    raw_code = error_mapping.get("code")
    raw_message = error_mapping.get("message")
    if raw_message is None and isinstance(error, str):
        raw_message = error
    if raw_message is None and isinstance(detail, str):
        raw_message = detail

    provider_type = (
        _safe_error_value(raw_type, known_secrets, limit=MAX_ERROR_FIELD_CHARS)
        if isinstance(raw_type, (str, int))
        else None
    )
    provider_code = (
        _safe_error_value(raw_code, known_secrets, limit=MAX_ERROR_FIELD_CHARS)
        if isinstance(raw_code, (str, int))
        else None
    )
    message = (
        _safe_error_value(raw_message, known_secrets, limit=MAX_ERROR_MESSAGE_CHARS)
        if isinstance(raw_message, (str, int))
        else None
    )
    return provider_type, provider_code, message


def _request_json(
    request_fn: RequestFn,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    known_secrets: Sequence[str],
) -> tuple[dict[str, Any], list[str], list[str]]:
    try:
        response = request_fn(
            "POST",
            url,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as exc:
        raise ProbeFailure(
            None,
            kind="transport",
            details={"exception_class": _safe_exception_class(exc)},
        ) from None

    if not 200 <= response.status_code < 300:
        try:
            raw_error = response.json()
        except Exception:
            raw_error = None
        error_data = raw_error if isinstance(raw_error, dict) else {}
        request_ids = _request_ids(response, known_secrets, error_data)
        provider_type, provider_code, message = _provider_error_fields(
            error_data,
            known_secrets,
        )
        details: dict[str, Any] = {"status_code": response.status_code}
        if provider_type:
            details["provider_type"] = provider_type
        if provider_code:
            details["provider_code"] = provider_code
        raise ProbeFailure(
            message or f"provider returned HTTP {response.status_code}",
            kind="http",
            details=details,
            request_ids=request_ids,
        ) from None

    try:
        data = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProbeFailure(
            "provider returned invalid JSON",
            request_ids=_request_ids(response, known_secrets),
        ) from exc
    if not isinstance(data, dict):
        raise ProbeFailure(
            "provider returned a non-object JSON response",
            request_ids=_request_ids(response, known_secrets),
        )

    request_ids = _request_ids(response, known_secrets, data)
    response_ids: list[str] = []
    body_id = data.get("id")
    if isinstance(body_id, str) and body_id:
        response_ids.append(_safe_identifier(body_id, known_secrets))
    return data, request_ids, response_ids


def _anthropic_headers(api_key: str) -> dict[str, str]:
    return {
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }


def _bearer_headers(api_key: str) -> dict[str, str]:
    return {"content-type": "application/json", "Authorization": f"Bearer {api_key}"}


def _anthropic_tool() -> dict[str, Any]:
    return {
        "name": "preflight_echo",
        "description": "Return the supplied value unchanged.",
        "input_schema": TOOL_PARAMETERS,
        "strict": True,
    }


def _responses_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "name": "preflight_echo",
        "description": "Return the supplied value unchanged.",
        "parameters": TOOL_PARAMETERS,
        "strict": True,
    }


def _chat_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "preflight_echo",
            "description": "Return the supplied value unchanged.",
            "parameters": TOOL_PARAMETERS,
        },
    }


def _require_anthropic_text(data: Mapping[str, Any]) -> None:
    content = data.get("content") or []
    if not isinstance(content, list) or not any(
        isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
        and block["text"].strip()
        for block in content
    ):
        raise ProbeFailure("provider did not return final text after the tool result")


def _require_responses_text(data: Mapping[str, Any]) -> None:
    output = data.get("output") or []
    found = False
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content") or []
            if isinstance(content, list) and any(
                isinstance(part, dict)
                and part.get("type") in {"output_text", "text"}
                and isinstance(part.get("text"), str)
                and part["text"].strip()
                for part in content
            ):
                found = True
                break
    if not found:
        raise ProbeFailure("provider did not return final text after the tool result")


def _chat_message(data: Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
    choices = data.get("choices") or []
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProbeFailure("chat provider returned no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ProbeFailure("chat provider returned no assistant message")
    finish_reason = choices[0].get("finish_reason")
    return message, finish_reason if isinstance(finish_reason, str) else None


def _require_chat_text(data: Mapping[str, Any]) -> None:
    message, _ = _chat_message(data)
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return
    if isinstance(content, list) and any(
        isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip()
        for item in content
    ):
        return
    raise ProbeFailure("provider did not return final text after the tool result")


def _probe_anthropic(
    spec: ProbeSpec,
    api_key: str,
    request_fn: RequestFn,
    result: dict[str, Any],
) -> None:
    tool = _anthropic_tool()
    first_user = {"role": "user", "content": PREFLIGHT_PROMPT}
    common: dict[str, Any] = {
        "model": spec.resolved_model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "tools": [tool],
        "thinking": {"type": "adaptive"},
    }
    if effort := spec.agent_kwargs.get("reasoning_effort"):
        common["output_config"] = {"effort": effort}
    first_payload = {
        **common,
        "messages": [first_user],
        # Forced tool_choice is incompatible with Fable's always-on adaptive thinking.
        # The prompt requires the call and the response is validated below.
        "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
    }
    first, request_ids, response_ids = _request_json(
        request_fn,
        spec.endpoint,
        headers=_anthropic_headers(api_key),
        payload=first_payload,
        known_secrets=(api_key,),
    )
    _record_ids(result, request_ids, response_ids)
    _add_usage(result["usage"], _anthropic_usage(first))
    content = first.get("content") or []
    if not isinstance(content, list):
        raise ProbeFailure("Anthropic response content was not a list")
    result["reasoning_metadata"] = any(
        isinstance(block, dict) and block.get("type") in {"thinking", "redacted_thinking"}
        for block in content
    )
    tool_calls = [
        block
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "tool_use"
        and block.get("name") == "preflight_echo"
    ]
    if first.get("stop_reason") != "tool_use" or len(tool_calls) != 1:
        raise ProbeFailure("Anthropic model did not make exactly one preflight_echo tool call")
    tool_call = tool_calls[0]
    tool_input = tool_call.get("input")
    if not isinstance(tool_input, dict) or tool_input.get("value") != "ping":
        raise ProbeFailure("Anthropic preflight_echo arguments were invalid")
    tool_use_id = tool_call.get("id")
    if not isinstance(tool_use_id, str) or not tool_use_id:
        raise ProbeFailure("Anthropic preflight_echo call had no id")
    result["tool_roundtrip"] = True

    second_payload = {
        **common,
        "messages": [
            first_user,
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": TOOL_RESULT,
                    }
                ],
            },
        ],
        "tool_choice": {"type": "none"},
    }
    second, request_ids, response_ids = _request_json(
        request_fn,
        spec.endpoint,
        headers=_anthropic_headers(api_key),
        payload=second_payload,
        known_secrets=(api_key,),
    )
    _record_ids(result, request_ids, response_ids)
    _add_usage(result["usage"], _anthropic_usage(second))
    second_content = second.get("content") or []
    if isinstance(second_content, list):
        result["reasoning_metadata"] = result["reasoning_metadata"] or any(
            isinstance(block, dict) and block.get("type") in {"thinking", "redacted_thinking"}
            for block in second_content
        )
    _require_anthropic_text(second)


def _responses_reasoning(data: Mapping[str, Any]) -> bool:
    output = data.get("output") or []
    return isinstance(output, list) and any(
        isinstance(item, dict)
        and (
            item.get("type") == "reasoning"
            or any(item.get(key) for key in ("reasoning", "reasoning_content", "encrypted_content"))
        )
        for item in output
    )


def _probe_responses(
    spec: ProbeSpec,
    api_key: str,
    request_fn: RequestFn,
    result: dict[str, Any],
) -> None:
    first_input = [{"role": "user", "content": PREFLIGHT_PROMPT}]
    common: dict[str, Any] = {
        "model": spec.resolved_model,
        "tools": [_responses_tool()],
        "parallel_tool_calls": False,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "store": False,
        "include": ["reasoning.encrypted_content"],
    }
    reasoning: dict[str, str] = {}
    if effort := spec.agent_kwargs.get("reasoning_effort"):
        reasoning["effort"] = effort
    if summary := spec.agent_kwargs.get("reasoning_summary"):
        reasoning["summary"] = summary
    if reasoning:
        common["reasoning"] = reasoning
    first_payload = {
        **common,
        "input": first_input,
        "tool_choice": {"type": "function", "name": "preflight_echo"},
    }
    first, request_ids, response_ids = _request_json(
        request_fn,
        spec.endpoint,
        headers=_bearer_headers(api_key),
        payload=first_payload,
        known_secrets=(api_key,),
    )
    _record_ids(result, request_ids, response_ids)
    _add_usage(result["usage"], _responses_usage(first))
    result["reasoning_metadata"] = _responses_reasoning(first)
    output = first.get("output") or []
    if not isinstance(output, list):
        raise ProbeFailure("Responses output was not a list")
    calls = [
        item
        for item in output
        if isinstance(item, dict)
        and item.get("type") == "function_call"
        and item.get("name") == "preflight_echo"
    ]
    if len(calls) != 1:
        raise ProbeFailure("Responses model did not make exactly one preflight_echo function call")
    call = calls[0]
    arguments = call.get("arguments")
    try:
        parsed_arguments = json.loads(arguments) if isinstance(arguments, str) else None
    except json.JSONDecodeError as exc:
        raise ProbeFailure("Responses preflight_echo arguments were invalid JSON") from exc
    if not isinstance(parsed_arguments, dict) or parsed_arguments.get("value") != "ping":
        raise ProbeFailure("Responses preflight_echo arguments were invalid")
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise ProbeFailure("Responses preflight_echo call had no call_id")
    result["tool_roundtrip"] = True

    second_payload = {
        **common,
        "input": [
            *first_input,
            *output,
            {"type": "function_call_output", "call_id": call_id, "output": TOOL_RESULT},
        ],
        "tool_choice": "none",
    }
    second, request_ids, response_ids = _request_json(
        request_fn,
        spec.endpoint,
        headers=_bearer_headers(api_key),
        payload=second_payload,
        known_secrets=(api_key,),
    )
    _record_ids(result, request_ids, response_ids)
    _add_usage(result["usage"], _responses_usage(second))
    result["reasoning_metadata"] = result["reasoning_metadata"] or _responses_reasoning(second)
    _require_responses_text(second)


def _chat_reasoning(message: Mapping[str, Any]) -> bool:
    return any(message.get(key) for key in ("reasoning", "reasoning_content", "reasoning_details"))


def _probe_chat(
    spec: ProbeSpec,
    api_key: str,
    request_fn: RequestFn,
    result: dict[str, Any],
) -> None:
    first_messages = [{"role": "user", "content": PREFLIGHT_PROMPT}]
    common: dict[str, Any] = {
        "model": spec.resolved_model,
        "tools": [_chat_tool()],
        "parallel_tool_calls": False,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "stream": False,
        "separate_reasoning": True,
    }
    if effort := spec.agent_kwargs.get("reasoning_effort"):
        common["reasoning_effort"] = effort
    first_payload = {
        **common,
        "messages": first_messages,
        "tool_choice": {"type": "function", "function": {"name": "preflight_echo"}},
    }
    first, request_ids, response_ids = _request_json(
        request_fn,
        spec.endpoint,
        headers=_bearer_headers(api_key),
        payload=first_payload,
        known_secrets=(api_key,),
    )
    _record_ids(result, request_ids, response_ids)
    _add_usage(result["usage"], _chat_usage(first))
    assistant, finish_reason = _chat_message(first)
    result["reasoning_metadata"] = _chat_reasoning(assistant)
    raw_calls = assistant.get("tool_calls") or []
    calls = []
    if isinstance(raw_calls, list):
        calls = [
            call
            for call in raw_calls
            if isinstance(call, dict)
            and isinstance(call.get("function"), dict)
            and call["function"].get("name") == "preflight_echo"
        ]
    if finish_reason != "tool_calls" or len(calls) != 1:
        raise ProbeFailure("chat model did not make exactly one preflight_echo function call")
    call = calls[0]
    function = call["function"]
    try:
        parsed_arguments = json.loads(function.get("arguments", ""))
    except json.JSONDecodeError as exc:
        raise ProbeFailure("chat preflight_echo arguments were invalid JSON") from exc
    if not isinstance(parsed_arguments, dict) or parsed_arguments.get("value") != "ping":
        raise ProbeFailure("chat preflight_echo arguments were invalid")
    call_id = call.get("id")
    if not isinstance(call_id, str) or not call_id:
        raise ProbeFailure("chat preflight_echo call had no id")
    result["tool_roundtrip"] = True

    second_payload = {
        **common,
        "messages": [
            *first_messages,
            assistant,
            {"role": "tool", "tool_call_id": call_id, "content": TOOL_RESULT},
        ],
        "tool_choice": "none",
    }
    second, request_ids, response_ids = _request_json(
        request_fn,
        spec.endpoint,
        headers=_bearer_headers(api_key),
        payload=second_payload,
        known_secrets=(api_key,),
    )
    _record_ids(result, request_ids, response_ids)
    _add_usage(result["usage"], _chat_usage(second))
    final_message, _ = _chat_message(second)
    result["reasoning_metadata"] = result["reasoning_metadata"] or _chat_reasoning(final_message)
    _require_chat_text(second)


def probe_model(
    spec: ProbeSpec,
    credentials: Mapping[str, str],
    request_fn: RequestFn = httpx.request,
) -> dict[str, Any]:
    """Run one evaluated model probe and return sanitized operational metadata."""

    result = _base_result(spec)
    secrets = _known_secrets(credentials)
    started = time.perf_counter()
    try:
        api_key = credentials.get(spec.api_key_env)
        if not api_key:
            raise ProbeFailure(f"{spec.api_key_env} is not set")
        if spec.provider == "anthropic":
            _probe_anthropic(spec, api_key, request_fn, result)
        elif spec.endpoint_mode == "responses":
            _probe_responses(spec, api_key, request_fn, result)
        elif spec.endpoint_mode == "chat_completions":
            _probe_chat(spec, api_key, request_fn, result)
        else:  # pragma: no cover - load_probe_specs constrains this
            raise ProbeFailure(f"unsupported endpoint mode: {spec.endpoint_mode}")
        result["success"] = True
    except ProbeFailure as exc:
        _record_ids(result, exc.request_ids, exc.response_ids)
        result["error"] = _failure_metadata(exc, secrets)
    except Exception as exc:
        result["error"] = _internal_error(exc)
    finally:
        result["latency_ms"] = max(0, round((time.perf_counter() - started) * 1000))
    return _sanitize_value(result, secrets)


def _support_spec(model: str) -> ProbeSpec:
    return ProbeSpec(
        "anthropic",
        model,
        model,
        "messages",
        "ANTHROPIC_API_KEY",
        ANTHROPIC_MESSAGES_URL,
        {},
    )


def _probe_support_model(
    model: str,
    credentials: Mapping[str, str],
    request_fn: RequestFn,
) -> dict[str, Any]:
    spec = _support_spec(model)
    result = _base_result(spec)
    secrets = _known_secrets(credentials)
    started = time.perf_counter()
    try:
        api_key = credentials.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ProbeFailure("ANTHROPIC_API_KEY is not set")
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": SUPPORT_MAX_TOKENS,
            "messages": [{"role": "user", "content": "Reply with OK."}],
        }
        if model == "claude-sonnet-5":
            payload["thinking"] = {"type": "disabled"}
        data, request_ids, response_ids = _request_json(
            request_fn,
            ANTHROPIC_MESSAGES_URL,
            headers=_anthropic_headers(api_key),
            payload=payload,
            known_secrets=(api_key,),
        )
        _record_ids(result, request_ids, response_ids)
        _add_usage(result["usage"], _anthropic_usage(data))
        content = data.get("content") or []
        if isinstance(content, list):
            result["reasoning_metadata"] = any(
                isinstance(block, dict) and block.get("type") in {"thinking", "redacted_thinking"}
                for block in content
            )
        _require_anthropic_text(data)
        result["success"] = True
    except ProbeFailure as exc:
        _record_ids(result, exc.request_ids, exc.response_ids)
        result["error"] = _failure_metadata(exc, secrets)
    except Exception as exc:
        result["error"] = _internal_error(exc)
    finally:
        result["latency_ms"] = max(0, round((time.perf_counter() - started) * 1000))
    return _sanitize_value(result, secrets)


def run_preflight(
    config_path: str | Path,
    credentials: Mapping[str, str],
    request_fn: RequestFn = httpx.request,
) -> dict[str, Any]:
    """Run all six evaluated cells and both Anthropic support checks."""

    specs = load_probe_specs(config_path)
    evaluated = [probe_model(spec, credentials, request_fn) for spec in specs]
    support_checks = [
        _probe_support_model(model, credentials, request_fn) for model in SUPPORT_MODELS
    ]
    results = [*evaluated, *support_checks]
    passed = sum(bool(item["success"]) for item in results)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "config": str(config_path),
        "success": passed == len(results),
        "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed},
        "evaluated": evaluated,
        "support_checks": support_checks,
    }
    return _sanitize_value(report, _known_secrets(credentials))


def load_credentials(
    env_file: str | Path,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the runner-equivalent env overlay without mutating ``os.environ``."""

    path = Path(env_file)
    if not path.is_file():
        raise FileNotFoundError(f"environment file not found: {path}")
    file_values = dotenv_values(path)
    ambient = os.environ if environ is None else environ
    effective = dict(ambient)
    for key, value in file_values.items():
        # python-dotenv ignores bare ``KEY`` entries but applies ``KEY=`` as
        # an explicit blank when load_dotenv(..., override=True) is used.
        if value is not None:
            effective[key] = str(value)

    conflicting_routes = [key for key in ROUTING_ENV_VARS if effective.get(key)]
    if conflicting_routes:
        names = ", ".join(conflicting_routes)
        raise ProbeFailure(
            f"official provider endpoints require these variables to be unset: {names}",
            kind="configuration",
        )

    credentials: dict[str, str] = {}
    for key in API_KEY_ENV_VARS:
        value = effective.get(key)
        if value:
            credentials[key] = str(value)
    return credentials


def _write_report(
    output_path: str | Path,
    report: Mapping[str, Any],
    known_secrets: Sequence[str],
) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sanitized = _sanitize_value(dict(report), known_secrets)
    path.write_text(json.dumps(sanitized, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    request_fn: RequestFn = httpx.request,
) -> int:
    args = _parse_args(argv)
    credentials: dict[str, str] = {}
    try:
        credentials = load_credentials(args.env_file, environ)
        report = run_preflight(args.config, credentials, request_fn)
    except ProbeFailure as exc:
        secrets = _known_secrets(credentials)
        report = {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "config": str(args.config),
            "success": False,
            "summary": {"total": 1, "passed": 0, "failed": 1},
            "evaluated": [],
            "support_checks": [],
            "error": _failure_metadata(exc, secrets),
        }
    except Exception as exc:
        secrets = _known_secrets(credentials)
        report = {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "config": str(args.config),
            "success": False,
            "summary": {"total": 1, "passed": 0, "failed": 1},
            "evaluated": [],
            "support_checks": [],
            "error": _internal_error(exc),
        }
    secrets = _known_secrets(credentials)
    _write_report(args.output, report, secrets)
    summary = report["summary"]
    print(
        f"Frontier preflight: {summary['passed']}/{summary['total']} passed; "
        f"report={sanitize_text(args.output, secrets)}"
    )
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
