#!/usr/bin/env python3
"""Read-only, offline inventory of judge usage for Payer t008/t011.

Prints numeric usage and billing metadata only; never emits prompt, response,
credentials, patient data, or raw logs. No network calls and no file writes.
"""
import argparse
import json
from pathlib import Path

TARGETS = ("pa_t008_", "pa_t011_")
KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
        "cache_creation_input_tokens", "cached_input_tokens", "prompt_tokens",
        "completion_tokens", "total_tokens", "cost_usd", "total_cost_usd",
        "model", "model_id")
MAX_BYTES = 3_000_000


def walk(obj, prefix="", depth=0):
    if depth > 8:
        return
    if isinstance(obj, dict):
        values = {k: v for k, v in obj.items()
                  if k in KEYS and (type(v) in (int, float) or
                                    (k in ("model", "model_id") and isinstance(v, str)))}
        if values:
            yield prefix or "root", values
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                yield from walk(v, f"{prefix}.{k}" if prefix else str(k), depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:100]):
            if isinstance(v, (dict, list)):
                yield from walk(v, f"{prefix}[{i}]", depth + 1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results", type=Path, required=True)
    args = p.parse_args()
    for task in sorted(args.results.rglob("*")):
        if not task.is_dir() or not task.name.startswith(TARGETS):
            continue
        if task.parent.name != "payer":
            continue
        print(f"TASK {task.name}")
        n = 0
        for path in sorted(task.rglob("*.json")):
            if path.stat().st_size > MAX_BYTES:
                continue
            name = path.name.lower()
            if not any(s in name for s in ("judge", "metadata", "usage", "scorecard", "verdict")):
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for location, fields in walk(value):
                print(json.dumps({"artifact": str(path.relative_to(task)),
                                  "location": location, "fields": fields},
                                 ensure_ascii=False))
                n += 1
        if not n:
            print("NO_MEASURED_JUDGE_USAGE_IN_SELECTED_JSON_ARTIFACTS")
    print("INVENTORY_ONLY: Do not convert missing usage or ceiling into spend credit.")


if __name__ == "__main__":
    main()
