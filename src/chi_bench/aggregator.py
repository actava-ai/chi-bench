"""Aggregator core — importable from both the installed CLI and scripts/.

The repo-root ``scripts/aggregate.py`` is the canonical CLI for paper Table 1
reproduction. This module hosts the functions the CLI delegates to, so they
also work when ``chi-bench`` is invoked from an installed package (where
``scripts/`` is not on the import path).
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml


def wilson_score_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Return (low, high) of the Wilson 95% CI for k successes in n trials."""
    if n <= 0:
        return (0.0, 0.0)
    p_hat = k / n
    denom = 1 + z * z / n
    centre = p_hat + z * z / (2 * n)
    margin = z * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n))
    lo = (centre - margin) / denom
    hi = (centre + margin) / denom
    return (max(0.0, lo), min(1.0, hi))


@dataclass
class Trial:
    task_name: str
    agent: str
    model: str
    reward: float
    input_tokens: int
    output_tokens: int
    cache_tokens: int
    wall_clock_seconds: float


def _parse_trial(result_path: Path) -> Trial | None:
    data = json.loads(result_path.read_text())
    vr = data.get("verifier_result") or {}
    rb = vr.get("rewards") if isinstance(vr, dict) else None
    reward = float((rb or {}).get("reward", 0.0)) if rb else float(vr.get("reward", 0.0))
    ar = data.get("agent_result") or {}
    info = (data.get("agent_info") or {}).get("model_info") or {}
    provider = info.get("provider") or "unknown"
    name = info.get("name") or "unknown"
    model = f"{provider}/{name}"
    agent = (data.get("agent_info") or {}).get("agent", info.get("agent", "unknown"))
    if agent == "unknown":
        agent = data.get("agent") or "unknown"
    task_path = (data.get("task") or {}).get("path") or ""
    task_name = Path(task_path).name or result_path.parent.name.split("__", 1)[0]
    return Trial(
        task_name=task_name,
        agent=agent,
        model=model,
        reward=reward,
        input_tokens=int(ar.get("input_tokens", 0)),
        output_tokens=int(ar.get("output_tokens", 0)),
        cache_tokens=int(ar.get("n_cache_tokens", 0)),
        wall_clock_seconds=float(ar.get("wall_clock_seconds", 0.0)),
    )


def _load_prices(path: Path | None) -> dict[str, dict[str, float]]:
    if path is None or not path.exists():
        return {}
    return yaml.safe_load(path.read_text()).get("prices", {})


def _cost(trial: Trial, prices: dict[str, dict[str, float]]) -> float:
    p = prices.get(trial.model) or {}
    inp = p.get("input", 0.0)
    out = p.get("output", 0.0)
    cache = p.get("cache", inp * 0.1)
    return (
        trial.input_tokens / 1_000_000.0 * inp
        + trial.output_tokens / 1_000_000.0 * out
        + trial.cache_tokens / 1_000_000.0 * cache
    )


def aggregate_to_rows(
    trials_dir: Path,
    prices_path: Path | None = None,
) -> list[dict[str, object]]:
    """Walk ``trials_dir`` for Harbor ``result.json``s, group by (agent, model),
    and return one row dict per group with pass@1 / pass@3 / pass^3 + cost.

    The submission flow uses this directly and then projects down to the
    submission row schema; the paper-Table-1 CLI writes the full row shape.
    """
    trials: list[Trial] = []
    for result_json in trials_dir.rglob("result.json"):
        t = _parse_trial(result_json)
        if t is not None:
            trials.append(t)

    prices = _load_prices(prices_path)

    groups: dict[tuple[str, str], list[Trial]] = defaultdict(list)
    for t in trials:
        groups[(t.agent, t.model)].append(t)

    rows: list[dict[str, object]] = []
    for (agent, model), gs in sorted(groups.items()):
        k1 = sum(1 for x in gs if x.reward >= 1.0)
        n1 = len(gs)
        by_task: dict[str, list[Trial]] = defaultdict(list)
        for x in gs:
            by_task[x.task_name].append(x)
        k3 = sum(1 for ts in by_task.values() if any(x.reward >= 1.0 for x in ts))
        kpow3 = sum(
            1 for ts in by_task.values() if len(ts) >= 3 and all(x.reward >= 1.0 for x in ts)
        )
        nT = len(by_task)

        pass1_lo, pass1_hi = wilson_score_interval(k1, n1)
        pass3_lo, pass3_hi = wilson_score_interval(k3, nT)
        passpow3_lo, passpow3_hi = wilson_score_interval(kpow3, nT)

        total_cost = sum(_cost(x, prices) for x in gs)
        mean_walltime = sum(x.wall_clock_seconds for x in gs) / max(1, n1)

        rows.append(
            {
                "agent": agent,
                "model": model,
                "n_trials": n1,
                "n_tasks": nT,
                "pass_at_1": k1 / max(1, n1),
                "pass_at_1_lo": pass1_lo,
                "pass_at_1_hi": pass1_hi,
                "pass_at_3": k3 / max(1, nT),
                "pass_at_3_lo": pass3_lo,
                "pass_at_3_hi": pass3_hi,
                "pass_pow_3": kpow3 / max(1, nT),
                "pass_pow_3_lo": passpow3_lo,
                "pass_pow_3_hi": passpow3_hi,
                "mean_cost_usd": total_cost / max(1, n1),
                "mean_walltime_s": mean_walltime,
            }
        )
    return rows


def write_rows_csv(rows: list[dict[str, object]], out_csv: Path) -> None:
    """Write aggregator rows to ``out_csv``; no-op when ``rows`` is empty."""
    if not rows:
        return
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def aggregate(
    *,
    trials_dir: Path,
    prices_path: Path | None,
    out_csv: Path,
    out_json: Path | None,
) -> None:
    rows = aggregate_to_rows(trials_dir, prices_path)
    write_rows_csv(rows, out_csv)
    if rows and out_json is not None:
        out_json.write_text(json.dumps(rows, indent=2))
