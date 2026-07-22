"""OpenAI Agents adapter for the exact Nemotron-on-Tinker route."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from agents.agent_output import AgentOutputSchemaBase
from agents.handoffs import Handoff
from agents.items import ModelResponse, TResponseInputItem
from agents.model_settings import ModelSettings
from agents.models.fake_id import FAKE_RESPONSES_ID
from agents.models.interface import ModelTracing
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from agents.tool import Tool
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
from openai.types.responses.response_prompt_param import ResponsePromptParam

from chi_bench.experiment.agents.nemotron_tool_protocol import (
    normalize_nemotron_replay_input,
    parse_nemotron_tool_calls,
)


class NemotronTinkerChatCompletionsModel(OpenAIChatCompletionsModel):
    """Adapt Nemotron XML tools for ``Runner.run``'s non-streaming path.

    ``stream_response`` remains inherited and intentionally unadapted while the
    chi-Bench runner uses the SDK's non-streaming ``Runner.run`` entry point.
    """

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt: ResponsePromptParam | None = None,
    ) -> ModelResponse:
        response = await super().get_response(
            system_instructions,
            normalize_nemotron_replay_input(input),
            model_settings,
            tools,
            output_schema,
            handoffs,
            tracing,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            prompt=prompt,
        )

        if any(isinstance(item, ResponseFunctionToolCall) for item in response.output):
            return response

        converted_output = []
        changed = False
        for item in response.output:
            if (
                not isinstance(item, ResponseOutputMessage)
                or len(item.content) != 1
                or not isinstance(item.content[0], ResponseOutputText)
            ):
                converted_output.append(item)
                continue

            calls = parse_nemotron_tool_calls(item.content[0].text)
            if calls is None:
                converted_output.append(item)
                continue

            changed = True
            provider_data = getattr(item, "provider_data", None)
            for call in calls:
                call_kwargs: dict[str, Any] = {
                    "arguments": json.dumps(
                        call.arguments,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "call_id": call.call_id,
                    "id": FAKE_RESPONSES_ID,
                    "name": call.name,
                    "type": "function_call",
                }
                if isinstance(provider_data, Mapping):
                    call_kwargs["provider_data"] = dict(provider_data)
                converted_output.append(ResponseFunctionToolCall(**call_kwargs))

        if changed:
            response.output[:] = converted_output
        return response
