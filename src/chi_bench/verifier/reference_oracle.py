"""Trusted, deterministic reference workflows for contracts with executable gold inputs.

This module belongs to the simulator/verifier image. It must never be published as
an agent asset. Gold inputs choose service arguments; only ordinary workflow
services write state. A reference execution is not a semantic-judge verdict.
"""

from __future__ import annotations

import json
from inspect import signature
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, get_type_hints

from pydantic import TypeAdapter

from chi_bench.core.enums import (
    PayerRole,
    PeerToPeerOutcome,
    PlaceOfService,
    ServiceTypeCategory,
    UploadableDocumentKind,
)
from chi_bench.core.errors import UnsupportedLaneError

if TYPE_CHECKING:
    from chi_bench.core.context import ServiceContext


class UnsupportedReferenceContract(UnsupportedLaneError):
    """No grounded, executable reference is available for this contract."""


def _unsupported(reason: str) -> UnsupportedReferenceContract:
    return UnsupportedReferenceContract(f"Reference workflow unavailable: {reason}")


@dataclass(frozen=True)
class ProviderReference:
    order: dict[str, Any]
    documents: list[dict[str, str]]
    answers: dict[str, str]
    channel: str
    final_action: str
    source_summary: str


def _provider_plan(ctx: ServiceContext) -> ProviderReference:
    expected = ctx._expectations
    assert expected is not None
    final_action = expected.expected_provider_pre_submission.get("final_action") or "submit_pa"
    statuses = {
        "submit_pa": "submitted",
        "gather_more_evidence": "docs_needed",
        "do_not_submit": "closed",
    }
    if (
        statuses.get(final_action) != expected.expected_target_status
        or ctx.payer_mode.value != "agent"
    ):
        raise _unsupported("provider action and terminal-status contract do not match")
    path = ctx.fixtures_dir / "judge" / "canonical_case_record.json" if ctx.fixtures_dir else None
    if path is None or not path.is_file():
        raise _unsupported("provider reference needs the trusted canonical order inputs")
    facts = json.loads(path.read_text(encoding="utf-8")).get("clinical_facts") or {}
    request = expected.expected_service_request
    procedures = [code.strip() for code in str(facts.get("procedure_code") or "").split(",")]
    procedure = next(
        (code for code in procedures if code in request.get("acceptable_procedure_codes", [])), None
    )
    if procedure is None:
        raise _unsupported("canonical procedure does not match the task's service contract")
    service_types = request.get("acceptable_service_types") or []
    sites = request.get("acceptable_sites_of_service") or []
    if not service_types or not sites:
        raise _unsupported("provider reference requires accepted service and site values")
    practitioners = [
        p
        for p in ctx.store.list_resources("provider", "practitioners")
        if p.get("npi") and p["npi"] == facts.get("ordering_provider_npi")
    ]
    if len(practitioners) > 1:
        practitioners = [
            p for p in practitioners if p.get("name") == facts.get("ordering_provider_name")
        ]
    if len(practitioners) != 1:
        raise _unsupported("ordering practitioner cannot be resolved uniquely by NPI")
    patient_id = expected.target_patient_id
    if not patient_id:
        raise _unsupported("provider contract has no target patient")
    ctx.get_patient(patient_id)
    if any(c.patient_id == patient_id for c in ctx.list_cases()):
        raise _unsupported("provider reference requires a fresh target with no existing case")
    sources = [
        d
        for d in ctx.get_documents(patient_id=patient_id)
        if d.case_id is None and d.content.strip() and d.kind != "questionnaire_form"
    ]
    if not sources:
        raise _unsupported("provider reference has no chart source documents")
    required = expected.expected_provider_pre_submission.get("required_document_kinds") or []
    if final_action != "submit_pa":
        required = []
    documents = []
    for kind in required:
        UploadableDocumentKind(kind)
        if kind == "questionnaire_form":
            continue  # Forms service generates this from saved responses.
        matches = [d for d in sources if d.kind == kind]
        if not matches and kind != "letter_of_medical_necessity":
            raise _unsupported(f"provider reference has no source for required {kind}")
        selected = matches or sources
        content = "\n\n".join(f"Source: {d.title}\n{d.content}" for d in selected)
        if kind == "letter_of_medical_necessity":
            content = (
                f"Request: {facts.get('procedure_description') or procedure} ({procedure}).\n"
                "Clinical support transcribed from the available patient chart:\n\n" + content
            )
        documents.append(
            dict(kind=kind, title=f"Reference {kind.replace('_', ' ')}", content=content)
        )
    answers = dict(expected.expected_questionnaire_answers)
    for document in expected.documents_catalog if final_action == "submit_pa" else []:
        if document.get("doc_kind") != "questionnaire_form":
            continue
        for field in document.get("topics") or []:
            key, value = field.get("field_key"), field.get("field_expected_value")
            if key and value is not None:
                answers[key] = str(value)
            elif key and field.get("field_required", True):
                raise _unsupported("required questionnaire field has no reference answer")
    diagnoses = request.get("required_diagnosis_codes") or facts.get("diagnosis_codes") or []
    if not diagnoses or not facts.get("procedure_description"):
        raise _unsupported("provider order lacks diagnoses or procedure description")
    return ProviderReference(
        order=dict(
            patient_id=patient_id,
            ordering_practitioner_id=practitioners[0]["id"],
            service_type=ServiceTypeCategory(service_types[0]),
            procedure_code=procedure,
            description=facts["procedure_description"],
            priority="standard",
            diagnosis_codes=diagnoses,
            site_of_service=PlaceOfService(sites[0]),
        ),
        documents=documents,
        answers=answers,
        channel=expected.expected_submission_channel or "portal",
        final_action=final_action,
        source_summary="\n\n".join(f"{d.title}: {d.content}" for d in sources),
    )


def _execute_provider(ctx: ServiceContext, plan: ProviderReference) -> str:
    ctx.chart.get_patient_chart_by_patient(plan.order["patient_id"])
    case_id = ctx.cases.create_from_order(**plan.order)["case"]["id"]
    ctx.coverage.check_requirement(case_id, plan.channel)
    if plan.final_action != "submit_pa":
        ctx.auth.finalize_provider_determination(
            case_id,
            plan.final_action,
            override_reason=f"Chart reviewed for provider disposition {plan.final_action}:\n{plan.source_summary}",
        )
        return case_id
    ids = [
        ctx.docs.create_document(case_id=case_id, **document)["document"]["id"]
        for document in plan.documents
    ]
    if plan.answers:
        ctx.forms.save_form_response(case_id, plan.answers)
    bundle = ctx.docs.create_submission_bundle(case_id, ids)
    bundle_id = bundle["bundle_document"]["id"]
    ctx.auth.finalize_provider_determination(case_id, "submit_pa", bundle_document_id=bundle_id)
    ctx.auth.submit_authorization(case_id, plan.channel, bundle_document_id=bundle_id)
    return case_id


_STAGE_MODELS = {
    "IntakeCase": "intake",
    "TriageRecord": "triage",
    "NurseCaseRecommendation": "nurse_review",
    "MdCaseDecision": "md_review",
    "PayerPeerToPeerRequest": "p2p",
}
_INTAKE_FIELDS = {
    "decision_request_complete",
    "decision_member_eligible",
    "decision_service_covered",
    "provider_network_status",
    "diagnoses",
    "diagnosis_type",
    "requesting_provider",
    "line_items",
    # These describe source coverage and are populated by get_member_coverage.
    "coverage_details",
    "plan_type",
}


def _validate_service_inputs(method, *args, **kwargs) -> None:
    """Validate a fixed service call without executing its business effects."""
    try:
        arguments = signature(method).bind(*args, **kwargs).arguments
        types = get_type_hints(method)
        for key, value in arguments.items():
            if key in types:
                TypeAdapter(types[key]).validate_python(value)
    except (TypeError, ValueError) as exc:
        raise _unsupported(f"invalid inputs for {method.__name__}") from exc


def _p2p_slots(ctx: ServiceContext) -> list[str]:
    expected = ctx._expectations
    slots = (expected.expected_p2p_workflow.get("coordination_contract") or {}).get(
        "offered_slots"
    ) or []
    if not slots:
        for entry in expected.stage_ground_truth:
            if entry.get("model_name") == "PayerPeerToPeerRequest":
                slots = (entry.get("expected_fields") or {}).get("offered_slots") or slots
    _validate_service_inputs(ctx.p2p.offer_slots, "reference-preflight", slots=slots)
    return slots


def _payer_plan(ctx: ServiceContext) -> dict[str, dict[str, Any]]:
    expected = ctx._expectations
    assert expected is not None
    if not expected.target_case_id:
        raise _unsupported("payer contract has no target case")
    ctx.get_case(expected.target_case_id)
    p2p_contract = expected.expected_p2p_workflow
    needs_p2p = bool(
        p2p_contract or "p2p" in expected.included_stages or expected.task_kind == "payer_p2p"
    )
    if needs_p2p:
        slots = _p2p_slots(ctx)
        if (
            p2p_contract.get("benchmark_side") != "payer"
            or not slots
            or not p2p_contract.get("primary_issue")
        ):
            raise _unsupported(
                "P2P reference needs a configured payer-side counterpart conversation"
            )
        try:
            PeerToPeerOutcome(p2p_contract.get("fixed_result"))
            ctx.contact_for_payer_role(PayerRole.PHYSICIAN_REVIEWER)
        except (ValueError, KeyError) as exc:
            raise _unsupported(
                "P2P reference needs a supported result and physician reviewer"
            ) from exc
    plan = {}
    for entry in expected.stage_ground_truth:
        name = entry.get("model_name")
        if name not in _STAGE_MODELS or entry.get("stage") != _STAGE_MODELS[name]:
            raise _unsupported("stage ground truth has no executable service mapping")
        fields = dict(entry.get("expected_fields") or {})
        fields.pop("p2p_request_id", None)  # Gold IDs are not runtime resource IDs.
        if fields.get("decision") == "p2p_review" and not needs_p2p:
            raise _unsupported("P2P-dependent decisions require a configured conversation")
        if not fields:
            raise _unsupported("workflow stage has no structured reference inputs")
        # Node-level snapshots form one canonical stage payload. Preserve the
        # same chronological last-value semantics as the stage verifier.
        plan.setdefault(name, {}).update(fields)
    if needs_p2p:
        p2p_fields = plan.setdefault("PayerPeerToPeerRequest", {})
        if p2p_fields.get("outcome", p2p_contract["fixed_result"]) != p2p_contract["fixed_result"]:
            raise _unsupported("P2P reference outcome conflicts with its conversation contract")
        active_requests = [
            request
            for request in ctx.list_peer_to_peer_requests(expected.target_case_id)
            if request.status.value != "completed"
        ]
        creates_request = (plan.get("MdCaseDecision") or {}).get("decision") == "p2p_review"
        if len(active_requests) + int(creates_request) != 1:
            raise _unsupported(
                "P2P reference requires one existing or service-created target request"
            )
    for name, fields in plan.items():
        if name == "IntakeCase" and "decision_request_complete" not in fields:
            missing_fields, missing_documents = ctx.check_submission_completeness_for_case(
                expected.target_case_id, ctx.latest_submission_packet(expected.target_case_id)
            )
            fields["decision_request_complete"] = not missing_fields and not missing_documents
        if (
            name == "IntakeCase"
            and not {"decision_request_complete", "decision_member_eligible"} <= fields.keys()
        ):
            raise _unsupported(
                "intake reference lacks explicit completeness and eligibility decisions"
            )
        if name == "IntakeCase":
            if fields.keys() - _INTAKE_FIELDS:
                raise _unsupported("intake reference contains unsupported fields")
            if fields["decision_member_eligible"]:
                for field in ("decision_service_covered", "provider_network_status"):
                    if fields.get(field) is None:
                        raise _unsupported(f"eligible intake reference requires {field}")
            _validate_service_inputs(
                ctx.intake.confirm_intake_decisions,
                expected.target_case_id,
                request_complete=fields["decision_request_complete"],
                member_eligible=fields["decision_member_eligible"],
                service_covered=fields.get("decision_service_covered"),
                provider_network_status=fields.get("provider_network_status"),
            )
            if fields.get("requesting_provider"):
                _validate_service_inputs(
                    ctx.intake.save_requesting_provider,
                    expected.target_case_id,
                    fields["requesting_provider"],
                )
            if fields.get("diagnoses"):
                _validate_service_inputs(
                    ctx.intake.save_diagnoses,
                    expected.target_case_id,
                    {key: fields[key] for key in ("diagnoses", "diagnosis_type") if key in fields},
                )
            for line in fields.get("line_items") or []:
                _validate_service_inputs(ctx.intake.add_line_item, expected.target_case_id, line)
        methods = {
            "TriageRecord": ctx.triage.set_disposition,
            "NurseCaseRecommendation": ctx.review.submit_nurse_case_recommendation,
            "MdCaseDecision": ctx.review.submit_md_case_decision,
        }
        if name in methods:
            _validate_service_inputs(methods[name], expected.target_case_id, **fields)
    if not plan:
        raise _unsupported("payer contract has no structured stage reference inputs")
    if expected.expected_target_status not in {
        "approved",
        "denied",
        "partially_approved",
        "pended_action_required",
    }:
        raise _unsupported("payer terminal outcome has no reference mapping")
    if set(expected.expected_letter_types) - {"approval", "denial", "partial_approval", "pend"}:
        raise _unsupported("letter type has no reference service mapping")
    for name, stage in (
        ("NurseCaseRecommendation", "nurse_review"),
        ("MdCaseDecision", "md_review"),
    ):
        if name in plan:
            try:
                _criteria_inputs(ctx, expected.target_case_id, stage)
            except (KeyError, TypeError, ValueError) as exc:
                raise _unsupported(f"invalid clinical criterion reference for {stage}") from exc
    return plan


def _execute_intake(ctx: ServiceContext, case_id: str, fields: dict[str, Any]) -> None:
    intake = ctx.intake.create_intake_case(case_id)
    ctx.intake.get_member_coverage(case_id)
    ctx.intake.verify_provider(case_id)
    diagnoses = fields.get("diagnoses")
    if not diagnoses:
        case = ctx.get_case(case_id)
        order = ctx.load_service_request(case.service_request_id)
        diagnoses = [
            dict(name=code, code=code, code_set="ICD10", is_primary=index == 0)
            for index, code in enumerate(order.diagnosis_codes)
        ]
    if diagnoses:
        ctx.intake.save_diagnoses(
            case_id, {"diagnoses": diagnoses, "diagnosis_type": fields.get("diagnosis_type")}
        )
    if fields.get("requesting_provider"):
        ctx.intake.save_requesting_provider(case_id, fields["requesting_provider"])
    existing = {line["line_number"] for line in intake.get("line_items") or []}
    for line in fields.get("line_items") or []:
        if line["line_number"] in existing:
            ctx.intake.update_line_item(case_id, line["line_number"], line)
        else:
            ctx.intake.add_line_item(case_id, line)
    ctx.intake.confirm_intake_decisions(
        case_id,
        request_complete=fields["decision_request_complete"],
        member_eligible=fields["decision_member_eligible"],
        service_covered=fields.get("decision_service_covered"),
        provider_network_status=fields.get("provider_network_status"),
    )


def _criteria_inputs(ctx: ServiceContext, case_id: str, stage: str) -> dict[int, list]:
    grouped = defaultdict(list)
    for criterion in ctx._expectations.expected_clinical_criteria.get("criteria") or []:
        if criterion.get("stage") != stage:
            continue
        grouped[int(criterion.get("line_number") or 1)].append(
            dict(
                criterion_id=criterion["criterion_id"],
                criterion_text=criterion["criterion_text"],
                criteria_source=criterion.get("criteria_source", ""),
                criteria_version=criterion.get("criteria_version", ""),
                result=criterion["expected_criterion_result"],
                item_observations=[
                    dict(
                        item_id=item["item_id"],
                        observed_value=item.get("expected_observation"),
                        observed_unit=item.get("expected_unit") or "",
                        item_result=item["expected_item_result"],
                        source_refs_used=[
                            f"{ref.get('source_type', 'source')}:{ref['source_id']}"
                            if isinstance(ref, dict)
                            else str(ref)
                            for ref in item.get("source_refs") or []
                        ],
                        notes=item.get("notes") or "",
                    )
                    for item in criterion.get("evidence_items") or []
                ],
            )
        )
    save = (
        ctx.review.save_criteria_evaluation
        if stage == "nurse_review"
        else ctx.review.save_md_review
    )
    for line_number, evaluations in grouped.items():
        _validate_service_inputs(save, case_id, line_number, evaluations=evaluations)
    return grouped


def _save_criteria(ctx: ServiceContext, case_id: str, stage: str) -> None:
    save = (
        ctx.review.save_criteria_evaluation
        if stage == "nurse_review"
        else ctx.review.save_md_review
    )
    for line_number, evaluations in _criteria_inputs(ctx, case_id, stage).items():
        save(case_id, line_number, evaluations=evaluations)


def _execute_payer(ctx: ServiceContext, plan: dict[str, dict[str, Any]]) -> str:
    expected = ctx._expectations
    case_id = expected.target_case_id
    if "IntakeCase" in plan:
        _execute_intake(ctx, case_id, plan["IntakeCase"])
    if "TriageRecord" in plan:
        ctx.triage.set_disposition(case_id, **plan["TriageRecord"])
        ctx.route_case_internal(case_id)
    elif "triage" in expected.included_stages:
        urgency = "urgent" if ctx.get_case(case_id).urgency.value == "expedited" else "routine"
        sla = ctx.triage.calculate_sla_deadline(case_id, urgency)
        ctx.triage.set_disposition(
            case_id,
            urgency_level=urgency,
            sla_deadline=sla["sla_deadline"],
            sla_hours=sla["sla_hours"],
            sla_rule_source=sla["rule_source"],
            disposition="nurse_review" if "NurseCaseRecommendation" in plan else "md_review",
        )
        ctx.route_case_internal(case_id)
    if "NurseCaseRecommendation" in plan:
        _save_criteria(ctx, case_id, "nurse_review")
        ctx.review.submit_nurse_case_recommendation(case_id, **plan["NurseCaseRecommendation"])
    if "MdCaseDecision" in plan:
        _save_criteria(ctx, case_id, "md_review")
        ctx.review.submit_md_case_decision(case_id, **plan["MdCaseDecision"])
    if "PayerPeerToPeerRequest" in plan:
        _execute_p2p(ctx, case_id)
    if (
        expected.expected_target_status != "pended_action_required"
        and ctx.get_case(case_id).status.value != expected.expected_target_status
    ):
        ctx.determination.finalize_determination(case_id, expected.expected_target_status)
    for letter_type in expected.expected_letter_types:
        getattr(ctx.letters, f"generate_{letter_type}_letter")(case_id)
    return case_id


def _execute_p2p(ctx: ServiceContext, case_id: str) -> None:
    """Exercise normal scheduling and model-backed dialog; never insert turns."""
    contract = ctx._expectations.expected_p2p_workflow
    requests = [
        request
        for request in ctx.list_peer_to_peer_requests(case_id)
        if request.status.value != "completed"
    ]
    if len(requests) != 1:
        raise _unsupported("P2P reference requires exactly one active target request")
    request = requests[0]
    reviewer = (
        request.payer_contact_id or ctx.contact_for_payer_role(PayerRole.PHYSICIAN_REVIEWER).id
    )
    ctx.p2p.initialize_workflow_request(request.id)
    slots = _p2p_slots(ctx)
    ctx.p2p.offer_slots(request.id, payer_contact_id=reviewer, slots=slots)
    ctx.p2p.schedule_p2p(request.id, payer_contact_id=reviewer)
    source = "\n\n".join(
        document.content
        for document in ctx.get_documents(case_id=case_id)
        if document.kind != "submission_bundle"
    )
    points = "; ".join(contract.get("required_resolution_points") or [])
    messages = [
        f"Please explain the patient-specific evidence for the unresolved issue {contract['primary_issue']}. Address these points: {points}.",
        f"Compare your explanation with the submitted clinical source material and identify which policy criteria are met or still unsupported:\n{source}",
        f"My proposed adjudicated result is {contract['fixed_result']}. Please respond to the remaining issue and identify any additional patient-specific evidence that changes this conclusion.",
    ]
    session = ctx.get_p2p_session_for_request(request.id)
    for message in messages[: min(3, session.turn_limit - session.agent_turns_used)]:
        ctx.p2p.send_turn(request.id, message)
    context = ctx.p2p.get_context(request.id)
    summary = "\n\n".join(f"{turn['speaker']}: {turn['message']}" for turn in context["transcript"])
    ctx.p2p.submit_summary(request.id, summary, contract["fixed_result"])


def run_reference(ctx: ServiceContext) -> dict[str, Any]:
    """Return a static authored answer or execute an explicitly supported workflow."""
    ctx.ensure_loaded()
    if ctx.fixtures_dir and (ctx.fixtures_dir / "session_manifest.json").is_file():
        from chi_bench.verifier.reference_session import run_session_reference

        return run_session_reference(ctx)
    if ctx._cm_loaded:
        from chi_bench.verifier.reference_catalog import build_cm_reference

        expected = json.loads((ctx.fixtures_dir / "expectations.json").read_text())
        try:
            return build_cm_reference(expected)
        except FileNotFoundError as exc:
            raise _unsupported(str(exc)) from exc
    expected = ctx._expectations
    if expected is None:
        raise _unsupported("task has no reference expectations")
    if expected.task_kind == "provider_to_payer_e2e":
        from chi_bench.verifier.reference_e2e import run_e2e_reference

        return run_e2e_reference(ctx)
    if expected.task_kind == "provider_new_referral":
        plan = _provider_plan(ctx)
        case_id = _execute_provider(ctx, plan)
    elif expected.task_kind in {
        "payer_approved",
        "payer_denied",
        "payer_pended",
        "payer_not_covered",
        "payer_p2p",
    }:
        plan = _payer_plan(ctx)
        case_id = _execute_payer(ctx, plan)
    else:
        raise _unsupported(f"no executable reference for task kind {expected.task_kind!r}")
    status = ctx.get_case(case_id).status.value
    if status != expected.expected_target_status:
        raise RuntimeError(
            f"Reference workflow ended at {status!r}, expected {expected.expected_target_status!r}"
        )
    return {
        "executed": True,
        "reference_mode": "executed_workflow",
        "case_id": case_id,
        "target_status": status,
        "semantic_verification": "not_run",
    }


async def run_reference_control(environment: Any) -> dict[str, Any]:
    """Run a host-owned control in a fresh environment, then freeze for judging.

    Call before starting a model harness. ``control_request`` runs inside the
    trusted simulator and supplies its control token there; the clean agent
    receives neither the token nor this module. Published solution wrappers
    executed by stock Harbor's oracle agent cannot use this protected path.
    The caller continues the normal verifier/upload lifecycle after this returns.
    """
    result = await environment.control_request("/_oracle/solve", {})
    if not isinstance(result, dict):
        raise RuntimeError("Trusted reference did not report a completed workflow")
    if result.get("reference_mode") == "static_answer" and result.get("executed") is False:
        return result
    if result.get("executed") is not True:
        raise RuntimeError("Trusted reference did not report a completed workflow")
    await environment.begin_verification()
    return result
