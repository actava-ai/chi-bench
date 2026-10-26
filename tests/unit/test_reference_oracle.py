"""Trusted reference controls execute workflow services against a bootstrapped world."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chi_bench.core.scenario import ScenarioDefinition
from chi_bench.core.context import ServiceContext
from chi_bench.server.routers.common import create_common_router, register_exception_handlers
from chi_bench.services.service import WorldService
from chi_bench.verifier.stages import collect_stage_checks
from chi_bench.verifier.task_runtime import build_scorecard


def _world(*, provider: bool) -> dict:
    now = "2026-04-01T09:00:00"
    payload = {
        name: []
        for name, field in ScenarioDefinition.model_fields.items()
        if field.is_required() and "list[" in str(field.annotation)
    }
    payload.update(
        world_id="reference-test",
        scenario_id="reference-test",
        seed=1,
        generated_at=now,
        now=now,
        counts=dict.fromkeys(
            "provider_workers payer_workers patients encounters documents historical_cases active_cases".split(),
            0,
        ),
        provider_org={"id": "PROVIDER", "name": "Provider", "kind": "provider"},
        payer_org={"id": "PAYER", "name": "Payer", "kind": "payer"},
        task_kind="provider_new_referral" if provider else "payer_not_covered",
        task_actor="provider" if provider else "payer",
        payer_mode="agent",
        target_patient_id="PAT-TEST",
        target_case_id=None if provider else "CASE-TEST",
        target_order_id=None if provider else "SR-TEST",
        patients=[
            dict(
                id="PAT-TEST",
                member_id="MEMBER",
                first_name="Test",
                last_name="Patient",
                dob="1970-01-01",
                sex="female",
            )
        ],
        practitioners=[
            dict(
                id="PRAC-TEST",
                name="Test Doctor",
                role="clinician",
                specialty="Neurology",
                organization_id="PROVIDER",
                npi="1234567890",
            )
        ],
        contacts=[
            dict(
                id="COORDINATOR",
                name="Coordinator",
                role="pa_coordinator",
                email="",
                phone="",
                organization_id="PROVIDER",
                escalation_role="pa_coordinator",
            ),
            dict(
                id="PAYER-RN",
                name="Nurse",
                role="um_nurse",
                email="",
                phone="",
                organization_id="PAYER",
                escalation_role="um_nurse",
            ),
        ],
        coverages=[
            dict(
                id="COV-TEST",
                patient_id="PAT-TEST",
                payer_name="Payer",
                plan_name="Plan",
                member_number="MEMBER",
            )
        ],
        documents=[
            dict(
                id="DOC-SOURCE",
                patient_id="PAT-TEST",
                kind="chart_note",
                title="Neurology visit",
                content="Progressive headaches for three weeks; MRI brain requested by Test Doctor.",
                created_at=now,
            )
        ],
    )
    if not provider:
        payload["service_requests"] = [
            dict(
                id="SR-TEST",
                patient_id="PAT-TEST",
                ordering_practitioner_id="PRAC-TEST",
                service_type="radiology",
                procedure_code="70553",
                description="MRI brain",
                priority="standard",
                diagnosis_codes=["R51.9"],
                site_of_service="outpatient_hospital",
                requested_date=now,
            )
        ]
        payload["cases"] = [
            dict(
                id="CASE-TEST",
                external_case_id="PA-TEST",
                patient_id="PAT-TEST",
                service_request_id="SR-TEST",
                status="submitted",
                urgency="standard",
                requested_by="PRAC-TEST",
                assigned_to="PAYER-RN",
                created_at=now,
                updated_at=now,
                decision_due_at=now,
            )
        ]
        payload["hidden_policies"] = [
            dict(id="POL-TEST", case_id="CASE-TEST", route_target="standard_um")
        ]
    return payload


@pytest.fixture
def reference_world(tmp_path, monkeypatch):
    # Exercise actual workflow persistence; PDF rendering is a separate browser boundary.
    monkeypatch.setattr(
        ServiceContext, "_materialize_case_workspace_artifacts", lambda *a, **kw: None
    )
    monkeypatch.setenv("CHI_BENCH_CONTROL_TOKEN", "reference-test-token")
    monkeypatch.delenv("CHI_BENCH_FHIR_URL", raising=False)
    services = []

    def build(*, provider=False, unsupported=False, active=True):
        fixtures = tmp_path / str(len(services)) / "fixtures"
        fixtures.mkdir(parents=True)
        scenario = _world(provider=provider)
        scenario["coverages"][0]["active"] = active
        if unsupported:
            scenario["task_kind"] = "payer_p2p"
        expectations = dict(
            scenario_id="reference-test",
            task_kind=scenario["task_kind"],
            task_actor=scenario["task_actor"],
            verifier_contract="contract_v5",
            expected_payer_mode="agent",
            target_case_id=scenario["target_case_id"],
            target_patient_id="PAT-TEST",
            expected_target_status="submitted" if provider else "denied",
            included_stages=["new_referral", "provider_pre_submission"]
            if provider
            else ["intake", "outcome"],
            expected_provider_pre_submission={
                "required_document_kinds": ["chart_note", "letter_of_medical_necessity"]
            }
            if provider
            else {},
            expected_service_request={
                "acceptable_procedure_codes": ["70553"],
                "required_diagnosis_codes": ["R51.9"],
                "acceptable_service_types": ["radiology"],
                "acceptable_sites_of_service": ["outpatient_hospital"],
            },
            stage_ground_truth=[]
            if provider
            else [
                dict(
                    stage="intake",
                    model_name="IntakeCase",
                    expected_fields={
                        "decision_request_complete": True,
                        "decision_member_eligible": False,
                        "decision_service_covered": None,
                        "provider_network_status": "in_network",
                        "diagnoses": [
                            dict(name="Headache", code="R51.9", code_set="ICD10", is_primary=True)
                        ],
                    },
                )
            ],
        )
        (fixtures / "scenario.json").write_text(json.dumps(scenario))
        (fixtures / "expectations.json").write_text(json.dumps(expectations))
        (fixtures / "judge").mkdir()
        (fixtures / "judge/canonical_case_record.json").write_text(
            json.dumps(
                dict(
                    clinical_facts={
                        "ordering_provider_npi": "1234567890",
                        "procedure_description": "MRI brain",
                        "procedure_code": "70553",
                    }
                )
            )
        )
        service = WorldService(fixtures.parent / "runtime", fixtures)
        service.ensure_loaded()
        services.append(service)
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(create_common_router(service))
        return service, TestClient(app), expectations

    yield build
    for service in services:
        service.close()


def _solve(client, *, authorized=True):
    return client.post(
        "/_oracle/solve",
        headers={"Authorization": "Bearer reference-test-token"} if authorized else {},
    )


def test_concurrent_exports_preserve_the_same_live_case(reference_world):
    service, _, _ = reference_world()
    expected = service.export_state()["target_case"]
    with ThreadPoolExecutor(max_workers=4) as executor:
        exports = list(executor.map(lambda _: service.export_state(), range(16)))
    assert all(exported["target_case"] == expected for exported in exports)
    assert service.export_state()["target_case"] == expected


def test_provider_reference_executes_case_document_and_submission_services(reference_world):
    service, client, expectations = reference_world(provider=True)
    response = _solve(client)
    assert response.status_code == 200, response.text
    exported = service.export_state()
    assert exported["target_case"]["status"] == "submitted"
    assert exported["submission_packets"]
    assert exported["provider_determinations"]
    actions = {item["action"] for item in exported["audit_logs"]}
    assert {"create_case_from_order", "create_document", "submit_authorization"} <= actions
    checks, stages = collect_stage_checks(exported, expectations)
    assert build_scorecard(checks, stages)["failed_checks"] == []
    assert "canonical_case_record" not in response.text
    assert "clinical_facts" not in response.text


def test_intake_reference_reaches_denial_via_eligibility_and_determination(reference_world):
    service, client, expectations = reference_world()
    response = _solve(client)
    assert response.status_code == 200, response.text
    exported = service.export_state()
    assert exported["target_case"]["status"] == "denied"
    assert exported["payer_determinations"][0]["source"] == "intake_eligibility"
    assert exported["intake_cases"][0]["status"] == "complete"
    checks, stages = collect_stage_checks(exported, expectations)
    assert build_scorecard(checks, stages)["failed_checks"] == []


def test_unsupported_reference_rejects_before_mutating_world(reference_world):
    service, client, _ = reference_world(unsupported=True)
    before = service.export_state()
    before_audit = [item.model_dump(mode="json") for item in service.store.list_audit_logs()]
    response = _solve(client)
    assert response.status_code == 501, response.text
    assert "reference" in response.json()["detail"].lower()
    assert [
        item.model_dump(mode="json") for item in service.store.list_audit_logs()
    ] == before_audit
    after = service.export_state()
    # export_state itself records a list_messages read on an existing target.
    after["audit_logs"] = before["audit_logs"]
    assert after == before


def test_reference_rejects_agent_without_calling_solver(reference_world):
    service, client, _ = reference_world(provider=True)
    before = service.export_state()
    response = _solve(client, authorized=False)
    assert response.status_code == 401
    assert service.export_state() == before


@pytest.mark.parametrize(
    "action,status", [("gather_more_evidence", "docs_needed"), ("do_not_submit", "closed")]
)
def test_provider_reference_records_non_submission_without_a_packet(
    reference_world, action, status
):
    service, client, expectations = reference_world(provider=True)
    expectations["expected_target_status"] = status
    expectations["expected_provider_pre_submission"] = {
        "final_action": action,
        "packet_must_be_absent": True,
    }
    service._ctx._expectations = service._ctx._expectations.model_validate(expectations)
    response = _solve(client)
    assert response.status_code == 200, response.text
    state = service.export_state()
    assert state["target_case"]["status"] == status
    assert not state["submission_packets"]
    assert state["provider_determinations"][0]["final_action"] == action
    assert "Progressive headaches" in state["provider_determinations"][0]["override_reason"]
    checks, stages = collect_stage_checks(state, expectations)
    assert build_scorecard(checks, stages)["failed_checks"] == []


def test_incomplete_stage_inputs_fail_preflight_without_mutation(reference_world):
    service, client, _ = reference_world()
    service._ctx._expectations.stage_ground_truth[0]["expected_fields"].pop(
        "decision_member_eligible"
    )
    before = service.store.list_audit_logs()
    response = _solve(client)
    assert response.status_code == 501, response.text
    assert service.store.list_audit_logs() == before
    assert not service.store.list_resources("payer", "intake_cases")


def test_cm_reference_without_authored_answer_cannot_invent_an_interview(reference_world):
    service, client, _ = reference_world(provider=True)
    service._ctx._cm_loaded = True
    before = service.store.list_audit_logs()
    response = _solve(client)
    assert response.status_code == 501, response.text
    assert "No authored CM reference answer" in response.json()["detail"]
    assert service.store.list_audit_logs() == before
    assert not service.store.list_resources("provider", "cm_outreach_records")


def test_reference_merges_node_snapshots_and_records_real_criteria(reference_world):
    service, client, expectations = reference_world()
    expectations["task_kind"] = "payer_approved"
    expectations["expected_target_status"] = "approved"
    expectations["included_stages"] = ["intake", "triage", "nurse_review", "outcome"]
    fields = expectations["stage_ground_truth"][0]["expected_fields"]
    fields.update(decision_member_eligible=True, decision_service_covered=True)
    expectations["stage_ground_truth"] = [
        dict(stage="intake", model_name="IntakeCase", expected_fields={key: value})
        for key, value in fields.items()
    ] + [
        dict(
            stage="triage",
            model_name="TriageRecord",
            expected_fields=dict(
                urgency_level="routine",
                sla_deadline="2026-04-08T09:00:00",
                disposition="nurse_review",
            ),
        ),
        dict(
            stage="nurse_review",
            model_name="NurseCaseRecommendation",
            expected_fields=dict(
                recommendation="approve",
                clinical_notes="Headache chart and imaging criteria reviewed.",
            ),
        ),
    ]
    expectations["expected_clinical_criteria"] = dict(
        criteria=[
            dict(
                stage="nurse_review",
                line_number=1,
                criterion_id="indication",
                criterion_text="Headache imaging indicated",
                expected_criterion_result="met",
                evidence_items=[
                    dict(
                        item_id="history",
                        comparison_mode="presence",
                        expected_item_result="met",
                        source_refs=[dict(source_type="document", source_id="DOC-SOURCE")],
                    )
                ],
            )
        ]
    )
    service._ctx._expectations = service._ctx._expectations.model_validate(expectations)
    response = _solve(client)
    assert response.status_code == 200, response.text
    state = service.export_state()
    review = state["payer_nurse_reviews"][0]
    assert review["criteria_evaluations"][0]["item_observations"][0]["source_refs_used"] == [
        "document:DOC-SOURCE"
    ]
    assert state["payer_determinations"][0]["source"] == "nurse_recommendation"
    checks, stages = collect_stage_checks(state, expectations)
    assert build_scorecard(checks, stages)["failed_checks"] == []


def test_provider_reference_resolves_reused_npi_by_exact_provider_name(reference_world):
    service, client, _ = reference_world(provider=True)
    original = service.store.get_resource("provider", "practitioners", "PRAC-TEST")
    service.store.save_resource(
        "provider",
        "practitioners",
        "PRAC-DISTRACTOR",
        {**original, "id": "PRAC-DISTRACTOR", "name": "Different Doctor"},
    )
    canonical = service.fixtures_dir / "judge/canonical_case_record.json"
    fields = json.loads(canonical.read_text())
    fields["clinical_facts"]["ordering_provider_name"] = "Test Doctor"
    canonical.write_text(json.dumps(fields))
    response = _solve(client)
    assert response.status_code == 200, response.text
    assert service.export_state()["service_requests"][0]["ordering_practitioner_id"] == "PRAC-TEST"


def test_provider_reference_selects_allowed_code_from_composite_source_order(reference_world):
    service, client, _ = reference_world(provider=True)
    canonical = service.fixtures_dir / "judge/canonical_case_record.json"
    fields = json.loads(canonical.read_text())
    fields["clinical_facts"]["procedure_code"] = "70553, 70000"
    canonical.write_text(json.dumps(fields))
    response = _solve(client)
    assert response.status_code == 200, response.text
    assert service.export_state()["service_requests"][0]["procedure_code"] == "70553"


def test_unsupported_triage_arguments_reject_before_intake_mutation(reference_world):
    service, client, _ = reference_world()
    service._ctx._expectations.stage_ground_truth.append(
        dict(
            stage="triage",
            model_name="TriageRecord",
            expected_fields={"unknown_input": "unsupported"},
        )
    )
    response = _solve(client)
    assert response.status_code == 501, response.text
    assert not service.store.list_resources("payer", "intake_cases")
    assert not service.store.list_audit_logs()


def test_invalid_criterion_gold_rejects_before_intake_mutation(reference_world):
    service, client, _ = reference_world()
    service._ctx._expectations.stage_ground_truth.append(
        dict(
            stage="nurse_review",
            model_name="NurseCaseRecommendation",
            expected_fields={"recommendation": "approve"},
        )
    )
    service._ctx._expectations.expected_clinical_criteria = dict(
        criteria=[
            dict(
                stage="nurse_review",
                criterion_id="test",
                criterion_text="Test",
                expected_criterion_result="invented",
            )
        ]
    )
    response = _solve(client)
    assert response.status_code == 501, response.text
    assert not service.store.list_resources("payer", "intake_cases")
    assert not service.store.list_audit_logs()


@pytest.mark.parametrize(
    "field,value", [("unsupported_decision", True), ("requesting_provider", {"npi": []})]
)
def test_invalid_intake_gold_rejects_before_mutation(reference_world, field, value):
    service, client, _ = reference_world()
    service._ctx._expectations.stage_ground_truth[0]["expected_fields"][field] = value
    response = _solve(client)
    assert response.status_code == 501, response.text
    assert not service.store.list_resources("payer", "intake_cases")
    assert not service.store.list_audit_logs()


@pytest.mark.parametrize("field", ["decision_service_covered", "provider_network_status"])
@pytest.mark.parametrize("missing", [True, False], ids=["omitted", "null"])
def test_eligible_intake_requires_coverage_and_network_before_any_mutation(
    reference_world, field, missing
):
    from chi_bench.verifier.reference_oracle import (
        UnsupportedReferenceContract,
        _payer_plan,
    )

    service, client, _ = reference_world()
    fields = service._ctx._expectations.stage_ground_truth[0]["expected_fields"]
    fields.update(decision_member_eligible=True, decision_service_covered=True)
    if missing:
        fields.pop(field)
    else:
        fields[field] = None
    source_documents = service.store.list_resources("provider", "documents")

    response = _solve(client)

    assert response.status_code == 501, response.text
    assert field in response.json()["detail"]
    assert not service.store.list_resources("payer", "intake_cases")
    assert not service.store.list_audit_logs()
    assert not service.store.list_transitions()
    assert service.store.list_resources("provider", "documents") == source_documents
    with pytest.raises(UnsupportedReferenceContract, match=field):
        _payer_plan(service._ctx)


def test_ineligible_intake_can_omit_coverage_and_network_decisions(reference_world):
    service, client, _ = reference_world()
    fields = service._ctx._expectations.stage_ground_truth[0]["expected_fields"]
    fields.pop("decision_service_covered")
    fields.pop("provider_network_status")

    response = _solve(client)

    assert response.status_code == 200, response.text
    intake = service.store.list_resources("payer", "intake_cases")[0]
    assert intake["decision_member_eligible"] is False
    assert intake["decision_service_covered"] is None
    assert intake["decision_provider_network_status"] is None


def test_reference_fills_omitted_intake_diagnosis_from_the_submitted_order(reference_world):
    service, client, expectations = reference_world()
    expectations["stage_ground_truth"][0]["expected_fields"].pop("diagnoses")
    service._ctx._expectations = service._ctx._expectations.model_validate(expectations)
    response = _solve(client)
    assert response.status_code == 200, response.text
    state = service.export_state()
    assert state["intake_cases"][0]["diagnoses"][0]["code"] == "R51.9"
    checks, stages = collect_stage_checks(state, expectations)
    assert build_scorecard(checks, stages)["failed_checks"] == []


def test_reference_uses_normal_sla_and_routing_when_triage_has_no_gold_record(reference_world):
    service, client, expectations = reference_world()
    expectations["expected_target_status"] = "approved"
    expectations["included_stages"] = ["intake", "triage", "nurse_review", "outcome"]
    expectations["stage_ground_truth"][0]["expected_fields"].update(
        decision_member_eligible=True, decision_service_covered=True
    )
    expectations["stage_ground_truth"].append(
        dict(
            stage="nurse_review",
            model_name="NurseCaseRecommendation",
            expected_fields={"recommendation": "approve"},
        )
    )
    service._ctx._expectations = service._ctx._expectations.model_validate(expectations)
    response = _solve(client)
    assert response.status_code == 200, response.text
    state = service.export_state()
    assert state["payer_triage_records"][0]["sla_hours"] == 168
    assert state["payer_triage_records"][0]["disposition"] == "nurse_review"
    assert state["payer_routing_records"]
    assert "calculate_sla_deadline" in {item["action"] for item in state["audit_logs"]}


@pytest.mark.parametrize("complete", [True, False])
def test_reference_derives_omitted_completeness_from_actual_source_requirements(
    reference_world, complete
):
    service, client, expectations = reference_world()
    service._ctx._expectations.stage_ground_truth[0]["expected_fields"].pop(
        "decision_request_complete"
    )
    if not complete:
        source = service.fhir_read("ServiceRequest", "SR-TEST")
        source["code"] = {"text": ""}
        service.fhir_update("ServiceRequest", "SR-TEST", source)
    response = _solve(client)
    assert response.status_code == 200, response.text
    assert service.export_state()["intake_cases"][0]["decision_request_complete"] is complete


@pytest.mark.parametrize("contract_slots", [True, False])
def test_p2p_reference_uses_actual_service_exchange_before_recording_outcome(
    reference_world, monkeypatch, contract_slots
):
    from chi_bench.services.p2p import P2PService

    service, client, expectations = reference_world()
    service.store.save_resource(
        "provider",
        "directory_contacts",
        "PAYER-MD",
        dict(
            id="PAYER-MD",
            name="Doctor",
            role="physician_reviewer",
            email="",
            phone="",
            organization_id="PAYER",
            escalation_role="physician_reviewer",
        ),
    )
    expectations.update(
        task_kind="payer_p2p",
        included_stages=["intake", "md_review", "p2p", "outcome"],
        expected_p2p_workflow=dict(
            benchmark_side="payer",
            fixed_result="uphold_intended_adverse_decision",
            primary_issue="Imaging necessity",
            required_resolution_points=["Explain clinical indication"],
            turn_limit=3,
            coordination_contract=dict(
                offered_slots=["2026-04-02T10:00:00"] if contract_slots else [],
                slot_selection_rule="first_offered",
            ),
            event_contract=dict(opening_statement="Discuss the submitted MRI request."),
            determination_contract=dict(expected_decision="denied", expected_case_status="denied"),
        ),
    )
    expectations["stage_ground_truth"][0]["expected_fields"].update(
        decision_member_eligible=True, decision_service_covered=True
    )
    expectations["stage_ground_truth"] += [
        dict(
            stage="md_review",
            model_name="MdCaseDecision",
            expected_fields=dict(
                decision="p2p_review",
                clinical_notes="Imaging indication requires physician discussion.",
                determination_rationale="The submitted imaging indication requires a physician consultation before final determination.",
                signed_off=False,
            ),
        ),
        dict(
            stage="p2p",
            model_name="PayerPeerToPeerRequest",
            expected_fields=dict(
                outcome="uphold_intended_adverse_decision",
                status="completed",
                offered_slots=["2026-04-02T10:00:00"],
            ),
        ),
    ]
    service._ctx._expectations = service._ctx._expectations.model_validate(expectations)
    calls = []

    def reply(self, **kwargs):
        calls.append(kwargs["message"])
        return (
            "Synthetic model-boundary reply: the submitted evidence adds no new indication.",
            None,
        )

    monkeypatch.setattr(P2PService, "_generate_counterpart_reply", reply)
    response = _solve(client)
    assert response.status_code == 200, response.text
    state = service.export_state()
    request = state["payer_peer_to_peer_requests"][0]
    assert request["status"] == "completed"
    assert request["outcome_source"] == "simulated_session"
    session = next(
        s for s in state["payer_p2p_session_records"] if s["request_id"] == request["id"]
    )
    assert session["agent_turns_used"] == len(calls) > 0
    assert {"payer", "counterpart"} <= {turn["speaker"] for turn in session["transcript"]}
    assert "Synthetic model-boundary reply" in session["submitted_summary"]
    checks, stages = collect_stage_checks(state, expectations)
    assert build_scorecard(checks, stages)["failed_checks"] == []


def test_p2p_reference_without_a_request_or_creating_decision_rejects_before_mutation(
    reference_world,
):
    service, client, _ = reference_world()
    service.store.save_resource(
        "provider",
        "directory_contacts",
        "PAYER-MD",
        dict(
            id="PAYER-MD",
            name="Doctor",
            role="physician_reviewer",
            email="",
            phone="",
            organization_id="PAYER",
            escalation_role="physician_reviewer",
        ),
    )
    service._ctx._expectations.expected_p2p_workflow = dict(
        benchmark_side="payer",
        fixed_result="uphold_intended_adverse_decision",
        primary_issue="Clinical indication",
        coordination_contract=dict(offered_slots=["2026-04-02T10:00:00"]),
    )
    response = _solve(client)
    assert response.status_code == 501, response.text
    assert not service.store.list_resources("payer", "intake_cases")
    assert not service.store.list_audit_logs()


@pytest.mark.asyncio
async def test_host_reference_control_executes_protected_http_then_freezes(reference_world):
    from chi_bench.verifier.reference_oracle import run_reference_control

    service, client, _ = reference_world(provider=True)
    events = []

    class LocalTrustedEnvironment:
        async def control_request(self, path, payload=None):
            events.append((path, payload))
            response = client.post(
                path, json=payload, headers={"Authorization": "Bearer reference-test-token"}
            )
            response.raise_for_status()
            return response.json()

        async def begin_verification(self):
            assert service._ctx.list_cases()[0].status.value == "submitted"
            events.append("frozen")

    result = await run_reference_control(LocalTrustedEnvironment())
    assert result["executed"] is True
    assert events == [("/_oracle/solve", {}), "frozen"]
    assert service.export_state()["submission_packets"]


def test_e2e_handoff_preserves_false_pa_requirement_and_provider_advice(
    reference_world, monkeypatch
):
    monkeypatch.setenv("CHI_BENCH_E2E_PROTOCOL", "workflow_v2")
    service, _, _ = reference_world(provider=True)
    ctx = service._ctx
    ctx._scenario.task_kind = "provider_to_payer_e2e"
    ctx._expectations.task_kind = "provider_to_payer_e2e"
    case_id = ctx.cases.create_from_order(
        patient_id="PAT-TEST",
        ordering_practitioner_id="PRAC-TEST",
        service_type="radiology",
        procedure_code="70553",
        description="MRI brain",
        priority="standard",
        diagnosis_codes=["R51.9"],
        site_of_service="outpatient_hospital",
    )["case"]["id"]
    policy = ctx.get_policy(case_id)
    policy.authorization_required = False
    ctx.save_hidden_policy(policy)
    checked = ctx.coverage.check_requirement(case_id, "portal")
    assert checked["requirement_outcome"] == "not_required"
    ctx.auth.finalize_provider_determination(case_id, "do_not_submit")
    ctx.auth.submit_authorization(case_id, "portal")
    exported = service.export_state()
    assert exported["e2e_protocol"] == "workflow_v2"
    assert exported["submission_packets"]
    assert exported["target_case"]["status"] == "submitted"
    assert exported["provider_determinations"][-1]["final_action"] == "do_not_submit"
    assert exported["provider_determinations"][-1]["authorization_required"] is False
    assert ctx.get_policy(case_id).authorization_required is False
    assert any(
        trace.get("details", {}).get("e2e_protocol") == "workflow_v2"
        for trace in exported["stage_traces"]
    )


def _workflow_case(reference_world, monkeypatch, *, active):
    monkeypatch.setenv("CHI_BENCH_E2E_PROTOCOL", "workflow_v2")
    service, _, expectations = reference_world(provider=True, active=active)
    ctx = service._ctx
    ctx._scenario.task_kind = "provider_to_payer_e2e"
    ctx._expectations.task_kind = "provider_to_payer_e2e"
    expectations = {
        **expectations,
        "task_kind": "provider_to_payer_e2e",
        "expected_target_status": "approved",
        "included_stages": ["e2e_consistency", "nurse_review", "md_review", "p2p", "outcome"],
        "expected_e2e": {"final_decision": "approved"},
    }
    case_id = ctx.cases.create_from_order(
        patient_id="PAT-TEST",
        ordering_practitioner_id="PRAC-TEST",
        service_type="radiology",
        procedure_code="70553",
        description="MRI brain",
        priority="standard",
        diagnosis_codes=["R51.9"],
        site_of_service="outpatient_hospital",
    )["case"]["id"]
    coverage = ctx.get_coverage("PAT-TEST")
    coverage.active = active
    ctx.store.save_resource("provider", "coverages", coverage.id, coverage.model_dump(mode="json"))
    ctx.coverage.check_requirement(case_id, "portal")
    ctx.auth.finalize_provider_determination(case_id, "submit_pa")
    ctx.auth.submit_authorization(case_id, "portal")
    return service, expectations, case_id


def test_workflow_intake_denial_has_source_proof_and_skips_unreached_review(
    reference_world, monkeypatch
):
    service, expectations, case_id = _workflow_case(reference_world, monkeypatch, active=False)
    ctx = service._ctx
    ctx.intake.get_member_coverage(case_id)
    ctx.intake.confirm_intake_decisions(case_id, request_complete=True, member_eligible=False)
    ctx.determination.finalize_determination(case_id, "denied")
    exported = service.export_state()
    checks, _ = collect_stage_checks(exported, expectations)
    assert exported["e2e_source_eligibility"]["member_eligible"] is False
    assert checks["e2e.downstream_handling_complete"] is True
    assert checks["nurse.reviews_exist"] == checks["md.decision_exists"] == "not_applicable"
    exported["e2e_source_eligibility"]["member_eligible"] = True
    checks, _ = collect_stage_checks(exported, expectations)
    assert checks["nurse.reviews_exist"] is False
    assert checks["md.decision_exists"] is False


def test_workflow_real_intake_pend_keeps_approved_source_as_audit_only(
    reference_world, monkeypatch
):
    service, expectations, case_id = _workflow_case(reference_world, monkeypatch, active=True)
    service._ctx.request_missing_information_internal(
        case_id, ["Dated clinical note supporting the requested MRI"]
    )
    exported = service.export_state()
    checks, _ = collect_stage_checks(exported, expectations)
    assert checks["e2e.downstream_handling_complete"] is True
    assert checks["e2e.final_decision_matches"] == "not_applicable"
    assert checks["nurse.reviews_exist"] == checks["md.decision_exists"] == "not_applicable"


def test_workflow_nurse_approval_waives_never_reached_md_with_real_source_chain(
    reference_world, monkeypatch
):
    service, expectations, case_id = _workflow_case(reference_world, monkeypatch, active=True)
    ctx = service._ctx
    ctx.intake.confirm_intake_decisions(
        case_id,
        request_complete=True,
        member_eligible=True,
        service_covered=True,
        provider_network_status="in_network",
    )
    ctx.review.submit_nurse_case_recommendation(
        case_id,
        "approve",
        clinical_notes="Available source clinical evidence supports approval.",
        reviewer_id="PAYER-RN",
    )
    ctx.determination.finalize_determination(case_id, "approved")
    exported = service.export_state()
    checks, _ = collect_stage_checks(exported, expectations)
    assert checks["e2e.downstream_handling_complete"] is True
    assert checks["md.decision_exists"] == "not_applicable"
    exported["payer_determinations"][0]["source_record_id"] = "UNRELATED"
    checks, _ = collect_stage_checks(exported, expectations)
    assert checks["md.decision_exists"] is False


def test_workflow_export_does_not_choose_latest_packet_among_ambiguous_target_cases(
    reference_world, monkeypatch
):
    service, _, _ = _workflow_case(reference_world, monkeypatch, active=True)
    ctx = service._ctx
    ctx.cases.create_from_order(
        patient_id="PAT-TEST",
        ordering_practitioner_id="PRAC-TEST",
        service_type="radiology",
        procedure_code="70553",
        description="Second request",
        priority="standard",
        diagnosis_codes=["R51.9"],
        site_of_service="outpatient_hospital",
    )
    exported = service.export_state()
    assert exported["target_case"] is None
    assert exported["submission_packets"] == []
