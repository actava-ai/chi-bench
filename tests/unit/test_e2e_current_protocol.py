"""Current E2E scoring never reinterprets retained legacy or unversioned runs."""

import json

import pytest
from pydantic import ValidationError

from chi_bench.core.e2e_protocol import e2e_protocol, validate_e2e_protocol
from chi_bench.experiment.config import ExperimentConfig
from chi_bench.experiment.runner import _build_child_env, run_experiment
from chi_bench.verifier import task_runtime
from chi_bench.verifier.rejudge import rejudge_trial


@pytest.fixture(autouse=True)
def forbid_judge_boundary(monkeypatch):
    monkeypatch.setattr(
        "chi_bench.verifier.rejudge._run_judge_session",
        lambda **kwargs: pytest.fail("Protocol rejection must occur before any model boundary"),
    )


def test_new_execution_defaults_to_current_protocol(monkeypatch):
    monkeypatch.delenv("CHI_BENCH_E2E_PROTOCOL", raising=False)
    assert validate_e2e_protocol() == "workflow_v2"
    assert (
        _build_child_env(ExperimentConfig(dataset="synthetic"))["CHI_BENCH_E2E_PROTOCOL"]
        == "workflow_v2"
    )


def test_config_rejects_legacy_protocol():
    with pytest.raises(ValidationError):
        ExperimentConfig(dataset="synthetic", e2e_protocol="dual_viewpoint_v1")


@pytest.mark.parametrize("value", ["dual_viewpoint_v1", "", "typo"])
def test_execution_rejects_noncurrent_protocol(value):
    with pytest.raises(ValueError, match="workflow_v2"):
        validate_e2e_protocol(value)


def test_environment_legacy_rejected_before_modal_preflight(monkeypatch):
    monkeypatch.setenv("CHI_BENCH_E2E_PROTOCOL", "dual_viewpoint_v1")
    monkeypatch.setattr("chi_bench.experiment.runner._load_env", lambda _: None)
    monkeypatch.setattr(
        "chi_bench.experiment.runner._modal_preflight",
        lambda _: pytest.fail("preflight must not run"),
    )
    with pytest.raises(ValueError, match="workflow_v2"):
        run_experiment(dataset="synthetic", environment="modal")


@pytest.mark.parametrize("protocol", [None, "dual_viewpoint_v1"])
def test_unsupported_export_cannot_be_relabelled_by_process_environment(protocol, monkeypatch):
    monkeypatch.setenv("CHI_BENCH_E2E_PROTOCOL", "workflow_v2")
    exported = {} if protocol is None else {"e2e_protocol": protocol}
    with pytest.raises(ValueError, match="workflow_v2"):
        e2e_protocol(exported)


@pytest.mark.parametrize("protocol", [None, "dual_viewpoint_v1"])
def test_verify_rejects_old_export_before_scoring_or_judge(protocol, monkeypatch):
    exported = {} if protocol is None else {"e2e_protocol": protocol}
    monkeypatch.setattr(
        task_runtime,
        "collect_all_verifier_checks",
        lambda *a, **kw: pytest.fail("old export reached scoring"),
    )
    with pytest.raises(ValueError, match="workflow_v2"):
        task_runtime.verify_task(
            exported=exported, expectations={"task_kind": "provider_to_payer_e2e"}
        )


@pytest.mark.parametrize("protocol", [None, "dual_viewpoint_v1"])
def test_rejudge_rejects_old_export_without_writing_new_scores(tmp_path, protocol):
    verifier = tmp_path / "trial/verifier"
    verifier.mkdir(parents=True)
    exported = {} if protocol is None else {"e2e_protocol": protocol}
    (verifier / "exported_state.json").write_text(json.dumps(exported))
    (verifier / "scorecard.json").write_text(json.dumps({"binary_reward": 1}))
    expectations = tmp_path / "expectations.json"
    expectations.write_text(
        json.dumps({"task_kind": "provider_to_payer_e2e", "verifier_contract": "contract_e2e_v1"})
    )
    before = {p.name: p.read_bytes() for p in verifier.iterdir()}
    with pytest.raises(ValueError, match="workflow_v2"):
        rejudge_trial(trial_dir=verifier.parent, expectations_path=expectations)
    assert not (verifier.parent / "verifier_rejudge").exists()
    assert before == {p.name: p.read_bytes() for p in verifier.iterdir()}


def test_non_e2e_verifier_does_not_require_protocol(monkeypatch):
    monkeypatch.setattr(
        task_runtime,
        "collect_all_verifier_checks",
        lambda *a, **kw: ({"deterministic": True}, [], {}),
    )
    result = task_runtime.verify_task(
        exported={}, expectations={"task_kind": "provider_new_referral"}
    )
    assert result.reward == 1
    assert "e2e_protocol" not in result.scorecard


@pytest.mark.parametrize("protocol", [None, "dual_viewpoint_v1"])
def test_rejudge_cannot_carry_over_legacy_or_unversioned_checks(tmp_path, protocol):
    verifier = tmp_path / "trial/verifier"
    verifier.mkdir(parents=True)
    (verifier / "exported_state.json").write_text(json.dumps({"e2e_protocol": "workflow_v2"}))
    card = {} if protocol is None else {"e2e_protocol": protocol}
    (verifier / "scorecard.json").write_text(json.dumps(card))
    expectations = tmp_path / "expectations.json"
    expectations.write_text(json.dumps({"task_kind": "provider_to_payer_e2e"}))
    with pytest.raises(ValueError, match="scorecard.*workflow_v2"):
        rejudge_trial(trial_dir=verifier.parent, expectations_path=expectations)
    assert not (verifier.parent / "verifier_rejudge").exists()


def test_flat_legacy_scorer_cannot_score_an_e2e_task():
    with pytest.raises(ValueError, match="workflow_v2"):
        task_runtime.collect_verifier_checks_legacy({}, {"task_kind": "provider_to_payer_e2e"})


def test_cli_rejects_legacy_before_runner(monkeypatch, tmp_path):
    from typer.testing import CliRunner
    from chi_bench.cli import app

    monkeypatch.setattr(
        "chi_bench.experiment.runner.run_experiment",
        lambda **kw: pytest.fail("Unsupported protocol reached runner"),
    )
    result = CliRunner().invoke(
        app,
        ["experiment", "run", "--dataset", str(tmp_path), "--e2e-protocol", "dual_viewpoint_v1"],
    )
    assert result.exit_code != 0
    assert "workflow_v2" in result.output
    assert not list(tmp_path.iterdir())


def test_context_rejects_legacy_before_creating_runtime(monkeypatch, tmp_path):
    from chi_bench.core.context import ServiceContext

    monkeypatch.setenv("CHI_BENCH_E2E_PROTOCOL", "dual_viewpoint_v1")
    runtime = tmp_path / "runtime"
    with pytest.raises(ValueError, match="workflow_v2"):
        ServiceContext(runtime)
    assert not runtime.exists()


@pytest.mark.parametrize(
    "kind", ["provider_new_referral", "payer_p2p", "care_management_full_workflow"]
)
def test_generic_provider_path_helpers_do_not_require_e2e_protocol(kind):
    from chi_bench.core.agent_path import compute_agent_path, latest_provider_determination

    determination = {"case_id": "C", "final_action": "submit_pa"}
    exported = {
        "task_kind": kind,
        "provider_determinations": [determination],
        "submission_packets": [{"case_id": "C"}],
    }
    assert latest_provider_determination(exported) == determination
    assert compute_agent_path(exported) == "submit"


@pytest.mark.parametrize("protocol", [None, "dual_viewpoint_v1", "workflow_v2"])
def test_missing_e2e_expectation_kind_cannot_reach_legacy_flat_score(protocol):
    exported = {
        "task_kind": "provider_to_payer_e2e",
        "target_case": {"status": "approved"},
        "audit_logs": [],
    }
    if protocol is not None:
        exported["e2e_protocol"] = protocol
    expectations = {"verifier_contract": "contract_e2e_v1", "expected_target_status": "approved"}
    with pytest.raises(ValueError, match="workflow_v2"):
        task_runtime.verify_task(exported=exported, expectations=expectations)


def test_source_e2e_contract_requires_explicit_current_task_kind():
    with pytest.raises(ValueError, match="workflow_v2"):
        task_runtime.collect_verifier_checks_legacy({}, {"verifier_contract": "contract_e2e_v1"})
