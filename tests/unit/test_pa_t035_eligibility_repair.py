"""The eligibility repair restores source evidence without changing the answers."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from pypdf import PdfReader

from chi_bench.verifier.stages.intake import IntakeVerifier
from chi_bench.verifier.stages.outcome import OutcomeVerifier

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/repair_pa_t035_eligibility.py"
TASK_ID = "pa_t035_t035_o001_p01_intake_payer"
WORLD_NAME = "healthverse-pa-v2-payer.json"
PDF_NAME = "03_member-enrollment-record.pdf"


def _dataset(root: Path) -> Path:
    world = {
        "world_id": "healthverse-pa-v2-payer",
        "now": "2026-03-15T09:00:00",
        "patients": [
            {
                "id": "PAT-352B96A7",
                "member_id": "TIC-9037182654",
                "first_name": "Margaret",
                "last_name": "Donnelly",
                "dob": "1971-08-14",
                "sex": "female",
            }
        ],
        "coverages": [
            {
                "id": "COV-54C62474",
                "patient_id": "PAT-352B96A7",
                "payer_name": "The Insurance Company",
                "plan_name": "The Insurance Company HMO",
                "member_number": "TIC-9037182654",
                "group_number": "TIC-7741926",
                "active": False,
                "network_status": "in_network",
                "effective_date": None,
                "termination_date": None,
            },
            {"id": "OTHER-COV", "patient_id": "OTHER-PAT", "active": True},
        ],
        "documents": [{"id": "OTHER-DOC", "content": "Unrelated evidence"}],
        "counts": {"documents": 1},
    }
    for domain in ("prior_auth_provider", "prior_auth_um"):
        path = root / domain / "shared/worlds" / WORLD_NAME
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(world, indent=2) + "\n")

    task = root / "prior_auth_um/tasks" / TASK_ID
    fixtures = task / "fixtures"
    session_fixtures = root / "marathon/prior_auth_um/fixtures/tasks" / TASK_ID
    manifest = {
        "world_id": "healthverse-pa-v2-payer",
        "task_id": TASK_ID,
        "target_case_id": "CASE-516EF322",
        "target_patient_id": "PAT-352B96A7",
    }
    for directory in (fixtures, session_fixtures):
        (directory / "request").mkdir(parents=True)
        (directory / "manifest.json").write_text(json.dumps(manifest))

    expectations = {
        "target_case_id": "CASE-516EF322",
        "verifier_contract": "contract_v3",
        "expected_target_status": "requirement_checked",
        "stage_ground_truth": [
            {"model_name": "IntakeCase", "expected_fields": {"decision_member_eligible": False}}
        ],
    }
    for directory in (fixtures, task / "solution", task / "tests", session_fixtures):
        directory.mkdir(exist_ok=True)
        (directory / "expectations.json").write_text(json.dumps(expectations))
    for directory in (fixtures, session_fixtures):
        (directory / "judge").mkdir()
        (directory / "judge/canonical_case_record.json").write_text(
            json.dumps(
                {
                    "canonical_determination": {
                        "terminal_case_status": "requirement_checked",
                        "rationale": "Member coverage terminated before service.",
                    },
                    "canonical_review_trajectory": [
                        {"action": "requirement_checked_member_ineligible"}
                    ],
                    "documents_catalog": [],
                }
            )
        )
    return task


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--data-dir", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def _bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_repair_restores_enrollment_evidence_without_changing_eligibility(tmp_path: Path) -> None:
    task = _dataset(tmp_path)
    before = _bytes(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr

    world = json.loads((tmp_path / "prior_auth_um/shared/worlds" / WORLD_NAME).read_text())
    assert world["coverages"][0]["active"] is False
    assert world["coverages"][0]["termination_date"] == "2025-11-30"
    assert world["coverages"][1] == {"id": "OTHER-COV", "patient_id": "OTHER-PAT", "active": True}
    assert world["documents"][0] == {"id": "OTHER-DOC", "content": "Unrelated evidence"}
    assert world["counts"]["documents"] == len(world["documents"])
    document = world["documents"][1]
    assert document["case_id"] == "CASE-516EF322"
    assert document["patient_id"] == "PAT-352B96A7"
    assert "TERMED" in document["content"]
    assert "2025-11-30" in document["content"]
    assert "2026-03-18" in document["content"]
    assert "decision_member_eligible" not in document["content"]
    assert "requirement_checked" not in document["content"]

    pdf = task / "fixtures/request" / PDF_NAME
    reader = PdfReader(pdf)
    assert len(reader.pages) == 1
    text = " ".join(page.extract_text() for page in reader.pages)
    for fact in ("TIC-9037182654", "TIC-7741926", "TERMED", "2025-11-30", "2026-03-18", "COBRA"):
        assert fact in text
    session_pdf = (
        tmp_path / "marathon/prior_auth_um/fixtures/tasks" / TASK_ID / "request" / PDF_NAME
    )
    assert session_pdf.read_bytes() == pdf.read_bytes()
    assert (tmp_path / "prior_auth_provider/shared/worlds" / WORLD_NAME).read_bytes() == (
        tmp_path / "prior_auth_um/shared/worlds" / WORLD_NAME
    ).read_bytes()
    for relative, content in before.items():
        if relative.endswith("expectations.json"):
            expected = json.loads(content)
            expected["expected_target_status"] = "submitted"
            assert json.loads((tmp_path / relative).read_text()) == expected
        elif relative.endswith("canonical_case_record.json"):
            canonical = json.loads((tmp_path / relative).read_text())
            assert canonical["canonical_determination"]["terminal_case_status"] == "submitted"
            assert canonical["canonical_determination"]["rationale"] == (
                "Member coverage terminated before service."
            )
            assert canonical["documents_catalog"][0]["title_hint"] == "Member Enrollment Record"
        elif not relative.endswith(WORLD_NAME):
            assert (tmp_path / relative).read_bytes() == content


def test_ground_truth_accepts_the_intake_stop_reachable_through_payer_tools(tmp_path: Path) -> None:
    task = _dataset(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    expectations = json.loads((task / "fixtures/expectations.json").read_text())
    # confirm_decisions completes IntakeCase without changing PriorAuthCase.
    exported = {"target_case": {"id": "CASE-516EF322", "status": "submitted"}}
    checks = OutcomeVerifier(exported, expectations, []).verify().checks
    assert checks["outcome.target_status"] is True
    assert checks["outcome.determination_exists"] == "not_applicable"
    exported["intake_cases"] = [{"case_id": "CASE-516EF322", "decision_member_eligible": None}]
    ground_truth = expectations["stage_ground_truth"]
    before = IntakeVerifier(exported, expectations, ground_truth).verify().checks
    assert before["intake.decision_member_eligible"] is False
    exported["intake_cases"][0]["decision_member_eligible"] = False
    after = IntakeVerifier(exported, expectations, ground_truth).verify().checks
    assert after["intake.decision_member_eligible"] is True


def test_repair_preserves_bytes_on_second_run(tmp_path: Path) -> None:
    _dataset(tmp_path)
    first = _run(tmp_path)
    assert first.returncode == 0, first.stderr
    before = _bytes(tmp_path)
    second = _run(tmp_path)
    assert second.returncode == 0, second.stderr
    assert _bytes(tmp_path) == before


def test_repair_validates_all_worlds_before_writing(tmp_path: Path) -> None:
    _dataset(tmp_path)
    path = tmp_path / "prior_auth_um/shared/worlds" / WORLD_NAME
    world = json.loads(path.read_text())
    world["coverages"][0]["active"] = True
    path.write_text(json.dumps(world))
    before = _bytes(tmp_path)
    result = _run(tmp_path)
    assert result.returncode != 0
    assert "inactive" in result.stderr.lower()
    assert _bytes(tmp_path) == before
