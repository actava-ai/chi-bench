import csv
import json
from pathlib import Path


def _make_trial(
    tmp: Path,
    name: str,
    reward: float,
    n_in: int,
    n_out: int,
    cache: int,
    walltime: float,
    model: str = "openai/gpt-5.5",
    agent: str = "codex",
) -> None:
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "result.json").write_text(
        json.dumps(
            {
                "verifier_result": {"rewards": {"reward": reward}},
                "agent_result": {
                    "input_tokens": n_in,
                    "output_tokens": n_out,
                    "n_cache_tokens": cache,
                    "wall_clock_seconds": walltime,
                },
                "agent_info": {
                    "agent": agent,
                    "model_info": {"provider": model.split("/")[0], "name": model.split("/", 1)[1]},
                },
                "task": {"path": f"data/prior_auth_um/tasks/{name.split('__')[0]}"},
            }
        )
    )
    # reward.txt sentinel — aggregate.py checks for completion.
    (d / "reward.txt").write_text(str(reward))


def _make_harbor_020_trial(
    tmp: Path,
    name: str,
    *,
    reward: float,
    agent_result: dict[str, object] | None,
    agent_execution: dict[str, str | None] | None,
    exception_info: dict[str, str] | None = None,
    task_name: str = "datasets/chi-bench/task-current",
    model: str = "openai/gpt-5.6-sol",
    agent: str = "openai-agents",
) -> Path:
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    result_path = d / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "task_name": task_name,
                "verifier_result": {"rewards": {"reward": reward}},
                "agent_result": agent_result,
                "agent_execution": agent_execution,
                "exception_info": exception_info,
                "agent_info": {
                    "name": agent,
                    "version": "1.0.0",
                    "model_info": {
                        "provider": model.split("/")[0],
                        "name": model.split("/", 1)[1],
                    },
                },
            }
        )
    )
    return result_path


def test_aggregate_reads_harbor_020_agent_context_and_cost(tmp_path):
    from chi_bench.aggregator import _parse_trial, aggregate_to_rows

    trials = tmp_path / "trials"
    result_dir = trials / "trial-directory-name"
    result_dir.mkdir(parents=True)
    result_path = result_dir / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "task_name": "datasets/chi-bench/provider/task-current",
                "verifier_result": {"rewards": {"reward": 1.0}},
                "agent_result": {
                    "n_input_tokens": 4_219_791,
                    "n_output_tokens": 30_206,
                    "n_cache_tokens": 4_052_796,
                    "input_tokens": 9_999,
                    "output_tokens": 9_999,
                    # Aggregation deliberately uses normalized price-table
                    # rates rather than this provider-reported total.
                    "cost_usd": 3.8251855,
                },
                "agent_execution": {
                    "started_at": "2026-07-24T12:00:00+00:00",
                    "finished_at": "2026-07-24T12:00:12.500000+00:00",
                },
                "agent_info": {
                    "name": "claude-code",
                    "version": "2.1.219",
                    "model_info": {
                        "provider": "anthropic",
                        "name": "claude-opus-5",
                    },
                },
            }
        )
    )
    prices_path = tmp_path / "prices.yaml"
    prices_path.write_text(
        """
prices:
  anthropic/claude-opus-5:
    input: 5.0
    output: 25.0
    cache: 0.5
"""
    )

    trial = _parse_trial(result_path)
    assert trial is not None
    assert trial.task_name == "task-current"
    assert trial.agent == "claude-code"
    assert trial.input_tokens == 4_219_791
    assert trial.output_tokens == 30_206
    assert trial.cache_tokens == 4_052_796
    assert trial.wall_clock_seconds == 12.5

    rows = aggregate_to_rows(trials, prices_path)
    assert len(rows) == 1
    assert abs(float(rows[0]["mean_cost_usd"]) - 3.616523) < 1e-12


def test_parse_trial_keeps_legacy_usage_field_fallback(tmp_path):
    from chi_bench.aggregator import _parse_trial

    trials = tmp_path / "trials"
    _make_trial(
        trials,
        "legacy-task__abc",
        reward=1.0,
        n_in=1_000,
        n_out=200,
        cache=400,
        walltime=12.5,
    )

    trial = _parse_trial(trials / "legacy-task__abc" / "result.json")
    assert trial is not None
    assert trial.input_tokens == 1_000
    assert trial.output_tokens == 200
    assert trial.cache_tokens == 400
    assert trial.wall_clock_seconds == 12.5


def test_parse_trial_reads_harbor_020_fields(tmp_path):
    from chi_bench.aggregator import _parse_trial

    result_path = _make_harbor_020_trial(
        tmp_path,
        "trial-directory-name",
        reward=1.0,
        task_name="datasets/chi-bench/provider/task-current",
        agent_result={
            "n_input_tokens": 1_000,
            "n_output_tokens": 200,
            "n_cache_tokens": 400,
            # Conflicting legacy values prove the current schema wins.
            "input_tokens": 9_999,
            "output_tokens": 9_999,
            "wall_clock_seconds": 999.0,
        },
        agent_execution={
            "started_at": "2026-07-21T12:00:00+00:00",
            "finished_at": "2026-07-21T12:00:12.500000+00:00",
        },
    )

    trial = _parse_trial(result_path)

    assert trial is not None
    assert trial.task_name == "task-current"
    assert trial.agent == "openai-agents"
    assert trial.model == "openai/gpt-5.6-sol"
    assert trial.reward == 1.0
    assert trial.input_tokens == 1_000
    assert trial.output_tokens == 200
    assert trial.cache_tokens == 400
    assert trial.wall_clock_seconds == 12.5


def test_cost_does_not_charge_cached_tokens_twice():
    from chi_bench.aggregator import Trial, _cost

    trial = Trial(
        task_name="task-current",
        agent="openai-agents",
        model="openai/gpt-5.6-sol",
        reward=1.0,
        input_tokens=1_000,
        output_tokens=200,
        cache_tokens=400,
        wall_clock_seconds=12.5,
    )
    prices = {"openai/gpt-5.6-sol": {"input": 2.0, "output": 4.0, "cache": 0.2}}

    # Harbor's n_input_tokens includes cache: 600 uncached input + 400 cache.
    assert abs(_cost(trial, prices) - 0.00208) < 1e-12


def test_cost_does_not_produce_negative_uncached_input_charge():
    from chi_bench.aggregator import Trial, _cost

    trial = Trial(
        task_name="task-current",
        agent="openai-agents",
        model="openai/gpt-5.6-sol",
        reward=0.0,
        input_tokens=100,
        output_tokens=0,
        cache_tokens=200,
        wall_clock_seconds=0.0,
    )
    prices = {"openai/gpt-5.6-sol": {"input": 2.0, "output": 4.0, "cache": 0.2}}

    assert abs(_cost(trial, prices) - 0.00004) < 1e-12


def test_parse_trial_prefers_zero_current_duration_over_legacy_walltime(tmp_path):
    from chi_bench.aggregator import _parse_trial

    result_path = _make_harbor_020_trial(
        tmp_path,
        "zero-duration-trial",
        reward=0.0,
        agent_result={"wall_clock_seconds": 999.0},
        agent_execution={
            "started_at": "2026-07-21T12:00:00+00:00",
            "finished_at": "2026-07-21T12:00:00+00:00",
        },
    )

    trial = _parse_trial(result_path)

    assert trial is not None
    assert trial.wall_clock_seconds == 0.0


def test_aggregate_keeps_reward_when_harbor_020_agent_result_is_null(tmp_path):
    from chi_bench.aggregator import aggregate_to_rows

    trials = tmp_path / "trials"
    _make_harbor_020_trial(
        trials,
        "failed-agent-trial",
        reward=1.0,
        agent_result=None,
        agent_execution={"started_at": None, "finished_at": None},
        exception_info={
            "exception_type": "RuntimeError",
            "exception_message": "agent failed before reporting usage",
            "exception_traceback": "RuntimeError: agent failed before reporting usage",
            "occurred_at": "2026-07-21T12:00:00+00:00",
        },
    )

    rows = aggregate_to_rows(trials)

    assert len(rows) == 1
    assert rows[0]["agent"] == "openai-agents"
    assert rows[0]["n_tasks"] == 1
    assert rows[0]["pass_at_1"] == 1.0
    assert rows[0]["mean_cost_usd"] == 0.0
    assert rows[0]["mean_walltime_s"] == 0.0


def test_aggregate_produces_pass_at_1_and_bootstrap_ci(tmp_path):
    from scripts.aggregate import aggregate

    trials = tmp_path / "trials"
    # 3 tasks × 3 attempts each. 4/9 trials pass (mixed within and across tasks).
    _make_trial(trials, "t1__abc", 1.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t1__def", 1.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t1__ghi", 0.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t2__abc", 0.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t2__def", 0.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t2__ghi", 0.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t3__abc", 1.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t3__def", 1.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t3__ghi", 0.0, 1000, 500, 0, 10.0)

    out_csv = tmp_path / "table.csv"
    aggregate(trials_dir=trials, prices_path=None, out_csv=out_csv, out_json=None)

    rows = list(csv.DictReader(out_csv.open()))
    assert len(rows) == 1
    r = rows[0]
    assert r["agent"] == "codex"
    assert r["model"] == "openai/gpt-5.5"
    # pass@1 per-task mean: (2/3 + 0/3 + 2/3) / 3 = 4/9 (same as pooled here
    # because n_attempts is uniform across tasks).
    assert abs(float(r["pass_at_1"]) - 4 / 9) < 1e-6
    # pass@3 per-task: 2/3 (t1 + t3 each have ≥1 pass; t2 has 0)
    assert abs(float(r["pass_at_3"]) - 2 / 3) < 1e-6
    # pass^3 per-task: 0/3 (no task has all 3 attempts passing)
    assert abs(float(r["pass_pow_3"]) - 0.0) < 1e-6
    # Bootstrap CI columns present and bracket the point estimate.
    assert 0.0 <= float(r["pass_at_1_lo"]) <= float(r["pass_at_1"])
    assert float(r["pass_at_1"]) <= float(r["pass_at_1_hi"]) <= 1.0
    # pass^3 is identically zero, so its CI collapses to [0, 0].
    assert float(r["pass_pow_3_lo"]) == 0.0
    assert float(r["pass_pow_3_hi"]) == 0.0


def test_aggregate_bootstrap_seed_is_deterministic(tmp_path):
    """Two runs with the same seed must yield byte-identical CI columns."""
    from scripts.aggregate import aggregate

    trials = tmp_path / "trials"
    _make_trial(trials, "t1__a", 1.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t1__b", 0.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t1__c", 0.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t2__a", 1.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t2__b", 1.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t2__c", 0.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t3__a", 1.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t3__b", 1.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t3__c", 1.0, 1000, 500, 0, 10.0)

    out_a = tmp_path / "a.csv"
    out_b = tmp_path / "b.csv"
    aggregate(trials_dir=trials, prices_path=None, out_csv=out_a, out_json=None)
    aggregate(trials_dir=trials, prices_path=None, out_csv=out_b, out_json=None)
    assert out_a.read_text() == out_b.read_text()


def test_aggregate_ignores_run_level_aggregate_result_json(tmp_path):
    # Harbor writes a per-run aggregate result.json (no verifier_result block)
    # alongside the per-trial dirs. _parse_trial must skip it; otherwise it
    # surfaces as a stray ("unknown", "unknown/unknown") group with reward 0.
    from chi_bench.aggregator import aggregate_to_rows

    trials = tmp_path / "trials"
    _make_trial(trials, "t1__abc", 1.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t1__def", 0.0, 1000, 500, 0, 10.0)
    # Run-level aggregate sibling: same filename, different shape.
    (trials / "result.json").write_text(
        json.dumps({"id": "agg", "n_total_trials": 2, "stats": {"n_trials": 2}})
    )

    rows = aggregate_to_rows(trials)
    assert len(rows) == 1
    r = rows[0]
    assert (r["agent"], r["model"]) == ("codex", "openai/gpt-5.5")
    assert r["n_trials"] == 2
    assert abs(float(r["pass_at_1"]) - 0.5) < 1e-6
