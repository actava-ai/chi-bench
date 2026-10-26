"""Print an unaccepted candidate identity without modifying source data."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from chi_bench.experiment.content_identity import DOMAIN_ROOTS, compute_dataset_identity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--domain", action="append", dest="domains")
    parser.add_argument("--out", type=Path, help="Optional report destination outside data-root")
    args = parser.parse_args()
    root = args.data_root.resolve(strict=True)
    if args.out is not None and args.out.resolve().is_relative_to(root):
        parser.error("--out must be outside the source data root")
    try:
        identity = compute_dataset_identity(root, args.domains or list(DOMAIN_ROOTS))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    text = json.dumps(asdict(identity), indent=2) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
