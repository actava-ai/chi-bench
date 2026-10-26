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
agent harnesses. Trials use a clean agent image (`chi-bench:agent`) and a trusted simulator/verifier image
(`chi-bench:latest`), locally or inside disposable Modal Docker sandboxes.

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

A trial uses the isolated lifecycle in `experiment/docker_env.py` for both Docker and Modal:

1. The trusted container starts the simulator with private task data and a per-trial control token.
2. The clean agent container receives role-scoped MCP access, public read-only assets, permitted raw source artifacts, and a shared task workspace. It has no private filesystem/process mounts or daemon access.
3. The host controls E2E role changes through authenticated management requests.
4. Harbor's reserved `/tests` upload stops the whole agent container, closes tool admission, and waits for admitted calls to finish before sending verifier inputs to the trusted container. Stop or drain failures prevent verification. Verifier execution then occurs there.
5. Native Hub exports use a trusted simulator sidecar and Harbor's separate verifier environment, with a frozen state snapshot collected after the agent stops.

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

- **Write Kaggle FAQs as direct participant answers in ASD-STE100 style, using the known
  CHI-Bench dates. Omit organizer-reply citations, review notes, repeated requirements, and
  verbatim restatements of user directions. Keep contact links in FAQs and only necessary
  source links in announcements.
  Assess existing rules against the intended workflow before proposing them.**
- **Use the CHI-Bench Cup sequence: competition deadline, private evaluation, result release,
  then the IEEE-format camera-ready report. Do not add a paper-acceptance stage.** **Why:**
  CHI-Bench evaluates competition systems; the report follows competition results. Use its
  own schedule and participation policy; do not import another Cup's instructions. Use
  organizer-specified submission routes; do not infer a requirement from a portal listing.
- **Preserve published task paths with image compatibility aliases when fixing runtime renames.**
  **Why:** Rewriting downloaded `instruction.md` files changes task checksums. For tool references,
  alias `/opt/healthverse-task-assets` to `/opt/chi-bench-task-assets` as a directory so per-task
  selection and tool-name rewriting remain visible through the published path.
- **For simple, explicitly scoped maintenance PRs, work directly on a `codex/` branch in the
  current clean checkout unless the user asks for a worktree or design spec.** **Why:** The user
  prefers direct execution over extra process for low-risk changes such as a model-default update.
- **After a Harbor upgrade, custom environments must read the canonical network policy
  (`_network_is_public` / `_network_disabled`), not `task_env_config.allow_internet`.** **Why:**
  Harbor 0.20 migrates the legacy field into `NetworkPolicy` and then clears it; treating the
  resulting `None` as false launches API-backed agents with `--network none`.
- **Aggregate Harbor 0.20 usage from `n_input_tokens` / `n_output_tokens` / `n_cache_tokens`,
  preferring those over legacy names, and subtract cache tokens from total input before applying
  the base input rate.** **Why:** `n_input_tokens` includes cached input; ignoring the renamed
  fields or charging it as wholly uncached makes leaderboard cost wrong.
- **Check CLI versions in both `chi-bench:agent` (agent) and `chi-bench:latest` (judge), and rebuild both with `cb docker build` after an authorized version change.** **Why:** they execute separate CLI copies, and Docker can reuse an unchanged npm install layer. `CLAUDE_CODE_VERSION` pins 2.1.219 for official evaluation; changing only the trusted image does not update the agent image.
- **Do not `source .env`; let `cb` load it or parse ad-hoc checks with `python-dotenv`.** **Why:**
  `.env` is dotenv syntax rather than guaranteed shell syntax, and currently contains an unquoted
  value with spaces that a shell tries to execute as a command.
- **Both patient and P2P counterpart simulation on `claude-sonnet-5` must explicitly disable
  adaptive thinking unless their response parsers and token budgets are redesigned for thinking
  blocks.** **Why:** Sonnet 5 enables thinking by default; both simulators read the first block's
  `.text`, with budgets of 1,024 and 512 output tokens respectively. Updating only the patient
  call leaves P2P `send_turn` failing on `ThinkingBlock`; `thinking={"type": "disabled"}` also
  requires `anthropic>=0.101.0`.
  Treat an empty P2P model override as the default too: Harbor Hub export forwards an omitted
  override as an empty string, so testing only an absent environment variable misses that path.
- **Do not pass Harbor's `thinking` agent kwarg to the stock `claude-code` harness without first
  checking the pinned Claude Code CLI.** **Why:** Harbor 0.6.1 renders it as `--thinking`, but
  Claude Code 2.1.207 and 2.1.216 do not expose that flag; use `reasoning_effort`/`--effort`
  instead, while models such as Fable keep their inherent adaptive-thinking behavior.
- **Do not present a proposed provider adapter as an existing harness, and do not add a new
  harness solely to remap credentials/base URLs when agent-scoped routing can reuse a stock
  harness.** **Why:** calling a hypothetical Inkling adapter `tinker-claude-code` obscured that
  it did not exist and made the evaluation configuration look hallucinated; keep the selected
  existing harness name and make any new routing layer explicit.
- **Choose the harness by model vendor, not gateway: Anthropic Fable uses `claude-code` even
  through OpenRouter, while third-party model vendors use `openai-agents`.** **Why:** the gateway
  does not change harness identity, and agent-scoped OpenRouter credentials must not replace the
  native `ANTHROPIC_API_KEY` used by the WorkspaceJudge.
- **Treat Tinker as an explicit provider route independent of vendor prefix: Tinker-served
  `nvidia/*` uses `openai-agents` Chat Completions, `TINKER_API_KEY`, and the same separated-
  reasoning replay as Inkling; do not infer OpenRouter solely from a non-`thinkingmachines` ID.**
  **Why:** gateway/provider routing differs from model vendor identity.
- **For the exact Nemotron 3 Ultra Tinker route, omit `reasoning_effort` and keep the strict
  `nemotron_tinker_model` adapter: inbound XML-only calls become SDK function calls, while replay
  arguments become mappings only at the Tinker boundary; preserve empty argument objects with the
  adapter's private truthy mapping until wire serialization.** **Why:** Tinker rejects the model's
  `reasoning_effort` parameter, returns valid Nemotron tool XML as plain content, and its Hugging
  Face template cannot iterate JSON-string historical arguments. The pinned Agents SDK otherwise
  applies a falsy fallback that changes an empty `{}` mapping back into the string `"{}"`.
- **Do not infer same-turn tool-call concurrency from `agent/trajectory.json`: its serializer
  flattens SDK tool-call items into one-call steps.** **Why:** this makes parallel batches look
  sequential. Reconstruct batches from `agent/trace.jsonl` call/result adjacency and correlated
  IDs, or corroborate them with server timestamps, without inspecting arguments or reasoning.
- **`ANTHROPIC_API_KEY` is always required**, even for non-Anthropic agents — the judge is pinned
  to `claude-opus-4-7`. `CHI_BENCH_JUDGE_MODEL` overrides it but deviates from the paper protocol.
  Judge voting defaults to one; `CHI_BENCH_JUDGE_NUM_VOTES` configures additional votes.
- **Dataset version pin** lives at `data/.chi-bench-version` and must match the submission YAML's
  `dataset.version`. Also require `dataset.content_sha256` to match the accepted task/shared-world/handbook bytes; inspect candidates with `uv run python scripts/dataset_identity.py --data-root data`, without rewriting source data or automatically accepting drift. `cb submission validate` (preflight) rejects mismatches. `cb data download`
  writes the pin in one step; the raw `huggingface-cli download` path needs `echo "$REV" > data/.chi-bench-version`.
- **Model-id convention for `claude-code`:** `cb` configs/submissions pass `anthropic/<bare-id>`
  (e.g. `anthropic/claude-fable-5`); Harbor's harness strips the vendor prefix and exports
  `ANTHROPIC_MODEL=<bare-id>` to the claude CLI. Bare ids are only needed for raw `harbor run`
  against hub-exported tasks, where `anthropic/<id>` 404s (commit 769744a). New models also need
  a `configs/prices.yaml` entry (input/output/cache $ per 1M; cache = 0.1× input) or
  `scripts/aggregate.py` cost columns come out empty.
- **Materialize Modal task mirrors as regular file copies.** The public-asset publisher rejects symlinks; preserve source task bytes and checksums.
- **Drop `NET_RAW` while retaining normal package-manager capabilities.** Agent harness installation needs UID and ownership operations; keep `no-new-privileges` enabled.
- **Create `/logs/verifier` in the trusted container before uploading `/tests`.** Verifier command redirection requires the directory before the script starts.
- **Use the same lexical workspace root for metadata and rooted file I/O.** Ancestor aliases such as `/tmp` and `/private/tmp` must identify the same workspace; links inside the writable workspace remain rejected.
- **Bind P2P evidence to its case and request.** Manual recording requires sourced external evidence. In E2E relay, `p2p_session.get_context` is read-only; `send_turn` and `submit_summary` cannot replace the two-role exchange. Final scoring checks the completed relay.
- **E2E execution and scoring use `workflow_v2`.** Provider submits a source-grounded packet; Payer processes that packet in a separate role context. Verification, rejudging, and aggregation reject legacy or unversioned E2E records. Original task evidence and gold remain read-only.
- **Use full frozen-state verification to validate deterministic verifier changes.** `cb experiment rejudge` retains deterministic checks and reruns only the semantic judge. Write verification results beside the retained trial.
- **CM references are static authored answers.** Their `executed` and `observed` fields remain false; reading a reference does not run the simulator or verifier.
- **Use Compose's resolved project name for Hub stop confirmation.** `CHI_BENCH_COMPOSE_PROJECT` and the `main` service label identify the agent container; host networking can give the container a host name.
- **Keep private task data in the trusted container.** The agent receives public assets, task workspaces and permitted `raw/artifacts` only; the raw chart database stays private.
- **Repair index metadata with `uv run python scripts/build_tasks_jsonl.py --repair-index data`.** This updates task IDs and fixture file counts. Marathon IDs come from session manifests; counts include regular files only.
- **Two data layouts.** Host source: `data/<domain>/tasks/...`. Inside the baked image
  (`/opt/chi-bench`): flat `tasks/` with `marathon/`/`worlds/` siblings, handbook at
  `/workspace/skills/managed-care-operations-handbook`. `cb data verify` auto-detects.
- **Local Docker must pass the leaf task ID to `CHI_BENCH_TASK_ID`, not Harbor's qualified
  `environment_name`.** **Why:** task metadata names are typically `actava-ai/<task-id>`, while
  the runtime image stores fixtures at `/opt/chi-bench/tasks/<task-id>`; forwarding the qualified
  name makes the entrypoint exit 65 before Harbor can provision `/logs`.
- **`cb serve` starts the payer in agent mode** by setting `CHI_BENCH_PAYER_MODE=agent` if unset.
- **Never use `--no-verify` / `--no-gpg-sign` / hook skips on commits.** Fix the underlying issue.
- **Test markers gate by default.** `pyproject.toml` sets `addopts = "-m 'not requires_anthropic_key and not slow'"`,
  so live-judge and docker-build smokes are opt-in via `-m`.
- **Modal profile.** `cb experiment run -e modal` defaults to profile `actava`; pass
  `--modal-profile ''` to skip Modal preflight, or `MODAL_PROFILE=<name>` for a named profile.
- **Git worktrees do not inherit `.env` or downloaded `data/`.** Link them from the primary
  checkout (or pass absolute paths) before live checks. `.env` stays ignored, but a `data`
  symlink appears as untracked because the `data/` ignore rule matches directories, not the
  symlink; remove it before final staging. Never copy keys or downloaded data into commits.
- **OpenAI Agents SDK 0.13.6 replays Chat Completions `reasoning_content` only for DeepSeek by
  default.** Tinker/Inkling tool loops need an explicit `should_replay_reasoning_content` hook;
  otherwise the second turn drops the signed/reasoning state even though the first call succeeds.
- **Pin the runtime `openai` SDK together with `openai-agents==0.13.6`; the validated pair is
  `openai==2.36.0`.** **Why:** an unconstrained install resolved OpenAI 2.46.0, whose required
  `InputTokensDetails.cache_write_tokens` field makes Agents 0.13.6 fail while constructing its
  default `Usage`, before the first model call.
- **Treat zero token/cost fields on an `openai-agents` exception trial as unknown, not free.**
  **Why:** the current runner loses partial SDK usage and trace data when `Runner.run` raises
  (for example, `MaxTurnsExceeded` or an invalid tool alias); inspect the server audit log for
  behavioral diagnosis and report cost coverage separately from known spend.
- **Combine disjoint evaluation roots by aggregating each root independently and concatenating
  their model rows; do not stage and re-aggregate the trial files.** **Why:** the fixed-seed
  bootstrap samples task vectors in filesystem traversal order, so staging can reorder tasks and
  shift confidence intervals even when every underlying outcome is unchanged.
- **Never inspect a live Harbor command with `ps`, `pgrep -a`, or another command-line dump.**
  **Why:** chi-Bench forwards provider credentials to Harbor as `--ae KEY=value`, so the process
  table contains raw secrets. Use the runner's redacted `Running:` line, Modal container counts,
  and trial artifact counts for monitoring instead.
- **Do not force a named tool choice for models with always-on/adaptive thinking.** Fable 5 and
  Kimi K3 reject forced tool selection while thinking is enabled; use `auto` plus an imperative
  prompt, then validate that the expected tool call actually occurred and replay all reasoning.
- **Agent-phase failures: read `trials/<name>/agent/claude-code.txt` tail first.** The stream-json
  log carries the raw API error + request_id; `NonZeroAgentExitCodeError` alone says nothing.
  Known case: Fable 5 (`claude-fable-5`) 400s with `model_not_available` ("organization or
  workspace must have data retention enabled") unless the org has data retention on — an
  Anthropic Console setting, not a harness/config bug. Reproduce with a bare curl before
  blaming the pipeline.

## Subdirectory note

`actava-bench/` at the repo root is a separate legacy project with its own `pyproject.toml`,
`CLAUDE.md`, and tests. It is **not** part of the `chi-bench` package; do not edit it when
making changes to the primary codebase unless explicitly asked.
