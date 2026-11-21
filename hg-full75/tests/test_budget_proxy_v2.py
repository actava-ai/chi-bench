"""Free, offline tests for the reconciled budget proxy and the resume guard."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import chi_budget_proxy as bp  # noqa: E402
import chi_resume_guard as guard  # noqa: E402

PRICES = {"m": {"input": 1.0, "output": 6.0, "cache_read": 0.1, "cache_write": 1.25}}


def test_reservation_counts_tokens_not_bytes():
    led = bp.Ledger(10.0, None, PRICES)
    body = json.dumps({"model": "m", "input": "x" * 40000}).encode()
    _, amount = led.reserve("m", body, 1000)
    assert 0 < amount < len(body) / 1e6  # byte-based reservation would be ~4x larger
    assert amount >= 1000 * 6.0 / 1e6  # output floor is always reserved


def test_openai_usage_is_not_double_counted():
    usage = {"input_tokens": 1000, "output_tokens": 100,
             "input_tokens_details": {"cached_tokens": 900}}
    cost = bp.usage_cost(usage, PRICES["m"])
    assert abs(cost - (100 * 1.0 + 900 * 0.1 + 100 * 6.0) / 1e6) < 1e-12


def test_anthropic_usage_excludes_cache_and_discounts_it():
    usage = {"input_tokens": 1000, "cache_read_input_tokens": 2000,
             "cache_creation_input_tokens": 500, "output_tokens": 100}
    cost = bp.usage_cost(usage, PRICES["m"])
    assert abs(cost - (1000 * 1.0 + 2000 * 0.1 + 500 * 1.25 + 100 * 6.0) / 1e6) < 1e-12


def test_no_cache_discount_without_reported_hits():
    usage = {"input_tokens": 1000, "output_tokens": 0}
    assert abs(bp.usage_cost(usage, PRICES["m"]) - 1000 * 1.0 / 1e6) < 1e-12


def test_unknown_model_is_denied_and_counted():
    led = bp.Ledger(10.0, None, PRICES)
    try:
        led.reserve("not-a-model", b'{"model":"x"}', 10)
    except bp.BudgetDenied as exc:
        assert "unpriced" in str(exc)
    else:
        raise AssertionError("unknown model must be denied")
    assert led.calls == 0


def test_cap_is_enforced_before_forwarding():
    led = bp.Ledger(0.010, None, PRICES)
    led.reserve("m", b"{}", 1000)
    try:
        led.reserve("m", b"{}", 1000)
    except bp.BudgetDenied:
        pass
    else:
        raise AssertionError("second call must not fit under the cap")
    assert led.denied == 1 and led.calls == 1


def test_settlement_never_exceeds_the_reservation_and_flags_it():
    led = bp.Ledger(10.0, None, {"m": {"input": 1.0, "output": 1.0, "cache_read": 1.0, "cache_write": 1.0}})
    rid, amount = led.reserve("m", b"{}", 1)
    led.settle(rid, "m", {"input_tokens": 10_000_000, "output_tokens": 1})
    assert led.spent == amount and led.settle_capped == 1


def test_adjustments_are_append_only_and_drive_the_cap(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"cap": 45.0, "spent": 40.0, "reserved": {}, "calls": 3, "denied": 0}))
    led = bp.Ledger(45.0, path, PRICES)
    led.add_adjustment(-39.0, "reconcile:test", {"evidence": ["rollout"]})
    snap = led.snapshot()
    assert snap["gross_spent_usd"] == 40.0
    assert snap["adjustments_usd"] == -39.0
    assert snap["spent_usd"] == 1.0
    saved = json.loads(path.read_text())
    assert saved["spent"] == 40.0 and len(saved["adjustments"]) == 1


def test_inflight_reservations_become_spend_after_restart(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"cap": 45.0, "spent": 1.0, "reserved": {"a": 0.5}, "calls": 1, "denied": 0}))
    led = bp.Ledger(45.0, path, PRICES)
    assert led.spent == 1.5 and led.reserved == {}


def test_interrupted_marker_retires_a_task_without_replay(tmp_path):
    out = tmp_path / "task"
    out.mkdir()
    fp = "f" * 64
    (out / guard.INTERRUPTED_MARKER).write_text(json.dumps({
        "state": guard.INTERRUPTED_STATE, "task_id": "t", "fingerprint": fp,
        "reason": "budget_denied_402", "approved_by": "owner", "evidence": ["402"],
    }))
    assert guard.classify_task(out, fp, "t") == guard.INTERRUPTED_STATE
    pending, completed, interrupted, rejudged = guard.resume_rows(
        [("t", ["cmd"], out)], fp)
    assert (pending, completed, interrupted, rejudged) == ([], [], ["t"], [])


def test_interrupted_marker_must_match_task_fingerprint_and_reason(tmp_path):
    out = tmp_path / "task"
    out.mkdir()
    (out / guard.INTERRUPTED_MARKER).write_text(json.dumps({
        "state": guard.INTERRUPTED_STATE, "task_id": "other", "fingerprint": "x",
        "reason": "because", "approved_by": "owner", "evidence": ["e"],
    }))
    assert guard.classify_task(out, "f" * 64, "t") == "ambiguous_do_not_replay"
    try:
        guard.resume_rows([("t", ["cmd"], out)], "f" * 64)
    except ValueError:
        pass
    else:
        raise AssertionError("an unverifiable marker must still block resumption")
