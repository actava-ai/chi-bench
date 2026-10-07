"""Repair pa_t035 coverage evidence and its payer denial expectations.

Run after downloading data and before building the image. The termination
date comes from the task's original intake ground truth. No document is added.
"""

import argparse
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from chi_bench.core.models import Coverage, Patient, PriorAuthCase, ServiceRequest
from chi_bench.core.pdf import generate_request_form_pdf
from chi_bench.core.pdf.maintenance import stable_pdf_bytes

TASK_ID = "pa_t035_t035_o001_p01_intake_payer"
WORLD_NAME = "healthverse-pa-v2-payer.json"


def repair(data_dir: Path) -> list[Path]:
    task = data_dir / "prior_auth_um/tasks" / TASK_ID
    fixtures = task / "fixtures"
    session = data_dir / "marathon/prior_auth_um/fixtures/tasks" / TASK_ID
    expected = json.loads((fixtures / "expectations.json").read_text())
    intake_gt = next(
        entry["expected_fields"]
        for entry in expected["stage_ground_truth"]
        if entry["model_name"] == "IntakeCase"
    )
    if (
        expected["task_kind"] != "payer_not_covered"
        or intake_gt["decision_member_eligible"] is not False
    ):
        raise ValueError("Expected a payer task with failed member eligibility.")
    match = re.search(r"terminated effective (\d{4}-\d{2}-\d{2})", intake_gt["coverage_details"])
    if match is None:
        raise ValueError("The original ground truth has no coverage termination date.")
    termination_date = match.group(1)
    updates: dict[Path, bytes] = {}

    def update_json(path, payload):
        updates[path] = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode()

    for domain in ("prior_auth_provider", "prior_auth_um"):
        path = data_dir / domain / "shared/worlds" / WORLD_NAME
        world = json.loads(path.read_text())
        coverage = next(
            c for c in world["coverages"] if c["patient_id"] == expected["target_patient_id"]
        )
        if coverage["active"] or coverage.get("termination_date") not in (None, termination_date):
            raise ValueError(f"Unexpected coverage state in {path}.")
        coverage["termination_date"] = termination_date
        update_json(path, world)

    # Use the existing models and form template for both copies of the request.
    case = PriorAuthCase.model_validate(
        next(c for c in world["cases"] if c["id"] == expected["target_case_id"])
    )
    patient = Patient.model_validate(
        next(p for p in world["patients"] if p["id"] == case.patient_id)
    )
    coverage = Coverage.model_validate(coverage)
    service_request = ServiceRequest.model_validate(
        next(s for s in world["service_requests"] if s["id"] == case.service_request_id)
    )
    if termination_date >= service_request.requested_date.date().isoformat():
        raise ValueError("Coverage termination must precede the requested service date.")
    provider_name = next(
        (
            p["name"]
            for p in world["practitioners"]
            if p["id"] == service_request.ordering_practitioner_id
        ),
        service_request.ordering_practitioner_id,
    )

    for directory in (fixtures, task / "tests", task / "solution", session):
        path = directory / "expectations.json"
        if not path.exists():
            continue
        payload = json.loads(path.read_text())
        if payload["target_case_id"] != case.id:
            raise ValueError(f"Unexpected target case in {path}.")
        payload["expected_target_status"] = "denied"
        payload["expected_letter_types"] = ["denial"]
        update_json(path, payload)

    for directory in (fixtures, session):
        path = directory / "judge/canonical_case_record.json"
        if not path.exists():
            continue
        payload = json.loads(path.read_text())
        payload["canonical_determination"].update(decision="denied", terminal_case_status="denied")
        for entry in payload.get("canonical_review_trajectory", []):
            if entry.get("action") == "requirement_checked_member_ineligible":
                entry["action"] = "deny_for_terminated_coverage"
        update_json(path, payload)

    instruction = task / "instruction.md"
    if instruction.exists():
        text = instruction.read_text().replace(
            "You own this case end-to-end: walk the intake checklist, route it, then drive clinical review, MD decision, and any P2P through to final determination yourself.",
            "Complete the intake checklist. If a failed check requires rejection, finalize the denial and issue the required letter. Otherwise, route the case and complete clinical review, the physician decision, and any required peer-to-peer review.",
        )
        updates[instruction] = text.encode()

    form_paths = [
        directory / "request/prior-auth-request-form.pdf"
        for directory in (fixtures, session)
        if (directory / "request").is_dir()
    ]
    needs_pdf = False
    for path in form_paths:
        try:
            text = " ".join(page.extract_text() or "" for page in PdfReader(path).pages)
            needs_pdf |= not all(
                fact in text for fact in ("Coverage Status", "Inactive", termination_date)
            )
        except (FileNotFoundError, PdfReadError):
            needs_pdf = True
    if needs_pdf:
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "prior-auth-request-form.pdf"
            generate_request_form_pdf(
                output,
                case=case,
                patient=patient,
                coverage=coverage,
                service_request=service_request,
                provider_name=provider_name,
            )
            updates.update({path: stable_pdf_bytes(output) for path in form_paths})

    changed = []
    for path, content in updates.items():
        if not path.exists() or path.read_bytes() != content:
            path.write_bytes(content)
            changed.append(path)
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    for path in repair(parser.parse_args().data_dir):
        print(path)
