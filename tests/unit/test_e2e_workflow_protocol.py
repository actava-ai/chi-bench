"""Protocol controls use synthetic state; no task gold or model calls are changed."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from chi_bench.core.agent_path import compute_agent_path
from chi_bench.experiment.agents.dual_pa_e2e_harness import DualPaE2EHarness, _phase_instruction
from chi_bench.experiment.config import ExperimentConfig
from chi_bench.experiment.runner import _build_child_env
from chi_bench.verifier.judge.judge import should_run_workspace_judge
from chi_bench.verifier.judge.pa_um_adapter import PaUmJudgeAdapter
from chi_bench.verifier.stages import collect_stage_checks
from chi_bench.verifier.stages.e2e_consistency import E2EConsistencyVerifier


@pytest.fixture
def expectations():
    return {
        "task_kind": "provider_to_payer_e2e",
        "verifier_contract": "contract_v3",
        "target_case_id": "C",
        "expected_provider_action": "do_not_submit",
        "expected_target_status": "approved",
        "included_stages": [
            "new_referral",
            "provider_pre_submission",
            "e2e_consistency",
            "nurse_review",
            "md_review",
            "outcome",
        ],
        "expected_provider_pre_submission": {
            "final_action": "do_not_submit",
            "packet_must_be_absent": True,
        },
        "expected_service_request": {"acceptable_procedure_codes": ["123"]},
        "expected_e2e": {"final_decision": "approved"},
        "semantic_judge_rubric": {
            "nurse_review": [{"rubric_id": "nurse.custom", "prompt": "Review nurse evidence"}],
            "md_review": [{"rubric_id": "md.custom", "prompt": "Review MD evidence"}],
            "provider_request_package": [
                {"rubric_id": "provider.quality", "prompt": "Request fidelity"}
            ],
        },
    }


@pytest.fixture
def state():
    return {
        "task_kind": "provider_to_payer_e2e",
        "e2e_protocol": "workflow_v2",
        "target_case_id": "C",
        "target_case": {
            "id": "C",
            "patient_id": "P",
            "service_request_id": "S",
            "status": "submitted",
            "payer_intake_case_id": "I",
        },
        "cases": [{"id": "C", "patient_id": "P", "service_request_id": "S", "status": "submitted"}],
        "service_requests": [{"id": "S", "patient_id": "P", "procedure_code": "123"}],
        "submission_packets": [{"id": "PK", "case_id": "C", "submitted_at": "2026-01-01T00:00:00"}],
        "provider_determinations": [{"case_id": "C", "final_action": "do_not_submit"}],
        "audit_logs": [{"case_id": "C", "action": "submit_authorization"}],
        "intake_cases": [
            {"id": "I", "case_id": "C", "status": "complete", "decision_member_eligible": True}
        ],
    }


@pytest.mark.parametrize("action", [None, "do_not_submit", "gather_more_evidence", "submit_pa"])
def test_current_target_packet_overrides_standalone_disposition(state, action):
    state["provider_determinations"] = (
        [] if action is None else [{"case_id": "C", "final_action": action}]
    )
    assert compute_agent_path(state) == "submit"


def test_unrelated_packet_does_not_trigger_target_payer_path(state):
    state["submission_packets"][0]["case_id"] = "OTHER"
    assert compute_agent_path(state) == "no_submit"


def test_workflow_waives_standalone_decision_but_requires_handoff(expectations, state):
    original = deepcopy(expectations)
    result = E2EConsistencyVerifier(state, expectations, []).verify()
    assert result.checks["e2e.provider_judgment_path"] == "not_applicable"
    assert "workflow_v2" in result.details["e2e.provider_judgment_path"]["message"]
    assert result.checks["e2e.provider_submission_exists"] is True
    state["submission_packets"] = []
    result = E2EConsistencyVerifier(state, expectations, []).verify()
    assert result.checks["e2e.provider_submission_exists"] is False
    assert not result.passed
    assert should_run_workspace_judge(expectations, state)
    assert expectations == original


def test_workflow_removes_only_standalone_provider_gold_axes(expectations, state):
    checks, stages = collect_stage_checks(state, expectations)
    assert checks["new_referral.case_status"] == "not_applicable"
    assert checks["new_referral.procedure_code"] is True
    assert checks["provider_pre_submission.final_action"] == "not_applicable"
    assert checks["provider_pre_submission.packet_absent"] == "not_applicable"
    assert checks["cross.closed_backed_by_provider_determination"] == "not_applicable"
    assert checks["outcome.target_status"] == "not_applicable"
    state["service_requests"][0]["procedure_code"] = "WRONG"
    checks, _ = collect_stage_checks(state, expectations)
    assert checks["new_referral.procedure_code"] is False
    assert all(
        s.details.get("not_applicable_reasons")
        for s in stages
        if s.stage in {"new_referral", "provider_pre_submission"}
    )


def fast_track(state):
    state["target_case"]["status"] = "approved"
    state["e2e_policy_route"] = "gold_card_lane"
    state["payer_routing_records"] = [
        {"id": "R", "case_id": "C", "intake_case_id": "I", "recommended_target": "gold_card_lane"}
    ]
    state["payer_determinations"] = [
        {
            "id": "D",
            "case_id": "C",
            "intake_case_id": "I",
            "source": "triage_auto_approve",
            "source_record_id": "R",
            "final_decision": "approved",
            "overridden": False,
        }
    ]


def test_lawful_fast_track_waives_review_checks_and_only_review_rubrics(
    expectations, state, monkeypatch
):
    fast_track(state)
    checks, stages = collect_stage_checks(state, expectations)
    assert checks["nurse.reviews_exist"] == checks["md.decision_exists"] == "not_applicable"
    assert next(s for s in stages if s.stage == "nurse_review").details["not_applicable_reason"]
    monkeypatch.setattr("chi_bench.verifier.judge.pa_um_adapter._find_bundle", lambda _: None)
    adapter = PaUmJudgeAdapter(expectations, state)
    judge_input = adapter.build()
    assert {r["rubric_id"] for r in judge_input.rubrics} == {
        "provider.quality",
        "e2e.provider_request_source_fidelity",
        "e2e.payer_actual_packet_policy",
    }
    assert set(adapter.not_applicable_rubrics) == {"nurse.custom", "md.custom"}


@pytest.mark.parametrize(
    "invalid",
    ["no_policy", "wrong_policy", "no_route", "wrong_source", "ineligible", "different_case"],
)
def test_missing_or_invalid_route_never_waives_review(expectations, state, invalid):
    fast_track(state)
    if invalid == "no_policy":
        state.pop("e2e_policy_route")
    elif invalid == "wrong_policy":
        state["e2e_policy_route"] = "standard_um"
    elif invalid == "no_route":
        state["payer_routing_records"] = []
    elif invalid == "wrong_source":
        state["payer_determinations"][0]["source_record_id"] = "OTHER"
    elif invalid == "ineligible":
        state["intake_cases"][0]["decision_member_eligible"] = False
    elif invalid == "different_case":
        state["payer_routing_records"][0]["case_id"] = "OTHER"
    checks, _ = collect_stage_checks(state, expectations)
    assert checks["nurse.reviews_exist"] is False
    assert checks["md.decision_exists"] is False


def test_pending_episode_is_status_not_final_determination(expectations, state):
    expectations["expected_target_status"] = "pended_action_required"
    expectations["expected_e2e"] = {
        "final_decision": "pended_action_required",
        "require_pend_resolution": False,
    }
    state["target_case"]["status"] = "pended_action_required"
    result = E2EConsistencyVerifier(state, expectations, []).verify()
    assert result.checks["e2e.final_decision_matches"] == "not_applicable"
    assert result.checks["e2e.episode_status_matches"] == "not_applicable"
    assert result.checks["e2e.determination_linked_to_intake"] == "not_applicable"
    assert result.checks["e2e.pend_provider_responded"] == "not_applicable"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", [None, "do_not_submit", "gather_more_evidence"])
async def test_harness_runs_payer_for_real_packet_even_without_submit_disposition(state, action):
    state["provider_determinations"] = (
        [] if action is None else [{"case_id": "C", "final_action": action}]
    )
    harness = object.__new__(DualPaE2EHarness)
    harness._resolved_flags = {"max_cycles": 2}
    harness.provider_model = harness.payer_model = "synthetic"
    harness._export_state = AsyncMock(return_value=state)
    harness._write_early_exit_marker = AsyncMock()
    harness._verify_no_new_p2p_bypass = lambda **kwargs: None

    async def phase(**kwargs):
        state["target_case"]["status"] = "approved"

    harness._run_role_phase = AsyncMock(side_effect=phase)
    await harness._run_state_machine(
        instruction="Original task",
        environment=SimpleNamespace(),
        provider_mcp_url="http://localhost:8020/mcp",
        payer_mcp_url="http://localhost:8100/mcp",
    )
    assert [c.kwargs["role"] for c in harness._run_role_phase.await_args_list] == ["payer"]


@pytest.mark.asyncio
async def test_harness_stops_at_authored_pending_episode(state):
    state["e2e_episode_target_status"] = "pended_action_required"
    state["target_case"]["status"] = "pended_action_required"
    harness = object.__new__(DualPaE2EHarness)
    harness._resolved_flags = {"max_cycles": 1}
    harness._export_state = AsyncMock(return_value=state)
    harness._run_role_phase = AsyncMock()
    harness._write_early_exit_marker = AsyncMock()
    await harness._run_state_machine(
        instruction="Original task",
        environment=SimpleNamespace(),
        provider_mcp_url="http://localhost:8020/mcp",
        payer_mcp_url="http://localhost:8100/mcp",
    )
    harness._run_role_phase.assert_not_awaited()


def test_workflow_provider_prompt_overrides_standalone_no_submit_instructions(state):
    prompt = _phase_instruction("provider", "provider_submit", "Decide whether to submit.", state)
    assert "workflow_v2" in prompt
    assert "mandatory" in prompt.lower()
    assert "does not depend" in prompt.lower()


def test_config_selects_trusted_protocol_and_rejects_unknown():
    cfg = ExperimentConfig(dataset="synthetic", e2e_protocol="workflow_v2")
    assert _build_child_env(cfg)["CHI_BENCH_E2E_PROTOCOL"] == "workflow_v2"
    with pytest.raises(ValueError):
        ExperimentConfig(dataset="synthetic", e2e_protocol="typo")


def test_resolved_dynamic_target_cannot_be_overridden_by_unrelated_disposition_packet(state):
    state["target_case_id"] = None
    state["submission_packets"] = [{"id": "OTHER-PK", "case_id": "OTHER"}]
    state["provider_determinations"] = [{"case_id": "OTHER", "final_action": "submit_pa"}]
    assert compute_agent_path(state) == "no_decision"


def test_scorecard_protocol_comes_from_export_not_current_process(expectations, state, monkeypatch):
    from chi_bench.verifier import task_runtime

    monkeypatch.setenv("CHI_BENCH_E2E_PROTOCOL", "dual_viewpoint_v1")
    monkeypatch.setattr(
        task_runtime, "collect_all_verifier_checks", lambda *a, **kw: ({"synthetic": True}, [], {})
    )
    assert (
        task_runtime.verify_task(exported=state, expectations=expectations).scorecard[
            "e2e_protocol"
        ]
        == "workflow_v2"
    )
    state.pop("e2e_protocol")
    monkeypatch.setenv("CHI_BENCH_E2E_PROTOCOL", "workflow_v2")
    with pytest.raises(ValueError, match="explicit workflow_v2"):
        task_runtime.verify_task(exported=state, expectations=expectations)


def test_invalid_trusted_protocol_rejected_at_context_startup(tmp_path, monkeypatch):
    from chi_bench.core.context import ServiceContext

    monkeypatch.setenv("CHI_BENCH_E2E_PROTOCOL", "typo")
    with pytest.raises(ValueError, match="CHI_BENCH_E2E_PROTOCOL"):
        ServiceContext(tmp_path)


def test_protocol_round_trip_and_backend_forwarding(tmp_path, monkeypatch):
    from chi_bench.experiment.docker_env import FORWARDED_ENV_KEYS, build_docker_run_argv
    from chi_bench.experiment.modal_env import _collect_forwarded_env

    path = tmp_path / "experiment.yaml"
    path.write_text("dataset: synthetic\ne2e_protocol: workflow_v2\nagent: dual-pa-e2e\n")
    cfg = ExperimentConfig.from_yaml(path)
    assert cfg.e2e_protocol == "workflow_v2"
    env = _build_child_env(cfg)
    assert "CHI_BENCH_E2E_PROTOCOL" in FORWARDED_ENV_KEYS
    cmd = build_docker_run_argv(
        image="synthetic",
        container_name="synthetic",
        task_id="synthetic",
        host_env=env,
        allow_internet=False,
    )
    assert "CHI_BENCH_E2E_PROTOCOL=workflow_v2" in cmd
    monkeypatch.setenv("CHI_BENCH_E2E_PROTOCOL", env["CHI_BENCH_E2E_PROTOCOL"])
    assert _collect_forwarded_env()["CHI_BENCH_E2E_PROTOCOL"] == "workflow_v2"


def test_published_stage_shape_gets_request_fidelity_and_semantic_review(
    expectations, state, monkeypatch
):
    expectations["included_stages"] = [
        "e2e_consistency",
        "nurse_review",
        "md_review",
        "p2p",
        "outcome",
    ]
    expectations.pop("semantic_judge_rubric")
    state["service_requests"][0]["procedure_code"] = "WRONG"
    checks, _ = collect_stage_checks(state, expectations)
    assert checks["new_referral.procedure_code"] is False
    fast_track(state)
    monkeypatch.setattr("chi_bench.verifier.judge.pa_um_adapter._find_bundle", lambda _: None)
    item = PaUmJudgeAdapter(expectations, state).build()
    assert "e2e.provider_request_source_fidelity" in {r["rubric_id"] for r in item.rubrics}
    assert item.contract == "e2e_workflow_v2"
    rubric = next(
        r for r in item.rubrics if r["rubric_id"] == "e2e.provider_request_source_fidelity"
    )
    assert "approval likelihood" in rubric["prompt"]
    assert item.agent_outputs["provider_submission"]["submission_packets"]


def test_workflow_judge_keeps_actual_packet_and_provider_chart_contexts_separate(
    expectations, state, monkeypatch
):
    from chi_bench.verifier.judge.pa_um_adapter import _build_extra_workspace_files

    world = {
        "documents": [
            {"id": "ORIGINAL", "patient_id": "P", "case_id": "C", "content": "original chart fact"}
        ]
    }
    monkeypatch.setattr(
        "chi_bench.verifier.judge.pa_um_adapter._load_shared_world_payload", lambda _: world
    )
    state["target_documents"] = [
        {"id": "SUBMITTED", "patient_id": "P", "case_id": "C", "content": "actual submitted fact"},
        {"id": "PRIVATE", "patient_id": "P", "case_id": "C", "content": "unsubmitted fact"},
    ]
    state["submission_packets"][0]["attached_document_ids"] = ["SUBMITTED"]
    files = _build_extra_workspace_files(expectations, state, "C")
    submitted = [v for k, v in files.items() if k.startswith("source_context/submitted_documents/")]
    assert any("actual submitted fact" in str(v) for v in submitted)
    assert not any(
        "original chart fact" in str(v) or "unsubmitted fact" in str(v) for v in submitted
    )
    provider = [v for k, v in files.items() if k.startswith("provider_source_context/")]
    assert any("original chart fact" in str(v) for v in provider)


def pend(state, *, stage="intake"):
    state["target_case"]["status"] = "pended_action_required"
    state["messages"] = [
        {"id": "M", "case_id": "C", "kind": "pend_request", "body": "Missing chart evidence"}
    ]
    state["payer_letter_requests"] = [
        {"id": "L", "case_id": "C", "letter_type": "pend", "rationale": "Missing chart evidence"}
    ]
    state["stage_traces"] = [
        {
            "case_id": "C",
            "stage": "outbound_communication",
            "outcome": "pend_requested",
            "details": {"message_id": "M", "letter_request_id": "L"},
            "created_at": "2026-01-01T00:01:00",
        }
    ]
    state["state_transitions"] = [
        {
            "case_id": "C",
            "to_status": "pended_action_required",
            "from_status": "submitted",
            "created_at": "2026-01-01T00:01:00",
        }
    ]
    state["audit_logs"].append(
        {
            "case_id": "C",
            "action": "request_missing_information",
            "details": {"missing_items": ["chart evidence"]},
            "created_at": "2026-01-01T00:01:00",
        }
    )
    if stage == "nurse_review":
        state["payer_nurse_case_recommendations"] = [
            {
                "id": "N",
                "case_id": "C",
                "intake_case_id": "I",
                "recommendation": "request_info",
                "clinical_notes": "Missing chart evidence",
            }
        ]
        state["audit_logs"].append({"case_id": "C", "action": "submit_case_recommendation"})


def test_approved_source_can_correctly_pend_actual_incomplete_packet(expectations, state):
    pend(state)
    checks, stages = collect_stage_checks(state, expectations)
    assert checks["e2e.final_decision_matches"] == "not_applicable"
    assert checks["outcome.target_status"] == "not_applicable"
    assert checks["e2e.downstream_handling_complete"] is True
    assert checks["nurse.reviews_exist"] == checks["md.decision_exists"] == "not_applicable"
    assert (
        next(s for s in stages if s.stage == "e2e_consistency").details[
            "source_outcome_observation"
        ]["expected"]
        == "approved"
    )
    item = PaUmJudgeAdapter(expectations, state).build()
    assert "e2e.payer_actual_packet_policy" in {r["rubric_id"] for r in item.rubrics}


@pytest.mark.parametrize(
    "missing",
    ["messages", "payer_letter_requests", "stage_traces", "audit_logs", "state_transitions"],
)
def test_pending_without_provenance_never_waives_review_or_completes(expectations, state, missing):
    pend(state)
    state[missing] = []
    checks, _ = collect_stage_checks(state, expectations)
    assert checks["e2e.downstream_handling_complete"] is False
    assert checks["nurse.reviews_exist"] is False
    assert checks["md.decision_exists"] is False


def test_nurse_pend_waives_only_downstream_md(expectations, state):
    pend(state, stage="nurse_review")
    checks, _ = collect_stage_checks(state, expectations)
    assert checks["nurse.reviews_exist"] is False  # a case recommendation is not a line review
    assert checks["md.decision_exists"] == "not_applicable"


def test_source_gold_comparisons_are_audit_only_but_actual_review_mandatory(expectations, state):
    checks, _ = collect_stage_checks(state, expectations)
    assert checks["e2e.final_decision_matches"] == "not_applicable"
    assert checks["outcome.target_status"] == "not_applicable"
    assert checks["nurse.reviews_exist"] is False
    assert checks["md.decision_exists"] is False
    assert checks["e2e.downstream_handling_complete"] is False


def test_lawful_early_pend_waives_unreached_source_p2p_but_real_request_reactivates(
    expectations, state
):
    expectations["expected_e2e"]["require_p2p_resolution"] = True
    expectations["expected_e2e"]["require_pend_resolution"] = True
    pend(state)
    checks, _ = collect_stage_checks(state, expectations)
    assert checks["e2e.p2p_completed"] == "not_applicable"
    assert checks["e2e.pend_provider_responded"] == "not_applicable"
    state["payer_peer_to_peer_requests"] = [{"id": "P2P", "case_id": "C", "status": "requested"}]
    checks, _ = collect_stage_checks(state, expectations)
    assert checks["e2e.p2p_completed"] is False


def test_source_world_cannot_replace_actual_payer_handoff_metadata(
    expectations, state, monkeypatch
):
    from chi_bench.verifier.judge.pa_um_adapter import _build_extra_workspace_files

    conflicting_world = {
        "cases": [{"id": "C", "service_request_id": "S", "status": "approved"}],
        "service_requests": [{"id": "S", "patient_id": "P", "procedure_code": "WORLD-WRONG"}],
        "submission_packets": [{"id": "WORLD-PACKET", "case_id": "C"}],
        "lines": [{"case_id": "C", "description": "WORLD-WRONG"}],
    }
    monkeypatch.setattr(
        "chi_bench.verifier.judge.pa_um_adapter._load_shared_world_payload",
        lambda _: conflicting_world,
    )
    files = _build_extra_workspace_files(expectations, state, "C")
    context = files["source_context/case_context.json"]
    assert context["case"]["status"] == "submitted"
    assert [r["id"] for r in context["submission_packets"]] == ["PK"]
    assert context["service_requests"][0]["procedure_code"] == "123"
    assert "WORLD-WRONG" not in str(context)


def test_fast_track_does_not_hide_reviews_that_were_actually_performed(expectations, state):
    fast_track(state)
    state["payer_nurse_case_recommendations"] = [{"case_id": "C", "recommendation": "deny"}]
    state["payer_md_case_decisions"] = [{"case_id": "C", "decision": "deny", "signed_off": False}]
    checks, _ = collect_stage_checks(state, expectations)
    assert checks["nurse.no_unauthorized_denial"] is False
    assert checks["nurse.audit"] is False
    assert checks["md.signed_off"] is False
    assert checks["md.audit"] is False


def test_workflow_policy_fallback_uses_handbook_and_keeps_duplicate_basenames(
    expectations, state, tmp_path, monkeypatch
):
    from chi_bench.verifier.judge.workspace_judge import WorkspaceJudge

    monkeypatch.setattr(
        "chi_bench.verifier.judge.pa_um_adapter._policy_paths_for_scenario", lambda _: ()
    )
    handbook = tmp_path / "skills/managed-care-operations-handbook/references"
    for folder in (
        "medical-library/medical-policies",
        "medical-library/clinical-guidelines",
        "payer-um/operational",
    ):
        target = handbook / folder / "same.md"
        target.parent.mkdir(parents=True)
        target.write_text(folder)
    monkeypatch.setenv("CHI_BENCH_WORLDS_DIR", str(tmp_path / "prior_auth_e2e/worlds"))
    item = PaUmJudgeAdapter(expectations, state).build()
    assert len(item.policy_paths) == 3
    workspace = tmp_path / "judge"
    workspace.mkdir()
    WorkspaceJudge(runner=SimpleNamespace())._populate_workspace(item, workspace)
    copied = list((workspace / "policies").rglob("*.md"))
    assert len(copied) == 3
    assert {p.read_text() for p in copied} == {
        "medical-library/medical-policies",
        "medical-library/clinical-guidelines",
        "payer-um/operational",
    }


def test_missing_governing_policies_marks_required_payer_rubric_unavailable(
    expectations, state, monkeypatch
):
    monkeypatch.setattr(
        "chi_bench.verifier.judge.pa_um_adapter._policy_paths_for_scenario", lambda _: ()
    )
    # Test a hermetic unavailable corpus rather than relying on host data.
    monkeypatch.setattr(
        "chi_bench.verifier.judge.pa_um_adapter._workflow_policy_paths", lambda _: ()
    )
    adapter = PaUmJudgeAdapter(expectations, state)
    adapter.build()
    assert "e2e.payer_actual_packet_policy" in adapter.unavailable_rubrics


def test_normal_runner_cli_selects_protocol_without_touching_dataset(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from chi_bench.cli import app

    seen = []
    monkeypatch.setattr(
        "chi_bench.experiment.runner.run_experiment", lambda **kwargs: seen.append(kwargs)
    )
    result = CliRunner().invoke(
        app,
        [
            "experiment",
            "run",
            "--dataset",
            str(tmp_path),
            "--agent",
            "dual-pa-e2e",
            "--e2e-protocol",
            "workflow_v2",
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen[0]["e2e_protocol"] == "workflow_v2"
    assert list(tmp_path.iterdir()) == []


def test_missing_policy_cannot_become_valid_by_synthetic_judge_pass(
    expectations, state, monkeypatch
):
    import json
    from chi_bench.verifier import task_runtime

    monkeypatch.setattr(
        "chi_bench.verifier.judge.pa_um_adapter._workflow_policy_paths", lambda _: ()
    )
    monkeypatch.setenv("CHI_BENCH_JUDGE_NUM_VOTES", "1")

    class Runner:
        def run_session(self, *args, cwd, **kwargs):
            rubrics = json.loads((cwd / "rubrics.json").read_text())["rubrics"]
            (cwd / "verdicts.json").write_text(
                json.dumps(
                    {
                        "rubric_verdicts": {
                            r["rubric_id"]: {
                                "pass": True,
                                "explanation": "synthetic",
                                "evidence_refs": [],
                            }
                            for r in rubrics
                        }
                    }
                )
            )

    result = task_runtime.verify_task(exported=state, expectations=expectations, judge=Runner())
    assert result.scorecard["scoring_status"] == "invalid"
    assert "judge.e2e.payer_actual_packet_policy" in result.scorecard["invalid_checks"]


def test_lawful_route_cannot_hide_a_reached_review_task(expectations, state):
    fast_track(state)
    state["payer_review_tasks"] = [
        {"case_id": "C", "required_role": "physician_reviewer", "status": "claimed"}
    ]
    checks, _ = collect_stage_checks(state, expectations)
    assert checks["md.decision_exists"] is False


def test_workflow_dynamic_target_ambiguity_does_not_pick_latest_packet(expectations):
    from chi_bench.verifier.stages._provider_new_referral_targets import resolved_target_case_id

    expectations = {**expectations, "target_case_id": None, "target_patient_id": "P"}
    exported = {
        "e2e_protocol": "workflow_v2",
        "target_case": None,
        "cases": [
            {"id": "C1", "patient_id": "P", "service_request_id": "S1"},
            {"id": "C2", "patient_id": "P", "service_request_id": "S2"},
        ],
        "service_requests": [{"id": "S1", "patient_id": "P"}, {"id": "S2", "patient_id": "P"}],
        "submission_packets": [{"case_id": "C2"}],
    }
    assert resolved_target_case_id(exported, expectations) == ""


def test_p2p_source_outcome_alias_is_audit_only(expectations, state):
    expectations["expected_payer_artifacts"] = [
        {"artifact_type": "p2p_resolution", "expected_fields": {"outcome": "uphold"}}
    ]
    state["payer_peer_to_peer_requests"] = [
        {"case_id": "C", "outcome": "overturn", "status": "completed"}
    ]
    checks, stages = collect_stage_checks(state, expectations)
    assert checks["outcome.p2p_outcome_matches"] == "not_applicable"
    outcome = next(s for s in stages if s.stage == "outcome")
    assert (
        outcome.details["source_comparison_observations"]["outcome.p2p_outcome_matches"]["actual"]
        == "overturn"
    )


def test_source_p2p_and_pend_requirements_do_not_activate_absent_actual_branches(
    expectations, state
):
    expectations["expected_e2e"].update(require_p2p_resolution=True, require_pend_resolution=True)
    checks, _ = collect_stage_checks(state, expectations)
    assert checks["e2e.p2p_completed"] == "not_applicable"
    assert checks["e2e.pend_provider_responded"] == "not_applicable"
    state["payer_md_case_decisions"] = [{"case_id": "C", "decision": "p2p_review"}]
    checks, _ = collect_stage_checks(state, expectations)
    assert checks["e2e.p2p_completed"] is False


@pytest.mark.parametrize("included", [[], ["e2e_consistency"]])
def test_workflow_owns_mandatory_checks_even_with_legacy_contract_scope(
    expectations, state, included, monkeypatch
):
    from chi_bench.verifier.task_runtime import collect_all_verifier_checks

    expectations["verifier_contract"] = "contract_e2e_v1"
    expectations["included_stages"] = included
    monkeypatch.setattr(
        "chi_bench.verifier.judge.workspace_judge.WorkspaceJudge.judge",
        lambda self, judge_input, **kw: SimpleNamespace(
            verdicts={},
            degraded_rubric_ids=tuple(r["rubric_id"] for r in judge_input.rubrics),
            session_metadata={},
            judge_unavailable_reason="synthetic unavailable",
        ),
    )
    checks, _, _ = collect_all_verifier_checks(state, expectations)
    assert "e2e.provider_submission_exists" in checks
    assert checks["judge.e2e.provider_request_source_fidelity"] == "unavailable"
    assert checks["judge.e2e.payer_actual_packet_policy"] == "unavailable"


def test_workflow_unresolved_target_never_falls_back_to_an_unrelated_submission():
    from chi_bench.core.agent_path import latest_provider_determination
    from chi_bench.experiment.agents.dual_pa_e2e_state import (
        has_provider_submission,
        target_case_id,
    )

    exported = {
        "task_kind": "provider_to_payer_e2e",
        "e2e_protocol": "workflow_v2",
        "target_case_id": None,
        "target_case": None,
        "cases": [{"id": "OTHER-A"}, {"id": "OTHER-B"}],
        "submission_packets": [{"case_id": "OTHER-B"}],
        "provider_determinations": [{"case_id": "OTHER-B", "final_action": "submit_pa"}],
    }
    assert latest_provider_determination(exported) is None
    assert compute_agent_path(exported) == "no_decision"
    assert target_case_id(exported) == ""
    assert not has_provider_submission(exported)
    exported["e2e_protocol"] = "dual_viewpoint_v1"
    with pytest.raises(ValueError, match="workflow_v2"):
        compute_agent_path(exported)
    with pytest.raises(ValueError, match="workflow_v2"):
        target_case_id(exported)
