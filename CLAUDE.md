# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Self-improvement protocol

This file is a living document. Whenever a session in this repo would have gone smoother with
a note here, **edit CLAUDE.md before ending the turn** — don't wait to be asked. Future sessions
inherit this file but inherit nothing else from this one.

**Triggers — add or update an entry when you notice any of these:**

- The user corrects an approach ("no", "not that", "stop doing X", "again, like I said before").
  → capture the rule and **why** (the reason the user gave, often a past incident).
- The user says "again" or you re-discover something already explained earlier in the session
  or in a prior session. Rediscovery = missing note.
- You hit the same error, friction point, or wrong-first-guess that has come up before
  (within this session or across sessions). One repeat is enough; don't wait for three.
- A command, path, env var, or convention was non-obvious and required grep / multiple file
  reads to locate.
- The user validates a non-obvious choice ("yes exactly", "that was the right call", accepting
  an unusual approach without pushback). Capture confirmations too — without them, future-you
  drifts away from validated approaches and re-litigates them.
- A command in the **Commands** section turned out to be wrong, stale, or missing a flag.

**How to update:**

- Add the note to the most relevant existing section (Commands, Things to remember,
  Architecture, Subdirectory note) rather than spawning new sections.
- Format: one-line rule first, then **Why:** clause when the reasoning is non-obvious, then
  optionally **How to apply:** when the trigger condition isn't obvious from the rule.
- If an existing item is wrong or stale, **fix or delete it** — don't accumulate cruft. CLAUDE.md
  is read in full at the start of every session; entries past line ~200 lose weight.
- Keep entries actionable and specific. "Be careful with X" is useless; "Run `foo` before
  `bar`, otherwise SQLite is left in state Y" is useful.
- Mention CLAUDE.md updates in your end-of-turn summary so the user can review the diff.

**What NOT to add:**

- Anything discoverable by reading code, running `--help`, or checking `git log` — those don't
  need a CLAUDE.md note.
- One-off task context (use conversation, plans, or memory — not CLAUDE.md).
- Generic engineering advice ("write tests", "handle errors"). Repo-specific facts only.
- Sensitive values (keys, tokens, internal URLs). Reference where to find them instead.

## What this repo is

Χ-Bench (chi-Bench) is a benchmark of long-horizon, policy-rich U.S. healthcare workflow agents
across three domains: provider prior authorization, payer utilization management, and
care management. A single Python package (`chi_bench`) hosts a FastAPI server, three MCP servers
(provider :8020, payer :8100, care-management :8200), the `WorkspaceJudge` verifier, and seven
agent harnesses. Trials run in a single Docker image (`chi-bench:latest`) either locally or in
parallel on Modal sandboxes.

Authoritative docs to consult before changing behavior:

- `docs/architecture.md` — system diagram + module boundaries.
- `docs/cli.md` — every `cb` subcommand, flag, and exit-code convention.
- `docs/judge.md` — verifier model pin, voting, and re-judge protocol.
- `docs/reproduce.md` — paper-table reproduction.
- `README.md` — user-facing setup + submission workflow.

When in doubt, those four files are the source of truth — keep them in sync with any change
that affects users.

## Commands

Always run Python through `uv` — there is no `pip install -e .` workflow.

```bash
# Install (one-time)
uv sync --extra dev

# Lint + format (CI runs both; format is check-only there)
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/      # or drop --check to apply

# Default unit-test run (skips judge-hitting + slow tests via pyproject addopts)
uv run pytest

# Single test file or test
uv run pytest tests/unit/test_aggregate.py
uv run pytest tests/unit/test_aggregate.py::test_name -v

# Opt into gated suites
uv run pytest -m requires_anthropic_key   # hits the live judge
uv run pytest -m slow                     # includes docker-build smoke

# Skip the slow docker-build smoke even when docker is available
CHI_BENCH_SKIP_DOCKER_BUILD=1 uv run pytest tests/smoke -v -m slow

# Build the runtime image (~5 min; required before local `cb experiment run`)
uv run cb docker build
uv run cb docker build --target ci-skeleton -t chi-bench:ci   # faster, for smoke tests

# Serve the simulator locally (FastAPI + 3 MCP threads)
uv run cb serve                  # backend only
uv run cb serve --frontend       # backend + Vite dev frontend on :5180

# Verify the downloaded dataset layout
uv run cb data verify

# Run a single trial
uv run cb experiment run --dataset <task-dir> --agent <id> --model <id>

# Submission lifecycle (one YAML drives all four steps)
uv run cb submission validate -f configs/submissions/<id>.yaml
uv run cb submission run      -f configs/submissions/<id>.yaml
uv run cb submission status   -f configs/submissions/<id>.yaml
uv run cb submission prepare  -f configs/submissions/<id>.yaml

# Reproduce a paper table (decomposes a matrix YAML into per-row commands)
./scripts/run_table.sh table1            # add --modal for parallel execution
```

`cb` and `chi-bench` are the same Typer app (`pyproject.toml` `[project.scripts]`); use
whichever isn't aliased on your shell.

## Architecture cheatsheet

A trial container is laid out so that:

1. `cb experiment run -f <config>` shells out to **Harbor**, which spawns one container per trial
   via `ChiBenchDockerEnvironment` (local) or `ChiBenchModalEnvironment` (Modal).
2. `docker/entrypoint.sh` reads `CHI_BENCH_TASK_ID`, wires `/opt/chi-bench/tasks/<id>/fixtures`
   to `/fixtures`, starts the unified server (HTTP + 3 MCP threads on fixed ports), and waits
   for all four endpoints to accept traffic before exec'ing the agent harness CLI.
3. Agent harness drives the agent against the MCP tools.
4. After the agent stops, Harbor invokes the verifier (`WorkspaceJudge` on `claude-opus-4-7`)
   in the same container; it reads `/fixtures/expectations.json` (hidden from the agent) and
   the full workspace, then writes `verifier/scorecard.json` + `verifier/verdicts.json`.
5. Harbor writes `result.json`. Trial reward is the AND of rubric verdicts (or a continuous
   score for care management).

Source layout under `src/chi_bench/`:

- `core/` — domain models (`PriorAuthCase`, `CMOutreachTask`, …), state machines, world store.
- `services/` — ~29 HTTP/MCP-backed domain services (chart, coverage, intake, p2p, …).
- `server/` — FastAPI app exposing the services as REST endpoints under `/api/...`.
- `mcp/` — three MCP servers wrapping the services; see `mcp/{server,payer_server,cm_server}.py`.
- `conversation/` — patient simulator and peer-to-peer session orchestration.
- `experiment/` — Harbor-driven trial runner + `agents/` (seven harnesses) + `dual_pa_e2e_*`.
- `verifier/` — pluggable judge (default `WorkspaceJudge`), rubric stages, and rejudge runner.

Configs:

- `configs/submission_example.yaml` — submission YAML schema (one config drives all 3 domains).
- `configs/experiments/table[1-5]_*.yaml` — paper-table matrix configs, decomposed by
  `scripts/_emit_run_table_commands.py` and run via `scripts/run_table.sh`.
- `configs/prices.yaml` — per-model $/1M-token table consumed by `scripts/aggregate.py`.

## Things to remember

- **`ANTHROPIC_API_KEY` is always required**, even for non-Anthropic agents — the judge is pinned
  to `claude-opus-4-7`. `CHI_BENCH_JUDGE_MODEL` overrides it but deviates from the paper protocol.
  Use `CHI_BENCH_JUDGE_NUM_VOTES > 1` for majority-voted judging.
- **Dataset version pin** lives at `data/.chi-bench-version` and must match the submission YAML's
  `dataset.version`. `cb submission validate` (preflight) rejects mismatches. `cb data download`
  writes the pin in one step; the raw `huggingface-cli download` path needs `echo "$REV" > data/.chi-bench-version`.
- **`/fixtures` is NOT exposed to the agent** as a readable mount — expectations, scoring contracts,
  and manifests are reserved for the verifier. The entrypoint exposes raw artifacts via
  `/workspace/raw/artifacts/` except for `*_new_referral_provider` tasks, where the chart is
  projected through MCP tools only.
- **Two data layouts.** Host source: `data/<domain>/tasks/...`. Inside the baked image
  (`/opt/chi-bench`): flat `tasks/` with `marathon/`/`worlds/` siblings, handbook at
  `/workspace/skills/managed-care-operations-handbook`. `cb data verify` auto-detects.
- **`cb serve` starts the payer in agent mode** by setting `CHI_BENCH_PAYER_MODE=agent` if unset.
- **Never use `--no-verify` / `--no-gpg-sign` / hook skips on commits.** Fix the underlying issue.
- **Test markers gate by default.** `pyproject.toml` sets `addopts = "-m 'not requires_anthropic_key and not slow'"`,
  so live-judge and docker-build smokes are opt-in via `-m`.
- **Modal profile.** `cb experiment run -e modal` defaults to profile `actava`; pass
  `--modal-profile ''` to skip Modal preflight, or `MODAL_PROFILE=<name>` for a named profile.

## Subdirectory note

`actava-bench/` at the repo root is a separate legacy project with its own `pyproject.toml`,
`CLAUDE.md`, and tests. It is **not** part of the `chi-bench` package; do not edit it when
making changes to the primary codebase unless explicitly asked.
