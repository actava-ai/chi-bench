"""Judge schema failures are unavailable evaluations, never agent outcomes."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from chi_bench.aggregator import aggregate_to_rows
from chi_bench.experiment.submission import prepare_packet, status_submission
from chi_bench.verifier import task_runtime
from chi_bench.verifier.judge.types import JudgeInput
from chi_bench.verifier.judge.prompts import build_judge_prompt, get_judge_prompt_version
from chi_bench.verifier.judge.workspace_judge import WorkspaceJudge
from tests.unit.test_submission_config import _populated_submission


def _input() -> JudgeInput:
    return JudgeInput(
        "strict-schema",
        ({"rubric_id": "one"}, {"rubric_id": "two"}),
        {},
        (),
        {},
        (),
        "pa_um",
        "contract_v5",
    )


def _response() -> dict:
    return {
        "rubric_verdicts": {
            "one": {
                "pass": True,
                "explanation": "The record supports this criterion.",
                "evidence_refs": ["agent_outputs/stage_review.json:criterion one"],
            },
            "two": {
                "pass": False,
                "explanation": "The required finding is absent from the record.",
                "evidence_refs": ["agent_outputs/stage_review.json:criterion two absent"],
            },
        },
        "session_metadata": {"investigation_notes": "Reviewed the available record."},
    }


def _parse(tmp_path: Path, payload, *, judge_input: JudgeInput | None = None):
    (tmp_path / "verdicts.json").write_text(
        payload if isinstance(payload, str) else json.dumps(payload)
    )
    return WorkspaceJudge(runner=object())._parse_verdicts(
        judge_input=judge_input or _input(),
        workspace_dir=tmp_path,
        duration_s=1.0,
        unavailable_reason=None,
    )


@pytest.mark.parametrize("value", ["false", "0", 0, 1, None, [], [False], {}])
def test_non_boolean_verdict_invalidates_whole_response(tmp_path, value):
    payload = _response()
    payload["rubric_verdicts"]["two"]["pass"] = value
    output = _parse(tmp_path, payload)
    assert output.verdicts == {}
    assert output.degraded_rubric_ids == ("one", "two")
    assert output.judge_unavailable_reason.startswith("VerdictsParseError:")


@pytest.mark.parametrize("field", ["explanation", "evidence_refs"])
@pytest.mark.parametrize("value", [None, "", "  ", 1, [], [""], ["  "], [1]])
def test_missing_or_malformed_evidence_invalidates_response(tmp_path, field, value):
    payload = _response()
    payload["rubric_verdicts"]["one"][field] = value
    assert not _parse(tmp_path, payload).verdicts


@pytest.mark.parametrize("field", ["pass", "explanation", "evidence_refs"])
def test_required_verdict_fields_cannot_be_omitted(tmp_path, field):
    payload = _response()
    del payload["rubric_verdicts"]["two"][field]
    assert _parse(tmp_path, payload).degraded_rubric_ids == ("one", "two")


@pytest.mark.parametrize("change", ["unknown", "missing", "list", "scalar", "metadata"])
def test_exact_rubric_id_set_and_object_shapes_are_required(tmp_path, change):
    payload = _response()
    if change == "unknown":
        payload["rubric_verdicts"]["unexpected"] = deepcopy(payload["rubric_verdicts"]["one"])
    elif change == "missing":
        del payload["rubric_verdicts"]["two"]
    elif change == "list":
        payload["rubric_verdicts"] = list(payload["rubric_verdicts"].values())
    elif change == "scalar":
        payload = []
    else:
        payload["session_metadata"] = []
    output = _parse(tmp_path, payload)
    assert output.verdicts == {}
    assert output.degraded_rubric_ids == ("one", "two")


@pytest.mark.parametrize("location", ["rubric", "field", "metadata"])
def test_duplicate_json_keys_are_rejected(tmp_path, location):
    payload = json.dumps(_response())
    if location == "rubric":
        payload = payload.replace('"two": {', '"one": {')
    elif location == "field":
        payload = payload.replace('"pass": true', '"pass": false, "pass": true')
    else:
        payload = payload.replace(
            '"investigation_notes":', '"investigation_notes": "old", "investigation_notes":'
        )
    output = _parse(tmp_path, payload)
    assert not output.verdicts
    assert "duplicate" in output.judge_unavailable_reason.lower()


def test_duplicate_requested_rubric_ids_are_unavailable(tmp_path):
    data = _input()
    data.rubrics[1]["rubric_id"] = "one"
    output = _parse(tmp_path, _response(), judge_input=data)
    assert output.verdicts == {}
    assert output.judge_unavailable_reason


@pytest.mark.parametrize(
    "value",
    [[], "text", {"items_credited": "wrong"}, {"evidence_quotes": [1]}, {"items_missing": [" "]}],
)
def test_malformed_optional_structured_evidence_is_unavailable(tmp_path, value):
    payload = _response()
    payload["rubric_verdicts"]["one"]["structured_evidence"] = value
    assert not _parse(tmp_path, payload).verdicts


def test_non_json_numeric_constant_is_unavailable(tmp_path):
    payload = json.dumps(_response()).replace(
        '"session_metadata": {', '"session_metadata": {"count": NaN,'
    )
    assert not _parse(tmp_path, payload).verdicts


def test_valid_true_false_and_optional_structured_evidence_round_trip(tmp_path):
    payload = _response()
    payload["rubric_verdicts"]["one"]["structured_evidence"] = {
        "items_credited": ["criterion one"],
        "items_missing": [],
        "evidence_quotes": ["recorded finding"],
    }
    payload["rubric_verdicts"]["two"]["structured_evidence"] = None
    output = _parse(tmp_path, payload)
    assert output.verdicts["one"].passed is True
    assert output.verdicts["two"].passed is False
    assert output.verdicts["one"].structured_evidence["items_credited"] == ("criterion one",)
    assert output.judge_unavailable_reason is None


@pytest.mark.parametrize(
    "contract", ["contract_v3", "contract_v5", "cm_v3", "cm_v4", "e2e_workflow_v2"]
)
def test_all_judge_roles_receive_strict_output_requirements(contract):
    prompt = build_judge_prompt(contract)
    assert "exactly the rubric IDs" in prompt
    assert "nonempty list of nonempty strings" in prompt
    assert "strict-schema" in get_judge_prompt_version(contract)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([True, True, False], True),
        ([True, False, "invalid"], False),
        ([True, "invalid", "invalid"], None),
    ],
)
def test_valid_vote_majority_and_malformed_vote_quorum(tmp_path, values, expected):
    class Runner:
        def run_session(self, *args, cwd, **kwargs):
            value = values[int(cwd.name.split("_")[-1]) - 1]
            payload = _response()
            for verdict in payload["rubric_verdicts"].values():
                verdict["pass"] = value
            (cwd / "verdicts.json").write_text(json.dumps(payload))

    output = WorkspaceJudge(runner=Runner(), num_votes=3).judge(_input(), workspace_dir=tmp_path)
    if expected is None:
        assert not output.verdicts
        assert output.degraded_rubric_ids == ("one", "two")
        assert "InsufficientJudgeVotes" in output.judge_unavailable_reason
    else:
        assert all(verdict.passed is expected for verdict in output.verdicts.values())
        assert output.degraded_rubric_ids == ()


@pytest.mark.parametrize(
    "malformation", ["string_false", "unknown_id", "missing_id", "empty_evidence", "duplicate_id"]
)
def test_malformed_judgment_cannot_be_aggregated_or_packaged(tmp_path, monkeypatch, malformation):
    payload = _response()
    payload["rubric_verdicts"]["two"]["pass"] = True
    if malformation == "string_false":
        payload["rubric_verdicts"]["two"]["pass"] = "false"
    elif malformation == "unknown_id":
        payload["rubric_verdicts"]["other"] = deepcopy(payload["rubric_verdicts"]["one"])
    elif malformation == "missing_id":
        del payload["rubric_verdicts"]["two"]
    elif malformation == "empty_evidence":
        payload["rubric_verdicts"]["two"]["evidence_refs"] = []
    else:
        payload = json.dumps(payload).replace('"pass": true', '"pass": false, "pass": true', 1)

    class Runner:
        def run_session(self, *args, cwd, **kwargs):
            (cwd / "verdicts.json").write_text(
                payload if isinstance(payload, str) else json.dumps(payload)
            )

    monkeypatch.setattr(
        "chi_bench.verifier.stages.collect_stage_checks", lambda *args: ({"structured": True}, [])
    )
    monkeypatch.setattr(
        "chi_bench.verifier.judge.pa_um_adapter.PaUmJudgeAdapter.build", lambda self: _input()
    )
    monkeypatch.setattr(
        WorkspaceJudge,
        "judge",
        lambda self, data, **kwargs: self._judge_once(data, workspace_dir=tmp_path / "judge"),
    )
    result = task_runtime.verify_task(
        exported={},
        expectations={"verifier_contract": "contract_v5", "included_stages": ["outcome"]},
        judge=Runner(),
    )
    assert result.scorecard["scoring_status"] == "invalid"
    assert result.scorecard["fractional_reward"] is None
    assert result.scorecard["failed_checks"] == []
    assert set(result.scorecard["invalid_checks"]) == {"judge.one", "judge.two"}

    cfg = _populated_submission(tmp_path, {"pa_provider": [result.reward]})
    result_path = next(cfg.paths.output_root.rglob("result.json"))
    verifier = result_path.parent / "verifier"
    verifier.mkdir(exist_ok=True)
    (verifier / "scorecard.json").write_text(json.dumps(result.scorecard))
    with pytest.raises(ValueError, match="invalid"):
        aggregate_to_rows(cfg.paths.output_root)
    provider = next(
        row for row in status_submission(cfg)["domains"] if row["domain"] == "pa_provider"
    )
    assert provider["n_invalid"] == 1
    assert provider["n_passed"] == provider["n_failed"] == 0
    with pytest.raises(ValueError, match="invalid"):
        prepare_packet(cfg, out_dir=tmp_path / "packet")
    assert not (tmp_path / "packet").exists()
