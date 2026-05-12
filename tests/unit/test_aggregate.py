import json
import csv
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


def test_aggregate_produces_pass_at_1_and_wilson(tmp_path):
    from scripts.aggregate import aggregate

    trials = tmp_path / "trials"
    # 3 tasks × 3 attempts each. 4/9 pass.
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
    # pass@1: 4/9 ≈ 0.4444
    assert abs(float(r["pass_at_1"]) - 4 / 9) < 1e-6
    # Wilson lo/hi columns present and within [0,1]
    assert 0.0 <= float(r["pass_at_1_lo"]) < float(r["pass_at_1"])
    assert float(r["pass_at_1"]) < float(r["pass_at_1_hi"]) <= 1.0
    # pass@3 per-task: 2/3 (t1 + t3 each have ≥1 pass; t2 has 0)
    assert abs(float(r["pass_at_3"]) - 2 / 3) < 1e-6
    # pass^3 per-task: 0/3 (no task has all 3 attempts passing)
    assert abs(float(r["pass_pow_3"]) - 0.0) < 1e-6


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
