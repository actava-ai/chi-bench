"""The current E2E verifier is the only accepted E2E aggregation contract."""

import json

import pytest

from chi_bench.aggregator import aggregate_to_rows


def _trial(root, name, protocol, *, exported_protocol="same", scorecard=True):
    trial = root / name
    (trial / "verifier").mkdir(parents=True)
    (trial / "result.json").write_text(
        json.dumps(
            {
                "task_name": "pa_t014_t014_o001_p01_e2e",
                "agent_info": {
                    "name": "dual-pa-e2e",
                    "model_info": {"provider": "synthetic", "name": "model"},
                },
                "verifier_result": {"rewards": {"reward": 1}},
            }
        )
    )
    if scorecard:
        score = {"scoring_status": "valid", "e2e_protocol_source": "trusted_runtime_export"}
        if protocol is not None:
            score["e2e_protocol"] = protocol
        (trial / "verifier/scorecard.json").write_text(json.dumps(score))
    if exported_protocol != "same":
        (trial / "verifier/exported_state.json").write_text(
            json.dumps({"e2e_protocol": exported_protocol})
        )


@pytest.mark.parametrize("protocol", ["dual_viewpoint_v1", None, "unknown-protocol"])
def test_old_unversioned_or_unknown_e2e_score_is_rejected(tmp_path, protocol):
    _trial(tmp_path, "old", protocol)
    with pytest.raises(ValueError, match="E2E|protocol|workflow_v2"):
        aggregate_to_rows(tmp_path)


def test_e2e_without_scorecard_is_rejected(tmp_path):
    _trial(tmp_path, "old", None, scorecard=False)
    with pytest.raises(ValueError, match="E2E|protocol|workflow_v2"):
        aggregate_to_rows(tmp_path)


def test_mixed_old_and_new_e2e_scores_are_rejected(tmp_path):
    _trial(tmp_path, "old", "dual_viewpoint_v1")
    _trial(tmp_path, "new", "workflow_v2")
    with pytest.raises(ValueError, match="E2E|protocol|workflow_v2"):
        aggregate_to_rows(tmp_path)


def test_current_e2e_row_retains_protocol(tmp_path):
    _trial(tmp_path, "new", "workflow_v2")
    row = aggregate_to_rows(tmp_path)[0]
    assert row["e2e_protocol"] == "workflow_v2"
    assert row["n_trials"] == 1


def test_conflicting_export_and_score_protocol_is_rejected(tmp_path):
    _trial(tmp_path, "conflict", "workflow_v2", exported_protocol="dual_viewpoint_v1")
    with pytest.raises(ValueError, match="E2E|protocol|workflow_v2"):
        aggregate_to_rows(tmp_path)
