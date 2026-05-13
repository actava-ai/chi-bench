# Extending chi-bench

chi-bench is a leaderboard benchmark. To climb it you change one of two things — the **model** running behind an agent, the **agent harness** driving the model, or both — and then run the standard 5-command submission flow (`validate → run → status → prepare → upload`) to produce a packet.

You **do not need to open a PR to chi-bench** to submit to the leaderboard. The packet at `logs/submissions/<id>/packet/...` is self-contained. Upstreaming your harness is encouraged (§ 6) so others can reproduce your run, but it is not a leaderboard requirement.

| Want to… | Read | Time |
|---|---|---|
| Try a different model on an existing harness | § 2 (Path A) | ~5 min |
| Plug in your own agent loop / scaffolding | § 3 (Path B) | ~1 hr (thin) – ½ day (heavy) |
| Both | § 4 (Path C) | combine the above |
| Sanity-check what's registered today | `cb agent list` | 1 cmd |

## § 2 — Path A: new model on an existing harness

Most leaderboard model swaps are configuration-only. Three sub-cases.

### § 2.1 OpenAI-compatible endpoint (vLLM, OpenRouter, Together, self-hosted)

The `openai-agents` harness auto-routes on the model id prefix (`src/chi_bench/experiment/agents/openai_agents_harness.py:84-150`):

| `submission.model:` | Routes to | Reads from `.env` |
|---|---|---|
| `openai/<id>` or bare `<id>` | OpenAI directly | `OPENAI_API_KEY` |
| `<vendor>/<id>` (vendor ≠ `openai`) | OpenRouter | `OPENROUTER_API_KEY` |
| anything, when `OPENAI_BASE_URL` is set | that URL verbatim | `OPENAI_API_KEY` |

The `OPENAI_BASE_URL` escape hatch is how you point at a self-hosted vLLM / fine-tune / proxy.

**Example: point `openai-agents` at a self-hosted vLLM.**

`.env`:

```
OPENAI_BASE_URL=https://vllm.my-org.com/v1
OPENAI_API_KEY=sk-vllm-...
ANTHROPIC_API_KEY=sk-ant-...   # still required for the judge
```

`configs/submissions/my-finetune.yaml`:

```yaml
schema: chi-bench/submission/v1
submission:
  id: my-team-my-finetune
  team: My Team
  contact: you@example.com
  agent: openai-agents
  model: my-org/my-finetune
run:
  environment: modal
  env_file: .env
dataset:
  version: chi-bench-v1.0.0
  domains: [pa_provider, pa_um, cm]
```

Then `uv run cb submission validate -f configs/submissions/my-finetune.yaml` and continue with the standard 5-command flow.

### § 2.2 Anthropic-compatible endpoint

For Anthropic-style proxies (e.g. Bedrock-fronted, internal gateway), use the `claude-code` harness with `ANTHROPIC_BASE_URL`.

`.env`:

```
ANTHROPIC_BASE_URL=https://anthropic.my-proxy.com
ANTHROPIC_API_KEY=sk-ant-proxy-...
```

`submission.model: anthropic/<your-id>`.

**Judge isolation.** `ANTHROPIC_BASE_URL` only affects the agent — chi-bench strips it from the judge's subprocess env so `claude-opus-4-7` always hits `api.anthropic.com` (see `src/chi_bench/verifier/judge/claude_runner.py:_subprocess_env`). If you need to route the judge through a custom endpoint too (e.g. a proxy that round-trips the official model), set `CHI_BENCH_JUDGE_BASE_URL` — it overrides the strip for the judge subprocess only.

### § 2.3 Just a new model id on an existing provider

Not really "extending" — but worth saying: if Anthropic or OpenAI ships a new model and the existing harness already routes its provider, just update `submission.model:`. No env changes, no rebuild.

### § 2.4 Compatibility matrix

| Harness | OpenAI-direct | OpenRouter | OpenAI-compat (custom `BASE_URL`) | Anthropic-direct | Anthropic-compat | Notes |
|---|:---:|:---:|:---:|:---:|:---:|---|
| `openai-agents` | ✅ | ✅ | ✅ | via OpenRouter | — | Auto-routes on model prefix; `OPENAI_BASE_URL` overrides |
| `deepagents` | ✅ | ✅ | ✅ | ✅ | ✅ | Per-provider env-var table inside the harness |
| `claude-code` | — | — | — | ✅ | ✅ | `ANTHROPIC_BASE_URL` for proxies |
| `codex-cli` | ✅ | ✅ | ✅ | — | — | |
| `gemini-cli` | — | — | — | — | — | Gemini API only |
| `hermes` | ✅ | ✅ | ✅ | ✅ | — | |
| `openclaw` | ✅ | ✅ | ✅ | ✅ | — | |

Where your provider isn't supported on any harness, write your own — see § 3.

### § 2.5 Common gotchas

- `data/.chi-bench-version` must equal your submission's `dataset.version`. `cb submission validate` rejects mismatches.
- `ANTHROPIC_API_KEY` is **always** required, even when the agent is non-Anthropic — the judge is pinned to `claude-opus-4-7`.
- Env-only changes do not require a Docker rebuild. Only rebuild (`uv run cb docker build`) when you change Python source.

## § 3 — Path B: new agent harness

A chi-bench harness is a Python class that subclasses Harbor's `BaseInstalledAgent` and runs **inside** the chi-bench Docker image. The canonical reference implementation is `openai-agents` — the first non-built-in agent we shipped. The file pointers in this section refer to it.

### § 3.1 The contract

| Member | Purpose | Reference |
|---|---|---|
| `@staticmethod name() -> str` | Canonical agent name used in submission YAML | `src/chi_bench/experiment/agents/openai_agents_harness.py:77-79` |
| `SUPPORTS_ATIF: bool = True` | Declare ATIF v1.2 trajectory support so downstream analysis tooling treats your harness like the built-ins | `src/chi_bench/experiment/agents/openai_agents_harness.py:51` |
| `CLI_FLAGS: list[CliFlag]` | Tunable knobs (e.g. `max_turns`) with type, default, env fallback | `src/chi_bench/experiment/agents/openai_agents_harness.py:53-75` |
| `get_version_command() -> str \| None` | Shell command to print the agent package version inside the container | `src/chi_bench/experiment/agents/openai_agents_harness.py:152` |
| `async install(self, environment)` | Install deps in the container (`uv pip install …`); runs as root | `src/chi_bench/experiment/agents/openai_agents_harness.py:155-159` |
| `@with_prompt_template async run(self, instruction, environment, context)` | Execute the agent; reads MCP URL from `self.mcp_servers`; writes logs to `self.logs_dir` | `src/chi_bench/experiment/agents/openai_agents_harness.py:161-233` |
| `populate_context_post_run(self, context)` | Read metrics + emit ATIF trajectory; populates `context.{n_input_tokens, cost_usd, …}` | `src/chi_bench/experiment/agents/openai_agents_harness.py:240-282` |

Harbor owns `BaseInstalledAgent`; consult Harbor's docs for the upstream contract. This page covers chi-bench-specific patterns.

### § 3.2 The two-file pattern

Recommended layout for any non-trivial harness:

- **Harness file** `src/chi_bench/experiment/agents/<my_agent>.py` — Harbor-facing glue. Install, run, post-run trajectory translation.
- **Runner file** `src/chi_bench/experiment/agents/<my_agent>_runner.py` — the actual agent loop, executed inside the container as `python -m chi_bench.experiment.agents.<my_agent>_runner`. Reads the instruction from a temp file, connects to MCP, drives the model, writes `run_result.json` + `trace.jsonl` to `/logs/agent/`.

`openai_agents_harness.py` (465 lines) + `openai_agents_runner.py` (687 lines) is the reference pair. Single-file harnesses are fine for thin CLI wrappers — see `claude_code_cli_harness.py` (82 lines) — but the two-file pattern is what scales.

### § 3.3 Step-by-step

1. **Drop the harness file** at `src/chi_bench/experiment/agents/<my_agent>.py`. Easiest start: copy `openai_agents_harness.py`, rename the class, change the value returned by `name()`, strip OpenAI-specific routing if not relevant.
2. **Drop the runner file** (if using the two-file pattern) at `src/chi_bench/experiment/agents/<my_agent>_runner.py`.
3. **Register in the unified registry** — `src/chi_bench/experiment/agents/registry.py`. One line:

   ```python
   IN_TREE_AGENT_IMPORT_PATHS["my-agent"] = (
       "chi_bench.experiment.agents.my_agent:MyAgentHarness"
   )
   ```

   That single edit makes the name resolvable for both Harbor dispatch (`runner.py`) and submission validation (`submission.py`).

4. **Allowlist new provider env vars** at `src/chi_bench/experiment/runner.py:37` (`AGENT_ENV_ALLOWLIST`) if your harness needs API keys not already on the list. Only allowlisted keys are forwarded into trial containers via Harbor's `--ae` flag. Skip this step if your harness only reads keys already present.

5. **Rebuild the image** so the new files are baked in:

   ```
   uv run cb docker build
   ```

6. **Sanity-check the registration:**

   ```
   uv run cb agent list
   ```

   Your agent should appear with `kind: in-tree`.

7. **Smoke-test against one task** before committing to a full submission:

   ```
   uv run cb experiment run \
       --dataset data/prior_auth_provider/tasks/<one-task-dir> \
       --agent my-agent --model <model-id>
   ```

### § 3.4 Plumbing checklist (subtle things easy to miss)

These come from the `openai-agents` and `hermes` harnesses. Skipping any of them tends to manifest as a confusing failure mid-trial:

- **MCP URL discovery.** `self.mcp_servers` is set from `task.toml`. Iterate and pick the first non-empty `server.url`. Raise on miss; do not silently default (`src/chi_bench/experiment/agents/openai_agents_harness.py:168-177`).
- **Provider env preflight.** Mirror provider API keys from `self._extra_env` (populated by Harbor's `--ae`) into `os.environ` at `run()` entry. Routing decisions often read `os.environ` directly; per-row overrides via `--ae` only land in `_extra_env`. Pattern at `openai_agents_harness.py:191-194`.
- **Save/restore `_extra_env` around `exec_as_agent`.** Harbor merges `_extra_env` over the env you pass. To make your routing decisions win (not a stale host key), strip the conflicting keys before exec and restore in `finally` (`openai_agents_harness.py:204-233`).
- **Quote the instruction.** Use `shlex.quote(instruction)` before shell-interpolating into the exec command — the instruction often contains shell metacharacters.
- **Tee a `run_log.txt`.** Pipe the runner's stdout to `/logs/agent/run_log.txt` (`openai_agents_harness.py:228`). When post-run parsing fails on Modal, this is your only signal.
- **Use the container venv.** The chi-bench image installs Python deps into `/workspace/.venv` (`docker/Dockerfile:18-21`). In `install()`, prefix `uv pip` invocations with `--python /workspace/.venv` so your package lands where the venv-on-PATH actually looks.

### § 3.5 Trajectory normalization (optional but recommended)

If your harness emits a custom log format (most do), translate it to **ATIF v1.2** in `populate_context_post_run`. Writing the result to `self.logs_dir / "trajectory.json"` makes your trial show up uniformly in cost rollups and per-step inspection.

Reference: `openai_agents_harness.py:285-465` (`_build_atif_trajectory` and `_read_trace`). The Harbor types live at `harbor.models.trajectories.*` — `Trajectory`, `Step`, `Agent`, `ToolCall`, `Observation`, `ObservationResult`, `Metrics`, `FinalMetrics`.

If you skip ATIF, your trial still scores correctly (the verifier reads the workspace, not the trajectory), but cost reporting and trace analysis on the leaderboard side won't work for your submission.

## § 4 — Path C: both new harness and new model

Cross-references §§ 2 and 3. The only working tip: **write the harness first** (§ 3), pin a known public model as your dev model, get the harness working end-to-end on a single task, **then** swap in your endpoint via § 2. Debugging two unknowns simultaneously is much harder than debugging them in sequence.

## § 5 — Submitting with a custom agent / model

The point of this section: **nothing changes** vs. the README § "Submit your agent" flow. The packet shape is identical.

```bash
uv run cb submission validate -f configs/submissions/<your-id>.yaml
uv run cb submission run      -f configs/submissions/<your-id>.yaml
uv run cb submission status   -f configs/submissions/<your-id>.yaml
uv run cb submission prepare  -f configs/submissions/<your-id>.yaml
```

Two custom-agent-specific notes:

- `cb submission validate` emits only a soft warning for custom agent names, not a hard error. Hard errors are still reserved for malformed YAML, dataset-version mismatch, or missing env files.
- `provenance.json` in the packet records the resolved image digest + git SHA. A custom-agent run is reproducible from *your* checkout; others can only reproduce it if your harness source is available (which is what § 6 is about).

## § 6 — Contributing upstream (optional)

If you want others to reproduce your run, open a PR to chi-bench with:

1. Your harness file(s) under `src/chi_bench/experiment/agents/`.
2. A line in `src/chi_bench/experiment/agents/registry.py`'s `IN_TREE_AGENT_IMPORT_PATHS`.
3. A unit test in `tests/unit/test_agent_registry.py` is automatic — your import path will be picked up by the parametrized `test_import_paths_resolve_to_base_installed_agent`.
4. A row added to the § 2.4 compatibility matrix in this file.

This is **not** a leaderboard requirement.

## § 7 — Reference appendix

- **Unified registry:** `src/chi_bench/experiment/agents/registry.py`.
- **Env allowlist** (runtime contract for what's forwarded into trial containers): `AGENT_ENV_ALLOWLIST` at `src/chi_bench/experiment/runner.py:37`.
- **CLI:** `cb agent list` (registry introspection), `cb experiment run --agent <name> --model <id>` (single-task smoke), `cb submission {validate,run,status,prepare}` (submission flow). See [`docs/cli.md`](cli.md) for full flag reference.
- **Harbor's harness contract:** see Harbor's upstream documentation for the `BaseInstalledAgent` base class.
- **ATIF v1.2 types:** `harbor.models.trajectories.*`.
- **Known limitation: per-trial agent kwargs.** The submission YAML does not expose per-trial harness kwargs today (those flow through `ExperimentConfig.agent_kwargs` in `src/chi_bench/experiment/config.py`). For a harness that needs a runtime knob, see `dual_pa_e2e_harness.py` for a precedent — it uses `agent_kwargs` heavily. Exposing them in submission YAML is on the roadmap.
