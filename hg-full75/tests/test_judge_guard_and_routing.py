"""Offline tests for judge-invalid classification and judge routing (no model calls)."""
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import chi_resume_guard as guard  # noqa: E402

FP = "f" * 64
TID = "pa_t013_test"


def _trial(tmp_path, *, checks, stdout="", scoring="invalid", invalid_checks=None):
    out = tmp_path / "trial"
    (out / "verifier").mkdir(parents=True)
    names = invalid_checks if invalid_checks is not None else ["judge.a", "judge.b"]
    validity = {"scoring_status": scoring, "invalid_checks": names if scoring == "invalid" else []}
    (out / "verifier" / "validity.json").write_text(json.dumps(validity))
    (out / "verifier" / "reward.json").write_text('{"reward": 0.0}')
    (out / "verifier" / "scorecard.json").write_text(json.dumps({"checks": checks}))
    (out / "verifier" / "test-stdout.txt").write_text(stdout)
    return out


def _marker(out, reason="judge_invalid_no_replay", **extra):
    sha = hashlib.sha256((out / "verifier" / "validity.json").read_bytes()).hexdigest()
    m = {"state": guard.INTERRUPTED_STATE, "task_id": TID, "fingerprint": FP, "reason": reason,
         "approved_by": "owner", "evidence": ["validity.json"], "validity_sha256": sha}
    m.update(extra)
    (out / guard.INTERRUPTED_MARKER).write_text(json.dumps(m))
    return m


def test_genuine_invalid_verdict_is_retired_without_replay(tmp_path):
    out = _trial(tmp_path, checks={"judge.a": False, "judge.b": False}, stdout="ok")
    _marker(out)
    assert guard.classify_task(out, FP, TID) == guard.INTERRUPTED_STATE


def test_judge_outage_is_not_a_genuine_invalid(tmp_path):
    # Shape of t013: validity says invalid, but the judge never evaluated the checks.
    out = _trial(tmp_path, checks={"judge.a": "unavailable", "judge.b": "unavailable"},
                 stdout="Judge session failed for CASE-1: Claude CLI exited 1")
    _marker(out)
    assert guard.classify_task(out, FP, TID) == "ambiguous_do_not_replay"


def test_failed_check_text_alone_blocks_retirement(tmp_path):
    out = _trial(tmp_path, checks={"judge.a": False, "judge.b": False},
                 stdout="Judge session failed for CASE-1")
    _marker(out)
    assert guard.classify_task(out, FP, TID) == "ambiguous_do_not_replay"


def test_marker_hash_must_match_the_validity_file(tmp_path):
    out = _trial(tmp_path, checks={"judge.a": False, "judge.b": False})
    _marker(out)
    (out / "verifier" / "validity.json").write_text(json.dumps({"scoring_status": "invalid", "invalid_checks": ["x"]}))
    assert guard.classify_task(out, FP, TID) == "ambiguous_do_not_replay"


def test_valid_trial_cannot_be_retired_as_invalid(tmp_path):
    out = _trial(tmp_path, checks={}, scoring="valid")
    _marker(out)
    assert guard.classify_task(out, FP, TID) == "ambiguous_do_not_replay"


def test_judge_infrastructure_reason_is_not_accepted(tmp_path):
    out = _trial(tmp_path, checks={"judge.a": False, "judge.b": False})
    _marker(out, reason="judge_infra_failure")
    assert guard.classify_task(out, FP, TID) == "ambiguous_do_not_replay"


def _rejudged_task(tmp_path, *, judge_checks=None, validity="valid", binary=0.0):
    """Original trial (untouched) plus a side-by-side rejudge, as the guard expects."""
    import shutil
    out = tmp_path / "task"
    trial = out / "pa_trial__abc"
    (trial / "verifier").mkdir(parents=True)
    (trial / "verifier" / "scorecard.json").write_text('{"checks": {}}')
    (trial / "result.json").write_text("{}")
    rj = out / guard.REJUDGED_DIR
    rj.mkdir()
    checks = judge_checks if judge_checks is not None else {"judge.a": True, "judge.b": False}
    (rj / "validity.json").write_text(json.dumps({"scoring_status": validity, "invalid_checks": []}))
    (rj / "scorecard.json").write_text(json.dumps({"checks": checks, "binary_reward": binary}))
    (rj / "verdicts.json").write_text("{}")
    files = {n: hashlib.sha256((rj / n).read_bytes()).hexdigest() for n in ("validity.json", "scorecard.json", "verdicts.json")}
    marker = {"state": guard.REJUDGED_STATE, "task_id": TID, "fingerprint": FP, "approved_by": "owner",
              "trial_name": trial.name, "trial_manifest_sha256": guard.digest(guard.artifact_hashes(trial)),
              "files_sha256": files}
    (out / guard.REJUDGED_MARKER).write_text(json.dumps(marker))
    return out


def test_valid_rejudge_is_accepted_without_replay(tmp_path):
    out = _rejudged_task(tmp_path)
    assert guard.classify_task(out, FP, TID) == guard.REJUDGED_STATE
    pending, completed, interrupted, rejudged = guard.resume_rows([(TID, ["cmd"], out)], FP)
    assert (pending, completed, interrupted, rejudged) == ([], [], [], [TID])


def test_rejudge_is_rejected_if_the_original_trial_changes(tmp_path):
    out = _rejudged_task(tmp_path)
    (out / "pa_trial__abc" / "result.json").write_text('{"tampered": true}')
    assert guard.classify_task(out, FP, TID) == "ambiguous_do_not_replay"


def test_rejudge_is_rejected_if_a_judge_rubric_was_never_evaluated(tmp_path):
    out = _rejudged_task(tmp_path, judge_checks={"judge.a": "unavailable", "judge.b": True})
    assert guard.classify_task(out, FP, TID) == "ambiguous_do_not_replay"


def test_rejudge_with_invalid_scoring_is_rejected(tmp_path):
    out = _rejudged_task(tmp_path, validity="invalid")
    assert guard.classify_task(out, FP, TID) == "ambiguous_do_not_replay"


def test_resume_still_refuses_unresolved_judge_outage(tmp_path):
    out = _trial(tmp_path, checks={"judge.a": "unavailable", "judge.b": "unavailable"},
                 stdout="Judge session failed")
    with pytest.raises(ValueError):
        guard.resume_rows([(TID, ["cmd"], out)], FP)


def _runner_cls():
    src = Path("/opt/chi-bench/src")
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from chi_bench.verifier.judge import claude_runner
    return claude_runner.ClaudeAgentRunner


def _env_for(monkeypatch, **env):
    for k in ("ANTHROPIC_BASE_URL", "HG_JUDGE_ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_rejudge_pins_the_run_judge_model(monkeypatch):
    src = Path("/opt/chi-bench/src")
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from chi_bench.verifier import rejudge
    monkeypatch.delenv("CHI_BENCH_JUDGE_MODEL", raising=False)
    assert rejudge.rejudge_judge_model() == "claude-opus-4-7"
    monkeypatch.setenv("CHI_BENCH_JUDGE_MODEL", "claude-opus-4-7")
    assert rejudge.rejudge_judge_model() == "claude-opus-4-7"
    assert 'ClaudeAgentRunner(model="opus"' not in (src / "chi_bench/verifier/rejudge.py").read_text()


def test_judge_is_routed_through_the_budget_proxy(monkeypatch):
    cls = _runner_cls()
    _env_for(monkeypatch, ANTHROPIC_BASE_URL="http://agent.example/anthropic",
             HG_JUDGE_ANTHROPIC_BASE_URL="http://host.docker.internal:18045/anthropic")
    r = object.__new__(cls)
    r.max_output_tokens = None
    r._auth_logged_in = False
    r._auth_method = "api_key"
    env = r._subprocess_env()
    assert env["ANTHROPIC_BASE_URL"] == "http://host.docker.internal:18045/anthropic"
