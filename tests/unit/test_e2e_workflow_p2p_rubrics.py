"""Offline controls for contingent P2P semantic scoring in workflow_v2."""

from copy import deepcopy

import pytest

from chi_bench.verifier.judge.pa_um_adapter import PaUmJudgeAdapter


@pytest.fixture
def p2p_expectations():
    # These keys use the published legacy rubric builder, including position
    # fields which do not have the expected_ prefix used by other gold values.
    return {
        "task_kind": "provider_to_payer_e2e",
        "verifier_contract": "contract_v3",
        "target_case_id": "C",
        "included_stages": ["p2p"],
        "expected_p2p_workflow": {
            "fixed_result": "uphold_denial",
            "primary_issue": "Source packet does not establish the prerequisite.",
            "required_resolution_points": ["Establish the missing prerequisite."],
            "forbidden_shortcuts": ["Do not invent a prerequisite result."],
            "payer_policy": {
                "position_summary": "Uphold denial on the source packet.",
                "required_anchors": ["The source packet lacks the prerequisite."],
                "forbidden_arguments": ["Approve without establishing the prerequisite."],
            },
            "provider_policy": {
                "position_summary": "Acknowledge the source packet is incomplete.",
                "required_anchors": ["Request the prerequisite evidence."],
                "forbidden_arguments": ["Claim the prerequisite is established."],
            },
        },
        "semantic_judge_rubric": {
            "p2p": [
                {
                    "rubric_id": "p2p:relay_integrity",
                    "prompt": "Are the role transcript and recorded outcome consistent?",
                    "hidden_expectation": {"evaluation_mode": "relay_integrity"},
                }
            ]
        },
    }


def _state():
    return {
        "e2e_protocol": "workflow_v2",
        "task_kind": "provider_to_payer_e2e",
        "target_case_id": "C",
        "target_case": {"id": "C", "status": "pended_action_required"},
    }


def _p2p_ids(judge_input):
    return {r["rubric_id"] for r in judge_input.rubrics if r.get("stage") == "p2p"}


def test_unentered_p2p_branch_waives_all_p2p_semantic_rubrics(p2p_expectations):
    original = deepcopy(p2p_expectations)
    adapter = PaUmJudgeAdapter(p2p_expectations, _state())
    judge_input = adapter.build()

    assert _p2p_ids(judge_input) == set()
    assert {
        "p2p:forbidden_shortcuts",
        "p2p:payer_policy_alignment",
        "p2p:provider_policy_alignment",
    }.issubset(adapter.not_applicable_rubrics)
    assert all("branch" in reason for reason in adapter.not_applicable_rubrics.values())
    assert "e2e.payer_actual_packet_policy" in {r["rubric_id"] for r in judge_input.rubrics}
    assert p2p_expectations == original


@pytest.mark.parametrize("branch_evidence", ["request", "md_decision", "audit"])
def test_actual_p2p_keeps_integrity_but_source_uphold_does_not_grade_actual_overturn(
    p2p_expectations, branch_evidence
):
    state = _state()
    state["target_case"]["status"] = "approved"
    if branch_evidence == "request":
        state["payer_peer_to_peer_requests"] = [
            {"id": "P2P", "case_id": "C", "status": "completed", "outcome": "overturn_denial"}
        ]
    elif branch_evidence == "md_decision":
        state["payer_md_case_decisions"] = [{"case_id": "C", "decision": "p2p_review"}]
    else:
        state["audit_logs"] = [{"case_id": "C", "action": "request_p2p"}]
    adapter = PaUmJudgeAdapter(p2p_expectations, state)
    judge_input = adapter.build()

    assert _p2p_ids(judge_input) == {"p2p:forbidden_shortcuts"}
    assert {
        "p2p:outcome_selection",
        "p2p:payer_policy_alignment",
        "p2p:provider_policy_alignment",
    }.issubset(adapter.not_applicable_rubrics)
    assert "e2e.payer_actual_packet_policy" in {r["rubric_id"] for r in judge_input.rubrics}
    assert p2p_expectations["expected_p2p_workflow"]["fixed_result"] == "uphold_denial"


def test_legacy_p2p_export_cannot_build_current_rubrics(p2p_expectations):
    state = _state()
    state["e2e_protocol"] = "dual_viewpoint_v1"
    adapter = PaUmJudgeAdapter(p2p_expectations, state)
    with pytest.raises(ValueError, match="workflow_v2"):
        adapter.build()


@pytest.mark.parametrize("has_branch", [False, True])
def test_custom_p2p_integrity_rubric_follows_actual_branch(p2p_expectations, has_branch):
    p2p_expectations.pop("expected_p2p_workflow")
    state = _state()
    if has_branch:
        state["payer_peer_to_peer_requests"] = [{"case_id": "C", "status": "requested"}]
    adapter = PaUmJudgeAdapter(p2p_expectations, state)
    judge_input = adapter.build()
    assert _p2p_ids(judge_input) == ({"p2p:relay_integrity"} if has_branch else set())
    assert ("p2p:relay_integrity" in adapter.not_applicable_rubrics) is (not has_branch)


def test_actual_packet_policy_alignment_without_fixed_source_stance_stays_applicable(
    p2p_expectations,
):
    p2p_expectations.pop("expected_p2p_workflow")
    p2p_expectations["semantic_judge_rubric"]["p2p"].append(
        {
            "rubric_id": "p2p:actual_packet_policy",
            "prompt": "Assess the P2P conclusion against the actual packet and policy.",
            "hidden_expectation": {
                "evaluation_mode": "policy_alignment",
                "evidence_scope": "actual_packet",
            },
        }
    )
    state = _state()
    state["payer_peer_to_peer_requests"] = [{"case_id": "C", "status": "requested"}]
    adapter = PaUmJudgeAdapter(p2p_expectations, state)
    judge_input = adapter.build()
    assert "p2p:actual_packet_policy" in _p2p_ids(judge_input)
    assert "p2p:actual_packet_policy" not in adapter.not_applicable_rubrics
