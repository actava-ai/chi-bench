#!/usr/bin/env bash
# scripts/run_table.sh — drive one paper-table reproduction end to end.
#
# Usage:
#   ./scripts/run_table.sh tableN [filters...]
#
# Where tableN ∈ {table1, table2, table3, table4, table5} and filters can be
# any of:
#   --agent <name>          : run only rows with this --agent
#   --row <int>             : 1-based index into rows[] (table1, table3)
#   --domain <name>         : pa_provider | pa_um | cm
#   --condition <name>      : skill-ablation / mcp-vs-cli condition name
#   --modal                 : opt into Modal (default is local docker)
#   --dry-run               : print commands without executing
#
# After all trials finish, run `python scripts/aggregate.py` to produce CSV.

set -euo pipefail

usage() {
  sed -n '2,/^set -e/p' "${BASH_SOURCE[0]}" | sed -n '2,/Where tableN/p'
  exit 1
}

TABLE="${1:-}"
shift || usage

case "$TABLE" in
  table1|table2|table3|table4|table5) ;;
  *) usage ;;
esac

CONFIG="configs/experiments/${TABLE}_*.yaml"
CONFIG_PATH=$(ls $CONFIG 2>/dev/null | head -n1)
if [[ -z "$CONFIG_PATH" ]]; then
  echo "No config found for $TABLE under configs/experiments/" >&2
  exit 1
fi

AGENT_FILTER=""
ROW_FILTER=""
DOMAIN_FILTER=""
CONDITION_FILTER=""
ENVIRONMENT_FLAG=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent)      AGENT_FILTER="$2"; shift 2;;
    --row)        ROW_FILTER="$2"; shift 2;;
    --domain)     DOMAIN_FILTER="$2"; shift 2;;
    --condition)  CONDITION_FILTER="$2"; shift 2;;
    --modal)      ENVIRONMENT_FLAG="--environment modal"; shift;;
    --dry-run)    DRY_RUN=1; shift;;
    -h|--help)    usage;;
    *) echo "Unknown flag: $1" >&2; exit 1;;
  esac
done

# Delegate iteration to a Python helper because YAML × row/domain/condition
# matrices are easier to parse there. The helper prints one shell command per
# trial slice on stdout; we exec each in turn.
PY_DRIVER="$(dirname "${BASH_SOURCE[0]}")/_emit_run_table_commands.py"

python "$PY_DRIVER" \
  --config "$CONFIG_PATH" \
  ${AGENT_FILTER:+--agent "$AGENT_FILTER"} \
  ${ROW_FILTER:+--row "$ROW_FILTER"} \
  ${DOMAIN_FILTER:+--domain "$DOMAIN_FILTER"} \
  ${CONDITION_FILTER:+--condition "$CONDITION_FILTER"} \
  ${ENVIRONMENT_FLAG} \
  | while IFS= read -r cmd; do
      echo "▶ $cmd"
      if [[ "$DRY_RUN" -eq 0 ]]; then
        eval "$cmd"
      fi
    done

echo "All slices for $TABLE completed."
echo "Run: python scripts/aggregate.py --trials-dir logs/experiments/${TABLE}_* --out-csv logs/${TABLE}.csv  to produce CSV."
