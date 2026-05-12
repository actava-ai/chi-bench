# CLI reference

This file documents every `cb` subcommand: synopsis, flags, behavior, exit codes, and example invocations. Run any leaf with `--help` for the canonical, machine-generated version of the flag list.

> `cb` is the short alias for `chi-bench`; both binaries resolve to the same Typer app (see `pyproject.toml` `[project.scripts]`). Pick whichever you prefer. If your shell already aliases `cb` to something else (e.g. a clipboard tool), use `chi-bench`.

## Command groups

| Group | Purpose |
| --- | --- |
| [`cb serve`](#cb-serve) | Run the in-process simulation server (FastAPI + judge + MCP threads). |
| [`cb mcp`](#cb-mcp) | Run one or more MCP servers in isolation (provider, payer, care-management). |
| [`cb experiment`](#cb-experiment) | Single-config experiment lifecycle: `run`, `rejudge`, `status`. |
| [`cb data`](#cb-data) | Dataset operations: `verify`, `download`. |
| [`cb submission`](#cb-submission) | Leaderboard submission lifecycle: `validate`, `run`, `status`, `package`. |
| [`cb docker`](#cb-docker) | Build the `chi-bench:latest` single-image container. |

Exit-code convention used throughout:

- `0` — success.
- `1` — runtime/validation failure (missing files, preflight errors, command returned non-zero).
- `2` — schema or YAML-load failure (typically `cb submission validate` / `cb submission run` / `cb submission status` / `cb submission package`).

---

## `cb serve`

Boot the chi-Bench simulation backend in-process: FastAPI on `--port`, all three MCP servers on their fixed ports (provider 8020, payer 8100, cm 8200) on threads, and optionally the Vite frontend dev server.

```
cb serve [--port 8023] [--host 0.0.0.0] [--frontend | --no-frontend]
         [--frontend-port 5180] [--frontend-wait-timeout 120.0]
         [--log-level INFO]
```

**Behavior**

- Before binding, the command attempts to kill any chi-Bench-related process already listening on `--port` (matched by command name against a small allowlist: `python`, `python3`, `node`, `npm`, `uvicorn`). Other processes are left alone with a warning. If `lsof` is not installed (e.g. inside slim Docker images), the kill step is skipped.
- Sets `CHI_BENCH_PAYER_MODE=agent` if unset.
- With `--frontend`, the frontend dev server is launched only after the backend reports healthy (or `--frontend-wait-timeout` elapses).

**Examples**

```bash
# Default: backend only, no frontend.
uv run cb serve

# Backend + frontend dev server on :5180.
uv run cb serve --frontend
```

---

## `cb mcp`

Start one or all of the chi-Bench MCP servers as standalone processes (without the FastAPI shell).

```
cb mcp [--provider | --no-provider] [--payer | --no-payer] [--cm | --no-cm]
       [--host 0.0.0.0] [--log-level INFO]
```

**Behavior**

- No flags = start all three (provider on `:8020`, payer on `:8100`, cm on `:8200`).
- Any combination of `--provider/--payer/--cm` restricts to that subset.

**Examples**

```bash
# All three (the default Docker entrypoint flavor).
uv run cb mcp

# Only the payer MCP — useful when the provider/CM are already running.
uv run cb mcp --payer
```

---

## `cb experiment`

The single-config experiment surface. A "config" here is a flat `ExperimentConfig` YAML — the matrix-style table configs (`scripts/run_table.sh`) are decomposed into single configs by `scripts/_emit_run_table_commands.py` before reaching this CLI.

### `cb experiment run`

Run a Harbor trial (or set of trials) from an `ExperimentConfig`, optionally overriding fields from the command line.

```
cb experiment run [-f <config.yaml>] [--dataset <path-or-id>]
                  [--agent <id>] [--model <id>] [-n <int>]
                  [--trials-dir <dir>]
                  [-e docker|modal] [--modal-profile <name>]
                  [--modal-sandbox-timeout-secs <int>]
                  [--modal-force-build | --no-modal-force-build]
```

**Flags**

| Flag | Default | Notes |
| --- | --- | --- |
| `-f / --config` | — | Path to an `ExperimentConfig` YAML. Required unless every field is provided via flags. |
| `--dataset` | — | Path to a dataset directory or a registry ID. |
| `--agent` | `claude-code` | Agent identifier (e.g. `claude-code`, `codex`, `openclaw`). |
| `--model` | — | Model identifier in the agent's namespace. |
| `-n` | `1` | Concurrent trials. |
| `--trials-dir` | — | Harbor trials output directory; falls back to the config's `paths.trials_dir`. |
| `-e / --environment` | `docker` | Either `docker` (local single-image) or `modal` (remote sandbox parallelism). The runner auto-terminates its own sandboxes on exit. |
| `--modal-profile` | `actava` | Modal profile from `~/.modal.toml`. Pass `''` to skip Modal preflight. |
| `--modal-sandbox-timeout-secs` | `86400` | Per-sandbox lifetime cap. Matches YAML key `modal.sandbox_timeout_secs`. |
| `--modal-force-build` | unset | Force Modal to rebuild the environment image. |

**Examples**

```bash
# One PA-UM trial via the local Docker harness.
uv run cb experiment run \
    --dataset data/prior_auth_um/tasks/pa_t008_t008_o002_p01_mdreview_payer \
    --agent codex --model openai/gpt-5.5

# Drive an entire config via Modal with 4-way parallelism.
uv run cb experiment run -f configs/pa_full.yaml -e modal -n 4
```

### `cb experiment rejudge`

Rerun only the judge stage across every trial under `--trial-root`. Original `verifier/` directories are never modified — rejudge artifacts land in `<trial>/<output-subdir>/`.

```
cb experiment rejudge --trial-root <dir> [-e local|modal]
                      [-n / --concurrency <int>]
                      [--output-subdir verifier_rejudge]
                      [--task-dataset-root data/care_management/tasks]
```

**Flags**

| Flag | Default | Notes |
| --- | --- | --- |
| `--trial-root` | **required** | Directory containing Harbor trial subdirs (each with a `verifier/`). |
| `-e / --environment` | `modal` | `local` = sequential in-process; `modal` = `ThreadPoolExecutor` at `--concurrency` (full Modal-sandbox wiring is a follow-up). |
| `-n / --concurrency` | `10` | Max parallel judge sessions when `-e modal`. |
| `--output-subdir` | `verifier_rejudge` | Per-trial output directory for rejudge artifacts (`scorecard.json`, `verdicts.json`, `judge_session_metadata.json`). |
| `--task-dataset-root` | `data/care_management/tasks` | Each trial's `expectations.json` is resolved by stripping the Harbor `__<slug>` suffix from the trial dir name and looking under `<root>/<task_id>/fixtures/`. |

**Example**

```bash
uv run cb experiment rejudge \
    --trial-root logs/experiments/cm_2025-12-15 \
    -e local
```

### `cb experiment status`

Compact pass/fail listing for trials in a directory.

```
cb experiment status [--trials-dir trials/]
```

**Behavior**

- Iterates `trials_dir/*/`, reading each trial's status and reward.
- Exits `1` if `--trials-dir` does not exist.

**Example**

```bash
uv run cb experiment status --trials-dir logs/experiments/pa_um_2025-12-15
```

---

## `cb data`

### `cb data verify`

Auto-detect the data layout (source `data/<domain>/tasks/...` tree, or the baked image's flat `tasks/`) and assert every expected directory + task count is present.

```
cb data verify [--data-dir data]
```

**Behavior**

- **Source layout** (typical host install): one `<domain>/tasks/` directory per task family.
- **Baked image layout** (inside `chi-bench:latest`): all families flattened under `tasks/`, with `marathon/` and `worlds/` as siblings. The handbook lives at `/workspace/skills/managed-care-operations-handbook` in this layout.
- Auto-detection: if `data_dir/tasks` exists but `data_dir/prior_auth_provider/tasks` does not, the baked layout is assumed.
- Exits `0` with `OK — data layout matches expectations.` on success, `1` with `missing:` / `count mismatch:` lines on failure.

**Example**

```bash
uv run cb data verify
uv run cb data verify --data-dir /opt/chi-bench
```

### `cb data download`

Convenience wrapper around `huggingface-cli download` that also writes the revision tag to `data/.chi-bench-version` so submission preflight can verify the pin.

```
cb data download --revision <tag> [--repo-id actava/chi-bench] [--data-dir data]
```

**Flags**

| Flag | Default | Notes |
| --- | --- | --- |
| `--revision` | **required** | HF dataset revision tag, e.g. `chi-bench-v1.0.0`. |
| `--repo-id` | `actava/chi-bench` | HF repo id. |
| `--data-dir` | `data` | Local data root. |

**Equivalent raw form** (documented as the primary route in `README.md`):

```bash
REV=chi-bench-v1.0.0
uv run huggingface-cli download actava/chi-bench --repo-type dataset \
    --revision "$REV" --local-dir data/
echo "$REV" > data/.chi-bench-version
```

`cb data download` exists so the pin file is written in one step; the README documents the raw HF CLI invocation as the canonical path.

---

## `cb submission`

Leaderboard submission lifecycle. See `configs/submission_example.yaml` for the YAML schema.

### `cb submission validate`

Schema-check a submission YAML; optionally run preflight (dataset version pin, Docker image / Modal token, agent name).

```
cb submission validate -f <sub.yaml> [--skip-preflight]
```

**Behavior**

- Always runs schema validation. Exits `2` on schema errors or YAML load failures.
- Without `--skip-preflight`, also probes `data/.chi-bench-version`, the chosen `run.environment`'s CLI/token, and warns on unknown agent names.
- Warnings are printed but non-blocking — exit code is `0` if no errors.
- Errors raise exit `1`.

**Example**

```bash
uv run cb submission validate -f configs/submissions/my-team.yaml
```

### `cb submission run`

Load the submission YAML, optionally preflight, then run each selected domain through `run_experiment()`. Raw per-trial outputs land under `paths.output_root` (default `logs/submissions/<id>/`).

```
cb submission run -f <sub.yaml> [--domain pa|um|cm ...] [--skip-preflight]
```

**Flags**

| Flag | Default | Notes |
| --- | --- | --- |
| `-f / --config` | **required** | Submission YAML to execute. |
| `--domain` | every domain in the YAML | Restrict to one or more domains (`pa`, `um`, `cm`, or canonical names like `pa_provider`). Repeatable. **Partial submissions are development-only — leaderboard policy requires all three.** |
| `--skip-preflight` | unset | Skip dataset/environment/agent preflight (not recommended). |

**Exit codes**

- `0` — submission completed.
- `1` — preflight errors, or one or more trials raised.
- `2` — schema/YAML failure.

**Example**

```bash
uv run cb submission run -f configs/submissions/my-team.yaml
```

### `cb submission status`

Per-domain pass/fail tallies for an in-progress or completed submission. Safe to run while `submission run` is in flight.

```
cb submission status -f <sub.yaml> [--json]
```

**Behavior**

- Counts only trials whose `result.json` carries a `verifier_result` block — the run-level aggregate `result.json` and incomplete trials are skipped (so the tally never claims more evidence than exists on disk).
- Default output is a human-readable table; `--json` emits a machine-readable shape.

**Example**

```bash
uv run cb submission status -f configs/submissions/my-team.yaml
uv run cb submission status -f configs/submissions/my-team.yaml --json
```

### `cb submission package`

Build the upload-ready zip at `<output_root>/<submission_id>.zip` (or `-o <path>`).

```
cb submission package -f <sub.yaml> [-o <output.zip>]
```

**Behavior**

- Always refreshes the manifest (`submission.json` + `results.csv`) before zipping, so the packet is coherent even if trials were added after the initial `submission run`.
- Packet contents: `submission.json`, `results.csv`, frozen `sub.yaml`, `provenance.json`, and per-trial `result.json` + `verifier/scorecard.json` + `verifier/reward.json` + `agent/trajectory.json`. Workspace artifacts, server logs, agent session caches, and Harbor scratch are deliberately excluded (typical packet size: <50 MB for a 75-trial pass@1 run).
- The raw trial tree on disk is unchanged.

**Example**

```bash
uv run cb submission package -f configs/submissions/my-team.yaml
uv run cb submission package -f configs/submissions/my-team.yaml -o /tmp/my-team.zip
```

---

## `cb docker`

### `cb docker build`

Build the chi-Bench single-image container.

```
cb docker build [-t chi-bench:latest] [--target runtime|ci-skeleton]
```

**Flags**

| Flag | Default | Notes |
| --- | --- | --- |
| `-t / --tag` | `chi-bench:latest` | Image tag. |
| `--target` | `runtime` | Build stage: `runtime` (full image), or `ci-skeleton` (faster, used by `tests/smoke/test_docker_image_builds.py`). |

**Behavior**

- Echoes the underlying `docker build ...` invocation to stdout, then `exec`s it. Exit code mirrors Docker's.

**Example**

```bash
uv run cb docker build
uv run cb docker build --target ci-skeleton -t chi-bench:ci
```

---

## Environment variables

API keys and tokens are read from process env (or `run.env_file` for `cb submission run`, default `.env`). The relevant variables (see `.env.example`):

| Variable | Used by |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude-family agents and the judge. |
| `OPENAI_API_KEY` | Codex rows. |
| `GEMINI_API_KEY` | Gemini-CLI rows. |
| `OPENROUTER_API_KEY` | OpenClaw, Hermes, OAI Agents, DeepAgents rows. |
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code agent harness OAuth token. |
| `HF_TOKEN` | Hugging Face dataset access (private/gated revisions). |
| `MODAL_PROFILE` | Modal profile for `cb experiment run -e modal` and `cb submission run` with `run.environment: modal`. |
| `CHI_BENCH_PAYER_MODE` | Auto-set to `agent` by `cb serve` if unset; controls the in-container payer routing. |

Provide whichever subset matches the rows you intend to run.
