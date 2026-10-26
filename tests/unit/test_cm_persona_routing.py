import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from chi_bench.conversation.patient_simulator import PatientSimulator, SimulatorResponse
from chi_bench.core.clock import WorldClock
from chi_bench.core.context import ServiceContext
from chi_bench.core.scenario import TaskManifest


@pytest.fixture
def context(tmp_path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    task_ids = ["cm_first_low_coop", "cm_second_hard_refuses"]
    manifests = []
    for index, task_id in enumerate(task_ids):
        manifest = {
            "world_id": "synthetic-cm-world",
            "task_id": task_id,
            "task_kind": "care_management_full_workflow",
            "task_actor": "care_manager",
            "target_case_id": f"CM-{index}",
            "persona_contract": {
                "persona_id": f"persona-{index}",
                "patient_profile": f"Distinct synthetic patient profile {index}.",
                "consent_willingness": "ready" if index == 0 else "initially_refuses",
                "consent_triggers": [],
            },
        }
        task_dir = fixtures / "tasks" / task_id
        task_dir.mkdir(parents=True)
        (task_dir / "manifest.json").write_text(json.dumps(manifest))
        manifests.append(manifest)
    (fixtures / "session_manifest.json").write_text(
        json.dumps(
            {
                "session_id": "synthetic",
                "world_id": "synthetic-cm-world",
                "domain": "care_management",
                "tasks": [{"task_id": task_id} for task_id in task_ids],
            }
        )
    )
    ctx = ServiceContext.build(tmp_path / "runtime", fixtures)
    ctx._cm_loaded = True
    ctx._is_session = True
    ctx._manifest = TaskManifest.model_validate(manifests[0])
    ctx._clock = WorldClock(datetime(2026, 10, 23, 10))
    for index in range(2):
        ctx.store.save_resource(
            "provider",
            "cm_cases",
            f"CM-{index}",
            {"case_id": f"CM-{index}", "patient_id": f"PAT-{index}", "status": "chart_reviewed"},
        )
    monkeypatch.setattr(
        "chi_bench.conversation.patient_simulator.anthropic.AsyncAnthropic",
        lambda: SimpleNamespace(),
    )
    yield ctx, manifests
    ctx.close()


async def test_marathon_outreach_binds_persona_to_each_case(context, monkeypatch):
    ctx, manifests = context
    prompts = []

    async def response(self, session):
        prompts.append((session.case_id, self._system_prompt))
        return SimulatorResponse("Synthetic patient reply.", False, 0, 0.0)

    monkeypatch.setattr(PatientSimulator, "generate_response", response)
    first = ctx.cm_outreach.start_outreach_call("CM-0")
    second = ctx.cm_outreach.start_outreach_call("CM-1")
    for session in [second, first, second]:
        await ctx.cm_outreach.send_message(session.session_id, "Hello.")
    for case_id, prompt in prompts:
        index = int(case_id[-1])
        assert manifests[index]["persona_contract"]["patient_profile"] in prompt
        assert manifests[1 - index]["persona_contract"]["patient_profile"] not in prompt


def test_case_manifest_does_not_fall_back_to_first_marathon_patient(context):
    ctx, _ = context
    assert ctx.cm_manifest_for_case("CM-UNKNOWN") is None


def test_single_case_persona_property_remains_lazy_and_compatible(context):
    ctx, manifests = context
    ctx._is_session = False
    assert (
        ctx.cm_outreach.persona_contract.patient_profile
        == manifests[0]["persona_contract"]["patient_profile"]
    )
    assert ctx.cm_manifest_for_case("CM-0").task_id == manifests[0]["task_id"]
    assert ctx.cm_manifest_for_case("CM-1") is None
