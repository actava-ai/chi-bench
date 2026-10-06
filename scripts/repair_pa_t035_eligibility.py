"""Restore pa_t035's enrollment evidence in a downloaded source-layout dataset.

The facts below come from the original t035.o001.p01 synthesis, before export
removed the intake fields. See docs/errata/pa-t035-eligibility.md for provenance.
It also corrects the unreachable case-status expectation while preserving the
eligibility answer and other clinical ground truth. Evidence comes from the
frozen source facts below, never from the downloaded expectations.
"""

from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from pypdf import PdfReader

from chi_bench.core.models import DocumentReference
from chi_bench.core.pdf.engine import html_to_pdf_sync


TASK_ID = "pa_t035_t035_o001_p01_intake_payer"
WORLD_ID = "healthverse-pa-v2-payer"
CASE_ID = "CASE-516EF322"
PATIENT_ID = "PAT-352B96A7"
DOCUMENT_ID = "DOC-516EF322-ENROLLMENT"
PDF_NAME = "03_member-enrollment-record.pdf"
TERMINATION_DATE = "2025-11-30"


def _document(world: dict, coverage: dict) -> dict:
    patient = next(p for p in world["patients"] if p["id"] == PATIENT_ID)
    content = f"""Source: Facets enrollment record

- Patient: {patient["first_name"]} {patient["last_name"]}
- Date of birth: {patient["dob"]}
- Member number: {coverage["member_number"]}
- Group number: {coverage["group_number"]}
- Payer: {coverage["payer_name"]}
- Plan: {coverage["plan_name"]}
- Requested service dates: 2026-03-18 through 2026-03-21
- Enrollment status for requested service dates: TERMED
- Coverage termination date: {TERMINATION_DATE}
- Group policy status: Lapsed
- Group policy lapse reason: Non-payment of premiums
- Continuity-of-care arrangement: None on file
- COBRA election: None on file
"""
    return DocumentReference(
        id=DOCUMENT_ID,
        patient_id=PATIENT_ID,
        case_id=CASE_ID,
        kind="other",
        title="Member Enrollment Record",
        content=content,
        created_at=world["now"],
    ).model_dump(mode="json")


def _pdf_text(path: Path) -> str:
    return " ".join(" ".join(page.extract_text() for page in PdfReader(path).pages).split())


def repair(data_dir: Path) -> list[Path]:
    fixtures = data_dir / "prior_auth_um/tasks" / TASK_ID / "fixtures"
    fixture_dirs = [fixtures]
    session = data_dir / "marathon/prior_auth_um/fixtures/tasks" / TASK_ID
    if session.exists():
        fixture_dirs.append(session)
    for directory in fixture_dirs:
        manifest = json.loads((directory / "manifest.json").read_text())
        expected = {
            "world_id": WORLD_ID,
            "target_case_id": CASE_ID,
            "target_patient_id": PATIENT_ID,
        }
        if any(manifest.get(key) != value for key, value in expected.items()):
            raise ValueError(f"Unexpected task identity: {directory}")
        if not (directory / "request").is_dir():
            raise ValueError(f"Missing request packet: {directory}")

    # Validate both copies before writing: Docker bakes worlds from the provider
    # directory, while host tools can resolve the UM copy.
    updates: list[tuple[Path, dict]] = []
    document = None
    for domain in ("prior_auth_provider", "prior_auth_um"):
        path = data_dir / domain / "shared/worlds" / f"{WORLD_ID}.json"
        world = json.loads(path.read_text())
        coverage = next(c for c in world["coverages"] if c["patient_id"] == PATIENT_ID)
        if (
            world["world_id"] != WORLD_ID
            or coverage["member_number"] != "TIC-9037182654"
            or coverage["group_number"] != "TIC-7741926"
            or coverage["active"] is not False
            or coverage.get("termination_date") not in (None, TERMINATION_DATE)
        ):
            raise ValueError(f"Expected the original inactive member coverage: {path}")
        candidate = _document(world, coverage)
        if document is not None and candidate != document:
            raise ValueError("World copies disagree on the enrollment record")
        document = candidate
        existing = next((d for d in world["documents"] if d["id"] == DOCUMENT_ID), None)
        if existing is not None and existing != document:
            raise ValueError(f"Conflicting enrollment document: {path}")
        changed = coverage.get("termination_date") != TERMINATION_DATE or existing is None
        coverage["termination_date"] = TERMINATION_DATE
        if existing is None:
            world["documents"].append(document)
            world["counts"]["documents"] = len(world["documents"])
        if changed:
            updates.append((path, world))

    assert document is not None
    expectation_paths = [directory / "expectations.json" for directory in fixture_dirs]
    expectation_paths += [
        fixtures.parent / name / "expectations.json" for name in ("solution", "tests")
    ]
    for path in expectation_paths:
        expectations = json.loads(path.read_text())
        intake_fields = [
            entry["expected_fields"]
            for entry in expectations["stage_ground_truth"]
            if "decision_member_eligible" in entry.get("expected_fields", {})
        ]
        status = expectations["expected_target_status"]
        if (
            status not in ("requirement_checked", "submitted")
            or not intake_fields
            or any(fields["decision_member_eligible"] is not False for fields in intake_fields)
        ):
            raise ValueError(f"Unexpected eligibility ground truth: {path}")
        if status != "submitted":
            expectations["expected_target_status"] = "submitted"
            updates.append((path, expectations))

    for directory in fixture_dirs:
        path = directory / "judge/canonical_case_record.json"
        if not path.exists():
            continue
        canonical = json.loads(path.read_text())
        original = json.dumps(canonical)
        determination = canonical["canonical_determination"]
        if determination["terminal_case_status"] not in ("requirement_checked", "submitted"):
            raise ValueError(f"Unexpected canonical case status: {path}")
        determination["terminal_case_status"] = "submitted"
        for entry in canonical.get("canonical_review_trajectory", []):
            if entry.get("action") == "requirement_checked_member_ineligible":
                entry["action"] = "member_ineligible_intake_stop"
        catalog = canonical.setdefault("documents_catalog", [])
        if not any(item.get("title_hint") == document["title"] for item in catalog):
            catalog.append(
                {
                    "doc_kind": "other",
                    "title_hint": document["title"],
                    "topics": [],
                    "documented_facts": [
                        "member_number",
                        "group_number",
                        "requested_service_dates",
                        "enrollment_status",
                        "coverage_termination_date",
                        "group_policy_lapse_reason",
                        "continuity_of_care",
                        "cobra_election",
                    ],
                    "facts_not_in_chart": [],
                }
            )
        if json.dumps(canonical) != original:
            updates.append((path, canonical))

    pdf_paths = [directory / "request" / PDF_NAME for directory in fixture_dirs]
    missing_pdfs = [path for path in pdf_paths if not path.exists()]
    # Existing repaired PDFs must contain the same facts. Preserve their bytes
    # on reruns rather than regenerating timestamps and changing task hashes.
    rows = [
        line.removeprefix("- ").split(": ", 1)
        for line in document["content"].splitlines()
        if line.startswith("- ")
    ]
    for path in pdf_paths:
        if path.exists():
            text = _pdf_text(path)
            if any(value not in text for _label, value in rows):
                raise ValueError(f"Conflicting enrollment PDF: {path}")

    pdf_bytes = None
    if missing_pdfs:
        existing_pdf = next((path for path in pdf_paths if path.exists()), None)
        if existing_pdf:
            pdf_bytes = existing_pdf.read_bytes()
        else:
            html = """<!doctype html><html><head><meta charset="utf-8"><style>
body { font: 11pt Arial, sans-serif; color: #222; }
h1 { font-size: 20pt; margin-bottom: 6pt; }
table { border-collapse: collapse; width: 100%; margin-top: 18pt; }
th, td { border: 1px solid #bbb; padding: 8pt; text-align: left; }
th { background: #eee; } td:first-child { width: 52%; }
</style></head><body><h1>Member Enrollment Record</h1>"""
            html += "<p>Source: Facets enrollment record</p><table>"
            html += "<tr><th>Enrollment field</th><th>Recorded value</th></tr>"
            html += "".join(
                f"<tr><td>{escape(label)}</td><td>{escape(value)}</td></tr>"
                for label, value in rows
            )
            html += "</table></body></html>"
            with TemporaryDirectory(prefix="chi-pa-t035-") as temporary:
                pdf = Path(temporary) / PDF_NAME
                html_to_pdf_sync(html, pdf)
                pdf_bytes = pdf.read_bytes()

    changed_paths = []
    for path, world in updates:
        path.write_text(json.dumps(world, indent=2, ensure_ascii=False) + "\n")
        changed_paths.append(path)
    for path in missing_pdfs:
        assert pdf_bytes is not None
        path.write_bytes(pdf_bytes)
        changed_paths.append(path)
    return changed_paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    for path in repair(args.data_dir):
        print(f"Repaired {path}")


if __name__ == "__main__":
    main()
