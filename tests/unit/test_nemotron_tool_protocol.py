"""Pure Nemotron tool-protocol compatibility tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from chi_bench.experiment.agents.nemotron_tool_protocol import (
    NEMOTRON_ULTRA_256K_MODEL,
    NemotronToolCall,
    normalize_nemotron_replay_input,
    parse_nemotron_tool_calls,
)

_MISSING = object()


def test_protocol_exports_exact_model_and_frozen_call_value() -> None:
    assert NEMOTRON_ULTRA_256K_MODEL == "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16:peft:262144"
    call = NemotronToolCall(
        call_id="call_example",
        name="lookup_case",
        arguments={"case_id": "case-1"},
    )

    with pytest.raises(FrozenInstanceError):
        call.name = "other"  # type: ignore[misc]


def test_parse_single_call_decodes_json_values_and_preserves_multiline_text() -> None:
    content = """\
<tool_call>
<function=update_case>
<parameter=metadata>
{"priority": 3, "flags": [true, null]}
</parameter>
<parameter=steps>
["collect", {"review": false}]
</parameter>
<parameter=score>
2.5
</parameter>
<parameter=approved>
true
</parameter>
<parameter=optional_value>
null
</parameter>
<parameter=notes>
first line
second line
</parameter>
</function>
</tool_call>"""

    calls = parse_nemotron_tool_calls(content)

    assert calls is not None
    assert len(calls) == 1
    assert calls[0].name == "update_case"
    assert calls[0].arguments == {
        "metadata": {"priority": 3, "flags": [True, None]},
        "steps": ["collect", {"review": False}],
        "score": 2.5,
        "approved": True,
        "optional_value": None,
        "notes": "first line\nsecond line",
    }


def test_parse_multiple_calls_generates_distinct_stable_ids() -> None:
    content = """
<tool_call>
<function=first_tool>
<parameter=value>
one
</parameter>
</function>
</tool_call>

<tool_call>
<function=second-tool>
</function>
</tool_call>
"""

    first_parse = parse_nemotron_tool_calls(content)
    second_parse = parse_nemotron_tool_calls(content)

    assert first_parse is not None
    assert second_parse is not None
    assert [call.name for call in first_parse] == ["first_tool", "second-tool"]
    assert first_parse[1].arguments == {}
    assert [call.call_id for call in first_parse] == [call.call_id for call in second_parse]
    assert first_parse[0].call_id != first_parse[1].call_id
    assert all(call.call_id.startswith("call_") for call in first_parse)


def test_parse_preserves_non_json_parameter_text() -> None:
    content = """\
<tool_call>
<function=write_note>
<parameter=note>
{this is ordinary text, not JSON}
</parameter>
</function>
</tool_call>"""

    calls = parse_nemotron_tool_calls(content)

    assert calls is not None
    assert calls[0].arguments == {"note": "{this is ordinary text, not JSON}"}


@pytest.mark.parametrize(
    "content",
    [
        "",
        "no tool call",
        "prefix\n<tool_call><function=ping></function></tool_call>",
        "<tool_call><function=ping></function></tool_call>\nsuffix",
        "<think>reasoning</think><tool_call><function=ping></function></tool_call>",
        "<tool_call><function=ping></tool_call>",
        "<tool_call><function=ping><unknown /></function></tool_call>",
        (
            "<tool_call><function=ping><parameter=value>one</parameter>"
            "<parameter=value>two</parameter></function></tool_call>"
        ),
        "<tool_call><function=invalid.name></function></tool_call>",
        (
            "<tool_call><function=ping><parameter=invalid.name>one</parameter>"
            "</function></tool_call>"
        ),
        "<tool_call><function=ping></function><extra /></tool_call>",
    ],
)
def test_parse_rejects_non_protocol_content(content: str) -> None:
    assert parse_nemotron_tool_calls(content) is None


def test_replay_normalizer_preserves_string_input() -> None:
    request_input = "Complete the workflow"

    assert normalize_nemotron_replay_input(request_input) is request_input


def test_replay_normalizer_copies_items_and_decodes_only_function_call_arguments() -> None:
    request_input: list[dict[str, object]] = [
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup_case",
            "arguments": '{"case_id": "case-1", "filters": [1, true]}',
        },
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Continue"}],
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "done",
        },
        {
            "type": "function_call",
            "call_id": "call_2",
            "name": "empty_call",
            "arguments": {},
        },
    ]

    normalized = normalize_nemotron_replay_input(request_input)

    assert normalized == [
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup_case",
            "arguments": {"case_id": "case-1", "filters": [1, True]},
        },
        request_input[1],
        request_input[2],
        request_input[3],
    ]
    assert normalized is not request_input
    assert isinstance(normalized, list)
    assert all(copied is not original for copied, original in zip(normalized, request_input))
    assert normalized[1]["content"] is not request_input[1]["content"]
    assert normalized[3]["arguments"] is not request_input[3]["arguments"]
    assert request_input[0]["arguments"] == ('{"case_id": "case-1", "filters": [1, true]}')


def test_replay_normalizer_preserves_mapping_arguments_and_is_idempotent() -> None:
    request_input: list[dict[str, object]] = [
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup_case",
            "arguments": {"case": {"id": "case-1"}},
        }
    ]

    normalized = normalize_nemotron_replay_input(request_input)
    normalized_again = normalize_nemotron_replay_input(normalized)

    assert normalized_again == normalized == request_input
    assert normalized is not request_input
    assert normalized_again is not normalized
    assert normalized[0] is not request_input[0]
    assert normalized_again[0] is not normalized[0]
    assert normalized[0]["arguments"] is not request_input[0]["arguments"]
    assert normalized_again[0]["arguments"] is not normalized[0]["arguments"]


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param(_MISSING, id="missing"),
        pytest.param([], id="list"),
        pytest.param(None, id="none"),
        pytest.param(7, id="integer"),
        pytest.param(False, id="boolean"),
    ],
)
def test_replay_normalizer_rejects_malformed_argument_values(arguments: object) -> None:
    function_call: dict[str, object] = {
        "type": "function_call",
        "call_id": "call_1",
        "name": "lookup_case",
    }
    if arguments is not _MISSING:
        function_call["arguments"] = arguments

    with pytest.raises(ValueError, match="function-call arguments must be a JSON object"):
        normalize_nemotron_replay_input([function_call])


@pytest.mark.parametrize(
    "arguments",
    [
        "{not valid JSON}",
        "[]",
        '"text"',
        "42",
        "true",
        "null",
    ],
)
def test_replay_normalizer_rejects_invalid_or_non_object_json(arguments: str) -> None:
    request_input = [
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup_case",
            "arguments": arguments,
        }
    ]

    with pytest.raises(ValueError, match="function-call arguments must be a JSON object"):
        normalize_nemotron_replay_input(request_input)
