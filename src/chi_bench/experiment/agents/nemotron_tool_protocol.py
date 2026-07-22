"""Pure compatibility helpers for Nemotron's XML tool-call protocol."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass

NEMOTRON_ULTRA_256K_MODEL = "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16:peft:262144"

_SAFE_NAME = r"[A-Za-z0-9_-]+"
_TOOL_CALL_PATTERN = re.compile(
    rf"""
    <tool_call>
    \s*
    <function=(?P<name>{_SAFE_NAME})>
    (?P<body>.*?)
    </function>
    \s*
    </tool_call>
    """,
    re.DOTALL | re.VERBOSE,
)
_PARAMETER_PATTERN = re.compile(
    rf"<parameter=(?P<name>{_SAFE_NAME})>(?P<value>.*?)</parameter>",
    re.DOTALL,
)
_WHITESPACE_PATTERN = re.compile(r"\s*")


@dataclass(frozen=True)
class NemotronToolCall:
    """A parsed Nemotron function call in provider-independent form."""

    call_id: str
    name: str
    arguments: dict[str, object]


def parse_nemotron_tool_calls(content: str) -> tuple[NemotronToolCall, ...] | None:
    """Parse only complete XML-only Nemotron tool responses; otherwise return ``None``."""

    source = content.strip()
    if not source:
        return None

    calls: list[NemotronToolCall] = []
    position = 0
    while position < len(source):
        match = _TOOL_CALL_PATTERN.match(source, position)
        if match is None:
            return None

        arguments = _parse_parameters(match.group("body"))
        if arguments is None:
            return None

        call_index = len(calls)
        call_source = match.group(0)
        digest = hashlib.sha256(f"{call_index}\0{call_source}".encode()).hexdigest()[:24]
        calls.append(
            NemotronToolCall(
                call_id=f"call_{digest}",
                name=match.group("name"),
                arguments=arguments,
            )
        )

        position = _WHITESPACE_PATTERN.match(source, match.end()).end()

    return tuple(calls) if calls else None


def normalize_nemotron_replay_input(
    request_input: str | list[dict[str, object]],
) -> str | list[dict[str, object]]:
    """Copy replay items and decode function-call argument JSON into mappings."""

    if isinstance(request_input, str):
        return request_input

    normalized = copy.deepcopy(request_input)
    for item in normalized:
        if item.get("type") != "function_call":
            continue
        arguments = item.get("arguments")
        if isinstance(arguments, dict):
            continue
        if not isinstance(arguments, str):
            raise ValueError("function-call arguments must be a JSON object")
        try:
            decoded = _load_json(arguments)
        except (TypeError, ValueError) as exc:
            raise ValueError("function-call arguments must be a JSON object") from exc
        if not isinstance(decoded, dict):
            raise ValueError("function-call arguments must be a JSON object")
        item["arguments"] = decoded
    return normalized


def _parse_parameters(body: str) -> dict[str, object] | None:
    arguments: dict[str, object] = {}
    position = 0
    while True:
        position = _WHITESPACE_PATTERN.match(body, position).end()
        if position == len(body):
            return arguments

        match = _PARAMETER_PATTERN.match(body, position)
        if match is None:
            return None
        name = match.group("name")
        if name in arguments:
            return None
        arguments[name] = _decode_parameter_value(match.group("value"))
        position = match.end()


def _decode_parameter_value(value: str) -> object:
    if value.startswith("\r\n"):
        value = value[2:]
    elif value.startswith("\n"):
        value = value[1:]
    if value.endswith("\r\n"):
        value = value[:-2]
    elif value.endswith("\n"):
        value = value[:-1]

    try:
        return _load_json(value)
    except (TypeError, ValueError):
        return value


def _load_json(value: str) -> object:
    def reject_nonstandard_constant(constant: str) -> object:
        raise ValueError(f"invalid JSON constant: {constant}")

    return json.loads(value, parse_constant=reject_nonstandard_constant)
