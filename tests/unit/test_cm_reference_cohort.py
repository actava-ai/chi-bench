"""Authored CM reference coverage and provenance; no patient or judge execution."""

import hashlib
from datetime import date, timedelta
from importlib.resources import files
import json
import os
from pathlib import Path
import re

import pytest

from chi_bench.verifier.reference_catalog import build_cm_reference


ASSETS = sorted(files("chi_bench").joinpath("verifier/reference_answers/cm").iterdir())
ASSETS = [p for p in ASSETS if p.name.endswith(".json")]
DATA = Path(os.environ.get("CHI_BENCH_TEST_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))


def _source_refs(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "source_refs":
                yield from item
            else:
                yield from _source_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _source_refs(item)


def _resolve_pointer(source, pointer):
    assert pointer.startswith("/"), pointer
    for part in pointer[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        source = source[int(part)] if isinstance(source, list) else source[part]
    return source


def test_all_authored_cm_answers_are_packaged_and_unobserved():
    assert len(ASSETS) == 25
    coverage = 0
    for asset in ASSETS:
        reference = json.loads(asset.read_text(encoding="utf-8"))
        assert reference["task_id"] == asset.name.removesuffix(".json")
        assert reference["reference_mode"] == "static_answer"
        assert reference["executed"] is False
        assert all(
            reference["authorship"][key] is False
            for key in ("observed", "simulator_run", "verifier_run")
        )
        assert reference["answer"]["outreach"]["ideal_dialogue"]
        assert set(reference["answer"]) >= {
            "chart_review",
            "outreach",
            "assessment",
            "care_plan",
            "final_status",
        }
        coverage += len(reference["required_item_coverage"])
    assert coverage == 93


def test_severe_mdd_reference_plans_urgent_bh_contact_before_monthly_maintenance():
    asset = next(p for p in ASSETS if p.name == "cm_mdd_hard_refuses_002.json")
    answer = json.loads(asset.read_text(encoding="utf-8"))["answer"]
    bh_interventions = [
        item
        for item in answer["care_plan"]["interventions"]
        if item["owner"] == "behavioral_health_provider"
    ]
    assert bh_interventions
    initial_contact = re.search(r"within (\d+) hours", bh_interventions[0]["timing"])
    assert initial_contact is not None, (
        "Severe PHQ-9 23 requires initial BH contact within 48 hours"
    )
    assert 0 < int(initial_contact.group(1)) <= 48
    assert "monthly" in bh_interventions[0]["timing"]
    assert "within 48 hours" in answer["assessment"]["behavioral_health"]["narrative"]


@pytest.mark.parametrize("asset", ASSETS, ids=lambda p: p.name.removesuffix(".json"))
def test_cm_reference_goals_have_absolute_calendar_deadlines(asset):
    reference = json.loads(asset.read_text(encoding="utf-8"))
    for goal in reference["answer"]["care_plan"]["goals"]:
        assert date.fromisoformat(goal["target_date"]).isoformat() == goal["target_date"]


def test_parkinson_deadlines_preserve_durations_from_explicit_authoring_assumption():
    asset = next(p for p in ASSETS if p.name == "cm_parkinson_hard_refuses_001.json")
    reference = json.loads(asset.read_text(encoding="utf-8"))
    assumption = reference["authorship"].get("plan_date_assumption")
    assert isinstance(assumption, dict)
    assert assumption["basis"] == "authored_same_day_as_source_referral"
    assert assumption["observed"] is False
    plan_date = date.fromisoformat(assumption["plan_finalization_date"])
    assert plan_date == date(2026, 4, 8)
    assert assumption["referral_date_source"]["value"] == plan_date.isoformat()
    offsets = {"G1": 90, "G2": 14, "G3": 60}
    assert assumption["goal_deadline_offsets_days"] == offsets
    for goal in reference["answer"]["care_plan"]["goals"]:
        assert date.fromisoformat(goal["target_date"]) == plan_date + timedelta(
            days=offsets[goal["id"]]
        )


@pytest.mark.skipif(
    not (DATA / "care_management/tasks").exists(), reason="CM source download absent"
)
@pytest.mark.parametrize("asset", ASSETS, ids=lambda p: p.name.removesuffix(".json"))
def test_cm_answer_matches_original_source_hash_contract_and_pointers(asset):
    original = (
        DATA
        / "care_management/tasks"
        / asset.name.removesuffix(".json")
        / "fixtures/expectations.json"
    )
    raw = original.read_bytes()
    expectations = json.loads(raw)
    reference = build_cm_reference(expectations)
    assert reference["source"]["expectations_sha256"] == hashlib.sha256(raw).hexdigest()
    required = {item["id"] for item in expectations["cm_reference"]["assessment_required_items"]}
    assert set(reference["required_item_coverage"]) == required
    assert reference["answer"]["final_status"] == expectations["expected_final_status"]
    refs = list(_source_refs(reference["answer"]))
    assert refs
    for pointer in refs:
        assert _resolve_pointer(expectations, pointer) is not None, pointer
    assumption = reference["authorship"].get("plan_date_assumption")
    if assumption:
        source = assumption["referral_date_source"]
        world = json.loads((DATA / source["file"]).read_text(encoding="utf-8"))
        referral = next(
            item for item in world[source["resource"]] if item["referral_id"] == source["id"]
        )
        assert referral[source["field"]] == source["value"]
