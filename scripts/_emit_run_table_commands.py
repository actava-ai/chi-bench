"""Emit one `chi-bench experiment run` command per (row x domain x condition) slice.

Read by scripts/run_table.sh; one command per line on stdout.

For each slice, we materialize a flat ExperimentConfig YAML on disk under
``logs/.slices/<table>/<slice-id>.yaml`` and emit::

    [CHI_BENCH_*=...] chi-bench experiment run -f logs/.slices/<table>/<slice-id>.yaml

This avoids the schema-mismatch problem where the matrix-style table configs
(``defaults: / domains: / rows: / conditions:``) are not directly consumable by
``ExperimentConfig.from_yaml(...)``.
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path
from typing import Any

import yaml


# Keys in `defaults:` that map directly onto ExperimentConfig fields. We keep
# this explicit (rather than splat) so future matrix-only knobs can be added
# under defaults without leaking into the runner config.
_DEFAULT_PASSTHROUGH_KEYS = (
    "environment",
    "env_file",
    "concurrency",
    "n_attempts",
    "max_retries",
    "agent_timeout_multiplier",
    "timeout_multiplier",
    "verifier_timeout_multiplier",
    "agent_setup_timeout_multiplier",
    "environment_build_timeout_multiplier",
)

# Keys on a row that map directly to ExperimentConfig fields.
_ROW_PASSTHROUGH_KEYS = (
    "agent",
    "model",
    "provider_agent",
    "provider_model",
    "payer_agent",
    "payer_model",
)


def _slug(value: str) -> str:
    """Make a filesystem-safe slug from a model/agent identifier."""

    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")


def _build_slice_config(
    matrix: dict[str, Any],
    row: dict[str, Any],
    dom_name: str,
    dom_cfg: dict[str, Any],
    cond: dict[str, Any],
    table_stem: str,
    row_idx: int,
    environment_override: str | None,
) -> tuple[dict[str, Any], str]:
    """Compose a flat ExperimentConfig dict for one slice.

    Returns the config dict and the slice-id used to name its YAML file.
    """

    defaults = matrix.get("defaults") or {}
    trials_root = defaults.get("trials_root") or f"logs/experiments/{table_stem}"

    # ── slice id ────────────────────────────────────────────────────────────
    parts = [f"{row_idx:02d}", _slug(row.get("agent", "agent"))]
    if row.get("model"):
        parts.append(_slug(row["model"]))
    if dom_name and dom_name != "_single":
        parts.append(_slug(dom_name))
    if cond.get("name"):
        parts.append(_slug(cond["name"]))
    slice_id = "_".join(parts)

    # ── compose flat config ─────────────────────────────────────────────────
    out: dict[str, Any] = {}

    # 1. defaults passthrough
    for k in _DEFAULT_PASSTHROUGH_KEYS:
        if k in defaults:
            out[k] = defaults[k]
    if "modal" in defaults:
        out["modal"] = defaults["modal"]

    # 2. row passthrough (agent/model/provider_*/payer_*)
    for k in _ROW_PASSTHROUGH_KEYS:
        if k in row and row[k] is not None:
            out[k] = row[k]

    # 3. domain passthrough (dataset/registry_path)
    if dom_cfg.get("dataset"):
        out["dataset"] = dom_cfg["dataset"]
    if dom_cfg.get("registry_path"):
        out["registry_path"] = dom_cfg["registry_path"]

    # 4. matrix-level dataset/registry_path for single-row tables (e.g. table2)
    if "dataset" not in out and matrix.get("dataset"):
        out["dataset"] = matrix["dataset"]
    if "registry_path" not in out and matrix.get("registry_path"):
        out["registry_path"] = matrix["registry_path"]

    # 5. agent_kwargs (matrix-level or row-level; row wins)
    agent_kwargs: dict[str, str] = {}
    if isinstance(matrix.get("agent_kwargs"), dict):
        agent_kwargs.update({str(k): str(v) for k, v in matrix["agent_kwargs"].items()})
    if isinstance(row.get("agent_kwargs"), dict):
        agent_kwargs.update({str(k): str(v) for k, v in row["agent_kwargs"].items()})
    if agent_kwargs:
        out["agent_kwargs"] = agent_kwargs

    # 6. condition: skill_ablation / tool_mode
    if cond.get("skills_ablate") is not None:
        out["skill_ablation"] = list(cond["skills_ablate"])
    if cond.get("tool_mode"):
        out["tool_mode"] = cond["tool_mode"]

    # 7. trials_dir = <trials_root>/<slice_id>
    out["trials_dir"] = f"{trials_root}/{slice_id}"

    # 8. environment override (--modal on the CLI)
    if environment_override:
        out["environment"] = environment_override

    # 9. matrix-level top-level overrides for single-row tables: agent might
    #    already be in `out` via row passthrough. But matrix-level row sometimes
    #    has agent_kwargs at the top — already merged above.

    return out, slice_id


def _emit_command_for_slice(
    slice_yaml_path: Path,
    cond: dict[str, Any],
    repo_root: Path,
) -> str:
    """Build the shell command line for one slice."""

    # Make the -f path relative to repo root for readability when possible.
    try:
        rel = slice_yaml_path.relative_to(repo_root)
        path_str = str(rel)
    except ValueError:
        path_str = str(slice_yaml_path)

    parts = ["chi-bench", "experiment", "run", "-f", path_str]
    shell = " ".join(shlex.quote(p) for p in parts)

    prefixes: list[str] = []
    if cond.get("skills_ablate"):
        prefixes.append(f"CHI_BENCH_SKILLS_ABLATE={','.join(cond['skills_ablate'])}")
    if cond.get("tool_mode"):
        prefixes.append(f"CHI_BENCH_TOOL_MODE={cond['tool_mode']}")
    if prefixes:
        shell = " ".join(prefixes) + " " + shell
    return shell


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--agent", default=None)
    ap.add_argument("--row", type=int, default=None)
    ap.add_argument("--domain", default=None)
    ap.add_argument("--condition", default=None)
    ap.add_argument("--environment", default=None)
    args = ap.parse_args()

    config_path = Path(args.config)
    matrix = yaml.safe_load(config_path.read_text())

    # ── normalize rows / domains / conditions ──────────────────────────────
    rows = matrix.get("rows")
    if rows is None and "agent" in matrix:
        # single-row config (table2): treat the matrix-level agent/model/etc.
        # as a one-element rows[] list.
        row: dict[str, Any] = {}
        for k in _ROW_PASSTHROUGH_KEYS:
            if matrix.get(k) is not None:
                row[k] = matrix[k]
        rows = [row]

    if rows is None:
        print("No rows[] and no top-level agent: in matrix config", file=sys.stderr)
        return 1

    domains = matrix.get("domains")
    if domains is None and matrix.get("dataset"):
        domains = {
            "_single": {
                "dataset": matrix["dataset"],
                "registry_path": matrix.get("registry_path"),
            }
        }
    if domains is None:
        print("No domains{} and no top-level dataset: in matrix config", file=sys.stderr)
        return 1

    conditions = matrix.get("conditions") or [{"name": None}]

    # ── filters ────────────────────────────────────────────────────────────
    # Track original row index BEFORE filtering, so slice ids stay stable.
    indexed_rows = list(enumerate(rows, start=1))
    if args.row is not None:
        indexed_rows = [(i, r) for i, r in indexed_rows if i == args.row]
    if args.agent:
        indexed_rows = [(i, r) for i, r in indexed_rows if r.get("agent") == args.agent]
    if args.domain:
        domains = {k: v for k, v in domains.items() if k == args.domain}
    if args.condition:
        conditions = [c for c in conditions if c.get("name") == args.condition]

    # ── output dir: logs/.slices/<table-stem>/ ─────────────────────────────
    repo_root = Path.cwd()
    table_stem = config_path.stem  # e.g. table1_main_matrix
    slices_dir = repo_root / "logs" / ".slices" / table_stem
    slices_dir.mkdir(parents=True, exist_ok=True)

    for row_idx, row in indexed_rows:
        for dom_name, dom_cfg in domains.items():
            for cond in conditions:
                slice_cfg, slice_id = _build_slice_config(
                    matrix=matrix,
                    row=row,
                    dom_name=dom_name,
                    dom_cfg=dom_cfg,
                    cond=cond,
                    table_stem=table_stem,
                    row_idx=row_idx,
                    environment_override=args.environment,
                )
                slice_yaml_path = slices_dir / f"{slice_id}.yaml"
                slice_yaml_path.write_text(
                    yaml.safe_dump(slice_cfg, sort_keys=False, default_flow_style=False)
                )
                print(_emit_command_for_slice(slice_yaml_path, cond, repo_root))

    return 0


if __name__ == "__main__":
    sys.exit(main())
