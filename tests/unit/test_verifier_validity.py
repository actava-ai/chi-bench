import json

import pytest

from chi_bench.aggregator import aggregate_to_rows
from chi_bench.experiment.submission import prepare_packet, status_submission
from chi_bench.verifier import task_runtime
from chi_bench.verifier.judge.claude_runner import ClaudeRunnerError
from chi_bench.verifier.judge.types import JudgeInput
from chi_bench.verifier.judge.workspace_judge import WorkspaceJudge
from tests.unit.test_submission_config import _populated_submission


def test_unavailable_required_check_invalidates_score_without_agent_failure():
    result = task_runtime.build_scorecard({"structured": True, "judge.required": "unavailable"})
    assert result["binary_reward"] == 0
    assert result["scoring_status"] == "invalid"
    assert result["invalid_checks"] == ["judge.required"]
    assert result["failed_checks"] == []
    assert result["fractional_reward"] is None
    assert result["check_scores"]["judge.required"] is None


def test_legitimate_not_applicable_does_not_invalidate_score():
    result = task_runtime.build_scorecard({"structured": True, "unused": "not_applicable"})
    assert result["binary_reward"] == 1
    assert result["scoring_status"] == "valid"


@pytest.mark.parametrize("contract", ["contract_v5", "cm_v4"])
@pytest.mark.parametrize("mode", ["outage", "partial", "pass", "fail"])
def test_required_judge_failures_are_invalid_through_real_judge(
    tmp_path, monkeypatch, contract, mode
):
    judge_input = JudgeInput(
        "synthetic-case",
        ({"rubric_id": "one"}, {"rubric_id": "two"}),
        {},
        (),
        {},
        (),
        "cm" if contract == "cm_v4" else "pa_um",
        contract,
    )
    monkeypatch.setattr(
        "chi_bench.verifier.stages.collect_stage_checks", lambda *args: ({"structured": True}, [])
    )
    monkeypatch.setattr(
        "chi_bench.verifier.judge.pa_um_adapter.PaUmJudgeAdapter.build", lambda self: judge_input
    )
    monkeypatch.setattr(
        "chi_bench.verifier.judge.cm_adapter.CmJudgeAdapter.build", lambda self: judge_input
    )

    class Runner:
        def run_session(self, *args, cwd, **kwargs):
            if mode == "outage":
                raise ClaudeRunnerError("synthetic outage, no model call")
            verdicts = {
                "one": {
                    "pass": mode != "fail",
                    "explanation": "synthetic",
                    "evidence_refs": ["agent_outputs/stage_review.json:one"],
                }
            }
            if mode != "partial":
                verdicts["two"] = {
                    "pass": True,
                    "explanation": "synthetic",
                    "evidence_refs": ["agent_outputs/stage_review.json:two"],
                }
            (cwd / "verdicts.json").write_text(json.dumps({"rubric_verdicts": verdicts}))

    monkeypatch.setattr(
        WorkspaceJudge,
        "judge",
        lambda self, data, **kwargs: self._judge_once(data, workspace_dir=tmp_path / "judge"),
    )
    result = task_runtime.verify_task(
        exported={},
        expectations={"verifier_contract": contract, "included_stages": ["outcome"]},
        judge=Runner(),
    )
    assert result.scorecard["scoring_status"] == (
        "invalid" if mode in {"outage", "partial"} else "valid"
    )
    assert result.reward == (1 if mode == "pass" else 0)
    if mode in {"outage", "partial"}:
        assert result.scorecard["invalid_checks"]
        assert not result.scorecard["failed_checks"]


@pytest.mark.parametrize("legacy", [False, True])
def test_invalid_trial_is_not_aggregated_or_packaged_as_pass(tmp_path, legacy):
    cfg = _populated_submission(tmp_path, {"pa_provider": [1.0]})
    root = cfg.paths.output_root
    result_path = next(root.rglob("result.json"))
    verifier = result_path.parent / "verifier"
    verifier.mkdir(exist_ok=True)
    if legacy:
        (verifier / "scorecard.json").write_text(
            json.dumps({"checks": {"structured": True, "judge.required": "not_applicable"}})
        )
        (verifier / "verifier_context.json").write_text(
            json.dumps({"judge_unavailable_reason": "Synthetic timeout"})
        )
    else:
        (verifier / "scorecard.json").write_text(
            json.dumps({"scoring_status": "invalid", "invalid_checks": ["judge.required"]})
        )
    with pytest.raises(ValueError, match="invalid"):
        aggregate_to_rows(root)
    rows = status_submission(cfg)["domains"]
    provider = next(row for row in rows if row["domain"] == "pa_provider")
    assert provider["n_passed"] == provider["n_failed"] == 0
    assert provider["n_invalid"] == 1
    assert provider["state"] == "invalid"
    destination = tmp_path / "packet"
    with pytest.raises(ValueError, match="invalid"):
        prepare_packet(cfg, out_dir=destination)
    assert not destination.exists()


def test_verifier_writes_only_small_non_sensitive_validity_marker(tmp_path):
    scorecard = {
        "binary_reward": 0,
        "scoring_status": "invalid",
        "invalid_checks": ["judge.required"],
    }
    task_runtime.write_verifier_outputs(
        scorecard,
        {"private_answer": "PRIVATE_SENTINEL"},
        {},
        reward_path=tmp_path / "reward.json",
        scorecard_path=tmp_path / "scorecard.json",
        exported_state_path=tmp_path / "state.json",
        verifier_context_path=tmp_path / "context.json",
    )
    validity = json.loads((tmp_path / "validity.json").read_text())
    assert validity == {"scoring_status": "invalid", "invalid_checks": ["judge.required"]}
    assert "PRIVATE_SENTINEL" not in (tmp_path / "validity.json").read_text()


def test_intentional_judge_skip_stays_valid(tmp_path, monkeypatch):
    judge_input = JudgeInput(
        "synthetic", ({"rubric_id": "unused-payer"},), {}, (), {}, (), "pa_um", "contract_v3"
    )
    monkeypatch.setattr(
        "chi_bench.verifier.stages.collect_stage_checks", lambda *args: ({"structured": True}, [])
    )
    monkeypatch.setattr(
        "chi_bench.verifier.judge.pa_um_adapter.PaUmJudgeAdapter.build", lambda self: judge_input
    )
    monkeypatch.setattr(
        "chi_bench.verifier.judge.judge.should_run_workspace_judge", lambda *args: False
    )
    result = task_runtime.verify_task(
        exported={},
        expectations={"verifier_contract": "contract_v3", "included_stages": ["outcome"]},
    )
    assert result.reward == 1
    assert result.scorecard["scoring_status"] == "valid"
    assert result.scorecard["checks"]["judge.unused-payer"] == "not_applicable"


def test_one_unavailable_marathon_task_invalidates_session(tmp_path, monkeypatch):
    from chi_bench.verifier import session_verifier

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "session_manifest.json").write_text(
        json.dumps(
            {
                "session_id": "synthetic",
                "world_id": "synthetic",
                "domain": "care_management",
                "tasks": [{"task_id": "first"}, {"task_id": "second"}],
            }
        )
    )

    def verify(*, scorecard_path, reward_path, **kwargs):
        invalid = scorecard_path.parent.name == "second"
        scorecard_path.write_text(
            json.dumps(
                {
                    "scoring_status": "invalid" if invalid else "valid",
                    "fractional_reward": None if invalid else 1,
                }
            )
        )
        reward_path.write_text(json.dumps({"reward": 0 if invalid else 1}))
        return 2 if invalid else 0

    monkeypatch.setattr(session_verifier, "run_verifier", verify)
    output = tmp_path / "verifier"
    assert session_verifier.run_session_verifier(fixtures, output) == 2
    assert json.loads((output / "reward.json").read_text())["reward"] == 0
    score = json.loads((output / "session_score.json").read_text())
    assert score["scoring_status"] == "invalid"
    assert score["invalid_checks"] == ["second"]
    assert score["mean_per_task_fractional"] is None
    assert json.loads((output / "validity.json").read_text())["scoring_status"] == "invalid"


@pytest.mark.parametrize("nested", [False, True])
def test_retained_inline_cm_and_nested_marathon_outages_are_invalid(tmp_path, nested):
    from chi_bench.verifier.validity import trial_invalid_reason

    result = tmp_path / "trial" / "result.json"
    verifier = result.parent / "verifier"
    if nested:
        verifier = verifier / "task_scores" / "synthetic-task"
    verifier.mkdir(parents=True)
    (verifier / "scorecard.json").write_text(
        json.dumps(
            {
                "checks": {"cm_rubric.required": "not_applicable"},
                "judge_unavailable_reason": "Synthetic timeout",
                "judge_session_metadata": {},
            }
        )
    )
    assert trial_invalid_reason(result) is not None
