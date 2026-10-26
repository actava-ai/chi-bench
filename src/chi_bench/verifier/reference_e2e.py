"""Trusted scripted workflow controls for mandatory-handoff E2E tasks.

These controls exercise ordinary services with authored source arguments. Their
role turns are reference text, never observed model behavior or semantic proof.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from chi_bench.core.enums import PayerRole, PeerToPeerOutcome
from chi_bench.core.scenario import ExpectationDefinition

if TYPE_CHECKING:
    from chi_bench.core.context import ServiceContext


@contextmanager
def _metadata(ctx: ServiceContext, **updates: Any) -> Iterator[None]:
    saved = {name: getattr(ctx, name) for name in updates}
    try:
        for name, value in updates.items():
            setattr(ctx, name, value)
        yield
    finally:
        for name, value in saved.items():
            setattr(ctx, name, value)


def _provider_fixtures(ctx: ServiceContext) -> Path:
    from chi_bench.verifier.reference_oracle import _unsupported

    task_id = ctx._expectations.scenario_id
    if not task_id.endswith("_e2e"):
        raise _unsupported("E2E task id has no standalone Provider source mapping")
    source_id = task_id[:-4] + "_new_referral_provider"
    candidates = [Path("/opt/chi-bench/tasks") / source_id / "fixtures"]
    if ctx.fixtures_dir:
        candidates.append(ctx.fixtures_dir.parent.parent / source_id / "fixtures")
        candidates.extend(
            p / "prior_auth_provider/tasks" / source_id / "fixtures"
            for p in ctx.fixtures_dir.parents
        )
    worlds = os.environ.get("CHI_BENCH_WORLDS_DIR")
    if worlds:
        candidates.extend(
            p / "prior_auth_provider/tasks" / source_id / "fixtures" for p in Path(worlds).parents
        )
    for candidate in candidates:
        if (candidate / "expectations.json").is_file() and (
            candidate / "judge/canonical_case_record.json"
        ).is_file():
            return candidate
    raise _unsupported("trusted standalone Provider canonical source is unavailable")


def _provider_reference(ctx: ServiceContext):
    from chi_bench.verifier.reference_oracle import _provider_plan, _unsupported

    fixtures = _provider_fixtures(ctx)
    source = ExpectationDefinition.model_validate_json((fixtures / "expectations.json").read_text())
    expected_source = ctx._expectations.scenario_id[:-4] + "_new_referral_provider"
    if (
        source.target_patient_id != ctx._expectations.target_patient_id
        or source.scenario_id != expected_source
    ):
        raise _unsupported("Provider source patient or task identity does not match this E2E task")
    with _metadata(ctx, _expectations=source, fixtures_dir=fixtures):
        plan = _provider_plan(ctx)
    return plan, source, fixtures


@contextmanager
def _phase(ctx: ServiceContext, case_id: str, role: str, phase: str) -> Iterator[None]:
    logical = "p2p" if "p2p" in phase else phase
    ctx.stage_trace(
        case_id,
        "e2e_phase_marker",
        "enter",
        action="enter",
        logical_phase=logical,
        role=role,
        role_phase=phase,
        reference_mode="scripted_reference_control",
    )
    try:
        yield
    finally:
        ctx.stage_trace(
            case_id,
            "e2e_phase_marker",
            "leave",
            action="leave",
            logical_phase=logical,
            role=role,
            role_phase=phase,
            reference_mode="scripted_reference_control",
        )


def _submit(ctx: ServiceContext, plan) -> str:
    ctx.chart.get_patient_chart_by_patient(plan.order["patient_id"])
    case_id = ctx.cases.create_from_order(**plan.order)["case"]["id"]
    with _phase(ctx, case_id, "provider", "provider_submit"):
        ctx.coverage.check_requirement(case_id, plan.channel)
        sources = [
            d
            for d in ctx.get_documents(patient_id=plan.order["patient_id"])
            if d.case_id is None and d.content.strip() and d.kind != "submission_bundle"
        ]
        # Chart-native originals are already visible on the new case. Bundle
        # them directly rather than rewriting their content or lineage.
        document_ids = [d.id for d in sources]
        source_kinds = {d.kind for d in sources}
        for document in plan.documents:
            if document["kind"] not in source_kinds:
                document_ids.append(
                    ctx.docs.create_document(case_id=case_id, **document)["document"]["id"]
                )
        if plan.answers:
            ctx.forms.save_form_response(case_id, plan.answers)
        bundle_id = ctx.docs.create_submission_bundle(case_id, document_ids)["bundle_document"][
            "id"
        ]
        ctx.auth.finalize_provider_determination(
            case_id,
            plan.final_action,
            bundle_document_id=bundle_id,
            override_reason="Scripted reference control preserves the standalone Provider assessment; workflow_v2 still requires truthful handoff.",
        )
        ctx.auth.submit_authorization(case_id, plan.channel, bundle_document_id=bundle_id)
    return case_id


def _gold_models(ctx: ServiceContext) -> dict[str, dict[str, Any]]:
    models: dict[str, dict[str, Any]] = {}
    for entry in ctx._expectations.stage_ground_truth:
        models.setdefault(entry.get("model_name"), {}).update(
            entry.get("expected_fields")
            or entry.get("validated_fields")
            or entry.get("fields")
            or {}
        )
    return models


def _intake_and_route(ctx: ServiceContext, case_id: str, unresolved: list[str]) -> None:
    ctx.intake.get_member_coverage(case_id)
    ctx.intake.verify_provider(case_id)
    case = ctx.get_case(case_id)
    coverage = ctx.get_coverage(case.patient_id)
    service_date = (
        ctx.load_service_request(case.service_request_id).requested_date.date().isoformat()
    )
    eligible = (
        coverage.active
        and (not coverage.effective_date or coverage.effective_date <= service_date)
        and (not coverage.termination_date or service_date <= coverage.termination_date)
    )
    missing_fields, missing_documents = ctx.check_submission_completeness_for_case(
        case_id, ctx.latest_submission_packet(case_id)
    )
    if missing_fields or missing_documents:
        unresolved.append(
            "Actual submitted packet retains missing source fields/documents: "
            + ", ".join(sorted(set(missing_fields + missing_documents)))
            + ". Authored clinical branch is replayed as a reference control, not independently accepted."
        )
    source_intake = _gold_models(ctx).get("IntakeCase") or {}
    service_covered = source_intake.get("decision_service_covered")
    if eligible and service_covered is None:
        service_covered = True
        unresolved.append(
            "No authored intake service_covered decision is available. True is recorded only "
            "as the scripted administrative prerequisite for replaying the authored clinical "
            "stage; benefit coverage has not been independently established."
        )
    ctx.intake.confirm_intake_decisions(
        case_id,
        request_complete=not missing_fields and not missing_documents,
        member_eligible=bool(eligible),
        service_covered=service_covered if eligible else None,
        provider_network_status=coverage.network_status if eligible else None,
    )
    if not eligible:
        ctx.determination.finalize_determination(case_id, "denied")
        return
    policy = ctx.get_policy(case_id)
    route, _ = ctx.route_target_for_policy(policy)
    fast_track = route is not None and route.value in {"gold_card_lane", "notification_only_lane"}
    gold = ctx.triage.check_gold_card(case_id)
    urgency = "urgent" if case.urgency.value == "expedited" else "routine"
    sla = ctx.triage.calculate_sla_deadline(case_id, urgency)
    ctx.triage.set_disposition(
        case_id,
        urgency,
        sla["sla_deadline"],
        sla_hours=sla["sla_hours"],
        sla_rule_source=sla["rule_source"],
        gold_card_eligible=bool(gold.get("gold_card_eligible")),
        disposition="auto_approval" if fast_track else "nurse_review",
        disposition_reason="Scripted reference routing from the actual packet and source policy.",
    )
    ctx.route_case_internal(case_id)


def _save_criteria(ctx: ServiceContext, case_id: str, stage: str, reviewer: str) -> None:
    from chi_bench.verifier.reference_oracle import _criteria_inputs

    method = (
        ctx.review.save_criteria_evaluation
        if stage == "nurse_review"
        else ctx.review.save_md_review
    )
    for line, evaluations in _criteria_inputs(ctx, case_id, stage).items():
        method(case_id, line, evaluations=evaluations, reviewer_id=reviewer)


def _service_fields(method, fields: dict[str, Any]) -> dict[str, Any]:
    from inspect import signature

    return {
        name: value
        for name, value in fields.items()
        if name in signature(method).parameters and name != "case_id"
    }


def _relay(
    ctx: ServiceContext,
    case_id: str,
    contract: dict[str, Any],
    notes: list[str],
    source_summary: str,
) -> None:
    from chi_bench.experiment.agents.dual_pa_e2e_relay import (
        RelayTranscript,
        RelayTurn,
        workspace_transcript_payload,
    )
    from chi_bench.verifier.reference_oracle import _unsupported

    requests = [r for r in ctx.list_peer_to_peer_requests(case_id) if r.status.value != "completed"]
    if len(requests) != 1:
        raise _unsupported("E2E relay requires one service-created active request")
    request = requests[0]
    reviewer = ctx.contact_for_payer_role(PayerRole.PHYSICIAN_REVIEWER).id
    outcome = PeerToPeerOutcome(contract["fixed_result"]).value
    slots = (contract.get("coordination_contract") or {}).get("offered_slots") or [
        ctx.now.isoformat()
    ]
    # Use the same two-role workflow_v2 scheduling path as a model harness.
    ctx.p2p.initialize_workflow_request(request.id)
    with _phase(ctx, case_id, "payer", "payer_p2p_coordination"):
        ctx.p2p.offer_slots(request.id, reviewer, slots)
    with _phase(ctx, case_id, "provider", "provider_p2p_coordination"):
        ctx.auth.respond_to_peer_to_peer(
            case_id,
            request.id,
            note="Scripted reference Provider scheduling response.",
            selected_slot=slots[0],
        )
    with _phase(ctx, case_id, "payer", "payer_p2p_coordination"):
        ctx.p2p.schedule_p2p(request.id, reviewer, slots[0])
    transcript = RelayTranscript(request.id, case_id)
    authored = {
        "provider_policy": contract.get("provider_policy") or {},
        "event_facts": (contract.get("event_contract") or {}).get("counterpart_facts") or [],
        "provider_context_sources": contract.get("provider_context_sources") or {},
    }
    provider_message = (
        "Scripted reference Provider turn; not observed model behavior. Available chart source:\n"
        + source_summary
        + "\nAuthored P2P reference context (not newly observed clinical evidence):\n"
        + json.dumps(authored, ensure_ascii=False)
        + "\nReference endpoint label from authored fixed_result (not observed clinician assent): "
        + outcome
    )
    payer_message = (
        "Scripted reference Payer turn; not observed model behavior. Authored P2P position:\n"
        + json.dumps(contract.get("payer_policy") or {}, ensure_ascii=False)
        + "\nAuthored resolution notes:\n"
        + "\n".join(notes)
        + "\nReference recorded outcome: "
        + outcome
    )
    with _phase(ctx, case_id, "provider", "provider_p2p_turn_1"):
        transcript.add(RelayTurn("provider", provider_message, final_position=outcome))
        ctx.p2p.record_relay_transcript(workspace_transcript_payload(transcript))
    with _phase(ctx, case_id, "payer", "payer_p2p_turn_1"):
        transcript.add(
            RelayTurn("payer", payer_message, final_position=outcome, ready_to_finalize=True)
        )
        ctx.p2p.record_relay_transcript(workspace_transcript_payload(transcript))
        ctx.p2p.record_p2p_outcome(
            request.id,
            reviewer,
            outcome,
            note="Scripted two-role reference control. " + "\n".join(notes),
        )


def _review(ctx: ServiceContext, case_id: str, plan, unresolved: list[str]) -> None:
    if ctx.get_case(case_id).status.value in {"approved", "denied"}:
        return
    models = _gold_models(ctx)
    nurse = dict(models.get("NurseCaseRecommendation") or {})
    md = dict(models.get("MdCaseDecision") or {})
    contract = ctx._expectations.expected_p2p_workflow
    if not nurse:
        nurse = {
            "recommendation": "escalate",
            "clinical_notes": "Scripted reference administrative bridge to the authored physician/P2P stage. This is not an independently inferred clinical recommendation.",
        }
        unresolved.append(
            "No authored NurseCaseRecommendation was supplied; scripted administrative escalation bridges the actual intake to the authored later stage."
        )
    reviewer = ctx.contact_for_payer_role(PayerRole.UM_NURSE).id
    _save_criteria(ctx, case_id, "nurse_review", reviewer)
    nurse["reviewer_id"] = reviewer
    ctx.review.submit_nurse_case_recommendation(
        case_id, **_service_fields(ctx.review.submit_nurse_case_recommendation, nurse)
    )
    if nurse.get("recommendation") == "request_info":
        return
    if nurse.get("recommendation") == "approve" and not md and not contract:
        ctx.determination.finalize_determination(case_id, "approved", actor=reviewer)
        return
    if not md and contract:
        anchors = (contract.get("determination_contract") or {}).get(
            "determination_rationale_anchors"
        ) or []
        md = {
            "decision": "p2p_review",
            "clinical_notes": "Scripted reference bridge to the authored P2P stage.",
            "determination_rationale": "\n".join(str(x) for x in anchors),
            "signed_off": False,
        }
        unresolved.append(
            "No authored MdCaseDecision was supplied; a scripted p2p_review routing decision opens the authored two-role relay."
        )
    if not md:
        from chi_bench.verifier.reference_oracle import _unsupported

        raise _unsupported("authored clinical decision is unavailable after nurse escalation")
    reviewer = ctx.contact_for_payer_role(PayerRole.PHYSICIAN_REVIEWER).id
    _save_criteria(ctx, case_id, "md_review", reviewer)
    md.pop("p2p_request_id", None)
    md["reviewer_id"] = reviewer
    if md.get("decision") in {"approve", "deny", "partial_approve"}:
        md["signed_off"] = True  # The scripted reference reviewer signs this execution.
    ctx.review.submit_md_case_decision(
        case_id, **_service_fields(ctx.review.submit_md_case_decision, md)
    )
    if md.get("decision") == "request_info":
        return
    if md.get("decision") == "p2p_review":
        p2p = models.get("PayerPeerToPeerRequest") or {}
        _relay(
            ctx, case_id, contract, [str(x) for x in p2p.get("notes") or []], plan.source_summary
        )
    final = ctx._expectations.expected_target_status
    ctx.determination.finalize_determination(case_id, final, actor=reviewer)


def run_e2e_reference(ctx: ServiceContext) -> dict[str, Any]:
    """Execute authored E2E service arguments; report no semantic acceptance."""
    from chi_bench.verifier.reference_oracle import _unsupported

    ctx.ensure_loaded()
    if ctx.task_kind != "provider_to_payer_e2e" or ctx.e2e_protocol != "workflow_v2":
        raise _unsupported("E2E reference execution requires workflow_v2")
    expected = ctx._expectations
    if expected is None:
        raise _unsupported("E2E reference expectations are unavailable")
    plan, source, fixtures = _provider_reference(ctx)
    unresolved: list[str] = []
    case_id = _submit(ctx, plan)
    with _phase(ctx, case_id, "payer", "payer_review"):
        _intake_and_route(ctx, case_id, unresolved)
        _review(ctx, case_id, plan, unresolved)
        status = ctx.get_case(case_id).status.value
        letter_type = {
            "approved": "approval",
            "denied": "denial",
            "partially_approved": "partial_approval",
            "pended_action_required": "pend",
        }.get(status)
        if letter_type:
            generated = getattr(ctx.letters, f"generate_{letter_type}_letter")(case_id)
            ctx.letters.deliver_letter(generated["letter"]["id"], plan.channel)
    if status != expected.expected_target_status:
        unresolved.append(
            f"Actual reference status {status} differs from authored source episode status {expected.expected_target_status}; source gold is unchanged."
        )
    return {
        "executed": True,
        "reference_mode": "executed_workflow",
        "protocol": "workflow_v2",
        "control_type": "scripted_reference_not_blind_model_run",
        "case_id": case_id,
        "target_status": status,
        "semantic_verification": "not_run",
        "provider_source_task": source.scenario_id,
        "provider_source_fixtures": str(fixtures),
        "standalone_provider_action": plan.final_action,
        "unresolved_reference_content": unresolved,
    }
