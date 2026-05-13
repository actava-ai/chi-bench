# Spec: Extending chi-bench — Bring Your Own Agent / Model

**Status:** approved 2026-05-12
**Owner:** weiran
**Implementation plan:** TBD (next step — writing-plans)

## Background

chi-bench is a leaderboard benchmark. External users improve their position by
swapping in a better **model**, a better **agent harness**, or both, and then
submitting the resulting packet to the
[actava-ai/leaderboard](https://github.com/actava-ai/leaderboard) repo via the
existing 5-command flow (`validate → run → status → prepare → upload`).

Today the registry surface for harnesses is split across two files
(`_AGENT_IMPORT_PATHS` at `src/chi_bench/experiment/runner.py:26` and
`KNOWN_AGENTS` at `src/chi_bench/experiment/submission.py:68`), the
extension recipe is unwritten, and the `openai-agents` harness — the first
non-built-in agent we added — is the only example a new contributor has to
reverse-engineer. Submission validation soft-warns on unknown agents but
points at no documentation.

A leaderboard submitter currently has to:

1. Read seven harness files to figure out the contract.
2. Discover by trial-and-error that two registries need to be updated.
3. Guess which provider env vars are forwarded into the container.
4. Re-derive the OpenAI-/Anthropic-compatible model routing rules from
   `openai_agents_harness._resolve_routing`.

This spec replaces that with **one canonical doc + three small code tweaks**.

## Goals

1. A single doc, `docs/extending.md`, that gives any leaderboard submitter
   an unambiguous recipe for the three extension paths:
   - **Path A** — new model on an existing harness (config-only, no code).
   - **Path B** — new agent harness on existing/standard models.
   - **Path C** — both.
2. Make in-place harness registration a **single-edit** operation: registering
   an agent in one location should also satisfy submission validation.
3. Add a `cb agent list` introspection command so a submitter can verify their
   registration without spelunking the source.
4. Wire the soft warning at `submission.py:361` to the new doc and command.

## Non-goals

- No plugin / Python entry-points discovery system.
- No new top-level `agents/` directory or new submission-YAML section for
  `models:` / `providers:`.
- No PR gate. Upstreaming a harness is framed as a "contribute back for
  reproducibility" plus, not a leaderboard requirement.
- No refactor of any harness's internal model-routing logic. Each harness
  keeps its own routing; the doc only **maps** provider styles to the
  harnesses that already support them.
- No changes to `BaseInstalledAgent` (Harbor's contract — out of our
  control) or to the submission packet format.
- No new submission YAML fields (`submission.agent:` stays a plain string).

## Design

The work is three parts: the doc, three small code changes, and pointers
from README + `docs/cli.md` into the new doc.

### Part 1 — `docs/extending.md`

Length target: ~350–500 lines. Tone matches `docs/architecture.md` and
`docs/cli.md`: prose-light, example-heavy, every claim links to a file
path or command. Section outline below; each bullet is a paragraph or
code-block-sized chunk in the final doc, not a sentence.

#### § 1 Overview / decision tree

Three-line intro: chi-bench expects a registered (agent, model) pair per
submission. To climb the leaderboard you change one or both.

A short decision tree:

> - Just want to try a different model on an agent that's already
>   wired up? → **§ 2 (Path A)**, ~5 minutes, no code.
> - Want to plug in your own agent loop / scaffolding? → **§ 3 (Path B)**,
>   ~1 hour for a thin harness, longer for a heavy one.
> - Both? → **§ 4 (Path C)**.

Explicitly state the non-requirement up front: **you do not need to open
a PR to chi-bench to submit to the leaderboard.** The packet
(`logs/submissions/<id>/packet/...`) is self-contained.

#### § 2 Path A — new model on an existing harness

Three worked subsections, each with a copy-pasteable `.env` block and
the matching `submission.model:` line.

**§ 2.1 — OpenAI-compatible endpoint** (vLLM, OpenRouter, Together,
self-hosted, fine-tunes). The path everyone hits first.

Show the existing routing logic for `openai-agents`
(`src/chi_bench/experiment/agents/openai_agents_harness.py:84-150`) in
concrete terms:

- `submission.model: openai/<id>` or bare `<id>` → direct OpenAI,
  uses `OPENAI_API_KEY`.
- `submission.model: <vendor>/<id>` for any non-`openai` vendor →
  OpenRouter, uses `OPENROUTER_API_KEY` (forwarded as `OPENAI_API_KEY`
  with `OPENAI_BASE_URL` set to OpenRouter).
- Setting `OPENAI_BASE_URL` explicitly in `.env` is the escape hatch:
  any model id is passed through verbatim. **This is how you point at
  a vLLM / Together / self-hosted endpoint.**

Worked example: pointing the `openai-agents` harness at a self-hosted
vLLM serving `my-org/my-finetune`. `.env`:

```
OPENAI_BASE_URL=https://vllm.my-org.com/v1
OPENAI_API_KEY=sk-vllm-...
```

Submission YAML:

```yaml
submission:
  agent: openai-agents
  model: my-org/my-finetune
```

That's it. Run `cb submission validate` → `cb submission run`.

**§ 2.2 — Anthropic-compatible endpoint** (proxy, Bedrock-style). Same
shape but for the `claude-code` harness. `ANTHROPIC_BASE_URL` +
`ANTHROPIC_API_KEY` in `.env`; `submission.model:
anthropic/<id>`.

**§ 2.3 — Just a new model id on an existing provider.** Not really
"extending" — covered for completeness so new users know they can do
this with no code touch.

**§ 2.4 — Compatibility matrix.** Markdown table:

| Harness | OpenAI-direct | OpenRouter | OpenAI-compat (custom `BASE_URL`) | Anthropic-direct | Anthropic-compat | Notes |
|---|---|---|---|---|---|---|
| `openai-agents` | ✅ | ✅ | ✅ | via OpenRouter | — | Auto-routes off model prefix; `OPENAI_BASE_URL` overrides |
| `deepagents` | ✅ | ✅ | ✅ | ✅ | ✅ | Per-provider env var table; see harness file |
| `claude-code` | — | — | — | ✅ | ✅ | `ANTHROPIC_BASE_URL` for compat |
| `codex-cli` | ✅ | ✅ | ✅ | — | — | |
| `gemini-cli` | — | — | — | — | — | Gemini API only |
| `hermes` | ✅ | ✅ | ✅ | ✅ | — | |
| `openclaw` | ✅ | ✅ | ✅ | ✅ | — | |

(The exact matrix is verified at doc-write time by reading each
harness's routing function. Where a harness doesn't support a style,
the answer is "use a different harness or extend this one".)

**§ 2.5 — Common gotchas.** `data/.chi-bench-version` pin must match,
`ANTHROPIC_API_KEY` is still required (for the judge) even when the
agent is non-Anthropic, and the image must be rebuilt only if you
changed code (env-only changes don't require a rebuild).

#### § 3 Path B — new agent harness

The canonical recipe. Five concrete steps. Each step references the
**reference implementation** — `openai-agents`, our first custom agent —
by file and line.

**§ 3.1 — Contract.** A chi-bench harness is a Python class that
subclasses `harbor.agents.installed.base.BaseInstalledAgent` and runs
inside the chi-bench Docker image. Required surface:

| Member | Purpose | Reference |
|---|---|---|
| `@staticmethod name() -> str` | Canonical agent name used in submission YAML | `openai_agents_harness.py:77` |
| `SUPPORTS_ATIF: bool = True` | Declare ATIF v1.2 trajectory support so downstream analysis tooling treats your harness like the built-ins | `openai_agents_harness.py:51` |
| `CLI_FLAGS: list[CliFlag]` | Tunable knobs (e.g. `max_turns`) with type, default, env fallback | `openai_agents_harness.py:53-75` |
| `get_version_command() -> str \| None` | Shell command to print the agent package version inside the container | `openai_agents_harness.py:152` |
| `async install(self, environment)` | Install deps in the container (`uv pip install ...`); runs as root | `openai_agents_harness.py:155-159` |
| `@with_prompt_template async run(self, instruction, environment, context)` | Execute the agent; writes logs to `self.logs_dir`; reads MCP URL from `self.mcp_servers` | `openai_agents_harness.py:161-233` |
| `populate_context_post_run(self, context)` | Read metrics + trajectory artifacts and populate `context.{n_input_tokens, cost_usd, …}` + write `trajectory.json` | `openai_agents_harness.py:240-282` |

Harbor itself owns `BaseInstalledAgent`; link to Harbor docs for the
deeper contract. Document the chi-bench-specific bits in detail
because Harbor doesn't.

**§ 3.2 — The two-file pattern.** The reference implementation splits
work between two files:

- **Harness file** (`src/chi_bench/experiment/agents/<my_agent>.py`) —
  Harbor-facing glue: install, run, post-run trajectory translation.
  Runs on the host side of Harbor's RPC.
- **Runner file** (`src/chi_bench/experiment/agents/<my_agent>_runner.py`) —
  the actual agent loop, executed inside the container as
  `python -m chi_bench.experiment.agents.<my_agent>_runner`. Reads the
  instruction from a temp file, connects to MCP, drives the model, and
  writes `run_result.json` + `trace.jsonl` to `/logs/agent/`.

Recommend the two-file pattern. Single-file harnesses are fine for
thin CLI wrappers (see `claude_code_cli_harness.py`, 82 lines) but the
two-file pattern is what `openai_agents_harness.py` (465 lines) +
`openai_agents_runner.py` (687 lines) use and is what scales.

**§ 3.3 — Step-by-step.**

1. **Drop the harness file.** `src/chi_bench/experiment/agents/<my_agent>.py`.
   Easiest start: copy `openai_agents_harness.py`, rename the class,
   change `name()`, strip OpenAI-specific routing if not relevant.
2. **Drop the runner file** (if using the two-file pattern).
   `src/chi_bench/experiment/agents/<my_agent>_runner.py`.
3. **Register in `chi_bench.experiment.agents.registry`** (one line):
   ```python
   IN_TREE_AGENT_IMPORT_PATHS["my-agent"] = (
       "chi_bench.experiment.agents.my_agent:MyAgentHarness"
   )
   ```
   See § Part 2 below — this registry will be a single source of truth
   after the cleanup.
4. **Allowlist any new provider env vars** at `runner.py:37`
   (`AGENT_ENV_ALLOWLIST`). Only allowlisted keys are forwarded into
   trial containers via Harbor's `--ae` flag. Skip this if your harness
   only consumes keys already on the list.
5. **Rebuild the image** so the new files are baked in:
   ```
   uv run cb docker build
   ```
6. **Sanity-check the registration:**
   ```
   uv run cb agent list
   ```
   Your agent should appear with `kind: in-tree`.
7. **Smoke-test against one task** before committing to a full run:
   ```
   uv run cb experiment run \
       --dataset data/prior_auth_provider/tasks/<one-task-dir> \
       --agent my-agent --model <model-id>
   ```

**§ 3.4 — Plumbing checklist (lessons from `openai-agents`).** Bullet
list of subtle things easy to miss:

- **MCP URL discovery.** `self.mcp_servers` is set from `task.toml`.
  Iterate and pick the first non-empty `server.url`. Raise if none —
  do not silently default.
  (`openai_agents_harness.py:168-177`)
- **Provider env preflight.** Mirror provider API keys from
  `self._extra_env` (populated by `--ae`) into `os.environ` at `run()`
  entry. Some routing decisions read `os.environ` directly, and
  per-row overrides via `--ae` only land in `_extra_env`. Pattern at
  `openai_agents_harness.py:191-194`. Same pattern in `hermes_harness.py`.
- **Save/restore `_extra_env` around `exec_as_agent`.** Harbor merges
  `_extra_env` over the env you pass to `exec_as_agent`. If you want
  your routing decisions to win (not the host's stale shared key),
  strip the conflicting keys from `_extra_env` before exec and restore
  in a `finally`. Pattern at `openai_agents_harness.py:204-233`.
- **Quote the instruction.** Use `shlex.quote(instruction)` before
  shell-interpolating into the exec command. The instruction often
  contains shell metacharacters.
- **Write `run_log.txt`.** Tee the runner's stdout to
  `/logs/agent/run_log.txt`. This is what shows up in the trajectory
  when post-run parsing fails — without it, debugging a broken harness
  on Modal is hell. (`openai_agents_harness.py:228`)
- **Container Python.** The chi-bench image installs into
  `/workspace/.venv` (see `docker/Dockerfile:18-21`). Use
  `uv pip install --python /workspace/.venv …` in `install()` so your
  package lands where the venv-on-PATH actually looks.

**§ 3.5 — Trajectory normalization (optional but recommended).** If
your harness emits a custom log format (most do), translate it to
**ATIF v1.2** in `populate_context_post_run`. Reference:
`openai_agents_harness.py:285-465` (`_build_atif_trajectory` and
`_read_trace`). The Harbor types live at
`harbor.models.trajectories.*` — `Trajectory`, `Step`, `Agent`,
`ToolCall`, `Observation`, `ObservationResult`, `Metrics`,
`FinalMetrics`. Writing the result to `self.logs_dir /
"trajectory.json"` makes your trial show up uniformly in downstream
analysis (cost rollups, per-step inspection, the verifier-side trace
review).

If you skip this, your trial still scores correctly — the verifier
reads the workspace, not the trajectory — but cost reporting and trace
analysis on the leaderboard side won't work for your submission.

#### § 4 Path C — both

Half a page. Cross-reference §§ 2 and 3. The only thing worth saying:
if you're bringing both, write the harness first (Path B), pin a known
public model as your dev model, get it working end-to-end on a single
task, then swap in your endpoint via Path A. This avoids debugging
two unknowns at once.

#### § 5 Submitting with a custom agent / model

The point of this section is "**nothing changes**, the packet shape is
identical." Walk through the 5-command flow from README §4 with a
custom agent name, and explicitly call out:

- `cb submission validate` accepts custom agent names. Soft warning if
  the name isn't in the unified registry; hard error only for malformed
  YAML or missing dataset pin.
- The packet's `provenance.json` records the resolved image digest +
  git SHA, so a custom agent run is reproducible from your local
  checkout (you cannot reproduce someone else's custom harness without
  their code — that's what § 6 is for).

#### § 6 Contributing upstream (optional)

Plain-English: if you want other people to be able to re-run your
agent, open a PR to chi-bench with three things:

1. Your harness file(s) under `src/chi_bench/experiment/agents/`.
2. A line in the unified registry (`agents/registry.py`).
3. A unit test in `tests/unit/test_agent_registry.py` asserting the
   name resolves to your import path.

Plus a row in the § 2.4 compatibility matrix. **Reiterate**: this is
not a leaderboard requirement.

#### § 7 Reference appendix

- Unified registry: `src/chi_bench/experiment/agents/registry.py`.
- Env allowlist: `AGENT_ENV_ALLOWLIST` at
  `src/chi_bench/experiment/runner.py:37`.
- CLI: `cb agent list`, `cb experiment run --agent <name> --model <id>`,
  `cb submission {validate,run,status,prepare}`.
- Harbor's harness contract: link to upstream docs.
- ATIF v1.2 types: `harbor.models.trajectories.*`.

### Part 2 — code touchpoints

Three small, self-contained changes. ~80 LOC including tests.

#### Part 2.1 — Unified harness registry

**Problem.** Two registries today, drifting:

- `_AGENT_IMPORT_PATHS` (`src/chi_bench/experiment/runner.py:26`) —
  in-tree chi-bench harnesses dispatched via `--agent-import-path`. Eight
  entries today.
- `KNOWN_AGENTS` (`src/chi_bench/experiment/submission.py:68`) —
  validation allowlist. Ten entries today: the eight above plus the
  Harbor built-ins `claude-code` and `codex` (which dispatch via `-a
  <name>`, not via import path).

Registering a new in-tree harness requires editing both, in different
files, with no test catching omissions.

**Fix.** Create `src/chi_bench/experiment/agents/registry.py` with:

```python
"""Single source of truth for which agent names chi-bench accepts.

`IN_TREE_AGENT_IMPORT_PATHS` lists harness classes shipped in this repo;
each is dispatched via Harbor's `--agent-import-path`.

`HARBOR_BUILTIN_AGENTS` lists agent names Harbor knows about natively
and dispatches via `-a <name>` (no import path). These ship with Harbor,
not chi-bench; do not add custom agents here.

`KNOWN_AGENTS = frozenset(IN_TREE_AGENT_IMPORT_PATHS) | HARBOR_BUILTIN_AGENTS`
is what `cb submission validate` checks against.
"""

IN_TREE_AGENT_IMPORT_PATHS: dict[str, str] = {
    "openai-agents":     "chi_bench.experiment.agents.openai_agents_harness:OpenAIAgentsHarness",
    "deepagents":        "chi_bench.experiment.agents.deepagents_harness:DeepAgentsHarness",
    "dual-pa-e2e":       "chi_bench.experiment.agents.dual_pa_e2e_harness:DualPaE2EHarness",
    "openclaw":          "chi_bench.experiment.agents.openclaw_harness:OpenClawHarness",
    "gemini-cli":        "chi_bench.experiment.agents.gemini_cli_harness:GeminiCliHarness",
    "hermes":            "chi_bench.experiment.agents.hermes_harness:HermesHarness",
    "codex-cli":         "chi_bench.experiment.agents.codex_cli_harness:CodexCLIHarness",
    "claude-code-cli":   "chi_bench.experiment.agents.claude_code_cli_harness:ClaudeCodeCLIHarness",
}

HARBOR_BUILTIN_AGENTS: frozenset[str] = frozenset({"claude-code", "codex"})

KNOWN_AGENTS: frozenset[str] = (
    frozenset(IN_TREE_AGENT_IMPORT_PATHS) | HARBOR_BUILTIN_AGENTS
)
```

`runner.py` imports `IN_TREE_AGENT_IMPORT_PATHS` and uses it where it
used `_AGENT_IMPORT_PATHS` before. `submission.py` imports
`KNOWN_AGENTS`. The old names get removed from their original files
(no backwards-compat shim — these are internal symbols, no external
imports).

#### Part 2.2 — `cb agent list`

Add a new Typer subcommand group `agent` in `src/chi_bench/cli.py`,
with one subcommand `list`. Output is a small table:

```
NAME              KIND            IMPORT PATH                                                ENV VARS
openai-agents     in-tree         chi_bench…openai_agents_harness:OpenAIAgentsHarness        OPENAI_API_KEY, OPENROUTER_API_KEY
deepagents        in-tree         chi_bench…deepagents_harness:DeepAgentsHarness             OPENAI_API_KEY, OPENROUTER_API_KEY, ANTHROPIC_API_KEY, …
…
claude-code       harbor-builtin  (dispatched by Harbor via -a)                              ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN
codex             harbor-builtin  (dispatched by Harbor via -a)                              OPENAI_API_KEY
```

The env-vars column comes from a small static map per harness. We
could try to introspect, but `AGENT_ENV_ALLOWLIST` is one shared list
and harnesses don't declare per-harness allowlists today. Keep it
static in the registry module for now; a future change can make it
introspectable.

`--json` flag emits the same content as JSON for scripting (e.g.,
`cb agent list --json | jq '.[] | select(.name=="openai-agents")'`).

#### Part 2.3 — Improve the unknown-agent soft warning

Current message
(`src/chi_bench/experiment/submission.py:361-372`):

> *"Agent `<x>` is not in the known list (known: \[...]). If you
> registered a custom harness out-of-tree, you can ignore this."*

New message:

> *"Agent `<x>` is not registered in chi-bench. If you're bringing a
> custom harness, see `docs/extending.md` § 3 for the recipe, or run
> `cb agent list` to inspect what's registered today. Continuing with
> `<x>` — Harbor will fail at dispatch time if the name doesn't
> resolve."*

This is a 6-line change.

### Part 3 — README + `docs/cli.md` updates

**README §4 "Submit your agent"** — one new paragraph at the top:

> Bringing your own agent harness or model endpoint? The end-to-end
> recipe is in [`docs/extending.md`](docs/extending.md). The rest of
> this section is the same regardless of whether you're submitting a
> built-in agent or a custom one — the packet shape is identical.

**README §"Supported agents"** — append one line:

> See [`docs/extending.md`](docs/extending.md) to plug in your own.

**`docs/cli.md`** — new short section for `cb agent list`. Existing
file structure (one section per `cb` subcommand group) makes this a
straight append.

### Reference implementation: openai-agents

The doc treats `openai-agents` as the canonical example for **every**
non-trivial pattern in Path B. This is intentional: it's the first
non-built-in agent we shipped, the implementation is the cleanest of
the bunch, and the two-file split (harness + runner) is the pattern
we want others to follow.

Specifically, the doc links to these lines as authoritative references:

| Pattern | File:line |
|---|---|
| `BaseInstalledAgent` subclassing | `openai_agents_harness.py:43-49` |
| `name()` static method | `openai_agents_harness.py:77-79` |
| `SUPPORTS_ATIF` declaration | `openai_agents_harness.py:51` |
| `CLI_FLAGS` table | `openai_agents_harness.py:53-75` |
| `_resolve_routing(model, host_env)` | `openai_agents_harness.py:84-150` |
| `install()` with `uv pip install --python /workspace/.venv` | `openai_agents_harness.py:155-159` |
| `run()` — MCP URL pickup, env preflight, `exec_as_agent` | `openai_agents_harness.py:161-233` |
| `_extra_env` save/restore around `exec_as_agent` | `openai_agents_harness.py:204-233` |
| `populate_context_post_run` — read JSON metrics + emit ATIF | `openai_agents_harness.py:240-282` |
| ATIF v1.2 trajectory builder | `openai_agents_harness.py:285-465` |
| Two-file pattern: runner module | `openai_agents_runner.py:1-19` |

Where the deepagents harness illustrates something openai-agents
doesn't (e.g., a richer per-provider env-var table for non-OpenRouter
providers), the doc references that file in addition — but openai-agents
is always the first pointer.

## Validation / testing

1. **`tests/unit/test_agent_registry.py`** (new) — two cases:
   - `test_known_agents_is_union`: assert `KNOWN_AGENTS ==
     frozenset(IN_TREE_AGENT_IMPORT_PATHS) | HARBOR_BUILTIN_AGENTS`.
   - `test_import_paths_resolve`: for each value in
     `IN_TREE_AGENT_IMPORT_PATHS`, assert the module:Class pair imports
     and is a subclass of `harbor.agents.installed.base.BaseInstalledAgent`.
2. **`tests/unit/test_cli_agent_list.py`** (new) — invoke
   `cb agent list` via Typer's `CliRunner`, assert exit 0, assert every
   `IN_TREE_AGENT_IMPORT_PATHS` key appears in stdout, assert
   `claude-code` and `codex` appear with `harbor-builtin` kind.
   Separate `--json` test.
3. **`tests/unit/test_submission_config.py`** (extend existing file) —
   add a case asserting that calling validate with an unknown agent
   name produces a warning that contains `"docs/extending.md"` and
   `"cb agent list"`. (Existing tests in this file already cover the
   schema-level validation paths.)
4. **Doc lint** (manual, recorded in spec):
   - `docs/extending.md` is referenced from README §4 and §"Supported agents".
   - Every file:line reference in § 3.1 / § 3.4 / "Reference implementation"
     matches the actual file contents at HEAD.
   - The compatibility matrix in § 2.4 matches each harness's current
     routing logic.
5. **No new gated tests.** Everything here is unit-level — no docker
   build, no live judge, no API keys required.

## Open questions / risks

1. **Harbor contract drift.** `BaseInstalledAgent` lives in Harbor.
   If they rename a method, our doc rots. **Mitigation:** § 3.1 links
   to upstream Harbor docs alongside the chi-bench file pointers, so
   the doc remains useful even if the names shift.
2. **Compat matrix maintenance.** § 2.4 lists per-harness provider
   support; this is read from harness source at doc-write time. If a
   harness's routing changes, the matrix drifts. **Mitigation:** the
   matrix is short (7 rows × 6 cols); we will recheck during PR review
   for any harness change. A future enhancement could derive it from
   each harness via a `supported_providers()` classmethod, but that
   requires touching every harness and is out of scope here.
3. **CLI-tool wrappers vs SDK harnesses.** Harnesses split into two
   stylistic groups: thin CLI wrappers (`claude_code_cli_harness.py`,
   `codex_cli_harness.py` — 80 lines each, mostly process plumbing) and
   SDK-driven harnesses (`openai_agents_harness.py`,
   `deepagents_harness.py` — 500–900 lines). § 3.2 mentions both
   patterns but leans into the SDK pattern as the recommendation. If
   a contributor's agent is fundamentally a CLI, the doc should
   accommodate that without leaving them adrift — keep an eye on this
   during user testing.
4. **`agent_kwargs` interaction.** The submission YAML doesn't expose
   per-trial agent kwargs today (those flow via
   `cfg.agent_kwargs` in `experiment/config.py`). If a custom harness
   needs a runtime knob, the contributor will hit this. **Decision:**
   out of scope for v1; mention as a known limitation in § 7 with a
   pointer to `dual-pa-e2e` (which uses `agent_kwargs` heavily as a
   precedent) for users who need to extend the surface.

## Out of scope (deferred)

- Python entry-points / plugin discovery.
- A `cb agent doctor <name>` command that introspects per-harness env
  requirements, image installation state, and MCP wiring.
- Per-harness `supported_providers()` classmethod to make the compat
  matrix self-describing.
- A `models.yaml` registry that decouples model-id-to-provider routing
  from the harness. Useful long-term but premature.

## File-by-file inventory

Files touched by the implementation plan that follows this spec:

- **New:** `docs/extending.md`
- **New:** `src/chi_bench/experiment/agents/registry.py`
- **New:** `tests/unit/test_agent_registry.py`
- **New:** `tests/unit/test_cli_agent_list.py`
- **Modified:** `src/chi_bench/experiment/runner.py` — import from
  `agents/registry.py`; remove the local `_AGENT_IMPORT_PATHS` literal.
- **Modified:** `src/chi_bench/experiment/submission.py` — import
  `KNOWN_AGENTS` from `agents/registry.py`; rewrite soft-warning copy.
- **Modified:** `src/chi_bench/cli.py` — add `agent` Typer subcommand
  group with `list` (and `--json`).
- **Modified:** `README.md` — §4 cross-link, §"Supported agents" link.
- **Modified:** `docs/cli.md` — section for `cb agent list`.
