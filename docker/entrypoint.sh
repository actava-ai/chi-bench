#!/bin/sh
# Entrypoint for the Modal single-image sandbox.
#
# Resolves the per-trial task id, wires /fixtures to the baked-in
# fixtures directory, bootstraps the runtime SQLite stores, starts
# cb serve (HTTP + MCP threads) in the background, then
# hands off to the requested command (default: sleep infinity).
set -e

TASK_ID="${CHI_BENCH_TASK_ID:-}"
TASKS_ROOT="${CHI_BENCH_TASKS_ROOT:-/opt/chi-bench/tasks}"
LOG_DIR=/logs/artifacts
[ -d "$LOG_DIR" ] || LOG_DIR=/tmp

if [ -z "$TASK_ID" ]; then
    echo "entrypoint: CHI_BENCH_TASK_ID is not set" >&2
    exit 64
fi

FIXTURES_SRC="${TASKS_ROOT}/${TASK_ID}/fixtures"
if [ ! -d "$FIXTURES_SRC" ]; then
    echo "entrypoint: fixtures not found at $FIXTURES_SRC" >&2
    exit 65
fi

export CHI_BENCH_FIXTURES_DIR="$FIXTURES_SRC"
# /fixtures symlink intentionally not created: agents must not read
# the scoring contract, expectations, or manifest JSONs directly (see
# handbook §5). Verifier resolves expectations via
# CHI_BENCH_FIXTURES_DIR or the tests/test.sh --expectations-path
# flag.

# Payer and legacy tasks may still expose raw-artifact PDFs under
# /workspace/raw/artifacts/. Provider-new-referral tasks deliberately do
# not, because the chart surface is projected through MCP/tools instead.
EXPOSE_RAW_ARTIFACTS="${CHI_BENCH_EXPOSE_RAW_ARTIFACTS:-1}"
case "${CHI_BENCH_TASK_ID:-}" in
  *_new_referral_provider)
    EXPOSE_RAW_ARTIFACTS=0
    ;;
esac

if [ "$EXPOSE_RAW_ARTIFACTS" != "0" ]; then
  mkdir -p "$CHI_BENCH_RAW_ROOT/artifacts" /workspace/raw
  ln -sfn "$CHI_BENCH_RAW_ROOT/artifacts" /workspace/raw/artifacts
fi

# Mirror the per-task `../tool_reference.md` bind mount from the local
# docker-compose at the path the agent's instruction.md references. PA
# tasks ship a per-task tool_reference.md; CM tasks rely on the shared
# default baked into the Modal image by Dockerfile.modal. Leave the
# baked default in place when no per-task file exists.
TOOL_REF_SRC="${TASKS_ROOT}/${TASK_ID}/tool_reference.md"
if [ -f "$TOOL_REF_SRC" ]; then
    mkdir -p /opt/chi-bench-task-assets
    ln -sfn "$TOOL_REF_SRC" /opt/chi-bench-task-assets/tool_reference.md
elif [ -f /opt/chi-bench-task-assets/tool_reference.md ]; then
    echo "entrypoint: no per-task tool_reference.md at $TOOL_REF_SRC — using baked default" >&2
else
    echo "entrypoint: warning — tool_reference.md missing at $TOOL_REF_SRC and no baked default present" >&2
fi

# When CHI_BENCH_MCP_TOOL_SEP overrides the default ``.`` (e.g. deepagents
# uses ``__`` so registered tool names pass OpenAI's function-name regex),
# rewrite tool_reference.md so the docs the agent reads match the tool names
# the MCP server actually registers. Materialize a writable copy because the
# baked default lives in a read-only image layer.
TOOL_SEP="${CHI_BENCH_MCP_TOOL_SEP:-}"
if [ -n "$TOOL_SEP" ] && [ "$TOOL_SEP" != "." ]; then
    case "$TOOL_SEP" in
        __|_|-) :;;
        *)
            echo "entrypoint: ignoring unsupported CHI_BENCH_MCP_TOOL_SEP=$TOOL_SEP" >&2
            TOOL_SEP=""
            ;;
    esac
fi
if [ -n "$TOOL_SEP" ] && [ "$TOOL_SEP" != "." ]; then
    REWRITE_TARGET=/opt/chi-bench-task-assets/tool_reference.md
    if [ -L "$REWRITE_TARGET" ] || [ -f "$REWRITE_TARGET" ]; then
        TMP_REF="$(mktemp)"
        cat "$REWRITE_TARGET" > "$TMP_REF" 2>/dev/null || cp "$REWRITE_TARGET" "$TMP_REF"
        # Replace ``namespace.method`` with ``namespace<sep>method`` for the
        # known chi-bench MCP namespaces. Limited scope so we don't touch
        # unrelated dotted text (filenames, version numbers, etc).
        python3 - "$TMP_REF" "$TOOL_SEP" <<'PY'
import re
import sys
path, sep = sys.argv[1], sys.argv[2]
namespaces = (
    "chart", "worklist", "inbox", "docs", "coverage", "forms", "auth", "people",
    "payer_portal", "payer_api_gateway", "payer_edi_gateway", "payer_fax_room",
    "payer_call_center", "payer_intake_hub", "payer_routing_engine",
    "payer_policy_library", "payer_p2p_scheduler", "payer_letter_center",
    "payer_appeals", "payer_audit",
    "cm_intake", "cm_chart", "cm_outreach", "cm_assessment", "cm_care_plan",
)
pattern = re.compile(rf"\b({'|'.join(namespaces)})\.([a-zA-Z_][a-zA-Z0-9_]*)")
text = open(path, "r", encoding="utf-8").read()
rewritten = pattern.sub(lambda m: f"{m.group(1)}{sep}{m.group(2)}", text)
open(path, "w", encoding="utf-8").write(rewritten)
PY
        mkdir -p /opt/chi-bench-task-assets
        # Replace the symlink/file with the rewritten copy.
        rm -f "$REWRITE_TARGET" 2>/dev/null || true
        mv "$TMP_REF" "$REWRITE_TARGET"
        echo "entrypoint: rewrote tool_reference.md with sep '$TOOL_SEP'" >&2
    fi
fi

# In docker-compose mode the server is a separate service reachable
# at host `chi-bench-server`. In the Modal single-sandbox layout
# the server runs in-process, so alias the hostname to loopback.
if ! grep -q "chi-bench-server" /etc/hosts 2>/dev/null; then
    echo "127.0.0.1 chi-bench-server" >> /etc/hosts || true
fi

. /workspace/.venv/bin/activate

python -m chi_bench.bootstrap

cb serve --host 0.0.0.0 --port 8023 --no-frontend \
    >"$LOG_DIR/chi-bench-server.log" 2>&1 &
SERVE_PID=$!

trap 'kill $SERVE_PID 2>/dev/null || true' INT TERM

# Wait until the HTTP server answers, so agent tool calls don't race
# server startup. Fail fast if the server never comes up — otherwise
# the agent's first MCP call surfaces as an opaque connection error.
READY=0
for _ in $(seq 1 60); do
    if python -c "import urllib.request; urllib.request.urlopen('http://localhost:8023/health')" \
            >/dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 1
done

if [ "$READY" -ne 1 ]; then
    echo "entrypoint: chi-bench server did not respond on :8023/health within 60s" >&2
    tail -n 50 "$LOG_DIR/chi-bench-server.log" >&2 2>/dev/null || true
    exit 69
fi

# /health on :8023 reports uvicorn readiness for the unified HTTP app, but
# the three FastMCP streamable-http session managers (provider :8020, payer
# :8100, CM :8200) run as separate threads and finish wiring their POST /mcp
# handler ~5-10s AFTER their "Uvicorn running" log line. Claude Code's
# MCP init happens once, right after this entrypoint exec-s the agent, and
# on a 400/405 it silently marks the server as "failed" for the whole trial
# (observed: ~65% payer MCP connection failure rate across curated-50 +
# phase2 smoke round 1/2). Probe each port with a real MCP initialize to
# gate agent startup on session-manager readiness. See
# docs/audit/2026-04-24-phase2-smoke-round2.md Finding F.
wait_mcp() {
    port=$1
    name=$2
    for _ in $(seq 1 60); do
        if python - <<PY >/dev/null 2>&1
import json, urllib.request
body = json.dumps({
    "jsonrpc": "2.0",
    "method": "initialize",
    "id": "entrypoint-probe",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "entrypoint-probe", "version": "1"},
    },
}).encode()
req = urllib.request.Request(
    f"http://localhost:${port}/mcp",
    data=body,
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    },
    method="POST",
)
with urllib.request.urlopen(req, timeout=5) as resp:
    assert 200 <= resp.status < 300
PY
        then
            return 0
        fi
        sleep 1
    done
    echo "entrypoint: $name MCP on :$port did not accept initialize within 60s" >&2
    tail -n 50 "$LOG_DIR/chi-bench-server.log" >&2 2>/dev/null || true
    return 1
}

wait_mcp 8020 provider || exit 70
wait_mcp 8100 payer    || exit 70
wait_mcp 8200 cm       || exit 70

# Skill ablation: blank out listed handbook sub-books before the agent starts.
# CHI_BENCH_SKILLS_ABLATE is a comma-separated list of sub-dir names under
# references/ (e.g. "provider-pa,medical-library"). Each named directory is
# removed and replaced with a one-line stub SKILL.md so the agent receives a
# clear "not available" signal rather than a filesystem error.
SKILLS_ABLATE="${CHI_BENCH_SKILLS_ABLATE:-}"
if [ -n "$SKILLS_ABLATE" ]; then
    HANDBOOK_REFS="/workspace/skills/managed-care-operations-handbook/references"
    for skill in $(echo "$SKILLS_ABLATE" | tr ',' ' '); do
        skill_path="${HANDBOOK_REFS}/${skill}"
        if [ -d "$skill_path" ]; then
            rm -rf "$skill_path"
            mkdir -p "$skill_path"
            printf '# This reference is not available in this experiment condition.\n' \
                > "${skill_path}/SKILL.md"
            echo "entrypoint: ablated skill sub-book: $skill" >&2
        else
            echo "entrypoint: warning — skill sub-book not found: $skill_path" >&2
        fi
    done
fi

TOOL_MODE="${CHI_BENCH_TOOL_MODE:-mcp}"
if [ "$TOOL_MODE" = "cli" ]; then
    npm install -g mcporter >/dev/null 2>&1
fi

exec "$@"
