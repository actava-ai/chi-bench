"""Aggregate Harbor trial outputs into a paper-table CSV row per (agent, model).

Thin CLI wrapper. The implementation lives in ``chi_bench.aggregator`` so the
same code is reachable from the installed ``chi-bench`` package (e.g. when
``cb submission package`` refreshes the manifest).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Re-export for backwards-compat callers that still do
# ``from scripts.aggregate import aggregate`` (tests, the run_table.sh
# helper).
from chi_bench.aggregator import (  # noqa: F401  (re-export)
    Trial,
    aggregate,
    aggregate_to_rows,
    wilson_score_interval,
    write_rows_csv,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials-dir", type=Path, required=True)
    ap.add_argument("--prices", type=Path, default=Path("configs/prices.yaml"))
    ap.add_argument("--out-csv", type=Path, required=True)
    ap.add_argument("--out-json", type=Path, default=None)
    args = ap.parse_args()
    aggregate(
        trials_dir=args.trials_dir,
        prices_path=args.prices,
        out_csv=args.out_csv,
        out_json=args.out_json,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
