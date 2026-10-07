import json
from datetime import UTC, datetime

import anthropic
import httpx
import pytest

from chi_bench.core.models import P2PSessionRecord, PayerPeerToPeerRequest
from chi_bench.services.p2p import P2PService


@pytest.mark.parametrize("benchmark_side", ["payer", "provider"])
@pytest.mark.parametrize(
    ("model_env", "expected_model"),
    [
        (None, "claude-sonnet-5"),
        ("", "claude-sonnet-5"),
        ("sonnet", "claude-sonnet-5"),
        ("claude-sonnet-5", "claude-sonnet-5"),
        ("haiku", "claude-haiku-4-5-20251001"),
    ],
)
def test_p2p_simulator_returns_text(monkeypatch, benchmark_side, model_env, expected_model):
    if model_env is None:
        monkeypatch.delenv("CHI_BENCH_P2P_SIMULATOR_MODEL", raising=False)
    else:
        monkeypatch.setenv("CHI_BENCH_P2P_SIMULATOR_MODEL", model_env)

    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if payload["model"] == "claude-sonnet-4-20250514":
            return httpx.Response(
                404,
                json={
                    "type": "error",
                    "error": {
                        "type": "not_found_error",
                        "message": "model: claude-sonnet-4-20250514",
                    },
                },
            )
        content = [{"type": "text", "text": "  Let's review the evidence.  "}]
        if payload["model"] == "claude-sonnet-5" and payload.get("thinking") != {
            "type": "disabled"
        }:
            content.insert(0, {"type": "thinking", "thinking": "Review", "signature": "test"})
        return httpx.Response(
            200,
            json={
                "id": "msg_p2p",
                "type": "message",
                "role": "assistant",
                "model": payload["model"],
                "content": content,
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 8},
            },
        )

    now = datetime(2026, 10, 7, tzinfo=UTC)
    p2p_request = PayerPeerToPeerRequest(
        id="p2p-1", case_id="case-1", created_at=now, updated_at=now
    )
    session = P2PSessionRecord(
        id="session-1",
        request_id=p2p_request.id,
        case_id=p2p_request.case_id,
        benchmark_side=benchmark_side,
        created_at=now,
        updated_at=now,
    )
    service = P2PService(ctx=None)
    monkeypatch.setattr(service, "_build_provider_context", lambda request: "You are the provider.")
    monkeypatch.setattr(service, "_build_payer_context", lambda request: "You are the payer.")
    with anthropic.Anthropic(
        api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(respond))
    ) as client:
        monkeypatch.setattr(anthropic, "Anthropic", lambda: client)
        reply, revealed_fact_id = service._generate_counterpart_reply(
            session=session,
            request=p2p_request,
            contract={},
            message="Can we review the evidence?",
            agent_turn_index=1,
        )

    assert reply == "Let's review the evidence."
    assert revealed_fact_id is None
    assert len(requests) == 1
    assert requests[0]["model"] == expected_model
    if expected_model == "claude-sonnet-5":
        assert requests[0]["thinking"] == {"type": "disabled"}
    else:
        assert "thinking" not in requests[0]
