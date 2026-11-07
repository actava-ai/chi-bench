"""Offline regression checks for Payer t015 judge-schema failure.

No network, judge calls, rejudge, or result rewriting. The production validator
must reject incomplete or spurious rubric IDs instead of inventing pass/fail.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from chi_bench.verifier.judge.workspace_judge import _validate_verdicts


IDS = [f"rubric_{i}" for i in range(8)]


def valid_payload():
    return {
        "rubric_verdicts": {
            rid: {
                "pass": False,
                "explanation": "Offline fixture: explicit grounded assessment.",
                "evidence_refs": ["fixture://exported-state"],
            }
            for rid in IDS
        },
        "session_metadata": {"test": True},
    }


def test_exact_eight_rubrics_validate():
    result = _validate_verdicts(valid_payload(), IDS)
    assert set(result) == set(IDS)
    assert all(v.passed is False for v in result.values())


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong_id", "not_object"])
def test_mismatched_rubric_ids_fail_closed(mutation):
    payload = valid_payload()
    rubric_map = payload["rubric_verdicts"]
    if mutation == "missing":
        rubric_map.pop(IDS[-1])
    elif mutation == "extra":
        rubric_map["unrequested_id"] = rubric_map[IDS[0]].copy()
    elif mutation == "wrong_id":
        rubric_map["relabelled_id"] = rubric_map.pop(IDS[-1])
    else:
        payload["rubric_verdicts"] = []
    with pytest.raises(ValueError, match="exactly the requested rubric IDs"):
        _validate_verdicts(payload, IDS)


def test_duplicate_requested_ids_fail_closed():
    with pytest.raises(ValueError, match="duplicate requested rubric IDs"):
        _validate_verdicts(valid_payload(), IDS + [IDS[0]])


def test_nonboolean_pass_and_unsubstantiated_evidence_fail_closed():
    payload = valid_payload()
    payload["rubric_verdicts"][IDS[0]]["pass"] = "true"
    with pytest.raises(ValueError, match="JSON boolean"):
        _validate_verdicts(payload, IDS)
    payload = valid_payload()
    payload["rubric_verdicts"][IDS[0]]["evidence_refs"] = []
    with pytest.raises(ValueError, match="nonempty strings"):
        _validate_verdicts(payload, IDS)
