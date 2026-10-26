"""Offline rejudging uses live scoring validity and preserves canonical results."""

import json
import pytest

from chi_bench.verifier.judge.claude_runner import ClaudeRunnerError
from chi_bench.verifier.rejudge import rejudge_trial


class SyntheticRunner:
    def __init__(self, mode):
        self.mode = mode
        self.calls = 0

    def run_session(self, *args, cwd, **kwargs):
        self.calls += 1
        if self.mode == "outage":
            raise ClaudeRunnerError("Synthetic judge outage; no model call")
        rubrics = json.loads((cwd / "rubrics.json").read_text())["rubrics"]
        if self.mode == "partial":
            rubrics = rubrics[:1]
        verdicts = {
            item["rubric_id"]: {
                "pass": self.mode != "fail" or index != 0,
                "explanation": "Synthetic model-boundary result",
                "evidence_refs": ["agent_outputs/stage_review.json:synthetic criterion"],
            }
            for index, item in enumerate(rubrics)
        }
        (cwd / "verdicts.json").write_text(json.dumps({"rubric_verdicts": verdicts}))


@pytest.fixture
def retained_trial(tmp_path, monkeypatch):
    monkeypatch.setenv("CHI_BENCH_JUDGE_NUM_VOTES", "1")

    def build(contract, *, gate_pass=True, structured=True, no_submit=False):
        trial = tmp_path / "trial"
        verifier = trial / "verifier"
        verifier.mkdir(parents=True)
        expectations = {
            "verifier_contract": contract,
            "target_case_id": "CASE-SYNTHETIC",
            "scenario_id": "synthetic-rejudge",
        }
        items = [
            {"rubric_id": name, "prompt": "Evaluate synthetic evidence.", "stage": "outreach"}
            for name in ("one", "two")
        ]
        if contract == "cm_v4":
            expectations["evidence_rubric_items"] = items
        elif contract.startswith("cm"):
            expectations["rubric_prompts"] = {item["rubric_id"]: item["prompt"] for item in items}
        else:
            expectations["semantic_judge_rubric"] = {"outcome": items}
            if contract == "contract_v4":
                expectations["included_stages"] = ["provider_request_package"]
        exported = {}
        if no_submit:
            expectations["task_kind"] = "provider_to_payer_e2e"
            exported["provider_determinations"] = [
                {"case_id": "CASE-SYNTHETIC", "final_action": "do_not_submit"}
            ]
        old_scorecard = {
            "checks": {"structured": structured, "judge.obsolete": "unavailable"},
            "scoring_status": "invalid",
            "binary_reward": 0,
        }
        if contract in {"cm_v1", "cm_v2", "cm_v3"}:
            old_scorecard.update(gate_pass=gate_pass, gate_results=[])
        for name, value in {
            "scorecard.json": old_scorecard,
            "exported_state.json": exported,
            "reward.json": {"reward": 0},
            "validity.json": {"scoring_status": "invalid"},
        }.items():
            (verifier / name).write_text(json.dumps(value))
        (trial / "result.json").write_text(json.dumps({"canonical": "must stay unchanged"}))
        (trial / "reward.json").write_text(json.dumps({"reward": 0}))
        expectations_path = tmp_path / "expectations.json"
        expectations_path.write_text(json.dumps(expectations))
        return trial, expectations_path

    return build


@pytest.mark.parametrize("contract", ["contract_v4", "cm_v4"])
@pytest.mark.parametrize("mode", ["outage", "partial", "pass", "fail"])
def test_stage_rejudge_required_verdicts_have_live_validity(retained_trial, contract, mode):
    trial, expectations = retained_trial(contract)
    runner = SyntheticRunner(mode)
    rejudge_trial(trial_dir=trial, expectations_path=expectations, runner=runner)
    output = trial / "verifier_rejudge"
    score = json.loads((output / "scorecard.json").read_text())
    invalid = mode in {"outage", "partial"}
    assert runner.calls == 1
    assert score["scoring_status"] == ("invalid" if invalid else "valid")
    assert score["binary_reward"] == (1 if mode == "pass" else 0)
    assert score["checks"]["structured"] is True
    assert "judge.obsolete" not in score["checks"]
    if invalid:
        assert score["fractional_reward"] is None
        assert score["invalid_checks"]
        assert all(score["checks"][key] == "unavailable" for key in score["invalid_checks"])
        assert score["failed_checks"] == []
    else:
        assert score["invalid_checks"] == []
        assert score["fractional_reward"] == (1 if mode == "pass" else 2 / 3)
    assert json.loads((output / "validity.json").read_text()) == {
        "scoring_status": score["scoring_status"],
        "invalid_checks": score["invalid_checks"],
    }


@pytest.mark.parametrize("contract", ["contract_v4", "cm_v4"])
def test_stage_rejudge_preserves_failed_deterministic_checks(retained_trial, contract):
    trial, expectations = retained_trial(contract, structured=False)
    rejudge_trial(trial_dir=trial, expectations_path=expectations, runner=SyntheticRunner("pass"))
    score = json.loads((trial / "verifier_rejudge/scorecard.json").read_text())
    assert score["binary_reward"] == 0
    assert score["failed_checks"] == ["structured"]
    assert score["scoring_status"] == "valid"


@pytest.mark.parametrize("gate_pass", [True, False])
def test_legacy_cm_outage_is_invalid_only_when_judgement_required(retained_trial, gate_pass):
    trial, expectations = retained_trial("cm_v2", gate_pass=gate_pass)
    runner = SyntheticRunner("outage")
    rejudge_trial(trial_dir=trial, expectations_path=expectations, runner=runner)
    output = trial / "verifier_rejudge"
    score = json.loads((output / "scorecard.json").read_text())
    assert runner.calls == int(gate_pass)
    assert score["binary_reward"] == 0
    assert score["scoring_status"] == ("invalid" if gate_pass else "valid")
    if gate_pass:
        assert score["fractional_reward"] is None
        assert set(score["invalid_checks"]) == {"cm_rubric.one", "cm_rubric.two"}
    else:
        assert score["fractional_reward"] == 0
        assert score["invalid_checks"] == []
    assert (
        json.loads((output / "validity.json").read_text())["scoring_status"]
        == score["scoring_status"]
    )


def test_unversioned_e2e_rejudge_is_rejected_without_model_call(retained_trial):
    trial, expectations = retained_trial("contract_v4", no_submit=True)
    runner = SyntheticRunner("outage")
    with pytest.raises(ValueError, match="explicit workflow_v2"):
        rejudge_trial(trial_dir=trial, expectations_path=expectations, runner=runner)
    assert runner.calls == 0
    assert not (trial / "verifier_rejudge").exists()


def test_rejudge_preserves_every_canonical_file(retained_trial):
    trial, expectations = retained_trial("contract_v4")
    before = {
        path.relative_to(trial): path.read_bytes() for path in trial.rglob("*") if path.is_file()
    }
    rejudge_trial(trial_dir=trial, expectations_path=expectations, runner=SyntheticRunner("pass"))
    assert all((trial / path).read_bytes() == content for path, content in before.items())
    assert (trial / "verifier_rejudge/validity.json").is_file()


@pytest.mark.parametrize("output_subdir", ["verifier", "verifier/nested", ".", "../outside"])
def test_rejudge_rejects_output_paths_that_are_not_side_by_side(retained_trial, output_subdir):
    trial, expectations = retained_trial("contract_v4")
    before = {
        path.relative_to(trial): path.read_bytes() for path in trial.rglob("*") if path.is_file()
    }
    runner = SyntheticRunner("pass")
    with pytest.raises(ValueError, match="output"):
        rejudge_trial(
            trial_dir=trial,
            expectations_path=expectations,
            output_subdir=output_subdir,
            runner=runner,
        )
    assert runner.calls == 0
    assert all((trial / path).read_bytes() == content for path, content in before.items())


@pytest.mark.parametrize("contract", ["contract_v4", "contract_v5"])
def test_rejudge_skips_contracts_without_online_judge_eligibility(retained_trial, contract):
    trial, expectations_path = retained_trial(contract)
    expectations = json.loads(expectations_path.read_text())
    expectations.update(
        task_kind="provider_new_referral",
        included_stages=["new_referral", "provider_pre_submission"],
        expected_provider_pre_submission={"final_action": "do_not_submit"},
        expected_target_status="closed",
    )
    expectations_path.write_text(json.dumps(expectations))
    runner = SyntheticRunner("outage")
    rejudge_trial(trial_dir=trial, expectations_path=expectations_path, runner=runner)
    score = json.loads((trial / "verifier_rejudge/scorecard.json").read_text())
    assert runner.calls == 0
    assert score["scoring_status"] == "valid"
    assert score["binary_reward"] == 1
    assert score["checks"] == {"structured": True}


@pytest.mark.parametrize("manifest_target", [False, True])
def test_cm_v4_rejudge_resolves_shared_world_and_case_from_manifest(
    retained_trial, tmp_path, monkeypatch, manifest_target
):
    trial, expectations_path = retained_trial("cm_v4")
    expectations = json.loads(expectations_path.read_text())
    expectations["target_patient_id"] = "PAT-SYNTHETIC"
    if manifest_target:
        expectations.pop("target_case_id")
    expectations_path.write_text(json.dumps(expectations))
    expectations_path.with_name("manifest.json").write_text(
        json.dumps({"world_id": "shared-rejudge-world", "target_case_id": "CASE-SYNTHETIC"})
    )
    worlds = tmp_path / "worlds"
    worlds.mkdir()
    world = {
        "patients": [{"id": "PAT-SYNTHETIC", "first_name": "Synthetic"}],
        "observations": [{"patient_id": "PAT-SYNTHETIC", "value": 42}],
    }
    (worlds / "shared-rejudge-world.json").write_text(json.dumps(world))
    monkeypatch.setenv("CHI_BENCH_WORLDS_DIR", str(worlds))
    rejudge_trial(
        trial_dir=trial, expectations_path=expectations_path, runner=SyntheticRunner("pass")
    )
    chart = json.loads(
        (trial / "artifacts/workspaces/CASE-SYNTHETIC_rejudge/chart_slice.json").read_text()
    )
    assert chart["patient"] == world["patients"][0]
    assert chart["observations"] == world["observations"]


@pytest.mark.parametrize("link_type", ["symlink", "hardlink"])
@pytest.mark.parametrize(
    "filename", ["scorecard.json", "validity.json", "verdicts.json", "judge_session_metadata.json"]
)
def test_rejudge_rejects_output_file_aliases_before_canonical_mutation(
    retained_trial, filename, link_type
):
    trial, expectations = retained_trial("contract_v4")
    canonical = trial / "verifier/scorecard.json"
    original = canonical.read_bytes()
    output = trial / "verifier_rejudge"
    output.mkdir()
    alias = output / filename
    if link_type == "symlink":
        alias.symlink_to(canonical)
    else:
        alias.hardlink_to(canonical)
    runner = SyntheticRunner("pass")
    with pytest.raises(ValueError, match="output"):
        rejudge_trial(trial_dir=trial, expectations_path=expectations, runner=runner)
    assert runner.calls == 0
    assert canonical.read_bytes() == original
