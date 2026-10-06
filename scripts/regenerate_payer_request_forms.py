"""Regenerate saved payer request forms with the shared form template.

Case facts come from the shared world. Only existing request PDFs and their
marathon copies are updated; world data and scoring expectations are unchanged.
"""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from chi_bench.core.models import Coverage, Patient, PriorAuthCase, ServiceRequest
from chi_bench.core.pdf import generate_request_form_pdf
from chi_bench.core.pdf.maintenance import stable_pdf_bytes


def regenerate(data_dir: Path) -> list[Path]:
    worlds = {}
    changed = []
    with TemporaryDirectory() as temporary:
        staged = []
        for manifest_path in sorted(
            (data_dir / "prior_auth_um/tasks").glob("*/fixtures/manifest.json")
        ):
            fixtures = manifest_path.parent
            form = fixtures / "request/prior-auth-request-form.pdf"
            if not form.is_file():
                continue
            manifest = json.loads(manifest_path.read_text())
            world_id = manifest["world_id"]
            if world_id not in worlds:
                world_path = data_dir / "prior_auth_um/shared/worlds" / f"{world_id}.json"
                worlds[world_id] = json.loads(world_path.read_text())
            world = worlds[world_id]
            case = PriorAuthCase.model_validate(
                next(c for c in world["cases"] if c["id"] == manifest["target_case_id"])
            )
            if case.patient_id != manifest["target_patient_id"]:
                raise ValueError(f"Case and patient do not match in {manifest_path}.")
            patient = Patient.model_validate(
                next(p for p in world["patients"] if p["id"] == case.patient_id)
            )
            coverage = Coverage.model_validate(
                next(c for c in world["coverages"] if c["patient_id"] == case.patient_id)
            )
            service_request = ServiceRequest.model_validate(
                next(s for s in world["service_requests"] if s["id"] == case.service_request_id)
            )
            provider_name = next(
                (
                    p["name"]
                    for p in world["practitioners"]
                    if p["id"] == service_request.ordering_practitioner_id
                ),
                service_request.ordering_practitioner_id,
            )
            output = Path(temporary) / f"{fixtures.parent.name}.pdf"
            generate_request_form_pdf(
                output,
                case=case,
                patient=patient,
                coverage=coverage,
                service_request=service_request,
                provider_name=provider_name,
            )
            staged.append((form, output))
            session_form = (
                data_dir
                / "marathon/prior_auth_um/fixtures/tasks"
                / fixtures.parent.name
                / "request/prior-auth-request-form.pdf"
            )
            if session_form.is_file():
                staged.append((session_form, output))

        # Finish rendering every form before replacing any original file.
        for destination, output in staged:
            content = stable_pdf_bytes(output)
            if destination.read_bytes() != content:
                destination.write_bytes(content)
                changed.append(destination)
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    changed = regenerate(parser.parse_args().data_dir)
    print(f"Updated {len(changed)} request PDFs.")
