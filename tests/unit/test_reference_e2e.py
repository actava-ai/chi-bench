"""Executable reference controls exercise services, never paid model boundaries."""

import importlib
import importlib.util
import os
from pathlib import Path

import pytest

from chi_bench.core.context import ServiceContext
from chi_bench.services.service import WorldService


DATA = Path(
    os.environ.get("CHI_BENCH_TEST_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data"))
)
TASKS = sorted((DATA / "prior_auth_e2e/tasks").glob("*/fixtures"))


def test_e2e_reference_entrypoint_exists():
    assert importlib.util.find_spec("chi_bench.verifier.reference_e2e") is not None


@pytest.fixture
def reference_context(tmp_path, monkeypatch):
    monkeypatch.setenv("CHI_BENCH_E2E_PROTOCOL", "workflow_v2")
    monkeypatch.setenv("CHI_BENCH_WORLDS_DIR", str(DATA / "prior_auth_e2e/worlds"))
    monkeypatch.delenv("CHI_BENCH_FHIR_URL", raising=False)

    def render_boundary(self, generator, path, **kwargs):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    monkeypatch.setattr(ServiceContext, "_generate_workspace_pdf", render_boundary)
    contexts = []

    def build(fixtures):
        ctx = ServiceContext.build(tmp_path / str(len(contexts)), fixtures)
        contexts.append(ctx)
        for name in (
            "send_turn",
            "submit_summary",
            "_generate_counterpart_reply",
            "_simulate_provider_slot_response",
        ):
            monkeypatch.setattr(
                ctx.p2p,
                name,
                lambda *a, **kw: pytest.fail("Reference invoked single-role P2P simulator"),
            )
        return ctx

    yield build
    for ctx in contexts:
        ctx.close()


@pytest.mark.skipif(not TASKS, reason="Downloaded E2E source cohort is absent")
@pytest.mark.parametrize("fixtures", TASKS, ids=lambda p: p.parent.name)
def test_all_23_references_use_actual_handoff_and_provenance(fixtures, reference_context):
    run = importlib.import_module("chi_bench.verifier.reference_e2e").run_e2e_reference
    before = {p: p.read_bytes() for p in fixtures.rglob("*") if p.is_file()}
    ctx = reference_context(fixtures)
    original_document_ids = {
        d.id
        for d in ctx.get_documents(patient_id=ctx._expectations.target_patient_id)
        if d.case_id is None and d.content.strip() and d.kind != "submission_bundle"
    }
    original = ctx._expectations
    manifest = ctx._manifest
    source_gt = ctx._e2e_payer_gt
    result = run(ctx)
    assert result["executed"] is True
    assert result["reference_mode"] == "executed_workflow"
    assert result["protocol"] == "workflow_v2"
    assert result["semantic_verification"] == "not_run"
    assert result["control_type"] == "scripted_reference_not_blind_model_run"
    assert ctx._expectations is original
    assert ctx._manifest is manifest
    assert ctx._e2e_payer_gt is source_gt
    exported = WorldService(ctx.runtime_dir, _ctx=ctx).export_state()
    case_id = result["case_id"]
    packets = [r for r in exported["submission_packets"] if r["case_id"] == case_id]
    assert packets
    bundle_id = packets[0]["payload"]["bundle_document_id"]
    bundle = next(d for d in ctx.get_documents(case_id=case_id) if d.id == bundle_id)
    assert original_document_ids <= set(bundle.structured_data["document_ids"])
    assert any(r["stage"] == "e2e_payer_gt_binding" for r in exported["stage_traces"])
    assert exported["intake_cases"]
    assert exported["payer_triage_records"]
    assert exported["payer_routing_records"]
    assert result["target_status"] == ctx.get_case(case_id).status.value
    assert result["target_status"] == original.expected_target_status
    assert result["unresolved_reference_content"] is not None
    from chi_bench.verifier.stages import collect_stage_checks

    checks, _ = collect_stage_checks(exported, original.model_dump(mode="json"))
    for name in (
        "e2e.provider_submission_exists",
        "e2e.intake_linked_to_submission",
        "e2e.payer_gt_binding_audit",
        "e2e.payer_gt_bound_after_submission",
        "e2e.shared_packet_documents_match",
        "e2e.downstream_handling_complete",
    ):
        assert checks[name] is True, (name, checks.get(name))
    if result["target_status"] == "pended_action_required":
        assert not exported["payer_determinations"]
        assert any(r["letter_type"] == "pend" for r in exported["letters"])
    else:
        assert exported["payer_determinations"]
    if original.expected_p2p_workflow:
        requests = [r for r in exported["payer_peer_to_peer_requests"] if r["case_id"] == case_id]
        assert len(requests) == 1 and requests[0]["status"] == "completed"
        assert requests[0]["outcome_source"] == "e2e_relay"
        relay = exported["payer_p2p_relay_evidence"][0]
        assert [t["actor"] for t in relay["turns"]] == ["provider", "payer"]
        assert all("Scripted reference" in t["message"] for t in relay["turns"])
        assert not any(r["transcript"] for r in exported["payer_p2p_session_records"])
    assert all(p.read_bytes() == content for p, content in before.items())


@pytest.mark.skipif(not TASKS, reason="Downloaded E2E source cohort is absent")
def test_provider_plan_failure_restores_live_e2e_metadata(reference_context, monkeypatch):
    module = importlib.import_module("chi_bench.verifier.reference_e2e")
    ctx = reference_context(TASKS[0])
    original = ctx._expectations
    fixtures = ctx.fixtures_dir

    def fail(*args, **kwargs):
        raise ValueError("Synthetic plan failure")

    monkeypatch.setattr("chi_bench.verifier.reference_oracle._provider_plan", fail)
    with pytest.raises(ValueError, match="Synthetic plan failure"):
        module.run_e2e_reference(ctx)
    assert ctx._expectations is original
    assert ctx.fixtures_dir == fixtures
    assert not ctx.list_cases()


@pytest.mark.skipif(not TASKS, reason="Downloaded E2E source cohort is absent")
def test_reference_rejects_legacy_protocol_before_mutation(reference_context):
    run = importlib.import_module("chi_bench.verifier.reference_e2e").run_e2e_reference
    ctx = reference_context(TASKS[0])
    ctx.e2e_protocol = "dual_viewpoint_v1"
    with pytest.raises(Exception, match="workflow_v2"):
        run(ctx)
    assert not ctx.list_cases()


@pytest.mark.skipif(not TASKS, reason="Downloaded E2E source cohort is absent")
def test_flat_baked_layout_resolves_sibling_provider_source(reference_context, tmp_path):
    module = importlib.import_module("chi_bench.verifier.reference_e2e")
    ctx = reference_context(TASKS[0])
    source_id = ctx._expectations.scenario_id[:-4] + "_new_referral_provider"
    source = DATA / "prior_auth_provider/tasks" / source_id / "fixtures"
    flat = tmp_path / "baked-tasks"
    sibling = flat / source_id / "fixtures"
    sibling.parent.mkdir(parents=True)
    sibling.symlink_to(source, target_is_directory=True)
    ctx.fixtures_dir = flat / ctx._expectations.scenario_id / "fixtures"
    assert module._provider_fixtures(ctx) == sibling


@pytest.mark.skipif(len(TASKS) < 2, reason="Downloaded E2E source cohort is absent")
def test_mismatched_provider_source_is_rejected_before_case_mutation(
    reference_context, monkeypatch
):
    module = importlib.import_module("chi_bench.verifier.reference_e2e")
    ctx = reference_context(TASKS[0])
    wrong = (
        DATA
        / "prior_auth_provider/tasks"
        / (TASKS[1].parent.name[:-4] + "_new_referral_provider")
        / "fixtures"
    )
    monkeypatch.setattr(module, "_provider_fixtures", lambda _: wrong)
    original = ctx._expectations
    with pytest.raises(Exception, match="Provider source patient"):
        module.run_e2e_reference(ctx)
    assert ctx._expectations is original
    assert not ctx.list_cases()
