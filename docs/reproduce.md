# Paper Table Reproduction

Each result has one config and one driver command. After trials complete,
`scripts/aggregate.py` rolls them up into a CSV with task-level percentile
bootstrap 95% CIs (1,000 iterations, seed `0` — matches the paper). Override
the resample count or seed with `--bootstrap-iters` / `--bootstrap-seed`.

## Cost expectations

The headline run (all 30 main-matrix cells) is **30 cells × 75 tasks × 3 trials = 6,750 trials**.
At an average per-trial cost from `configs/prices.yaml`, expect **$3,000-6,000 USD** of API spend
plus 24-72 hours of wall time at concurrency=5 per harness. The Quickstart single-task run is
under $1 and a few minutes.

## Main matrix — paper Table 2

```bash
./scripts/run_table.sh table1
# Filter slices when iterating:
./scripts/run_table.sh table1 --agent claude-code
./scripts/run_table.sh table1 --row 5 --domain pa_um
# Aggregate:
python scripts/aggregate.py \
  --trials-dir logs/experiments/table1_main_matrix \
  --out-csv logs/table1.csv
```

## E2E arena — paper Table 3

```bash
./scripts/run_table.sh table2
python scripts/aggregate.py --trials-dir logs/experiments/table2_e2e_arena --out-csv logs/table2.csv
```

## Marathon — paper Table 4

```bash
./scripts/run_table.sh table3
python scripts/aggregate.py --trials-dir logs/experiments/table3_marathon --out-csv logs/table3.csv
```

## Skill ablation — paper Figure 12

```bash
./scripts/run_table.sh table4
python scripts/aggregate.py --trials-dir logs/experiments/table4_skill_ablation --out-csv logs/table4.csv
```

## MCP vs CLI — paper Table 5

```bash
./scripts/run_table.sh table5
python scripts/aggregate.py --trials-dir logs/experiments/table5_mcp_vs_cli --out-csv logs/table5.csv
```

## Common flags

- `--modal` — opt into Modal sandboxes (default: local Docker).
- `--dry-run` — print commands without executing.
- `--row N` (table1, table3) — run only the N-th row of `rows[]`.
- `--agent <name>` — run only rows with this harness.
- `--domain pa_provider | pa_um | cm` — restrict to one domain.
- `--condition <name>` (table4, table5) — restrict to one ablation cell.
