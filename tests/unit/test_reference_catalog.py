"""Static authored answers are source-bound and never simulated observations."""

from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


CONTRACT_FIELDS = [
    "persona",
    "cm_reference",
    "stage_ground_truth",
    "expected_final_status",
    "expected_target_status",
    "program_type",
    "evidence_rubric_items",
    "target_case_id",
    "target_patient_id",
    "required_audit_actions",
    "expected_audit_actions",
]


@pytest.fixture
def static_reference(tmp_path, monkeypatch):
    from chi_bench.verifier import reference_catalog

    expected = {
        "scenario_id": "cm_static_test",
        "target_case_id": "CM-TEST",
        "expected_final_status": "closed",
        "persona": {"patient_profile": "Authored persona."},
        "cm_reference": {"assessment_required_items": [{"id": "required-one"}]},
    }
    digest = hashlib.sha256(
        json.dumps(
            {k: expected.get(k) for k in CONTRACT_FIELDS},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    reference = {
        "schema_version": "cm_static_reference_v1",
        "task_id": "cm_static_test",
        "reference_mode": "static_answer",
        "executed": False,
        "source": {"contract_sha256": digest, "contract_fields": CONTRACT_FIELDS},
        "answer": {
            "chart_review": {"summary": "Authored chart summary."},
            "outreach": {"ideal_dialogue": [{"speaker": "patient", "message": "Reference reply."}]},
            "assessment": {"clinical": {}, "medication": {}, "behavioral_health": {}, "sdoh": {}},
            "care_plan": {"problems": []},
            "final_status": "closed",
        },
        "authorship": {
            "kind": "authored_ideal_path",
            "observed": False,
            "simulator_run": False,
            "verifier_run": False,
        },
        "required_item_coverage": ["required-one"],
    }
    assets = tmp_path / "answers"
    assets.mkdir()
    (assets / "cm_static_test.json").write_text(json.dumps(reference))
    monkeypatch.setattr(reference_catalog, "CM_REFERENCE_ROOT", assets)
    return expected, reference


def test_static_reference_returns_authored_answer_without_execution(static_reference):
    from chi_bench.verifier.reference_catalog import build_cm_reference

    expected, source = static_reference
    before = deepcopy(expected)
    result = build_cm_reference(expected)
    assert result["executed"] is False
    assert result["reference_mode"] == "static_answer"
    assert result["answer"] == source["answer"]
    assert result["authorship"]["observed"] is False
    assert result["semantic_verification"] == "not_run"
    assert expected == before


def test_static_reference_rejects_stale_persona_or_gold(static_reference):
    from chi_bench.verifier.reference_catalog import build_cm_reference

    expected, _ = static_reference
    expected["persona"]["patient_profile"] = "Changed persona."
    with pytest.raises(ValueError, match="source contract"):
        build_cm_reference(expected)


def test_marathon_scope_changes_do_not_change_clinical_reference(static_reference):
    from chi_bench.verifier.reference_catalog import build_cm_reference

    expected, source = static_reference
    expected["forbidden_mutation_case_ids"] = []
    expected["allowed_mutation_case_ids"] = ["CM-ONE", "CM-TWO"]
    assert build_cm_reference(expected)["answer"] == source["answer"]


def test_reference_task_id_cannot_escape_catalog(static_reference):
    from chi_bench.verifier.reference_catalog import build_cm_reference

    expected, _ = static_reference
    expected["scenario_id"] = "../outside"
    with pytest.raises(ValueError, match="task ID"):
        build_cm_reference(expected)


def test_cm_dispatch_does_not_write_a_fake_conversation(static_reference, tmp_path):
    from chi_bench.verifier.reference_oracle import run_reference

    expected, _ = static_reference
    (tmp_path / "expectations.json").write_text(json.dumps(expected))
    ctx = SimpleNamespace(
        ensure_loaded=lambda: None, fixtures_dir=tmp_path, _cm_loaded=True, _expectations=None
    )
    assert run_reference(ctx)["executed"] is False
    assert not (tmp_path / "conversation.json").exists()


@pytest.mark.asyncio
async def test_static_host_reference_does_not_freeze_or_invoke_verifier():
    from chi_bench.verifier.reference_oracle import run_reference_control

    env = SimpleNamespace(
        control_request=AsyncMock(
            return_value={
                "executed": False,
                "reference_mode": "static_answer",
                "answer": {"final_status": "closed"},
                "authorship": {"observed": False},
            }
        ),
        begin_verification=AsyncMock(),
    )
    assert (await run_reference_control(env))["executed"] is False
    env.begin_verification.assert_not_awaited()
