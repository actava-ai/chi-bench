"""Emit one `chi-bench experiment run` command per (row × domain × condition) slice.

Read by scripts/run_table.sh; one command per line on stdout.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

import yaml


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--agent", default=None)
    ap.add_argument("--row", type=int, default=None)
    ap.add_argument("--domain", default=None)
    ap.add_argument("--condition", default=None)
    ap.add_argument("--environment", default=None)
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    rows = cfg.get("rows")
    if rows is None and "agent" in cfg:
        # single-row config (table2) — wrap as a one-element list.
        rows = [{k: cfg[k] for k in ("agent", "model") if k in cfg}]

    domains = cfg.get("domains")
    if domains is None and "dataset" in cfg:
        domains = {"_single": {"dataset": cfg["dataset"], "registry_path": cfg.get("registry_path")}}

    conditions = cfg.get("conditions") or [{"name": None}]

    if args.row is not None:
        rows = [rows[args.row - 1]]
    if args.agent:
        rows = [r for r in rows if r.get("agent") == args.agent]
    if args.domain:
        domains = {k: v for k, v in domains.items() if k == args.domain}
    if args.condition:
        conditions = [c for c in conditions if c.get("name") == args.condition]

    env_flag = f"--environment {args.environment}" if args.environment else ""

    for row in rows:
        for dom_name, dom_cfg in domains.items():
            for cond in conditions:
                parts = ["chi-bench", "experiment", "run", "-f", args.config]
                parts += ["--agent", row["agent"]]
                if row.get("model"):
                    parts += ["--model", row["model"]]
                parts += ["--dataset", dom_cfg["dataset"]]
                if env_flag:
                    parts += env_flag.split()
                # Pass-through env vars for ablation conditions:
                shell = " ".join(shlex.quote(p) for p in parts)
                prefixes = []
                if cond.get("skills_ablate"):
                    prefixes.append(
                        f"CHI_BENCH_SKILLS_ABLATE={','.join(cond['skills_ablate'])}"
                    )
                if cond.get("tool_mode"):
                    prefixes.append(f"CHI_BENCH_TOOL_MODE={cond['tool_mode']}")
                if prefixes:
                    shell = " ".join(prefixes) + " " + shell
                print(shell)

    return 0


if __name__ == "__main__":
    sys.exit(main())
