"""Aggregator core — importable from both the installed CLI and scripts/.

The repo-root ``scripts/aggregate.py`` is the canonical CLI for paper-table
reproduction. This module hosts the functions the CLI delegates to, so they
also work when ``chi-bench`` is invoked from an installed package (where
``scripts/`` is not on the import path).

Confidence intervals are task-level percentile bootstrap 95% CIs, matching
the paper's Table 2 / Figure 3 captions. The previous Wilson score interval
implementation was replaced because pass^3 and pass@3 are per-task indicator
variables, not Bernoulli counts pooled over trials — Wilson's iid-trials
assumption mis-states the uncertainty when n_trials_per_task > 1.
"""

from __future__ import annotations

import csv
import json
import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_BOOTSTRAP_ITERS = 1000
DEFAULT_BOOTSTRAP_SEED = 0
DEFAULT_CI_ALPHA = 0.05  # → 95% CI


def _bootstrap_ci(
    values: Sequence[float],
    *,
    iters: int = DEFAULT_BOOTSTRAP_ITERS,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
    alpha: float = DEFAULT_CI_ALPHA,
) -> tuple[float, float]:
    """Task-level percentile bootstrap CI on the mean of ``values``.

    Resamples ``values`` with replacement ``iters`` times and returns the
    (1 - alpha) percentile interval of the bootstrap distribution of the
    mean. Callers should pass per-task summary values (one observation per
    task), not raw per-trial values — the unit of uncertainty is the task,
    not the trial.
    """
    n = len(values)
    if n == 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(iters):
        total = 0.0
        for _ in range(n):
            total += values[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    lo_idx = int((alpha / 2) * iters)
    hi_idx = max(0, int((1 - alpha / 2) * iters) - 1)
    return (means[lo_idx], means[hi_idx])


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


def is_per_trial_result(path: Path) -> bool:
    """True iff ``path`` is a per-trial Harbor ``result.json`` (not a run-level
    aggregate). Harbor writes both shapes under the same filename; only
    per-trial files carry a ``verifier_result`` block, so that's the signal
    used by status, aggregation, and packaging to skip aggregates.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data.get("verifier_result"), dict)


def _parse_trial(result_path: Path) -> Trial | None:
    try:
        data = json.loads(result_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    vr = data.get("verifier_result")
    if not isinstance(vr, dict):
        return None
    rb = vr.get("rewards")
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
        # `or 0` (not a get-default) so an explicit null value — emitted by the
        # openai-agents/OpenRouter path, which leaves cost/token fields None —
        # coerces to 0 instead of crashing int(None)/float(None).
        input_tokens=int(ar.get("input_tokens") or 0),
        output_tokens=int(ar.get("output_tokens") or 0),
        cache_tokens=int(ar.get("n_cache_tokens") or 0),
        wall_clock_seconds=float(ar.get("wall_clock_seconds") or 0.0),
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


def _per_task_metrics(
    by_task: dict[str, list[Trial]],
) -> tuple[list[float], list[float], list[float]]:
    """Return per-task ``(pass_at_1, pass_at_3, pass_pow_3)`` value lists.

    - ``pass_at_1[i] = k_passes_i / n_attempts_i`` (HumanEval unbiased pass@1
      estimator; degenerates to ``k/n`` for any ``n >= 1``).
    - ``pass_at_3[i] = 1.0 if any attempt passed else 0.0`` (HumanEval pass@k
      with ``k = n_attempts = 3`` reduces to "≥1 pass").
    - ``pass_pow_3[i] = 1.0 if exactly 3 attempts and all passed else 0.0``
      (consistency / "no flake").
    """
    p1: list[float] = []
    p3: list[float] = []
    pp3: list[float] = []
    for attempts in by_task.values():
        n = len(attempts)
        k_passes = sum(1 for x in attempts if x.reward >= 1.0)
        p1.append(k_passes / n if n else 0.0)
        p3.append(1.0 if k_passes > 0 else 0.0)
        pp3.append(1.0 if (n == 3 and k_passes == 3) else 0.0)
    return p1, p3, pp3


def aggregate_to_rows(
    trials_dir: Path,
    prices_path: Path | None = None,
    *,
    bootstrap_iters: int = DEFAULT_BOOTSTRAP_ITERS,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> list[dict[str, object]]:
    """Walk ``trials_dir`` for Harbor ``result.json``s, group by (agent, model),
    and return one row dict per group with pass@1 / pass@3 / pass^3 + cost.

    Each pass metric is a per-task mean (HumanEval pass@k convention) paired
    with a task-level percentile bootstrap 95% CI. The submission flow uses
    this directly and then projects down to the submission row schema; the
    paper-table CLI writes the full row shape.
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
        n1 = len(gs)
        by_task: dict[str, list[Trial]] = defaultdict(list)
        for x in gs:
            by_task[x.task_name].append(x)
        nT = len(by_task)

        p1_vec, p3_vec, pp3_vec = _per_task_metrics(by_task)

        pass1_mean = sum(p1_vec) / nT if nT else 0.0
        pass3_mean = sum(p3_vec) / nT if nT else 0.0
        passpow3_mean = sum(pp3_vec) / nT if nT else 0.0

        pass1_lo, pass1_hi = _bootstrap_ci(p1_vec, iters=bootstrap_iters, seed=bootstrap_seed)
        pass3_lo, pass3_hi = _bootstrap_ci(p3_vec, iters=bootstrap_iters, seed=bootstrap_seed)
        passpow3_lo, passpow3_hi = _bootstrap_ci(
            pp3_vec, iters=bootstrap_iters, seed=bootstrap_seed
        )

        total_cost = sum(_cost(x, prices) for x in gs)
        mean_walltime = sum(x.wall_clock_seconds for x in gs) / max(1, n1)

        rows.append(
            {
                "agent": agent,
                "model": model,
                "n_trials": n1,
                "n_tasks": nT,
                "pass_at_1": pass1_mean,
                "pass_at_1_lo": pass1_lo,
                "pass_at_1_hi": pass1_hi,
                "pass_at_3": pass3_mean,
                "pass_at_3_lo": pass3_lo,
                "pass_at_3_hi": pass3_hi,
                "pass_pow_3": passpow3_mean,
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
    bootstrap_iters: int = DEFAULT_BOOTSTRAP_ITERS,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> None:
    rows = aggregate_to_rows(
        trials_dir,
        prices_path,
        bootstrap_iters=bootstrap_iters,
        bootstrap_seed=bootstrap_seed,
    )
    write_rows_csv(rows, out_csv)
    if rows and out_json is not None:
        out_json.write_text(json.dumps(rows, indent=2))
