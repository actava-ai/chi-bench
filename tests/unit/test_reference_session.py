"""Marathon references compose task metadata over one retained shared state."""

from hashlib import sha256
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from chi_bench.bootstrap import bootstrap_runtime
from chi_bench.core.context import ServiceContext
from chi_bench.core.scenario import ScenarioDefinition
from chi_bench.services.service import WorldService


def session_context(tmp_path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    ids = ["task-one", "task-two"]
    (fixtures / "session_manifest.json").write_text(
        json.dumps(
            {
                "session_id": "session-test",
                "world_id": "shared-test",
                "domain": "prior_auth_provider",
                "tasks": [{"task_id": task} for task in ids],
            }
        )
    )
    for i, task in enumerate(ids):
        folder = fixtures / "tasks" / task
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text(
            json.dumps(
                {
                    "world_id": "shared-test",
                    "task_id": task,
                    "task_kind": "provider_new_referral",
                    "task_actor": "provider",
                    "target_patient_id": f"PAT-{i}",
                }
            )
        )
        (folder / "expectations.json").write_text(
            json.dumps(
                {
                    "scenario_id": task,
                    "task_kind": "provider_new_referral",
                    "expected_target_status": "submitted",
                    "target_patient_id": f"PAT-{i}",
                }
            )
        )
    ctx = SimpleNamespace(
        fixtures_dir=fixtures,
        _scenario=ScenarioDefinition.model_construct(
            scenario_id="original", task_kind="provider_new_referral"
        ),
        _manifest="original-manifest",
        _expectations=None,
        _is_session=True,
        task_actor="provider",
        payer_mode="agent",
        _cm_loaded=False,
        store={"sentinel": "preserved"},
        ensure_loaded=lambda: None,
    )
    return ctx, ids


def test_session_composes_single_references_without_resetting_shared_store(tmp_path):
    from chi_bench.verifier.reference_session import run_session_reference

    ctx, ids = session_context(tmp_path)
    root = ctx.fixtures_dir
    scenario = ctx._scenario
    shared = ctx.store
    seen = []

    def run_one(current):
        assert current.store is shared
        assert current.store["sentinel"] == "preserved"
        task_id = current._expectations.scenario_id
        if seen:
            assert current.store[seen[0]] == "done"
        seen.append(task_id)
        current.store[task_id] = "done"
        return {"executed": True, "reference_mode": "executed_workflow", "case_id": task_id}

    result = run_session_reference(ctx, run_one=run_one)
    assert result["executed"] is True
    assert result["reference_mode"] == "executed_session"
    assert seen == ids
    assert ctx.fixtures_dir == root
    assert ctx._scenario is scenario
    assert ctx._manifest == "original-manifest"
    assert ctx._expectations is None
    assert ctx._is_session is True
    assert len(result["tasks"]) == 2


def test_session_restores_metadata_when_a_constituent_fails(tmp_path):
    from chi_bench.verifier.reference_session import run_session_reference

    ctx, _ = session_context(tmp_path)
    before = (ctx.fixtures_dir, ctx._scenario, ctx._manifest)

    def fail(_):
        raise RuntimeError("constituent failed")

    with pytest.raises(RuntimeError, match="constituent failed"):
        run_session_reference(ctx, run_one=fail)
    assert (ctx.fixtures_dir, ctx._scenario, ctx._manifest) == before
    assert ctx._expectations is None
    assert ctx._is_session is True


def test_cm_static_session_never_claims_an_executed_workflow(tmp_path):
    from chi_bench.verifier.reference_session import run_session_reference

    ctx, ids = session_context(tmp_path)

    def answer(_):
        return {
            "executed": False,
            "reference_mode": "static_answer",
            "answer": {"final_status": "closed"},
        }

    result = run_session_reference(ctx, run_one=answer)
    assert result["executed"] is False
    assert result["reference_mode"] == "static_answer"
    assert len(result["answer"]["tasks"]) == len(ids)
    assert result["authorship"]["observed"] is False


# Set CHI_BENCH_TEST_DATA_DIR to the privately downloaded dataset root to run
# these controls. Missing downloads skip them; no source fixture is rewritten.
DATA = Path(
    os.environ.get("CHI_BENCH_TEST_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data"))
)


def _fixture_hashes(fixtures):
    return {
        str(path.relative_to(fixtures)): sha256(path.read_bytes()).hexdigest()
        for path in fixtures.rglob("*")
        if path.is_file()
    }


def _write_control_receipt(domain, payload):
    destination = os.environ.get("CHI_BENCH_REFERENCE_CONTROL_LOG_DIR")
    if destination:
        path = Path(destination) / f"marathon-{domain}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n")


@pytest.fixture
def downloaded_marathon(tmp_path, monkeypatch):
    """Normal bootstrap/services, with only PDF rendering and P2P LLM stubs."""
    import anthropic
    from chi_bench.conversation.patient_simulator import PatientSimulator
    from chi_bench.services.p2p import P2PService

    monkeypatch.delenv("CHI_BENCH_FHIR_URL", raising=False)
    for variable in (
        "CHI_BENCH_WORKSPACE_ROOT",
        "CHI_BENCH_RAW_ROOT",
        "CHI_BENCH_PAYER_MODE",
        "CHI_BENCH_TASK_ACTOR",
        "CHI_BENCH_AGENT_OWNED_PAYER_FLOW",
    ):
        monkeypatch.delenv(variable, raising=False)
    boundary_calls = {"pdf_scripted_stub": 0, "p2p_model_scripted_stub": 0}

    def paid_boundary_forbidden(*args, **kwargs):
        pytest.fail("Downloaded Marathon reference attempted a paid model boundary")

    def pdf_stub(self, generator, path, **kwargs):
        # This verifies artifact/service plumbing only, never PDF visual quality.
        boundary_calls["pdf_scripted_stub"] += 1
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    def counterpart_stub(self, **kwargs):
        # Real scheduling, send_turn, transcript persistence and summary services
        # remain active. This reply cannot establish clinical-dialogue adequacy.
        boundary_calls["p2p_model_scripted_stub"] += 1
        return "Scripted model-boundary stub: no new patient evidence is supplied.", None

    monkeypatch.setattr(ServiceContext, "_generate_workspace_pdf", pdf_stub)
    monkeypatch.setattr(P2PService, "_generate_counterpart_reply", counterpart_stub)
    monkeypatch.setattr(PatientSimulator, "generate_response", paid_boundary_forbidden)
    monkeypatch.setattr(anthropic, "Anthropic", paid_boundary_forbidden)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", paid_boundary_forbidden)
    services = []

    def build(domain):
        fixtures = DATA / "marathon" / domain / "fixtures"
        if not (fixtures / "session_manifest.json").is_file():
            pytest.skip(f"Downloaded {domain} Marathon is absent: {fixtures}")
        monkeypatch.setenv("CHI_BENCH_WORLDS_DIR", str(DATA / domain / "shared/worlds"))
        runtime = tmp_path / domain
        before = _fixture_hashes(fixtures)
        bootstrap_runtime(fixtures_dir=fixtures, runtime_dir=runtime)
        service = WorldService(runtime, fixtures)
        services.append(service)
        return service, fixtures, before, boundary_calls

    yield build
    for service in services:
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["prior_auth_provider", "prior_auth_um"])
async def test_downloaded_pa_marathon_runs_normal_services_in_one_world_then_freezes_once(
    downloaded_marathon,
    monkeypatch,
    domain,
):
    from chi_bench.verifier import reference_oracle

    service, fixtures, source_before, boundaries = downloaded_marathon(domain)
    ctx = service._ctx
    ctx.ensure_loaded()
    names = (
        "fixtures_dir",
        "_expectations",
        "_manifest",
        "_scenario",
        "_is_session",
        "task_actor",
        "payer_mode",
    )
    metadata = {name: getattr(ctx, name) for name in names}
    store = ctx.store
    fingerprint = store._world_marker_path.read_bytes()
    manifest = json.loads((fixtures / "session_manifest.json").read_text())
    expected_ids = [entry["task_id"] for entry in manifest["tasks"]]
    assert len(expected_ids) == 25
    seen = []
    retained = {}
    retained_resources = {}
    previous_audits = set()
    run_reference = reference_oracle.run_reference

    def track_constituent(current):
        nonlocal previous_audits
        if (current.fixtures_dir / "session_manifest.json").is_file():
            return run_reference(current)
        assert current.store is store
        assert store._world_marker_path.read_bytes() == fingerprint
        for case_id, status in retained.items():
            assert current.get_case(case_id).status.value == status
        for (side, kind, resource_id), payload in retained_resources.items():
            assert store.get_resource(side, kind, resource_id) == payload
        assert previous_audits <= {entry.id for entry in store.list_audit_logs()}
        result = run_reference(current)
        expected = json.loads((current.fixtures_dir / "expectations.json").read_text())
        assert result["target_status"] == expected["expected_target_status"]
        assert result["semantic_verification"] == "not_run"
        retained[result["case_id"]] = result["target_status"]
        for side, connection in (("provider", store._provider), ("payer", store._payer)):
            for row in connection.execute(
                "SELECT resource_type, resource_id, payload FROM resources"
            ):
                payload = json.loads(row["payload"])
                if payload.get("case_id") == result["case_id"]:
                    retained_resources[(side, row["resource_type"], row["resource_id"])] = payload
        previous_audits = {entry.id for entry in store.list_audit_logs()}
        seen.append(current.fixtures_dir.name)
        return result

    monkeypatch.setattr(reference_oracle, "run_reference", track_constituent)
    events = []

    class LocalTrustedControl:
        async def control_request(self, route, payload):
            assert route == "/_oracle/solve" and payload == {}
            events.append("solve")
            # The normal facade is the same run_oracle entrypoint used by HTTP.
            return service.run_oracle()

        async def begin_verification(self):
            # Exercise the host's freeze interface after all 25 constituents.
            # Container stopping/admission drain is covered by isolated-runtime tests.
            assert len(seen) == 25
            events.append("freeze_interface")

    result = await reference_oracle.run_reference_control(LocalTrustedControl())
    assert result["executed"] is True
    assert result["reference_mode"] == "executed_session"
    assert result["semantic_verification"] == "not_run"
    assert seen == expected_ids
    assert [task["task_id"] for task in result["tasks"]] == expected_ids
    assert events == ["solve", "freeze_interface"]
    assert ctx.store is store
    assert store._world_marker_path.read_bytes() == fingerprint
    for name, value in metadata.items():
        assert getattr(ctx, name) is value
    for case_id, status in retained.items():
        assert ctx.get_case(case_id).status.value == status
    assert _fixture_hashes(fixtures) == source_before
    for (side, kind, resource_id), payload in retained_resources.items():
        assert store.get_resource(side, kind, resource_id) == payload
    assert retained_resources
    _write_control_receipt(
        domain,
        {
            "control_type": "scripted_reference_not_blind_model_run",
            "semantic_verification": "not_run",
            "tasks": result["tasks"],
            "retained_resource_count": len(retained_resources),
            "retained_audit_count": len(previous_audits),
            "boundaries": boundaries,
            "metadata_restored": True,
            "source_hashes_unchanged": True,
            "world_fingerprint_unchanged": True,
            "freeze_interface_calls": 1,
        },
    )
    assert boundaries["pdf_scripted_stub"] > 0
    if domain == "prior_auth_um":
        assert boundaries["p2p_model_scripted_stub"] > 0


@pytest.mark.asyncio
async def test_downloaded_cm_marathon_reads_25_static_answers_without_workflow_or_freeze(
    downloaded_marathon,
    monkeypatch,
):
    from chi_bench.verifier.reference_oracle import run_reference_control

    service, fixtures, source_before, _ = downloaded_marathon("care_management")
    ctx = service._ctx
    metadata = (ctx.fixtures_dir, ctx._scenario, ctx._manifest, ctx._expectations, ctx._is_session)
    # Logical SQLite dumps make every persistent resource/audit mutation visible.
    before = tuple(
        tuple(connection.iterdump())
        for connection in (
            ctx.store._provider,
            ctx.store._payer,
            ctx.store._audit,
        )
    )
    events = []

    class StaticControl:
        async def control_request(self, route, payload):
            events.append(route)
            return service.run_oracle()

        async def begin_verification(self):
            pytest.fail("Static CM answer collection must not freeze or start verification")

    result = await run_reference_control(StaticControl())
    assert result["executed"] is False
    assert result["reference_mode"] == "static_answer"
    assert result["authorship"] == {
        "kind": "authored_ideal_path_collection",
        "observed": False,
        "simulator_run": False,
        "verifier_run": False,
    }
    assert len(result["answer"]["tasks"]) == 25
    expected_ids = [
        entry["task_id"]
        for entry in json.loads((fixtures / "session_manifest.json").read_text())["tasks"]
    ]
    assert [task["task_id"] for task in result["answer"]["tasks"]] == expected_ids
    for task in result["answer"]["tasks"]:
        original = json.loads(
            (fixtures / "tasks" / task["task_id"] / "expectations.json").read_text()
        )
        assert task["answer"]["final_status"] == original["expected_final_status"]
    assert events == ["/_oracle/solve"]
    assert (
        ctx.fixtures_dir,
        ctx._scenario,
        ctx._manifest,
        ctx._expectations,
        ctx._is_session,
    ) == metadata
    assert before == tuple(
        tuple(connection.iterdump())
        for connection in (
            ctx.store._provider,
            ctx.store._payer,
            ctx.store._audit,
        )
    )
    assert _fixture_hashes(fixtures) == source_before

    _write_control_receipt(
        "care_management",
        {
            "control_type": "authored_static_answer_collection",
            "reference_mode": result["reference_mode"],
            "executed": False,
            "task_ids": expected_ids,
            "count": len(expected_ids),
            "persistent_state_unchanged": True,
            "source_hashes_unchanged": True,
            "metadata_restored": True,
            "simulator_run": False,
            "verifier_run": False,
            "freeze_interface_calls": 0,
        },
    )
