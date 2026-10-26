import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def test_verifier_export_request_uses_trusted_headers(monkeypatch):
    from chi_bench.verifier import task_runtime

    monkeypatch.setenv("CHI_BENCH_CONTROL_TOKEN", "private-control")
    seen = []

    def urlopen(request, timeout):
        seen.append(request)
        return io.BytesIO(b'{"final":"state"}')

    monkeypatch.setattr(task_runtime.urllib.request, "urlopen", urlopen)
    assert task_runtime.fetch_json("http://localhost:8023/export") == {"final": "state"}
    assert seen[0].get_header("Authorization") == "Bearer private-control"


@pytest.mark.asyncio
async def test_e2e_control_calls_do_not_run_in_model_container():
    from chi_bench.experiment.agents.dual_pa_e2e_harness import DualPaE2EHarness

    harness = object.__new__(DualPaE2EHarness)
    harness.exec_as_agent = AsyncMock(side_effect=AssertionError("must not run as agent"))
    environment = SimpleNamespace(control_request=AsyncMock(return_value={"trusted": True}))
    assert await harness._agent_get_json(environment, "http://localhost:8023/export") == {
        "trusted": True
    }
    await harness._agent_post_json(
        environment, "http://localhost:8023/_admin/phase_marker", {"phase": "enter"}
    )
    assert environment.control_request.await_args_list[0].args == ("/export",)
    assert environment.control_request.await_args_list[1].args == (
        "/_admin/phase_marker",
        {"phase": "enter"},
    )


def test_frozen_state_verification_never_contacts_the_live_server(tmp_path, monkeypatch):
    import json
    from chi_bench.verifier import task_runtime

    frozen = tmp_path / "final-state.json"
    frozen.write_text(json.dumps({"canary": "frozen-final-state"}))
    monkeypatch.setattr(task_runtime, "load_expectations", lambda path: {})
    monkeypatch.setattr(
        task_runtime, "fetch_json", lambda *a, **kw: pytest.fail("live export called")
    )
    seen = []
    monkeypatch.setattr(
        task_runtime,
        "collect_all_verifier_checks",
        lambda exported, *a, **kw: (seen.append(exported) or [], [], {}),
    )
    monkeypatch.setattr(task_runtime, "build_scorecard", lambda *a, **kw: {"binary_reward": 1.0})
    monkeypatch.setattr(task_runtime, "write_verifier_outputs", lambda *a, **kw: None)
    assert task_runtime.run_verifier(exported_state_input=frozen) == 0
    assert seen == [{"canary": "frozen-final-state"}]
