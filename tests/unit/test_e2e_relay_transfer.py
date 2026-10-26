"""Relay output crosses the agent-container boundary before host parsing."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chi_bench.experiment.agents.dual_pa_e2e_harness import DualPaE2EHarness
from chi_bench.experiment.agents.dual_pa_e2e_relay import RelayOutputError, RelayTranscript


async def run_turn(tmp_path, monkeypatch, *, role, outputs, transfer_error=None):
    harness = DualPaE2EHarness(logs_dir=tmp_path / "logs")
    harness._resolved_flags = {"p2p_repair_attempts": 1}
    events = []
    remote = {}
    source = f"/logs/agent/e2e_relay/R/{role}_01.json"
    target = harness.logs_dir / "e2e_relay/R" / f"{role}_01.json"
    attempts = iter(outputs)

    async def phase(**kwargs):
        events.append("phase")
        payload = next(attempts)
        if payload is None:
            remote.pop(source, None)
        else:
            remote[source] = payload

    async def check(environment, *, command, **kwargs):
        events.append("check")
        assert command == f"test -f {source}"
        return SimpleNamespace(return_code=0 if source in remote else 1)

    class Environment:
        async def download_file(self, source_path, target_path):
            events.append("download")
            assert source_path == source
            assert Path(target_path) == target
            if transfer_error:
                raise transfer_error
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(remote[source])

    monkeypatch.setattr(harness, "_run_role_phase", phase)
    monkeypatch.setattr(harness, "exec_as_agent", check)
    result = await harness._run_relay_role_once(
        role=role,
        instruction="Synthetic transfer control.",
        turn_index=1,
        request={"id": "R", "case_id": "C"},
        transcript=RelayTranscript("R", "C"),
        environment=Environment(),
        mcp_url="http://synthetic/mcp",
        model_name=None,
    )
    return result, events


def payload(role):
    return json.dumps(
        {"actor": role, "message": "Actual role response.", "ready_to_finalize": False}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["provider", "payer"])
async def test_relay_downloads_successful_agent_output_before_loading(tmp_path, monkeypatch, role):
    turn, events = await run_turn(tmp_path, monkeypatch, role=role, outputs=[payload(role)])
    assert turn.actor == role
    assert turn.message == "Actual role response."
    assert events == ["phase", "check", "download"]


@pytest.mark.asyncio
async def test_missing_agent_file_can_be_repaired(tmp_path, monkeypatch):
    turn, events = await run_turn(
        tmp_path, monkeypatch, role="provider", outputs=[None, payload("provider")]
    )
    assert turn.actor == "provider"
    assert events == ["phase", "check", "phase", "check", "download"]


@pytest.mark.asyncio
async def test_invalid_agent_output_is_downloaded_again_after_repair(tmp_path, monkeypatch):
    turn, events = await run_turn(
        tmp_path, monkeypatch, role="provider", outputs=["{", payload("provider")]
    )
    assert turn.actor == "provider"
    assert events == ["phase", "check", "download"] * 2


@pytest.mark.asyncio
async def test_transfer_failure_is_not_misreported_as_missing_model_output(tmp_path, monkeypatch):
    with pytest.raises(ConnectionError, match="synthetic transfer outage"):
        await run_turn(
            tmp_path,
            monkeypatch,
            role="provider",
            outputs=[payload("provider")],
            transfer_error=ConnectionError("synthetic transfer outage"),
        )


@pytest.mark.asyncio
async def test_missing_agent_output_still_fails_after_bounded_repair(tmp_path, monkeypatch):
    with pytest.raises(RelayOutputError, match="missing"):
        await run_turn(tmp_path, monkeypatch, role="provider", outputs=[None, None])


@pytest.mark.parametrize(
    ("action", "allowed"),
    [("get_p2p_session_context", True), ("p2p_session_turn", False), ("submit_p2p_summary", False)],
)
def test_readonly_context_lookup_is_not_a_simulator_bypass(tmp_path, action, allowed):
    from chi_bench.verifier.stages.e2e_consistency import E2EConsistencyVerifier

    state = {
        "task_kind": "provider_to_payer_e2e",
        "e2e_protocol": "workflow_v2",
        "target_case_id": "C",
        "target_case": {"id": "C", "status": "p2p_scheduled"},
        "payer_peer_to_peer_requests": [{"id": "R", "case_id": "C", "status": "event_open"}],
        "audit_logs": [{"case_id": "C", "action": action, "request_id": "R"}],
    }
    harness = DualPaE2EHarness(logs_dir=tmp_path)
    if allowed:
        harness._verify_no_p2p_bypass_after_relay_turn(exported=state, request_id="R", case_id="C")
    else:
        with pytest.raises(RuntimeError, match="direct p2p_session"):
            harness._verify_no_p2p_bypass_after_relay_turn(
                exported=state, request_id="R", case_id="C"
            )
    result = E2EConsistencyVerifier(
        state, {"task_kind": "provider_to_payer_e2e", "target_case_id": "C"}, []
    ).verify()
    assert result.checks["e2e.p2p_no_direct_session_tools"] is allowed
