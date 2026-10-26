"""Trusted relay records recover links lost by workspace-file reindexing."""

from copy import deepcopy
import json

import pytest

from chi_bench.verifier.stages.e2e_consistency import E2EConsistencyVerifier
from tests.unit.test_p2p_evidence import ctx as ctx


@pytest.fixture(params=["recovered", "linked"])
def relay_state(request):
    turns = [
        {
            "actor": "provider",
            "message": "The gap remains.",
            "final_position": "uphold_intended_adverse_decision",
            "ready_to_finalize": False,
        },
        {
            "actor": "payer",
            "message": "The adverse decision stands.",
            "final_position": "uphold_intended_adverse_decision",
            "ready_to_finalize": True,
        },
    ]
    payload = {
        "request_id": "R",
        "case_id": "C",
        "turns": turns,
        "provider_final_position": "uphold_intended_adverse_decision",
        "payer_final_position": "uphold_intended_adverse_decision",
        "payer_ready_to_finalize": True,
    }
    return {
        "task_kind": "provider_to_payer_e2e",
        "e2e_protocol": "workflow_v2",
        "target_case_id": "C",
        "target_case": {"id": "C", "status": "denied"},
        "payer_peer_to_peer_requests": [
            {
                "id": "R",
                "case_id": "C",
                "status": "completed",
                "outcome": "uphold_intended_adverse_decision",
                "outcome_source": "e2e_relay",
                "outcome_evidence_id": "R",
            }
        ],
        "payer_p2p_relay_evidence": [deepcopy(payload)],
        "audit_logs": [
            {"case_id": "C", "action": "record_p2p_outcome", "created_at": "2026-10-24T10:00:00"}
        ],
        "workspace_artifacts": [
            {
                "case_id": "C",
                "scope": "shared",
                "artifact_type": "peer_to_peer_transcript",
                "linked_resource_type": (
                    "peer_to_peer_request" if request.param == "linked" else None
                ),
                "linked_resource_id": "R" if request.param == "linked" else None,
                "content": json.dumps(payload),
                "created_at": "2026-10-24T09:00:00",
            }
        ],
    }


def checks(state):
    return (
        E2EConsistencyVerifier(
            state, {"task_kind": "provider_to_payer_e2e", "target_case_id": "C"}, []
        )
        .verify()
        .checks
    )


def test_reindexed_transcript_uses_matching_trusted_relay_binding(relay_state):
    before = deepcopy(relay_state)
    result = checks(relay_state)
    for key in [
        "transcript_exists",
        "transcript_has_both_roles",
        "no_simulator_turns",
        "outcome_after_transcript",
        "payer_position_recorded",
        "outcome_matches_transcript",
    ]:
        assert result[f"e2e.p2p_{key}"] is True, key
    assert relay_state == before


@pytest.mark.parametrize(
    "damage",
    [
        "missing_anchor",
        "wrong_case",
        "wrong_request",
        "changed_words",
        "missing_role",
        "explicit_wrong_link",
    ],
)
def test_untrusted_or_conflicting_transcript_is_not_rebound(relay_state, damage):
    record = relay_state["payer_p2p_relay_evidence"][0]
    if damage == "missing_anchor":
        relay_state["payer_p2p_relay_evidence"] = []
    elif damage == "wrong_case":
        record["case_id"] = "OTHER"
    elif damage == "wrong_request":
        record["request_id"] = "OTHER"
    elif damage == "changed_words":
        record["turns"][0]["message"] = "Different trusted statement."
    elif damage == "missing_role":
        record["turns"] = record["turns"][:1]
        record["payer_final_position"] = None
        record["payer_ready_to_finalize"] = False
    else:
        relay_state["workspace_artifacts"][0].update(
            linked_resource_type="peer_to_peer_request", linked_resource_id="OTHER"
        )
    assert checks(relay_state)["e2e.p2p_transcript_exists"] is False


@pytest.mark.parametrize("role", ["provider", "payer"])
def test_writable_position_cannot_replace_private_relay_proof(relay_state, role):
    before = deepcopy(relay_state["payer_p2p_relay_evidence"])
    payload = json.loads(relay_state["workspace_artifacts"][0]["content"])
    payload[f"{role}_final_position"] = "overturn_to_approval"
    for turn in payload["turns"]:
        if turn["actor"] == role:
            turn["final_position"] = "overturn_to_approval"
    relay_state["workspace_artifacts"][0]["content"] = json.dumps(payload)
    if role == "payer":
        relay_state["payer_peer_to_peer_requests"][0]["outcome"] = "overturn_to_approval"
    result = checks(relay_state)
    assert result["e2e.p2p_transcript_exists"] is False
    assert result["e2e.p2p_outcome_matches_transcript"] is False
    assert relay_state["payer_p2p_relay_evidence"] == before


@pytest.mark.parametrize("field", ["payer_ready_to_finalize", "turn_ready_to_finalize"])
def test_writable_readiness_cannot_replace_private_relay_proof(relay_state, field):
    payload = json.loads(relay_state["workspace_artifacts"][0]["content"])
    payload["payer_ready_to_finalize"] = False
    if field == "turn_ready_to_finalize":
        payload["turns"][1]["ready_to_finalize"] = False
    relay_state["workspace_artifacts"][0]["content"] = json.dumps(payload)
    assert checks(relay_state)["e2e.p2p_transcript_exists"] is False


@pytest.mark.parametrize("side", ["private_receipt", "workspace_artifact"])
def test_actor_message_only_receipt_is_not_silently_upgraded(relay_state, side):
    if side == "private_receipt":
        payload = relay_state["payer_p2p_relay_evidence"][0]
    else:
        payload = json.loads(relay_state["workspace_artifacts"][0]["content"])
    for key in ("provider_final_position", "payer_final_position", "payer_ready_to_finalize"):
        payload.pop(key)
    for turn in payload["turns"]:
        turn.pop("final_position")
        turn.pop("ready_to_finalize")
    if side == "workspace_artifact":
        relay_state["workspace_artifacts"][0]["content"] = json.dumps(payload)
    else:
        with pytest.raises(ValueError, match="trusted relay receipt.*rerun required"):
            checks(relay_state)
        return
    result = checks(relay_state)
    assert result["e2e.p2p_transcript_exists"] is False
    assert result["e2e.p2p_outcome_matches_transcript"] is False


@pytest.mark.parametrize("side", ["private_receipt", "workspace_artifact"])
def test_position_summary_must_match_the_recorded_turns(relay_state, side):
    if side == "private_receipt":
        payload = relay_state["payer_p2p_relay_evidence"][0]
    else:
        payload = json.loads(relay_state["workspace_artifacts"][0]["content"])
    payload["payer_final_position"] = "overturn_to_approval"
    if side == "workspace_artifact":
        relay_state["workspace_artifacts"][0]["content"] = json.dumps(payload)
    else:
        with pytest.raises(ValueError, match="trusted relay receipt.*rerun required"):
            checks(relay_state)
        return
    assert checks(relay_state)["e2e.p2p_transcript_exists"] is False


@pytest.mark.parametrize("other_field", ["case_id", "request_id"])
def test_unrelated_legacy_receipt_does_not_refuse_current_request(relay_state, other_field):
    unrelated = {
        "case_id": "C",
        "request_id": "R",
        "turns": [{"actor": "payer", "message": "Old unrelated receipt."}],
    }
    unrelated[other_field] = "OTHER"
    relay_state["payer_p2p_relay_evidence"].append(unrelated)
    assert checks(relay_state)["e2e.p2p_outcome_matches_transcript"] is True


def test_missing_workspace_cannot_turn_incomplete_private_proof_into_agent_failure(relay_state):
    from chi_bench.verifier.task_runtime import verify_task

    receipt = relay_state["payer_p2p_relay_evidence"][0]
    receipt.pop("payer_final_position")
    relay_state["workspace_artifacts"] = []
    with pytest.raises(ValueError, match="trusted relay receipt.*rerun required"):
        verify_task(
            exported=relay_state,
            expectations={"task_kind": "provider_to_payer_e2e", "target_case_id": "C"},
        )


@pytest.mark.asyncio
async def test_live_host_relay_preserves_complete_private_scoring_receipt(ctx, tmp_path):
    from chi_bench.core.enums import PeerToPeerStatus
    from chi_bench.experiment.agents.dual_pa_e2e_harness import DualPaE2EHarness
    from chi_bench.experiment.agents.dual_pa_e2e_relay import (
        RelayTranscript,
        RelayTurn,
    )
    from chi_bench.verifier.stages.e2e_consistency import _p2p_transcript_artifact

    ctx._scenario.task_kind = "provider_to_payer_e2e"
    request = ctx.get_peer_to_peer_request("P2P-TEST")
    request.status = PeerToPeerStatus.EVENT_OPEN
    ctx.save_peer_to_peer_request(request)
    harness = DualPaE2EHarness(logs_dir=tmp_path / "host-logs")

    class TrustedControl:
        async def control_request(self, path, payload):
            assert path == "/_admin/p2p_relay_transcript"
            return ctx.p2p.record_relay_transcript(payload)

    transcript = RelayTranscript("P2P-TEST", "CASE-TEST")
    transcript.add(
        RelayTurn(
            "provider",
            "The available chart does not resolve the gap.",
            final_position="uphold_intended_adverse_decision",
            source_path="/logs/agent/provider_01.json",
        )
    )
    await harness._persist_relay_transcript(
        environment=TrustedControl(), http_base="http://synthetic", transcript=transcript
    )
    receipt = ctx.store.get_resource("payer", "payer_p2p_relay_evidence", "P2P-TEST")
    assert receipt == transcript.to_payload()
    assert receipt["payer_final_position"] is None
    recorded = ctx.p2p.record_p2p_outcome("P2P-TEST", outcome="uphold_intended_adverse_decision")
    assert recorded["p2p_request"]["outcome_source"] == "e2e_relay"

    transcript.add(
        RelayTurn(
            "payer",
            "I uphold the adverse outcome on the submitted evidence.",
            final_position="uphold_intended_adverse_decision",
            ready_to_finalize=True,
            source_path="/logs/agent/payer_01.json",
        )
    )
    await harness._persist_relay_transcript(
        environment=TrustedControl(), http_base="http://synthetic", transcript=transcript
    )
    receipt = ctx.store.get_resource("payer", "payer_p2p_relay_evidence", "P2P-TEST")
    assert receipt == transcript.to_payload()
    artifacts = [
        row.model_dump(mode="json")
        for row in ctx.list_workspace_artifacts(case_id="CASE-TEST", sync=False)
    ]
    exported = {
        "payer_peer_to_peer_requests": [recorded["p2p_request"]],
        "payer_p2p_relay_evidence": [receipt],
        "workspace_artifacts": artifacts,
    }
    matched = _p2p_transcript_artifact(exported, "CASE-TEST")
    assert matched is not None
    assert json.loads(matched["content"]) == receipt
