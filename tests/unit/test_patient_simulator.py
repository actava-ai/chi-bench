from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from chi_bench.conversation import patient_simulator
from chi_bench.conversation.session import ConversationSession


def test_patient_simulator_defaults_to_sonnet_5(monkeypatch):
    monkeypatch.delenv("CHI_BENCH_PATIENT_SIM_MODEL", raising=False)
    monkeypatch.setattr(patient_simulator.anthropic, "AsyncAnthropic", object)

    simulator = patient_simulator.PatientSimulator(
        scenario={},
        clinical_context="",
        patient_profile="Remain in character as the patient.",
    )

    assert simulator._model == "claude-sonnet-5"


async def test_sonnet_5_disables_adaptive_thinking(monkeypatch):
    create = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(text="Hello")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
        )
    )
    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    monkeypatch.setattr(patient_simulator.anthropic, "AsyncAnthropic", lambda: client)

    simulator = patient_simulator.PatientSimulator(
        scenario={},
        clinical_context="",
        patient_profile="Remain in character as the patient.",
    )
    session = ConversationSession(
        session_id="session-1",
        case_id="case-1",
        patient_name="Patient",
        reason_for_call="Care management outreach",
        created_at=datetime.now(UTC),
    )
    session.add_care_manager_message("Hello", datetime.now(UTC))

    await simulator.generate_response(session)

    assert create.await_args.kwargs["thinking"] == {"type": "disabled"}
