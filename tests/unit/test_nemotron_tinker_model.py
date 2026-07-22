"""Nemotron-on-Tinker OpenAI Agents model adapter tests."""

from __future__ import annotations

import inspect
from typing import Any, cast

import pytest
from agents.items import ModelResponse
from agents.models.fake_id import FAKE_RESPONSES_ID
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputRefusal,
    ResponseOutputText,
    ResponseReasoningItem,
)
from openai.types.responses.response_reasoning_item import Summary

from chi_bench.experiment.agents.nemotron_tinker_model import (
    NemotronTinkerChatCompletionsModel,
)
from chi_bench.experiment.agents.nemotron_tool_protocol import (
    NEMOTRON_ULTRA_256K_MODEL,
    parse_nemotron_tool_calls,
)


def _model() -> NemotronTinkerChatCompletionsModel:
    return NemotronTinkerChatCompletionsModel(
        model=NEMOTRON_ULTRA_256K_MODEL,
        openai_client=cast(Any, object()),
    )


def _text(text: str) -> ResponseOutputText:
    return ResponseOutputText(annotations=[], text=text, type="output_text")


def _message(
    content: list[ResponseOutputText | ResponseOutputRefusal],
    *,
    message_id: str = "msg_1",
    provider_data: object | None = None,
) -> ResponseOutputMessage:
    kwargs: dict[str, Any] = {
        "id": message_id,
        "content": content,
        "role": "assistant",
        "status": "completed",
        "type": "message",
    }
    if provider_data is not None:
        kwargs["provider_data"] = provider_data
    return ResponseOutputMessage(**kwargs)


def _reasoning() -> ResponseReasoningItem:
    return ResponseReasoningItem(
        id="reasoning_1",
        summary=[Summary(text="opaque reasoning", type="summary_text")],
        type="reasoning",
        provider_data={"model": NEMOTRON_ULTRA_256K_MODEL},
    )


def _patch_parent_response(
    monkeypatch: pytest.MonkeyPatch,
    response: ModelResponse,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def fake_get_response(
        self,
        system_instructions,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing,
        previous_response_id=None,
        conversation_id=None,
        prompt=None,
    ):
        captured.update(
            {
                "self": self,
                "system_instructions": system_instructions,
                "input": input,
                "model_settings": model_settings,
                "tools": tools,
                "output_schema": output_schema,
                "handoffs": handoffs,
                "tracing": tracing,
                "previous_response_id": previous_response_id,
                "conversation_id": conversation_id,
                "prompt": prompt,
            }
        )
        return response

    monkeypatch.setattr(OpenAIChatCompletionsModel, "get_response", fake_get_response)
    return captured


async def _get_response(
    model: NemotronTinkerChatCompletionsModel,
    request_input: str | list[dict[str, object]],
) -> ModelResponse:
    return await model.get_response(
        "system instruction",
        cast(Any, request_input),
        cast(Any, object()),
        cast(Any, [object()]),
        cast(Any, object()),
        cast(Any, [object()]),
        cast(Any, object()),
        previous_response_id="previous_response_1",
        conversation_id="conversation_1",
        prompt=cast(Any, {"id": "prompt_1"}),
    )


def test_adapter_subclasses_pinned_model_and_overrides_only_nonstreaming_response() -> None:
    assert issubclass(NemotronTinkerChatCompletionsModel, OpenAIChatCompletionsModel)
    assert inspect.iscoroutinefunction(NemotronTinkerChatCompletionsModel.get_response)
    assert inspect.signature(NemotronTinkerChatCompletionsModel.get_response) == inspect.signature(
        OpenAIChatCompletionsModel.get_response
    )
    assert (
        NemotronTinkerChatCompletionsModel.stream_response
        is OpenAIChatCompletionsModel.stream_response
    )
    assert {
        name
        for name, value in NemotronTinkerChatCompletionsModel.__dict__.items()
        if callable(value) and not name.startswith("__")
    } == {"get_response"}


@pytest.mark.asyncio
async def test_adapter_normalizes_a_copy_before_parent_and_preserves_response_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reasoning = _reasoning()
    final_message = _message([_text("Workflow complete")])
    usage = Usage(requests=1, input_tokens=17, output_tokens=5, total_tokens=22)
    response = ModelResponse(
        output=[reasoning, final_message],
        usage=usage,
        response_id="response_1",
        request_id="request_1",
    )
    captured = _patch_parent_response(monkeypatch, response)
    request_input: list[dict[str, object]] = [
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup_case",
            "arguments": '{"case_id":"case-1","include_history":true}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "found",
        },
    ]

    result = await _get_response(_model(), request_input)

    assert captured["input"] == [
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup_case",
            "arguments": {"case_id": "case-1", "include_history": True},
        },
        request_input[1],
    ]
    assert captured["input"] is not request_input
    assert captured["input"][0] is not request_input[0]
    assert request_input[0]["arguments"] == ('{"case_id":"case-1","include_history":true}')
    assert captured["previous_response_id"] == "previous_response_1"
    assert captured["conversation_id"] == "conversation_1"
    assert captured["prompt"] == {"id": "prompt_1"}
    assert result is response
    assert result.usage is usage
    assert result.response_id == "response_1"
    assert result.request_id == "request_1"
    assert result.output[0] is reasoning
    assert result.output[1] is final_message


@pytest.mark.asyncio
async def test_adapter_replaces_xml_message_inline_with_ordered_standard_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xml = """\
<tool_call>
<function=update_case>
<parameter=metadata>
{"priority":3,"flags":[true,null]}
</parameter>
<parameter=note>
café
</parameter>
</function>
</tool_call>
<tool_call>
<function=refresh_status>
</function>
</tool_call>"""
    parsed = parse_nemotron_tool_calls(xml)
    assert parsed is not None
    before = _message([_text("Before")], message_id="msg_before")
    reasoning = _reasoning()
    provider_data = {
        "model": NEMOTRON_ULTRA_256K_MODEL,
        "response_id": "provider_response_1",
    }
    xml_message = _message(
        [_text(xml)],
        message_id=FAKE_RESPONSES_ID,
        provider_data=provider_data,
    )
    after = _message([_text("After")], message_id="msg_after")
    response = ModelResponse(
        output=[before, reasoning, xml_message, after],
        usage=Usage(),
        response_id=None,
    )
    output = response.output
    _patch_parent_response(monkeypatch, response)

    result = await _get_response(_model(), "Complete the workflow")

    assert result is response
    assert result.output is output
    assert len(result.output) == 5
    assert result.output[0] is before
    assert result.output[1] is reasoning
    assert result.output[4] is after
    first_call, second_call = result.output[2:4]
    assert isinstance(first_call, ResponseFunctionToolCall)
    assert isinstance(second_call, ResponseFunctionToolCall)
    assert first_call.id == second_call.id == FAKE_RESPONSES_ID
    assert [first_call.call_id, second_call.call_id] == [
        parsed[0].call_id,
        parsed[1].call_id,
    ]
    assert [first_call.name, second_call.name] == ["update_case", "refresh_status"]
    assert first_call.arguments == ('{"metadata":{"priority":3,"flags":[true,null]},"note":"café"}')
    assert second_call.arguments == "{}"
    assert first_call.provider_data == second_call.provider_data == provider_data
    assert first_call.provider_data is not xml_message.provider_data
    assert second_call.provider_data is not xml_message.provider_data
    assert first_call.provider_data is not second_call.provider_data


@pytest.mark.asyncio
async def test_adapter_leaves_normal_malformed_and_mixed_content_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    normal = _message([_text("Workflow complete")], message_id="msg_normal")
    malformed = _message(
        [_text("<tool_call><function=lookup_case></tool_call>")],
        message_id="msg_malformed",
    )
    two_texts = _message(
        [
            _text("<tool_call><function=lookup_case></function></tool_call>"),
            _text("extra"),
        ],
        message_id="msg_two_texts",
    )
    mixed = _message(
        [
            _text("<tool_call><function=lookup_case></function></tool_call>"),
            ResponseOutputRefusal(refusal="cannot comply", type="refusal"),
        ],
        message_id="msg_mixed",
    )
    response = ModelResponse(
        output=[normal, malformed, two_texts, mixed],
        usage=Usage(),
        response_id=None,
    )
    output = response.output
    original = tuple(output)
    _patch_parent_response(monkeypatch, response)

    result = await _get_response(_model(), "Complete the workflow")

    assert result is response
    assert result.output is output
    assert len(result.output) == len(original)
    assert all(actual is expected for actual, expected in zip(result.output, original, strict=True))


@pytest.mark.asyncio
async def test_adapter_skips_all_conversion_when_response_has_structured_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xml_message = _message([_text("<tool_call><function=lookup_case></function></tool_call>")])
    existing_call = ResponseFunctionToolCall(
        arguments='{"case_id":"case-1"}',
        call_id="call_existing",
        id=FAKE_RESPONSES_ID,
        name="lookup_case",
        type="function_call",
    )
    reasoning = _reasoning()
    response = ModelResponse(
        output=[reasoning, xml_message, existing_call],
        usage=Usage(),
        response_id=None,
    )
    output = response.output
    _patch_parent_response(monkeypatch, response)

    result = await _get_response(_model(), "Complete the workflow")

    assert result is response
    assert result.output is output
    assert result.output == output
    assert result.output[0] is reasoning
    assert result.output[1] is xml_message
    assert result.output[2] is existing_call
