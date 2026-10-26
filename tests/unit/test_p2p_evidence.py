from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chi_bench.core.clock import WorldClock
from chi_bench.core.context import ServiceContext
from chi_bench.core.enums import PayerMode, PeerToPeerStatus
from chi_bench.core.errors import InvalidCaseActionError
from chi_bench.core.models import (
    P2PSessionRecord,
    P2PSessionTurn,
    PayerPeerToPeerRequest,
    PriorAuthCase,
)
from chi_bench.core.scenario import ScenarioDefinition
from chi_bench.server.routers.common import create_common_router, register_exception_handlers
from chi_bench.verifier.stages.outcome import OutcomeVerifier
from chi_bench.experiment.agents.dual_pa_e2e_relay import (
    RelayTranscript,
    RelayTurn,
    workspace_transcript_payload,
)


@pytest.fixture
def ctx(tmp_path):
    context = ServiceContext.build(tmp_path)
    context._scenario = ScenarioDefinition.model_construct(task_kind="payer_end_to_end_review")
    context._clock = WorldClock(datetime(2026, 10, 23, 12))
    context.payer_mode = PayerMode.AGENT
    context.workspace_root.mkdir(parents=True)
    context.save_case(
        PriorAuthCase(
            id="CASE-TEST",
            external_case_id="PA-TEST",
            patient_id="PAT-TEST",
            service_request_id="SR-TEST",
            status="submitted",
            urgency="standard",
            requested_by="provider",
            assigned_to="payer",
            created_at=context.now,
            updated_at=context.now,
            decision_due_at=context.now,
        )
    )
    context.save_peer_to_peer_request(
        PayerPeerToPeerRequest(
            id="P2P-TEST",
            case_id="CASE-TEST",
            status="scheduled",
            scheduled_at="2026-10-23T11:00:00",
            created_at=context.now,
            updated_at=context.now,
        )
    )
    yield context
    context.close()


def complete(ctx):
    return ctx.p2p.record_p2p_outcome(
        "P2P-TEST",
        payer_contact_id="PAYER-MD",
        outcome="uphold_intended_adverse_decision",
        note="Recorded clinical conclusion.",
    )


def session(ctx, *, turns=True, other_case=False):
    request = ctx.get_peer_to_peer_request("P2P-TEST")
    request.status = PeerToPeerStatus.EVENT_OPEN
    ctx.save_peer_to_peer_request(request)
    messages = (
        [
            P2PSessionTurn(speaker=actor, message=text, created_at=ctx.now)
            for actor, text in [
                ("payer", "Please review the documented gap."),
                ("counterpart", "The requested documentation is unavailable."),
            ]
        ]
        if turns
        else []
    )
    ctx.save_p2p_session_record(
        P2PSessionRecord(
            id="SESSION-TEST",
            request_id="P2P-TEST",
            case_id="OTHER-CASE" if other_case else "CASE-TEST",
            benchmark_side="payer",
            agent_turns_used=1 if turns else 0,
            transcript=messages,
            created_at=ctx.now,
            updated_at=ctx.now,
        )
    )


@pytest.mark.parametrize("setup", ["no_session", "empty_session", "wrong_case_session"])
def test_unsupported_completion_is_rejected_without_mutation(ctx, setup):
    if setup != "no_session":
        session(ctx, turns=setup != "empty_session", other_case=setup == "wrong_case_session")
    before = ctx.get_peer_to_peer_request("P2P-TEST").model_dump(mode="json")
    with pytest.raises(InvalidCaseActionError, match="evidence"):
        complete(ctx)
    assert ctx.get_peer_to_peer_request("P2P-TEST").model_dump(mode="json") == before
    assert not ctx.store.list_resources("provider", "workspace_artifacts")


def test_real_simulated_conversation_can_be_manually_recorded(ctx):
    session(ctx)
    result = complete(ctx)
    assert result["p2p_request"]["status"] == "completed"
    assert result["p2p_request"]["outcome_source"] == "simulated_session"


def test_opening_and_failed_agent_turn_do_not_establish_completed_exchange(ctx):
    session(ctx)
    record = ctx.get_p2p_session_for_request("P2P-TEST")
    record.agent_turns_used = 0
    ctx.save_p2p_session_record(record)
    with pytest.raises(InvalidCaseActionError, match="evidence"):
        complete(ctx)


def external_payload():
    return {
        "id": "EXT-TEST",
        "case_id": "CASE-TEST",
        "request_id": "P2P-TEST",
        "source_ref": "external-clinical-record:synthetic-123",
        "occurred_at": "2026-10-23T11:00:00",
        "payer_contact_id": "PAYER-MD",
        "provider_contact_id": "PROVIDER-MD",
        "summary": "Imported record of an actual external consultation.",
        "outcome": "uphold_intended_adverse_decision",
    }


def client(ctx, monkeypatch):
    monkeypatch.setenv("CHI_BENCH_CONTROL_TOKEN", "synthetic-control-token")
    app = FastAPI()
    app.include_router(create_common_router(ctx))
    register_exception_handlers(app)
    return TestClient(app)


def test_external_manual_entry_keeps_existing_record_outcome_signature(ctx, monkeypatch):
    with client(ctx, monkeypatch) as api:
        response = api.post(
            "/_admin/p2p_external_evidence",
            headers={"Authorization": "Bearer synthetic-control-token"},
            json=external_payload(),
        )
    assert response.status_code == 200
    result = complete(ctx)
    assert result["p2p_request"]["status"] == "completed"
    assert result["p2p_request"]["outcome_source"] == "external"
    assert result["p2p_request"]["outcome_evidence_id"] == "EXT-TEST"
    assert evidence_check(ctx) is True


def test_agent_cannot_import_external_evidence(ctx, monkeypatch):
    with client(ctx, monkeypatch) as api:
        response = api.post("/_admin/p2p_external_evidence", json=external_payload())
    assert response.status_code == 401
    assert not ctx.store.list_resources("payer", "payer_p2p_external_evidence")


def test_agent_cannot_import_relay_transcript(ctx, monkeypatch):
    transcript = RelayTranscript(
        "P2P-TEST", "CASE-TEST", [RelayTurn("provider", "Synthetic turn.")]
    )
    with client(ctx, monkeypatch) as api:
        response = api.post(
            "/_admin/p2p_relay_transcript", json=workspace_transcript_payload(transcript)
        )
    assert response.status_code == 401
    assert not ctx.store.list_resources("payer", "payer_p2p_relay_evidence")


def test_external_manual_entry_rejects_wrong_outcome_and_reviewer(ctx, monkeypatch):
    with client(ctx, monkeypatch) as api:
        assert (
            api.post(
                "/_admin/p2p_external_evidence",
                headers={"Authorization": "Bearer synthetic-control-token"},
                json=external_payload(),
            ).status_code
            == 200
        )
    for reviewer, outcome in [
        ("OTHER-MD", "uphold_intended_adverse_decision"),
        ("PAYER-MD", "overturn_to_approval"),
    ]:
        with pytest.raises(InvalidCaseActionError, match="evidence"):
            ctx.p2p.record_p2p_outcome("P2P-TEST", payer_contact_id=reviewer, outcome=outcome)
    assert ctx.get_peer_to_peer_request("P2P-TEST").status == PeerToPeerStatus.SCHEDULED


def test_external_manual_entry_with_default_reviewer_uses_imported_identity(ctx, monkeypatch):
    with client(ctx, monkeypatch) as api:
        assert (
            api.post(
                "/_admin/p2p_external_evidence",
                headers={"Authorization": "Bearer synthetic-control-token"},
                json=external_payload(),
            ).status_code
            == 200
        )
    result = ctx.p2p.record_p2p_outcome("P2P-TEST", outcome="uphold_intended_adverse_decision")
    assert result["p2p_request"]["payer_contact_id"] == "PAYER-MD"


def test_multiple_external_records_select_the_explicit_meeting_reviewer(ctx, monkeypatch):
    first = external_payload()
    first.update(id="EXT-FIRST", payer_contact_id="FIRST-MD")
    with client(ctx, monkeypatch) as api:
        for payload in (first, external_payload()):
            assert (
                api.post(
                    "/_admin/p2p_external_evidence",
                    headers={"Authorization": "Bearer synthetic-control-token"},
                    json=payload,
                ).status_code
                == 200
            )
    result = complete(ctx)
    assert result["p2p_request"]["outcome_evidence_id"] == "EXT-TEST"
    assert evidence_check(ctx) is True


@pytest.mark.parametrize(
    "field,value",
    [("case_id", "OTHER-CASE"), ("occurred_at", "2027-01-01T00:00:00"), ("source_ref", "")],
)
def test_external_evidence_requires_bound_past_meeting(ctx, monkeypatch, field, value):
    payload = external_payload()
    payload[field] = value
    with client(ctx, monkeypatch) as api:
        response = api.post(
            "/_admin/p2p_external_evidence",
            headers={"Authorization": "Bearer synthetic-control-token"},
            json=payload,
        )
    assert response.status_code in {400, 409, 422}
    assert not ctx.store.list_resources("payer", "payer_p2p_external_evidence")


def test_submit_summary_cannot_bypass_missing_conversation(ctx):
    session(ctx, turns=False)
    with pytest.raises(InvalidCaseActionError, match="evidence"):
        ctx.p2p.submit_summary(
            "P2P-TEST", "Unsupported claimed discussion.", "uphold_intended_adverse_decision"
        )
    assert not ctx.get_p2p_session_for_request("P2P-TEST").finalized
    assert not ctx.store.list_resources("provider", "workspace_artifacts")


def test_scoring_rejects_legacy_completed_outcome_without_conversation():
    state = {
        "target_case": {"id": "CASE-TEST", "status": "submitted"},
        "payer_peer_to_peer_requests": [
            {
                "id": "P2P-TEST",
                "case_id": "CASE-TEST",
                "status": "completed",
                "outcome": "uphold_intended_adverse_decision",
            }
        ],
        "audit_logs": [
            {
                "case_id": "CASE-TEST",
                "action": "record_p2p_outcome",
                "details": {"request_id": "P2P-TEST"},
            }
        ],
    }
    checks = (
        OutcomeVerifier(
            state, {"target_case_id": "CASE-TEST", "expected_target_status": "submitted"}, []
        )
        .verify()
        .checks
    )
    assert checks["outcome.p2p_consultation_evidence"] is False


def evidence_state(ctx):
    return {
        "target_case": ctx.get_case("CASE-TEST").model_dump(mode="json"),
        "payer_peer_to_peer_requests": [
            row.model_dump(mode="json") for row in ctx.list_peer_to_peer_requests()
        ],
        "payer_p2p_session_records": [
            row.model_dump(mode="json") for row in ctx.list_p2p_session_records()
        ],
        "payer_p2p_external_evidence": ctx.store.list_resources(
            "payer", "payer_p2p_external_evidence"
        ),
        "payer_p2p_relay_evidence": ctx.store.list_resources("payer", "payer_p2p_relay_evidence"),
    }


def evidence_check(ctx):
    return (
        OutcomeVerifier(
            evidence_state(ctx),
            {"target_case_id": "CASE-TEST", "expected_target_status": "submitted"},
            [],
        )
        .verify()
        .checks["outcome.p2p_consultation_evidence"]
    )


def test_e2e_can_record_inside_payer_turn_and_final_scoring_requires_both_roles(ctx, monkeypatch):
    ctx._scenario.task_kind = "provider_to_payer_e2e"
    session(ctx, turns=False)
    transcript = RelayTranscript("P2P-TEST", "CASE-TEST")
    transcript.add(RelayTurn("provider", "The source documents do not resolve the gap."))
    with client(ctx, monkeypatch) as api:
        headers = {"Authorization": "Bearer synthetic-control-token"}
        response = api.post(
            "/_admin/p2p_relay_transcript",
            headers=headers,
            json=workspace_transcript_payload(transcript),
        )
        assert response.status_code == 200, response.text
        assert complete(ctx)["p2p_request"]["outcome_source"] == "e2e_relay"
        assert evidence_check(ctx) is False
        transcript.add(RelayTurn("payer", "I am recording the upheld outcome."))
        response = api.post(
            "/_admin/p2p_relay_transcript",
            headers=headers,
            json=workspace_transcript_payload(transcript),
        )
        assert response.status_code == 200, response.text
        assert evidence_check(ctx) is True
        transcript.turns[0] = RelayTurn("provider", "Replacement text is not allowed.")
        assert (
            api.post(
                "/_admin/p2p_relay_transcript",
                headers=headers,
                json=workspace_transcript_payload(transcript),
            ).status_code
            == 409
        )


def test_agent_written_relay_artifact_is_not_conversation_evidence(ctx):
    ctx._scenario.task_kind = "provider_to_payer_e2e"
    session(ctx, turns=False)
    transcript = RelayTranscript(
        "P2P-TEST",
        "CASE-TEST",
        [
            RelayTurn("provider", "Invented provider text."),
            RelayTurn("payer", "Invented payer text."),
        ],
    )
    ctx.workspace.write_workspace_artifact(
        **workspace_transcript_payload(transcript), owner="payer"
    )
    with pytest.raises(InvalidCaseActionError, match="evidence"):
        complete(ctx)


def test_context_lookup_does_not_generate_conversation(ctx):
    ctx._scenario.task_kind = "provider_to_payer_e2e"
    session(ctx, turns=False)
    result = ctx.p2p.get_context("P2P-TEST")
    assert result["transcript"] == []
    assert result["finalized"] is False
    record = ctx.get_p2p_session_for_request("P2P-TEST")
    assert record.agent_turns_used == 0
    assert not record.submitted_summary


def test_workspace_reindex_preserves_explicit_relay_request_binding(ctx):
    transcript = RelayTranscript(
        "P2P-TEST", "CASE-TEST", [RelayTurn("provider", "Source-grounded statement.")]
    )
    ctx.workspace.write_workspace_artifact(
        **workspace_transcript_payload(transcript), owner="payer"
    )
    artifact = next(
        a
        for a in ctx.list_workspace_artifacts(case_id="CASE-TEST", sync=False)
        if a.artifact_type == "peer_to_peer_transcript"
    )
    artifact = ctx.register_workspace_artifact(
        path=ctx.workspace_root / artifact.relative_path, case_id="CASE-TEST"
    )
    assert artifact.linked_resource_type == "peer_to_peer_request"
    assert artifact.linked_resource_id == "P2P-TEST"


@pytest.mark.asyncio
async def test_production_relay_persists_provider_before_payer_records(ctx, monkeypatch, tmp_path):
    from chi_bench.experiment.agents.dual_pa_e2e_harness import DualPaE2EHarness

    ctx._scenario.task_kind = "provider_to_payer_e2e"
    session(ctx, turns=False)
    harness = DualPaE2EHarness(logs_dir=tmp_path / "relay-logs")
    role_calls = []
    control_paths = []
    with client(ctx, monkeypatch) as api:

        class Environment:
            async def control_request(self, path, payload=None):
                control_paths.append(path)
                if path == "/export":
                    return evidence_state(ctx)
                response = api.post(
                    path,
                    headers={"Authorization": "Bearer synthetic-control-token"},
                    json=payload,
                )
                assert response.status_code == 200, response.text
                return response.json()

        async def role_turn(*, role, **kwargs):
            role_calls.append(role)
            if role == "provider":
                return RelayTurn(role, "The submitted sources leave the clinical gap unresolved.")
            # The normal payer records during its turn, before the host has
            # appended that payer's output to the trusted transcript.
            recorded = complete(ctx)
            assert recorded["p2p_request"]["outcome_source"] == "e2e_relay"
            assert evidence_check(ctx) is False
            return RelayTurn(
                role,
                "The adverse decision is upheld on the documented evidence.",
                final_position="uphold_intended_adverse_decision",
                ready_to_finalize=True,
            )

        monkeypatch.setattr(harness, "_run_relay_role_once", role_turn)
        exported = evidence_state(ctx)
        await harness._run_p2p_relay(
            instruction="Synthetic relay compatibility control.",
            environment=Environment(),
            http_base="http://testserver",
            provider_mcp_url="http://testserver:8020/mcp",
            payer_mcp_url="http://testserver:8100/mcp",
            exported=exported,
            request=exported["payer_peer_to_peer_requests"][0],
        )
    assert role_calls == ["provider", "payer"]
    assert control_paths.count("/_admin/p2p_relay_transcript") == 2
    assert evidence_check(ctx) is True
    assert ctx.get_p2p_session_for_request("P2P-TEST").agent_turns_used == 0


def test_real_session_submit_summary_remains_supported(ctx):
    session(ctx)
    result = ctx.p2p.submit_summary(
        "P2P-TEST", "Summary of the recorded exchange.", "uphold_intended_adverse_decision"
    )
    assert result["session"]["finalized"] is True
    assert ctx.get_peer_to_peer_request("P2P-TEST").status == PeerToPeerStatus.COMPLETED
    assert evidence_check(ctx) is True


def test_manual_outcome_then_summary_preserves_existing_real_conversation(ctx):
    session(ctx)
    complete(ctx)
    result = ctx.p2p.submit_summary(
        "P2P-TEST", "Summary of the actual conversation.", "uphold_intended_adverse_decision"
    )
    assert result["session"]["finalized"] is True
    assert ctx.get_peer_to_peer_request("P2P-TEST").outcome_source == "simulated_session"


def test_summary_reviewer_mismatch_is_rejected_before_any_mutation(ctx, monkeypatch):
    session(ctx, turns=False)
    request = ctx.get_peer_to_peer_request("P2P-TEST")
    request.payer_contact_id = "OTHER-MD"
    ctx.save_peer_to_peer_request(request)
    with client(ctx, monkeypatch) as api:
        assert (
            api.post(
                "/_admin/p2p_external_evidence",
                headers={"Authorization": "Bearer synthetic-control-token"},
                json=external_payload(),
            ).status_code
            == 200
        )
    with pytest.raises(InvalidCaseActionError, match="reviewer"):
        ctx.p2p.submit_summary(
            "P2P-TEST",
            "A manually entered external-meeting summary.",
            "uphold_intended_adverse_decision",
        )
    assert not ctx.get_p2p_session_for_request("P2P-TEST").finalized
    assert not ctx.store.list_resources("provider", "workspace_artifacts")


def test_external_entry_checks_existing_session_binding_before_recording(ctx, monkeypatch):
    session(ctx, other_case=True)
    with client(ctx, monkeypatch) as api:
        assert (
            api.post(
                "/_admin/p2p_external_evidence",
                headers={"Authorization": "Bearer synthetic-control-token"},
                json=external_payload(),
            ).status_code
            == 200
        )
    with pytest.raises(InvalidCaseActionError, match="another case"):
        complete(ctx)
    assert ctx.get_peer_to_peer_request("P2P-TEST").status == PeerToPeerStatus.EVENT_OPEN
    assert not ctx.store.list_resources("provider", "workspace_artifacts")
