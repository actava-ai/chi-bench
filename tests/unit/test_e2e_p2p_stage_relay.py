"""workflow_v2 P2P stage controls without model calls or original fixtures."""

from copy import deepcopy
import json

import pytest

from chi_bench.verifier.stages.p2p import P2PVerifier


@pytest.fixture
def expectations():
    return {
        "task_kind": "provider_to_payer_e2e",
        "verifier_contract": "contract_v3",
        "target_case_id": "C",
        "included_stages": ["p2p", "outcome"],
        "expected_p2p_workflow": {
            "benchmark_side": "payer",
            "fixed_result": "uphold_intended_adverse_decision",
            "coordination_contract": {
                "offered_slots": ["source-gold-slot"],
                "slot_selection_rule": "first_offered",
                "required_file_sequence": [
                    "coordination/01_offer.eml",
                    "coordination/02_slot_response.eml",
                    "coordination/03_confirmation.eml",
                    "event/00_opening.md",
                ],
            },
            "determination_contract": {
                "expected_decision": "denied",
                "expected_case_status": "denied",
            },
        },
    }


@pytest.fixture
def state():
    slots = ["2026-10-24T12:00:00", "2026-10-24T13:00:00"]
    artifacts = []
    for index, (suffix, details) in enumerate(
        [
            ("coordination/01_offer.eml", {"offered_slots": slots}),
            ("coordination/02_slot_response.eml", {"provider_selected_slot": slots[1]}),
            ("coordination/03_confirmation.eml", {"scheduled_at": slots[1]}),
            ("event/outcome.md", {"outcome": "overturn_to_approval"}),
            (
                "thread_state.json",
                {"request_id": "R", "request_status": "completed", "benchmark_side": "payer"},
            ),
        ]
    ):
        artifacts.append(
            {
                "id": f"A{index}",
                "case_id": "C",
                "channel": "peer_to_peer",
                "relative_path": f"C/shared/peer_to_peer/R/{suffix}",
                "linked_resource_type": "peer_to_peer_request",
                "linked_resource_id": "R",
                "details": {"p2p_request_id": "R", **details},
                "content": json.dumps(details),
                "created_at": f"2026-10-24T10:0{index}:00",
            }
        )
    return {
        "e2e_protocol": "workflow_v2",
        "target_case_id": "C",
        "target_case": {"id": "C", "status": "approved"},
        "submission_packets": [{"case_id": "C"}],
        "payer_peer_to_peer_requests": [
            {
                "id": "R",
                "case_id": "C",
                "status": "completed",
                "offered_slots": slots,
                "provider_selected_slot": slots[1],
                "scheduled_at": slots[1],
                "outcome": "overturn_to_approval",
                "outcome_source": "e2e_relay",
                "outcome_evidence_id": "R",
            }
        ],
        "payer_p2p_relay_evidence": [
            {
                "request_id": "R",
                "case_id": "C",
                "turns": [
                    {
                        "actor": "provider",
                        "message": "Here is the additional evidence.",
                        "final_position": "overturn_to_approval",
                        "ready_to_finalize": False,
                    },
                    {
                        "actor": "payer",
                        "message": "The documented gap is now resolved.",
                        "final_position": "overturn_to_approval",
                        "ready_to_finalize": True,
                    },
                ],
                "provider_final_position": "overturn_to_approval",
                "payer_final_position": "overturn_to_approval",
                "payer_ready_to_finalize": True,
            }
        ],
        "workspace_artifacts": artifacts,
        "audit_logs": [
            {
                "case_id": "C",
                "action": action,
                "details": {"request_id": "R"},
                "created_at": f"2026-10-24T10:0{index}:00",
            }
            for index, action in enumerate(
                ["offer_slots", "respond_to_peer_to_peer", "schedule_p2p", "record_p2p_outcome"]
            )
        ],
    }


def verify(state, expectations):
    return P2PVerifier(state, expectations, []).verify()


def test_real_relay_needs_no_simulator_opening_or_transcript(state, expectations):
    original = deepcopy(expectations)
    result = verify(state, expectations)
    assert result.passed, {k: v for k, v in result.checks.items() if v is False}
    assert result.checks["p2p.consultation_evidence"] is True
    assert result.checks["p2p.event_opened"] is True
    assert result.checks["p2p.turns_recorded"] is True
    assert result.checks["p2p.result_recorded"] is True
    assert result.checks["p2p.offer_slots_match_contract"] == "not_applicable"
    assert result.checks["p2p.selected_slot_matches_rule"] == "not_applicable"
    assert result.checks["p2p.determination_matches_contract"] == "not_applicable"
    assert result.details["source_comparison_observations"]
    assert expectations == original


@pytest.mark.parametrize(
    "defect",
    [
        "missing_payer",
        "blank_payer",
        "wrong_request",
        "wrong_case",
        "not_open",
        "missing_offer",
        "missing_response",
        "missing_confirmation",
        "wrong_artifact_request",
        "wrong_audit_request",
        "missing_audit",
        "missing_timestamp",
        "reversed_chronology",
        "wrong_selected_slot",
        "wrong_confirmation",
        "missing_outcome",
        "wrong_evidence_source",
    ],
)
def test_actual_relay_branch_rejects_missing_or_unbound_proof(state, expectations, defect):
    relay = state["payer_p2p_relay_evidence"][0]
    request = state["payer_peer_to_peer_requests"][0]
    if defect == "missing_payer":
        relay["turns"].pop()
    elif defect == "blank_payer":
        relay["turns"][1]["message"] = "  "
    elif defect == "wrong_request":
        relay["request_id"] = "OTHER"
    elif defect == "wrong_case":
        relay["case_id"] = "OTHER"
    elif defect == "not_open":
        request["status"] = "scheduled"
    elif defect.startswith("missing_") and defect.split("missing_")[1] in {
        "offer",
        "response",
        "confirmation",
    }:
        state["workspace_artifacts"].pop(
            {"missing_offer": 0, "missing_response": 1, "missing_confirmation": 2}[defect]
        )
    elif defect == "wrong_artifact_request":
        state["workspace_artifacts"][0]["details"]["p2p_request_id"] = "OTHER"
    elif defect == "wrong_audit_request":
        state["audit_logs"][0]["details"]["request_id"] = "OTHER"
    elif defect == "missing_audit":
        state["audit_logs"] = []
    elif defect == "missing_timestamp":
        state["audit_logs"][0].pop("created_at")
    elif defect == "reversed_chronology":
        state["audit_logs"][0]["created_at"] = "2026-10-24T11:00:00"
    elif defect == "wrong_selected_slot":
        request["provider_selected_slot"] = "not-offered"
    elif defect == "wrong_confirmation":
        state["workspace_artifacts"][2]["details"]["scheduled_at"] = "wrong-time"
    elif defect == "missing_outcome":
        request.pop("outcome")
    elif defect == "wrong_evidence_source":
        request["outcome_source"] = "simulated_session"
    result = verify(state, expectations)
    assert not result.passed
    assert any(value is False for value in result.checks.values())


def _external_meeting(state):
    request = state["payer_peer_to_peer_requests"][0]
    request.update(outcome_source="external", outcome_evidence_id="EXT", payer_contact_id="MD")
    request["offered_slots"] = []
    request["provider_selected_slot"] = None
    state["workspace_artifacts"] = []
    state["payer_p2p_relay_evidence"] = []
    state["payer_p2p_external_evidence"] = [
        {
            "id": "EXT",
            "case_id": "C",
            "request_id": "R",
            "source_ref": "meeting-record:1",
            "occurred_at": "2026-10-24T09:00:00",
            "payer_contact_id": "MD",
            "provider_contact_id": "PROVIDER-MD",
            "summary": "Actual meeting summary.",
            "outcome": "overturn_to_approval",
        }
    ]
    state["audit_logs"] = [
        {
            "case_id": "C",
            "action": action,
            "details": {"request_id": "R", "evidence_id": "EXT"},
            "created_at": f"2026-10-24T10:0{index}:00",
        }
        for index, action in enumerate(["import_external_p2p_evidence", "record_p2p_outcome"])
    ]
    return state


def test_trusted_external_meeting_does_not_require_internal_scheduling(state, expectations):
    _external_meeting(state)
    result = verify(state, expectations)
    assert result.passed, {k: v for k, v in result.checks.items() if v is False}
    assert result.checks["p2p.consultation_evidence"] is True


def test_legacy_export_is_rejected_instead_of_scored(state, expectations):
    state["e2e_protocol"] = "dual_viewpoint_v1"
    with pytest.raises(ValueError, match="workflow_v2"):
        verify(state, expectations)


def test_later_external_import_does_not_replace_the_recorded_relay_receipt(state, expectations):
    state["payer_p2p_external_evidence"] = [
        {
            "id": "LATER-EXT",
            "case_id": "C",
            "request_id": "R",
            "source_ref": "meeting-record:later",
            "occurred_at": "2026-10-24T09:00:00",
            "payer_contact_id": "MD",
            "provider_contact_id": "PROVIDER-MD",
            "summary": "Another trusted record of the same meeting.",
            "outcome": "overturn_to_approval",
        }
    ]
    result = verify(state, expectations)
    assert result.passed, {k: v for k, v in result.checks.items() if v is False}
    assert result.details["consultation_source"] == "e2e_relay"


def test_real_service_coordination_and_trusted_relay_pass_without_simulator_files(
    tmp_path, monkeypatch, state, expectations
):
    from datetime import datetime

    from chi_bench.core.clock import WorldClock
    from chi_bench.core.context import ServiceContext
    from chi_bench.core.enums import PayerMode
    from chi_bench.core.models import DirectoryContact, PayerPeerToPeerRequest, PriorAuthCase
    from chi_bench.core.scenario import ScenarioDefinition

    ctx = ServiceContext.build(tmp_path)
    try:
        ctx._scenario = ScenarioDefinition.model_construct(task_kind="provider_to_payer_e2e")
        ctx.e2e_protocol = "workflow_v2"
        ctx._clock = WorldClock(datetime(2026, 10, 24, 10))
        ctx.payer_mode = PayerMode.AGENT
        ctx.workspace_root.mkdir(parents=True, exist_ok=True)
        contact = DirectoryContact(
            id="SYSTEM",
            name="System reviewer",
            role="physician_reviewer",
            email="reviewer@example.test",
            phone="",
            organization_id="payer",
            escalation_role="",
        )
        ctx.store.save_resource(
            "provider", "directory_contacts", contact.id, contact.model_dump(mode="json")
        )
        ctx.save_case(
            PriorAuthCase(
                id="C",
                external_case_id="C",
                patient_id="P",
                service_request_id="S",
                status="submitted",
                urgency="standard",
                requested_by="provider",
                assigned_to="payer",
                created_at=ctx.now,
                updated_at=ctx.now,
                decision_due_at=ctx.now,
            )
        )
        ctx.save_peer_to_peer_request(
            PayerPeerToPeerRequest(
                id="R",
                case_id="C",
                status="requested",
                created_at=ctx.now,
                updated_at=ctx.now,
            )
        )

        def reject_simulator(*args, **kwargs):
            pytest.fail("workflow_v2 must not fabricate a counterpart opening or provider reply")

        monkeypatch.setattr(ctx.p2p, "_generate_counterpart_reply", reject_simulator)
        monkeypatch.setattr(ctx.p2p, "_simulate_provider_slot_response", reject_simulator)
        ctx.p2p.initialize_workflow_request("R")
        slots = ["2026-10-24T12:00:00", "2026-10-24T13:00:00"]
        ctx.p2p.offer_slots("R", slots=slots)
        ctx.auth.respond_to_peer_to_peer("C", "R", selected_slot=slots[1])
        ctx.p2p.schedule_p2p("R", scheduled_at=slots[1])
        ctx.p2p.record_relay_transcript(
            {
                "case_id": "C",
                "title": "Trusted relay",
                "filename": "relay.json",
                "artifact_type": "p2p_transcript",
                "scope": "shared",
                "channel": "peer_to_peer",
                "content": json.dumps(state["payer_p2p_relay_evidence"][0]),
            }
        )
        ctx.p2p.record_p2p_outcome(
            "R", outcome="overturn_to_approval", note="Real role conclusion."
        )
        exported = {
            **state,
            "payer_peer_to_peer_requests": [
                r.model_dump(mode="json") for r in ctx.list_peer_to_peer_requests()
            ],
            "payer_p2p_session_records": [
                r.model_dump(mode="json") for r in ctx.list_p2p_session_records()
            ],
            "payer_p2p_relay_evidence": ctx.store.list_resources(
                "payer", "payer_p2p_relay_evidence"
            ),
            "audit_logs": [r.model_dump(mode="json") for r in ctx.store.list_audit_logs()],
            "workspace_artifacts": [
                ctx.workspace_artifact_payload(r) for r in ctx.list_workspace_artifacts(sync=False)
            ],
        }
        assert not any(r["transcript"] for r in exported["payer_p2p_session_records"])
        assert not any(
            r["relative_path"].endswith("event/00_opening.md")
            for r in exported["workspace_artifacts"]
        )
        result = verify(exported, expectations)
        assert result.passed, {k: v for k, v in result.checks.items() if v is False}
    finally:
        ctx.close()


def test_external_meeting_passes_full_e2e_p2p_consistency(state, expectations):
    from chi_bench.verifier.stages import collect_stage_checks

    _external_meeting(state)
    checks, _ = collect_stage_checks(state, expectations)
    assert checks["p2p.consultation_evidence"] is True
    assert checks["e2e.p2p_external_evidence_valid"] is True
    assert not {
        key: value for key, value in checks.items() if key.startswith("e2e.p2p") and value is False
    }
    assert checks["e2e.p2p_transcript_exists"] == "not_applicable"
    assert checks["e2e.p2p_record_outcome_phase_legal"] == "not_applicable"


@pytest.mark.parametrize(
    "damage",
    ["request_id", "case_id", "payer_contact_id", "outcome", "missing_import", "late_import"],
)
def test_external_e2e_consistency_rejects_unbound_or_late_evidence(state, expectations, damage):
    from chi_bench.verifier.stages.e2e_consistency import E2EConsistencyVerifier

    _external_meeting(state)
    evidence = state["payer_p2p_external_evidence"][0]
    if damage in {"request_id", "case_id", "payer_contact_id"}:
        evidence[damage] = "OTHER"
    elif damage == "outcome":
        evidence["outcome"] = "uphold_intended_adverse_decision"
    elif damage == "missing_import":
        state["audit_logs"] = state["audit_logs"][1:]
    else:
        state["audit_logs"][0]["created_at"] = "2026-10-24T11:00:00"
    checks = E2EConsistencyVerifier(state, expectations, []).verify().checks
    assert checks["e2e.p2p_external_evidence_valid"] is False


def test_external_meeting_does_not_waive_a_second_missing_relay(state, expectations):
    from chi_bench.verifier.stages.e2e_consistency import E2EConsistencyVerifier

    _external_meeting(state)
    state["payer_peer_to_peer_requests"].append(
        {
            "id": "R2",
            "case_id": "C",
            "status": "completed",
            "outcome": "overturn_to_approval",
            "outcome_source": "e2e_relay",
            "outcome_evidence_id": "R2",
        }
    )
    checks = E2EConsistencyVerifier(state, expectations, []).verify().checks
    assert checks["e2e.p2p_external_evidence_valid"] is True
    assert checks["e2e.p2p_transcript_exists"] is False


def test_external_meeting_keeps_direct_simulator_guard(state, expectations):
    from chi_bench.verifier.stages.e2e_consistency import E2EConsistencyVerifier

    _external_meeting(state)
    state["audit_logs"].append(
        {"case_id": "C", "action": "p2p_session_turn", "created_at": "2026-10-24T10:00:00"}
    )
    checks = E2EConsistencyVerifier(state, expectations, []).verify().checks
    assert checks["e2e.p2p_no_direct_session_tools"] is False


@pytest.mark.parametrize("source", ["external", "e2e_relay"])
def test_payer_judge_receives_only_case_bound_consultation_content(state, expectations, source):
    from chi_bench.verifier.judge.pa_um_adapter import PaUmJudgeAdapter

    if source == "external":
        _external_meeting(state)
        state["payer_p2p_external_evidence"][0]["summary"] = "TRUSTED_CURRENT_CLINICAL_FACT"
    else:
        state["payer_p2p_relay_evidence"][0]["turns"][0]["message"] = (
            "TRUSTED_CURRENT_CLINICAL_FACT"
        )
    state.setdefault("payer_p2p_external_evidence", []).append(
        {
            "id": "OTHER",
            "case_id": "OTHER",
            "request_id": "OTHER",
            "summary": "UNRELATED_HIDDEN_CLINICAL_FACT",
        }
    )
    state["payer_p2p_relay_evidence"].append(
        {
            "case_id": "OTHER",
            "request_id": "OTHER",
            "turns": [{"actor": "provider", "message": "UNRELATED_HIDDEN_CLINICAL_FACT"}],
        }
    )
    # Even a valid imported record for this case is unrelated when it was not used for the recorded outcome.
    if source == "external":
        unused = deepcopy(state["payer_p2p_external_evidence"][0])
        unused.update(id="UNUSED", summary="UNUSED_LATER_CONSULTATION")
        state["payer_p2p_external_evidence"].append(unused)
    item = PaUmJudgeAdapter(expectations, state).build()
    p2p = json.dumps(item.agent_outputs["p2p"])
    payer = json.dumps(item.agent_outputs["payer_workflow"])
    assert "TRUSTED_CURRENT_CLINICAL_FACT" in p2p
    assert "TRUSTED_CURRENT_CLINICAL_FACT" in payer
    assert "UNRELATED_HIDDEN_CLINICAL_FACT" not in p2p + payer
    assert "UNUSED_LATER_CONSULTATION" not in p2p + payer


def test_external_and_relay_meetings_keep_separate_chronology(state, expectations):
    from chi_bench.experiment.agents.dual_pa_e2e_relay import RelayTranscript, RelayTurn
    from chi_bench.verifier.stages.e2e_consistency import E2EConsistencyVerifier

    _external_meeting(state)
    transcript = RelayTranscript("R2", "C")
    for actor in ("provider", "payer"):
        transcript.add(
            RelayTurn(
                actor,
                "The source evidence supports approval.",
                "overturn_to_approval",
                actor == "payer",
            )
        )
    payload = transcript.to_payload()
    state["payer_peer_to_peer_requests"].append(
        {
            "id": "R2",
            "case_id": "C",
            "status": "completed",
            "outcome": "overturn_to_approval",
            "outcome_source": "e2e_relay",
            "outcome_evidence_id": "R2",
        }
    )
    state["payer_p2p_relay_evidence"] = [payload]
    state["workspace_artifacts"] = [
        {
            "case_id": "C",
            "scope": "shared",
            "artifact_type": "peer_to_peer_transcript",
            "linked_resource_type": "peer_to_peer_request",
            "linked_resource_id": "R2",
            "content": json.dumps(payload),
            "created_at": "2026-10-24T12:00:00",
        }
    ]
    state["audit_logs"].append(
        {
            "case_id": "C",
            "action": "record_p2p_outcome",
            "details": {"request_id": "R2"},
            "created_at": "2026-10-24T12:01:00",
        }
    )
    state["stage_traces"] = [
        {
            "case_id": "C",
            "stage": "e2e_phase_marker",
            "logical_phase": "p2p",
            "role": "payer",
            "action": action,
            "created_at": time,
        }
        for action, time in (("enter", "2026-10-24T11:59:00"), ("leave", "2026-10-24T12:02:00"))
    ]
    checks = E2EConsistencyVerifier(state, expectations, []).verify().checks
    assert checks["e2e.p2p_external_evidence_valid"] is True
    assert checks["e2e.p2p_outcome_matches_transcript"] is True
    assert checks["e2e.p2p_record_outcome_phase_legal"] is True
    assert checks["e2e.p2p_outcome_after_transcript"] is True
