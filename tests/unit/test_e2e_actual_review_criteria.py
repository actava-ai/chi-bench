"""Workflow criteria recording measures actual packet work, not private source IDs."""

from copy import deepcopy

import pytest

from chi_bench.verifier.stages.md_review import MdReviewVerifier
from chi_bench.verifier.stages.nurse_review import NurseReviewVerifier


@pytest.fixture(
    params=[(NurseReviewVerifier, "nurse", "nurse_review"), (MdReviewVerifier, "md", "md_review")]
)
def review_case(request):
    verifier, prefix, stage = request.param
    evaluation = {
        "criterion_id": "agent_policy_criterion",
        "criterion_text": "Submitted records document the policy condition.",
        "criteria_source": "Governing medical policy, section 2",
        "result": "met",
        "notes": "The submitted specialist note documents the condition.",
        "source_refs_used": ["submitted-specialist-note"],
    }
    state = {
        "e2e_protocol": "workflow_v2",
        "target_case_id": "C",
        "target_case": {"id": "C", "status": "under_review"},
        "submission_packets": [{"id": "PK", "case_id": "C"}],
        "intake_cases": [{"id": "I", "case_id": "C", "line_items": [{"line_number": 1}]}],
        f"payer_{prefix}_reviews": [
            {
                "id": "REVIEW",
                "case_id": "C",
                "intake_case_id": "I",
                "line_number": 1,
                "criteria_evaluations": [evaluation],
            }
        ],
    }
    expected = {
        "task_kind": "provider_to_payer_e2e",
        "verifier_contract": "contract_e2e_v1",
        "target_case_id": "C",
        "expected_clinical_criteria": {
            "criteria": [
                {
                    "stage": stage,
                    "line_number": 1,
                    "criterion_id": "private_source_id",
                    "expected_criterion_result": "met",
                }
            ]
        },
    }
    return verifier, prefix, state, expected


def test_workflow_accepts_actual_policy_criteria_with_agent_selected_ids(review_case):
    verifier, prefix, state, expected = review_case
    result = verifier(state, expected, []).verify()
    assert result.checks[f"{prefix}.criteria_recorded"] is True


def test_workflow_requires_criteria_without_source_catalog(review_case):
    verifier, prefix, state, expected = review_case
    expected.pop("expected_clinical_criteria")
    assert verifier(state, expected, []).verify().checks[f"{prefix}.criteria_recorded"] is True
    state[f"payer_{prefix}_reviews"][0]["criteria_evaluations"] = []
    assert verifier(state, expected, []).verify().checks[f"{prefix}.criteria_recorded"] is False


@pytest.mark.parametrize("field", ["criterion_id", "criterion_text", "criteria_source", "notes"])
def test_workflow_rejects_blank_required_criteria_content(review_case, field):
    verifier, prefix, state, expected = review_case
    state[f"payer_{prefix}_reviews"][0]["criteria_evaluations"][0][field] = "  "
    assert verifier(state, expected, []).verify().checks[f"{prefix}.criteria_recorded"] is False


@pytest.mark.parametrize("value", ["approved", "", None])
def test_workflow_rejects_invalid_criterion_result(review_case, value):
    verifier, prefix, state, expected = review_case
    state[f"payer_{prefix}_reviews"][0]["criteria_evaluations"][0]["result"] = value
    assert verifier(state, expected, []).verify().checks[f"{prefix}.criteria_recorded"] is False


@pytest.mark.parametrize("line", [0, -1, True, 1.5, "invalid", 2, None])
def test_workflow_rejects_invalid_or_unsubmitted_review_line(review_case, line):
    verifier, prefix, state, expected = review_case
    state[f"payer_{prefix}_reviews"][0]["line_number"] = line
    assert verifier(state, expected, []).verify().checks[f"{prefix}.criteria_recorded"] is False


def test_workflow_requires_each_actual_submitted_line_not_source_lines(review_case):
    verifier, prefix, state, expected = review_case
    expected["expected_clinical_criteria"]["criteria"][0]["line_number"] = 99
    state["intake_cases"][0]["line_items"].append({"line_number": 2})
    assert verifier(state, expected, []).verify().checks[f"{prefix}.criteria_recorded"] is False
    second = deepcopy(state[f"payer_{prefix}_reviews"][0])
    second.update(id="REVIEW-2", line_number=2)
    state[f"payer_{prefix}_reviews"].append(second)
    assert verifier(state, expected, []).verify().checks[f"{prefix}.criteria_recorded"] is True


def test_workflow_rejects_missing_actual_reviews(review_case):
    verifier, prefix, state, expected = review_case
    state[f"payer_{prefix}_reviews"] = []
    assert verifier(state, expected, []).verify().checks[f"{prefix}.criteria_recorded"] is False


def test_legacy_export_cannot_reactivate_source_criterion_comparison(review_case):
    verifier, prefix, state, expected = review_case
    state["e2e_protocol"] = "dual_viewpoint_v1"
    with pytest.raises(ValueError, match="workflow_v2"):
        verifier(state, expected, []).verify()
