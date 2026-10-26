"""Trusted authored CM answers; loading an answer executes no patient workflow."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

CM_REFERENCE_ROOT = Path(__file__).with_name("reference_answers") / "cm"
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


def cm_contract_hash(expectations: dict[str, Any]) -> str:
    """Ignore session mutation-scope metadata while binding authored clinical inputs."""
    payload = {key: expectations.get(key) for key in CONTRACT_FIELDS}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def build_cm_reference(expectations: dict[str, Any]) -> dict[str, Any]:
    """Return a source-bound static answer, never an observed or executed rollout."""
    task_id = str(expectations.get("scenario_id") or "")
    if not task_id or Path(task_id).name != task_id or task_id in {".", ".."}:
        raise ValueError("Static reference requires a leaf task ID")
    source = CM_REFERENCE_ROOT / f"{task_id}.json"
    if not source.is_file():
        raise FileNotFoundError(f"No authored CM reference answer for {task_id}")
    reference = json.loads(source.read_text(encoding="utf-8"))
    if (
        reference.get("schema_version") != "cm_static_reference_v1"
        or reference.get("task_id") != task_id
        or reference.get("reference_mode") != "static_answer"
        or reference.get("executed") is not False
        or reference.get("authorship", {}).get("observed") is not False
        or reference.get("authorship", {}).get("simulator_run") is not False
        or reference.get("authorship", {}).get("verifier_run") is not False
    ):
        raise ValueError("CM reference must identify an authored, unexecuted static answer")
    provenance = reference.get("source") or {}
    if provenance.get("contract_fields") != CONTRACT_FIELDS or provenance.get(
        "contract_sha256"
    ) != cm_contract_hash(expectations):
        raise ValueError("CM reference source contract does not match the task")
    required = {
        str(item["id"])
        for item in (expectations.get("cm_reference") or {}).get("assessment_required_items") or []
    }
    if set(reference.get("required_item_coverage") or []) != required:
        raise ValueError("CM reference does not cover the authored required assessment items")
    answer = reference.get("answer") or {}
    if any(
        not isinstance(answer.get(key), dict)
        for key in ("chart_review", "outreach", "assessment", "care_plan")
    ) or answer.get("final_status") != expectations.get("expected_final_status"):
        raise ValueError("CM reference answer sections or final status do not match the task")
    return {
        **deepcopy(reference),
        "case_id": expectations.get("target_case_id"),
        "target_status": answer["final_status"],
        "semantic_verification": "not_run",
    }
