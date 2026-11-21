#!/usr/bin/env python3
"""Reconcile the Full75 budget ledger against real usage and verified prices.

Reads the per-task codex rollouts (client-side record of provider-reported usage),
prices every token with the pinned table from ``chi_budget_proxy``, and appends a
single audited correction to the ledger.

It never rewrites or deletes historical spend: ``spent`` stays as recorded and the
correction lives in ``adjustments`` with its evidence. Spend counted against the cap
becomes ``spent + adjustments``.

    reconcile_ledger.py --results ... --ledger ... --prices ... --unverified-baseline-usd 1.229775 [--apply]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import chi_budget_proxy as bp


def _last_usage(path: Path) -> dict | None:
    """Largest (i.e. cumulative) usage block in a codex rollout jsonl."""
    best, best_total = None, -1.0
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or '"usage"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            stack = [obj]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    if "input_tokens" in node or "prompt_tokens" in node:
                        total = float(node.get("input_tokens", node.get("prompt_tokens", 0)) or 0) \
                            + float(node.get("output_tokens", node.get("completion_tokens", 0)) or 0)
                        if total >= best_total:
                            best, best_total = node, total
                    stack.extend(node.values())
                elif isinstance(node, list):
                    stack.extend(node)
    return best


def rollouts(results: Path) -> list[tuple[str, Path, dict]]:
    out = []
    for path in sorted(results.rglob("rollout-*.jsonl")):
        task = path.parents[5].name if len(path.parents) > 5 else path.parent.name
        usage = _last_usage(path)
        if usage:
            out.append((task, path, usage))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--ledger", type=Path, required=True)
    ap.add_argument("--prices", type=Path, required=True)
    ap.add_argument("--model", default="gpt-5.6-luna")
    ap.add_argument("--unverified-baseline-usd", type=float, default=0.0,
                    help="spend already in the ledger that has no usage record; kept conservatively")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    prices = bp.load_prices(a.prices)
    price = bp.price_for(a.model, prices)
    ledger = json.loads(a.ledger.read_text())
    gross = float(ledger["spent"])

    rows, total = [], 0.0
    for task, path, usage in rollouts(a.results):
        cost = bp.usage_cost(usage, price)
        total += cost
        rows.append({
            "task": task, "rollout": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()[:16],
            "input": usage.get("input_tokens"), "cached": usage.get("cached_input_tokens"),
            "output": usage.get("output_tokens"), "usd": round(cost, 6),
        })

    reconciled = total + a.unverified_baseline_usd
    delta = reconciled - gross
    print(json.dumps({"model": a.model, "price_per_m": price, "tasks": rows,
                      "tasks_usd": round(total, 6),
                      "unverified_baseline_usd": a.unverified_baseline_usd,
                      "gross_ledger_usd": round(gross, 6),
                      "reconciled_usd": round(reconciled, 6),
                      "delta_usd": round(delta, 6)}, indent=2))

    if not a.apply:
        print("DRY_RUN (pass --apply to append the adjustment)")
        return 0
    if any(abs(float(x.get("usd", 0))) > 1e-9 and x.get("reason", "").startswith("reconcile:20261028-real-usage")
           for x in ledger.get("adjustments", [])):
        print("ALREADY_APPLIED")
        return 1

    lad = bp.Ledger(float(ledger["cap"]), None, prices)
    lad.spent = gross
    lad.adjustments = list(ledger.get("adjustments") or [])
    entry = lad.add_adjustment(
        delta,
        "reconcile:20261028-real-usage",
        {"evidence": [r["task"] for r in rows], "source": "codex rollout total_token_usage",
         "prices": str(a.prices), "reconciled_usd": round(reconciled, 6),
         "note": "replaces conservative ceiling estimate only; gross_spent_usd preserved"},
    )
    ledger.setdefault("adjustments", []).append(entry)
    tmp = a.ledger.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger))
    tmp.replace(a.ledger)
    print(f"APPLIED adjustment usd={entry['usd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
