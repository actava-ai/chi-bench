"""The data repair keeps the existing request form and restores its source facts."""

import json

from pypdf import PdfWriter

from scripts import repair_pa_t035


def test_repair_updates_existing_form_and_all_expectations(tmp_path, monkeypatch):
    task = tmp_path / "prior_auth_um/tasks" / repair_pa_t035.TASK_ID
    world = {
        "patients": [
            {
                "id": "PAT-TEST",
                "member_id": "MEMBER-TEST",
                "first_name": "Test",
                "last_name": "Patient",
                "dob": "1971-08-14",
                "sex": "female",
            }
        ],
        "coverages": [
            {
                "id": "COV-TEST",
                "patient_id": "PAT-TEST",
                "payer_name": "The Insurance Company",
                "plan_name": "HMO",
                "member_number": "MEMBER-TEST",
                "active": False,
                "termination_date": None,
            }
        ],
        "cases": [
            {
                "id": "CASE-TEST",
                "external_case_id": "PA-TEST",
                "patient_id": "PAT-TEST",
                "service_request_id": "SR-TEST",
                "status": "submitted",
                "urgency": "standard",
                "requested_by": "provider",
                "assigned_to": "payer",
                "created_at": "2026-03-15T09:00:00",
                "updated_at": "2026-03-15T09:00:00",
                "decision_due_at": "2026-03-29T09:00:00",
            }
        ],
        "service_requests": [
            {
                "id": "SR-TEST",
                "patient_id": "PAT-TEST",
                "ordering_practitioner_id": "DR-TEST",
                "service_type": "medical",
                "procedure_code": "95816",
                "description": "EEG",
                "priority": "standard",
                "diagnosis_codes": ["G40.009"],
                "site_of_service": "inpatient_hospital",
                "requested_date": "2026-03-18T09:00:00",
            }
        ],
        "practitioners": [],
        "documents": [{"id": "DOC-TEST", "content": "Original clinical note"}],
    }
    for domain in ("prior_auth_provider", "prior_auth_um"):
        path = tmp_path / domain / "shared/worlds" / repair_pa_t035.WORLD_NAME
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(world))
    expected = {
        "target_case_id": "CASE-TEST",
        "target_patient_id": "PAT-TEST",
        "task_actor": "payer",
        "task_kind": "payer_not_covered",
        "expected_target_status": "requirement_checked",
        "expected_letter_types": [],
        "stage_ground_truth": [
            {
                "model_name": "IntakeCase",
                "expected_fields": {
                    "decision_member_eligible": False,
                    "coverage_details": "Member coverage was terminated effective 2025-11-30.",
                },
            }
        ],
    }
    session = tmp_path / "marathon/prior_auth_um/fixtures/tasks" / repair_pa_t035.TASK_ID
    for directory in (task / "fixtures", task / "tests", task / "solution", session):
        directory.mkdir(parents=True)
        (directory / "expectations.json").write_text(json.dumps(expected))
    for directory in (task / "fixtures", session):
        (directory / "request").mkdir()
        (directory / "request/prior-auth-request-form.pdf").write_bytes(b"old form")
        (directory / "judge").mkdir()
        (directory / "judge/canonical_case_record.json").write_text(
            json.dumps(
                {
                    "canonical_determination": {"terminal_case_status": "requirement_checked"},
                    "canonical_review_trajectory": [
                        {"action": "requirement_checked_member_ineligible"}
                    ],
                    "documents_catalog": [],
                }
            )
        )
    calls = []

    def render(path, **kwargs):
        calls.append(kwargs)
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.write(path)

    monkeypatch.setattr(repair_pa_t035, "generate_request_form_pdf", render)

    repair_pa_t035.repair(tmp_path)

    assert len(calls) == 1
    assert calls[0]["coverage"].termination_date == "2025-11-30"
    for domain in ("prior_auth_provider", "prior_auth_um"):
        actual = json.loads(
            (tmp_path / domain / "shared/worlds" / repair_pa_t035.WORLD_NAME).read_text()
        )
        assert actual["coverages"][0]["termination_date"] == "2025-11-30"
        assert actual["documents"] == world["documents"]
        assert actual["cases"][0]["status"] == "submitted"
    for directory in (task / "fixtures", task / "tests", task / "solution", session):
        actual = json.loads((directory / "expectations.json").read_text())
        assert actual["expected_target_status"] == "denied"
        assert actual["expected_letter_types"] == ["denial"]
        assert actual["stage_ground_truth"] == expected["stage_ground_truth"]
    for directory in (task / "fixtures", session):
        assert list((directory / "request").iterdir()) == [
            directory / "request/prior-auth-request-form.pdf"
        ]
        record = json.loads((directory / "judge/canonical_case_record.json").read_text())
        assert record["canonical_determination"]["decision"] == "denied"
        assert record["canonical_determination"]["terminal_case_status"] == "denied"
        assert record["documents_catalog"] == []
