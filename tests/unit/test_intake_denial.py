"""A failed member eligibility check can end a payer case before clinical review."""

from datetime import datetime

import pytest

from chi_bench.core.clock import WorldClock
from chi_bench.core.context import ServiceContext
from chi_bench.core.enums import DeterminationDecision, IntakeStatus, PayerMode, PayerRouteTarget
from chi_bench.core.errors import InvalidCaseActionError
from chi_bench.core.models import (
    Coverage,
    HiddenCasePolicy,
    IntakeCase,
    MdCaseDecision,
    NurseCaseRecommendation,
    Patient,
    PriorAuthCase,
    ServiceRequest,
)
from chi_bench.core.pdf import render_request_form_html
from chi_bench.core.scenario import ScenarioDefinition
from chi_bench.verifier.stages.outcome import OutcomeVerifier


@pytest.fixture
def ctx(tmp_path):
    context = ServiceContext.build(tmp_path)
    context._scenario = ScenarioDefinition.model_construct(task_kind="payer_not_covered")
    context._clock = WorldClock(datetime(2026, 3, 15, 9))
    context.payer_mode = PayerMode.AGENT
    context.agent_owned_payer_workflow = True
    case = PriorAuthCase(
        id="CASE-TEST",
        external_case_id="PA-TEST",
        patient_id="PAT-TEST",
        service_request_id="SR-TEST",
        status="submitted",
        urgency="standard",
        requested_by="provider",
        assigned_to="payer",
        created_at=context.now,
        updated_at=context.now,
        decision_due_at=context.now,
    )
    context.save_case(case)
    context.save_hidden_policy(
        HiddenCasePolicy(id="POLICY-TEST", case_id=case.id, route_target="standard_um")
    )
    intake = IntakeCase(id="INTAKE-TEST", case_id=case.id, received_at=context.now)
    context.store.save_resource("payer", "intake_cases", intake.id, intake.model_dump(mode="json"))
    context.store.save_resource(
        "provider",
        "directory_contacts",
        "PAYER-RN",
        {
            "id": "PAYER-RN",
            "name": "Reviewer",
            "role": "um_nurse",
            "email": "",
            "phone": "",
            "organization_id": "ORG-PAYER",
            "escalation_role": "um_nurse",
        },
    )
    yield context
    context.close()


def confirm(ctx, *, member_eligible=False, service_covered=None):
    return ctx.intake.confirm_intake_decisions(
        "CASE-TEST",
        request_complete=True,
        member_eligible=member_eligible,
        service_covered=service_covered,
        provider_network_status="in_network",
    )


def exported(ctx):
    return {
        "target_case": ctx.get_case("CASE-TEST").model_dump(mode="json"),
        "intake_cases": ctx.store.list_resources("payer", "intake_cases"),
        "payer_determinations": ctx.store.list_resources("payer", "payer_determinations"),
        "payer_nurse_case_recommendations": ctx.store.list_resources(
            "payer", "payer_nurse_case_recommendations"
        ),
        "payer_md_case_decisions": ctx.store.list_resources("payer", "payer_md_case_decisions"),
        "review_decisions": ctx.store.list_resources("provider", "review_decisions"),
        "state_transitions": [x.model_dump(mode="json") for x in ctx.store.list_transitions()],
        "stage_traces": [x.model_dump(mode="json") for x in ctx.store.list_stage_traces()],
        "audit_logs": [x.model_dump(mode="json") for x in ctx.store.list_audit_logs()],
    }


def test_completed_ineligible_intake_can_be_denied(ctx):
    intake = confirm(ctx)
    result = ctx.determination.finalize_determination("CASE-TEST", DeterminationDecision.DENIED)
    assert result["case"]["status"] == "denied"
    assert "ELIG_TERMED" in result["case"]["outcome_reason"]
    assert result["determination"]["source"] == "intake_eligibility"
    assert result["determination"]["source_record_id"] == intake["id"]
    assert result["case"]["authorization_number"] is None
    assert intake["decision_service_covered"] is None
    letter_request = ctx.pending_letter_request("CASE-TEST", "denial")
    assert letter_request is not None
    assert "ELIG_TERMED" in letter_request.rationale
    assert "ELIG_TERMED" in letter_request.supporting_basis
    assert letter_request.policy_citations
    assert letter_request.appeal_information
    checks = (
        OutcomeVerifier(
            exported(ctx),
            {
                "target_case_id": "CASE-TEST",
                "expected_target_status": "denied",
            },
            [],
        )
        .verify()
        .checks
    )
    assert checks["outcome.clean_determination"] is True, checks


@pytest.mark.parametrize("decision", ["approved", "partially_approved"])
def test_ineligible_intake_cannot_be_approved_even_with_override(ctx, decision):
    confirm(ctx)
    with pytest.raises(InvalidCaseActionError, match="eligibility"):
        ctx.determination.finalize_determination(
            "CASE-TEST",
            decision,
            overridden=True,
            override_reason="override",
        )
    assert ctx.get_case("CASE-TEST").status.value == "submitted"
    assert not ctx.store.list_resources("payer", "payer_determinations")


def test_eligible_intake_still_requires_service_coverage(ctx):
    with pytest.raises(ValueError, match="service_covered"):
        confirm(ctx, member_eligible=True)
    assert ctx.intake_case_for_case("CASE-TEST").status == IntakeStatus.NEW


def test_intake_denial_does_not_generate_a_letter_automatically(ctx, monkeypatch):
    # Keep real letter persistence; skip PDF rendering at the filesystem boundary.
    monkeypatch.setattr(ctx, "_materialize_case_workspace_artifacts", lambda *args, **kwargs: None)
    ctx.agent_owned_payer_workflow = False
    confirm(ctx)
    ctx.determination.finalize_determination("CASE-TEST", "denied")
    assert not ctx.list_case_letters("CASE-TEST")
    assert ctx.pending_letter_request("CASE-TEST", "denial") is not None


def test_denial_letter_uses_the_intake_reason_and_basis(ctx, monkeypatch):
    monkeypatch.setattr(ctx, "_materialize_case_workspace_artifacts", lambda *args, **kwargs: None)
    confirm(ctx)
    ctx.determination.finalize_determination("CASE-TEST", "denied")
    result = ctx.letters.generate_denial_letter("CASE-TEST")
    assert result["letter"]["reason_code"] == "ELIG_TERMED"
    assert "ELIG_TERMED" in result["letter"]["supporting_basis"]
    assert ctx.letters.audit_letter_completeness(result["letter"]["id"])["complete"] is True


def test_eligible_intake_does_not_allow_denial_without_review(ctx):
    confirm(ctx, member_eligible=True, service_covered=True)
    with pytest.raises(ValueError, match="upstream"):
        ctx.determination.finalize_determination("CASE-TEST", "denied")


@pytest.mark.parametrize(
    "source, recommendation, decision",
    [
        ("nurse", "approve", "approved"),
        ("md", "approve", "approved"),
        ("md", "deny", "denied"),
    ],
)
def test_existing_clinical_determinations_still_pass(ctx, source, recommendation, decision):
    confirm(ctx, member_eligible=True, service_covered=True)
    if source == "nurse":
        record = NurseCaseRecommendation(
            id="REC-TEST",
            case_id="CASE-TEST",
            intake_case_id="INTAKE-TEST",
            recommendation=recommendation,
            created_at=ctx.now,
        )
        table = "payer_nurse_case_recommendations"
    else:
        record = MdCaseDecision(
            id="REC-TEST",
            case_id="CASE-TEST",
            intake_case_id="INTAKE-TEST",
            decision=recommendation,
            signed_off=True,
            created_at=ctx.now,
        )
        table = "payer_md_case_decisions"
    ctx.store.save_resource("payer", table, record.id, record.model_dump(mode="json"))
    result = ctx.determination.finalize_determination("CASE-TEST", decision)
    assert result["case"]["status"] == decision
    assert (
        OutcomeVerifier(
            exported(ctx),
            {
                "target_case_id": "CASE-TEST",
                "expected_target_status": decision,
            },
            [],
        )
        .verify()
        .checks["outcome.clean_determination"]
        is True
    )


def test_failed_eligibility_blocks_an_existing_approval_recommendation(ctx):
    confirm(ctx)
    record = NurseCaseRecommendation(
        id="REC-TEST",
        case_id="CASE-TEST",
        intake_case_id="INTAKE-TEST",
        recommendation="approve",
        created_at=ctx.now,
    )
    ctx.store.save_resource(
        "payer", "payer_nurse_case_recommendations", record.id, record.model_dump(mode="json")
    )
    with pytest.raises(InvalidCaseActionError, match="eligibility"):
        ctx.determination.finalize_determination("CASE-TEST", "approved")
    assert not ctx.store.list_resources("payer", "payer_determinations")


@pytest.mark.parametrize("lane", [None, "gold_card_lane"])
def test_ineligible_member_cannot_be_routed_to_review_or_approval(ctx, lane):
    confirm(ctx)
    with pytest.raises(InvalidCaseActionError, match="eligibility"):
        ctx.route_case_internal(
            "CASE-TEST", override_target=PayerRouteTarget(lane) if lane else None
        )
    assert ctx.get_case("CASE-TEST").status.value == "submitted"
    assert not ctx.store.list_resources("payer", "payer_routing_records")


def test_ineligible_member_cannot_enter_triage(ctx):
    confirm(ctx)
    with pytest.raises(InvalidCaseActionError, match="eligibility"):
        ctx.triage.set_disposition("CASE-TEST", "routine", "2026-03-22T09:00:00")
    assert not ctx.store.list_resources("payer", "payer_triage_records")


def test_verifier_rejects_denial_with_incomplete_or_eligible_intake():
    from chi_bench.verifier.stages.outcome import _recommendation_maps_to_final

    determination = {
        "source": "intake_eligibility",
        "source_record_id": "INTAKE-TEST",
        "case_id": "CASE-TEST",
        "intake_case_id": "INTAKE-TEST",
        "original_recommendation": "deny",
        "final_decision": "denied",
    }
    for status, eligible in [("new", False), ("complete", True), ("complete", None)]:
        assert not _recommendation_maps_to_final(
            {
                "intake_cases": [
                    {
                        "id": "INTAKE-TEST",
                        "case_id": "CASE-TEST",
                        "status": status,
                        "decision_member_eligible": eligible,
                    }
                ]
            },
            determination,
        )


def test_unconfirmed_eligibility_does_not_allow_denial(ctx):
    with pytest.raises(ValueError, match="upstream"):
        ctx.determination.finalize_determination("CASE-TEST", "denied")
    assert not ctx.store.list_resources("payer", "payer_determinations")


def test_request_form_displays_coverage_status_and_termination_date(ctx):
    patient = Patient(
        id="PAT-TEST",
        member_id="MEMBER-TEST",
        first_name="Test",
        last_name="Patient",
        dob="1971-08-14",
        sex="female",
    )
    coverage = Coverage(
        id="COV-TEST",
        patient_id=patient.id,
        payer_name="The Insurance Company",
        plan_name="HMO",
        member_number=patient.member_id,
        active=False,
        termination_date="2025-11-30",
    )
    request = ServiceRequest(
        id="SR-TEST",
        patient_id=patient.id,
        ordering_practitioner_id="DR-TEST",
        service_type="medical",
        procedure_code="95816",
        description="EEG",
        priority="standard",
        diagnosis_codes=["G40.009"],
        site_of_service="inpatient_hospital",
        requested_date=datetime(2026, 3, 18),
    )
    html = render_request_form_html(ctx.get_case("CASE-TEST"), patient, coverage, request, "Doctor")
    assert "Coverage Status" in html
    assert "Inactive" in html
    assert "Coverage Termination Date" in html
    assert "2025-11-30" in html
