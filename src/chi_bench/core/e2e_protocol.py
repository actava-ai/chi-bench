"""Versioned E2E execution and scoring rules from trusted runtime state."""

from __future__ import annotations

from typing import Any, Literal

E2EProtocol = Literal["workflow_v2"]
# Historical identifier is retained for identifying unsupported saved runs only.
LEGACY_PROTOCOL = "dual_viewpoint_v1"
WORKFLOW_PROTOCOL: E2EProtocol = "workflow_v2"
STANDALONE_DECISION_NA = (
    "workflow_v2 requires a submitted request and payer handoff; standalone "
    "Provider submit/no-submit gold does not score this workflow."
)
SOURCE_OUTCOME_NA = (
    "workflow_v2 judges the actual submitted packet against policy. Source-gold "
    "clinical values remain audit observations, not unconditional actual-packet answers."
)


def validate_e2e_protocol(value: Any = None) -> E2EProtocol:
    """Resolve new execution settings; only the current workflow is supported."""
    if value is None:
        return WORKFLOW_PROTOCOL
    if value != WORKFLOW_PROTOCOL:
        raise ValueError(
            f"Unsupported CHI_BENCH_E2E_PROTOCOL: {value!r}; only workflow_v2 is supported."
        )
    return value


def e2e_protocol(exported: dict[str, Any]) -> E2EProtocol:
    # A runtime default must never relabel a retained unversioned export.
    value = exported.get("e2e_protocol")
    if value != WORKFLOW_PROTOCOL:
        raise ValueError(
            f"Unsupported E2E export protocol: {value!r}; current scoring requires an explicit workflow_v2 runtime export. Historical artifacts are read-only."
        )
    return WORKFLOW_PROTOCOL


def is_workflow_v2(exported: dict[str, Any], expectations: dict[str, Any]) -> bool:
    return bool(e2e_score_metadata(exported, expectations))


def e2e_score_metadata(exported: dict[str, Any], expectations: dict[str, Any]) -> dict[str, Any]:
    kind = "provider_to_payer_e2e"
    expected_kind = expectations.get("task_kind")
    exported_kind = exported.get("task_kind")
    if (
        expected_kind != kind
        and exported_kind != kind
        and expectations.get("verifier_contract") != "contract_e2e_v1"
    ):
        return {}
    if expected_kind != kind or exported_kind not in {None, kind}:
        raise ValueError(
            "Current workflow_v2 scoring requires explicit E2E expectations task_kind and a matching runtime task identity; historical contracts cannot use legacy scoring."
        )
    return {
        "e2e_protocol": e2e_protocol(exported),
        "e2e_protocol_source": "trusted_runtime_export",
    }


def pending_episode_expected(expectations: dict[str, Any]) -> bool:
    expected = expectations.get("expected_e2e") or {}
    return (
        expectations.get("task_kind") == "provider_to_payer_e2e"
        and expected.get("final_decision") == "pended_action_required"
        and not expected.get("require_pend_resolution")
    )


def actual_p2p_branch(exported: dict[str, Any], case_id: str) -> bool:
    if any(
        row.get("case_id") == case_id
        for table in (
            "payer_peer_to_peer_requests",
            "payer_p2p_session_records",
            "payer_p2p_relay_evidence",
            "payer_p2p_external_evidence",
        )
        for row in exported.get(table, [])
    ):
        return True
    return any(
        row.get("case_id") == case_id and row.get("decision") == "p2p_review"
        for row in exported.get("payer_md_case_decisions", [])
    ) or any(
        row.get("case_id") == case_id
        and row.get("action")
        in {
            "request_peer_to_peer",
            "request_p2p",
            "offer_slots",
            "schedule_p2p",
            "record_p2p_outcome",
        }
        for row in exported.get("audit_logs", [])
    )


def pending_evidence_stage(exported: dict[str, Any], case_id: str) -> str | None:
    """Identify a real pending episode from linked communication and event evidence.

    This proves workflow provenance only. The mandatory semantic rubric still
    decides whether the claimed missing information is supported by the packet.
    """
    case = exported.get("target_case") or {}
    intake_id = case.get("payer_intake_case_id")
    if case.get("id") != case_id or case.get("status") != "pended_action_required":
        return None
    if not any(
        r.get("id") == intake_id and r.get("case_id") == case_id
        for r in exported.get("intake_cases", [])
    ):
        return None
    if any(
        r.get("case_id") == case_id and not r.get("superseded_by")
        for r in exported.get("payer_determinations", [])
    ):
        return None
    messages = {
        r.get("id")
        for r in exported.get("messages", [])
        if r.get("case_id") == case_id and r.get("kind") == "pend_request" and r.get("body")
    }
    letters = {
        r.get("id")
        for r in exported.get("payer_letter_requests", [])
        if r.get("case_id") == case_id and r.get("letter_type") == "pend" and r.get("rationale")
    }
    traces = [
        r
        for r in exported.get("stage_traces", [])
        if r.get("case_id") == case_id
        and r.get("stage") == "outbound_communication"
        and (r.get("details") or {}).get("message_id") in messages
        and (r.get("details") or {}).get("letter_request_id") in letters
    ]
    audits = [
        r
        for r in exported.get("audit_logs", [])
        if r.get("case_id") == case_id
        and r.get("action") == "request_missing_information"
        and (r.get("details") or {}).get("missing_items")
    ]
    transitions = [
        r
        for r in exported.get("state_transitions", [])
        if r.get("case_id") == case_id and r.get("to_status") == "pended_action_required"
    ]
    if not traces or not audits or not transitions:
        return None
    submitted_times = [
        str(r.get("submitted_at") or "")
        for r in exported.get("submission_packets", [])
        if r.get("case_id") == case_id
    ]
    event_times = [
        str(r.get("created_at") or r.get("timestamp") or r.get("at") or "")
        for r in [traces[-1], audits[-1], transitions[-1]]
    ]
    if not submitted_times or not all(event_times) or min(event_times) < max(submitted_times):
        return None
    md = [
        r
        for r in exported.get("payer_md_case_decisions", [])
        if r.get("case_id") == case_id and not r.get("superseded_by")
    ]
    nurses = [
        r
        for r in exported.get("payer_nurse_case_recommendations", [])
        if r.get("case_id") == case_id and not r.get("superseded_by")
    ]
    if md:
        return "md_review" if md[-1].get("decision") == "request_info" else None
    if nurses:
        return (
            "nurse_review"
            if nurses[-1].get("recommendation") == "request_info"
            and nurses[-1].get("intake_case_id") == intake_id
            else None
        )
    return "intake"


def lawful_review_skip_reason(
    exported: dict[str, Any], case_id: str, stage: str = "nurse_review"
) -> str | None:
    """Require a policy-authorized fast-track route and its real approval chain.

    ``e2e_policy_route`` is derived by the trusted server from source policy.
    A routing override, an absent review, or an unrelated approval is insufficient.
    """
    if e2e_protocol(exported) != WORKFLOW_PROTOCOL:
        return None
    actual_tables = (
        ("payer_md_reviews", "payer_md_case_decisions")
        if stage == "md_review"
        else ("payer_nurse_reviews", "payer_nurse_case_recommendations")
    )
    if any(
        row.get("case_id") == case_id for table in actual_tables for row in exported.get(table, [])
    ):
        return None  # A route cannot hide defects in review work actually performed.
    reviewer_role = "physician_reviewer" if stage == "md_review" else "um_nurse"
    if any(
        row.get("case_id") == case_id
        and row.get("required_role") == reviewer_role
        and row.get("status") not in {"cancelled", "canceled"}
        for row in exported.get("payer_review_tasks", [])
    ):
        return None
    pending_stage = pending_evidence_stage(exported, case_id)
    if pending_stage == "intake" or (pending_stage == "nurse_review" and stage == "md_review"):
        return f"Linked {pending_stage} missing-information episode precedes {stage}; actual-packet policy rubric remains required."
    case = exported.get("target_case") or {}
    if case.get("id") != case_id:
        return None
    intake_id = case.get("payer_intake_case_id")
    for determination in exported.get("payer_determinations", []):
        if determination.get("case_id") != case_id or determination.get("superseded_by"):
            continue
        if (
            stage == "md_review"
            and case.get("status") == "approved"
            and determination.get("source") == "nurse_recommendation"
            and determination.get("final_decision") == "approved"
            and determination.get("intake_case_id") == intake_id
            and not determination.get("overridden")
            and case.get("authorization_number")
        ):
            approved_recommendation = any(
                r.get("case_id") == case_id
                and r.get("intake_case_id") == intake_id
                and r.get("id") == determination.get("source_record_id")
                and r.get("recommendation") == "approve"
                for r in exported.get("payer_nurse_case_recommendations", [])
            )
            completed_intake = any(
                r.get("case_id") == case_id
                and r.get("id") == intake_id
                and r.get("status") == "complete"
                and r.get("decision_member_eligible") is True
                for r in exported.get("intake_cases", [])
            )
            finalized = any(
                r.get("case_id") == case_id
                and r.get("action") == "finalize"
                and r.get("app") == "payer_determination"
                for r in exported.get("audit_logs", [])
            )
            if approved_recommendation and completed_intake and finalized:
                return "Linked nurse-origin approval and completed eligible intake precede MD review; actual-packet policy rubric remains required."
        if (
            determination.get("source") == "intake_eligibility"
            and determination.get("final_decision") == "denied"
            and case.get("status") == "denied"
        ):
            source = exported.get("e2e_source_eligibility") or {}
            source_intake = next(
                (
                    r
                    for r in exported.get("intake_cases", [])
                    if r.get("id") == intake_id
                    and r.get("case_id") == case_id
                    and r.get("status") == "complete"
                    and r.get("decision_member_eligible") is False
                ),
                None,
            )
            has_notice = any(
                r.get("case_id") == case_id and r.get("letter_type") == "denial"
                for r in exported.get("payer_letter_requests", []) + exported.get("letters", [])
            )
            has_audit = any(
                r.get("case_id") == case_id
                and r.get("action") == "finalize"
                and r.get("app") == "payer_determination"
                for r in exported.get("audit_logs", [])
            )
            has_transition = any(
                r.get("case_id") == case_id and r.get("to_status") == "denied"
                for r in exported.get("state_transitions", [])
            )
            if (
                source.get("case_id") == case_id
                and source.get("member_eligible") is False
                and source_intake
                and determination.get("source_record_id") == intake_id
                and determination.get("intake_case_id") == intake_id
                and has_notice
                and has_audit
                and has_transition
            ):
                return "Source-confirmed ineligibility, linked intake denial, notice and finalization precede clinical review."
    policy_route = exported.get("e2e_policy_route")
    if policy_route not in {"gold_card_lane", "notification_only_lane"}:
        return None
    case = exported.get("target_case") or {}
    if case.get("id") != case_id or case.get("status") != "approved":
        return None
    linked_intake_id = case.get("payer_intake_case_id")
    intakes = {
        row.get("id")
        for row in exported.get("intake_cases", [])
        if row.get("case_id") == case_id
        and row.get("status") == "complete"
        and row.get("decision_member_eligible") is True
    }
    if not linked_intake_id or linked_intake_id not in intakes:
        return None
    routes = {
        row.get("id")
        for row in exported.get("payer_routing_records", [])
        if row.get("case_id") == case_id
        and row.get("intake_case_id") == linked_intake_id
        and row.get("recommended_target") == policy_route
    }
    if not routes:
        return None
    for determination in exported.get("payer_determinations", []):
        if (
            determination.get("case_id") == case_id
            and determination.get("intake_case_id") == linked_intake_id
            and determination.get("source") == "triage_auto_approve"
            and determination.get("source_record_id") in routes
            and determination.get("final_decision") == "approved"
            and not determination.get("superseded_by")
            and not determination.get("overridden")
        ):
            return (
                f"Source policy permits {policy_route}; linked intake, routing and approval exist."
            )
    return None
