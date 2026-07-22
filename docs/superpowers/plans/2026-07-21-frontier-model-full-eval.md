# Frontier Model Full Evaluation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run one leaderboard-policy pass@1 attempt over all 75 headline chi-Bench tasks for GPT-5.6 Sol/Terra/Luna, Kimi K3, and TML Inkling 256K, then add Fable 5 through its first-party Claude Code harness and report all 450 resulting trials.

**Architecture:** Add one reviewed matrix config that combines the full Table-1 domain roots with the five provider-tested smoke rows. Expand it into 15 model/domain slices, run those slices sequentially on Modal with five trials in flight inside each slice, and keep every slice in a stable output directory so failures can be resumed narrowly. Run Fable's three Claude Code/OpenRouter slices from an independent driver and root, then combine the two native aggregates without re-bootstrap. The separate 23-task E2E arena, three marathon sessions, and paper-only attempts two and three are outside this pass@1 run.

**Tech Stack:** Python 3.13, pytest, YAML, Harbor 0.6.1, Modal sandboxes, Docker runtime image, Codex, OpenAI Agents SDK, OpenRouter, Tinker, Anthropic WorkspaceJudge.

---

## Task 1: Add a contract-tested full-evaluation matrix

**Files:**

- Create: `configs/experiments/frontier_models_full_2026_07.yaml`
- Modify: `tests/unit/test_frontier_models_smoke_config.py`

- [x] **Step 1: Add the failing matrix contract test.** Define `FULL_MATRIX_PATH`, the three full task/registry mappings, and a test that requires: Modal, `.env`, concurrency `5`, `n_attempts: 1`, `max_retries: 2`, timeout multiplier `2.0`, stable trials root, exactly the five non-Fable rows, and the same per-row agent kwargs as the validated smoke matrix.
- [x] **Step 2: Run the test and observe RED.**

  ```bash
  uv run pytest tests/unit/test_frontier_models_smoke_config.py::test_frontier_full_matrix_matches_reviewed_configuration -v
  ```

  Expected: failure because `configs/experiments/frontier_models_full_2026_07.yaml` does not exist.

- [x] **Step 3: Add the minimal matrix.** Use these full domain mappings:

  ```yaml
  domains:
    pa_provider:
      dataset: data/prior_auth_provider/tasks
      registry_path: data/prior_auth_provider/registry.json
    pa_um:
      dataset: data/prior_auth_um/tasks
      registry_path: data/prior_auth_um/registry.json
    cm:
      dataset: data/care_management/tasks
      registry_path: data/care_management/registry.json
  ```

  Copy only the Sol, Terra, Luna, Kimi, and Inkling rows from the validated smoke matrix; do not add Fable or change their agent kwargs.

- [x] **Step 4: Add the expansion assertion.** Require exactly 15 unique emitted slice commands, five models, three datasets, no Fable identifier, `n_attempts == 1`, concurrency `5`, and 25 registry entries per domain (375 scheduled model/task cells).
- [x] **Step 5: Run focused and repository verification.**

  ```bash
  uv run pytest tests/unit/test_frontier_models_smoke_config.py -v
  uv run ruff check tests/unit/test_frontier_models_smoke_config.py
  uv run ruff format --check tests/unit/test_frontier_models_smoke_config.py
  git diff --check
  ```

- [x] **Step 6: Commit the matrix contract.**

  ```bash
  git add configs/experiments/frontier_models_full_2026_07.yaml tests/unit/test_frontier_models_smoke_config.py
  git commit -m "chore: add frontier model full evaluation matrix"
  ```

## Task 2: Run prelaunch gates

- [x] **Step 1: Verify the pinned dataset and credentials without printing secrets.**

  ```bash
  uv run cb data verify
  test "$(sed -n '1p' data/.chi-bench-version)" = "chi-bench-v1.0.0"
  uv run modal profile list
  ```

  Require 25 tasks and 25 matching registry entries in each headline domain. Require non-empty `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `TINKER_API_KEY`, and `ANTHROPIC_API_KEY` in `.env`.

- [x] **Step 2: Re-run local verification before paid work.**

  ```bash
  uv run pytest
  uv run ruff check src/ tests/ scripts/preflight_frontier_models.py
  uv run ruff format --check src/ tests/ scripts/preflight_frontier_models.py
  ```

- [x] **Step 3: Materialize and audit all slices without model calls.**

  ```bash
  uv run python scripts/_emit_run_table_commands.py \
    --config configs/experiments/frontier_models_full_2026_07.yaml \
    --environment modal
  ```

  Inspect the 15 generated YAMLs under `logs/.slices/frontier_models_full_2026_07/`. Confirm every trials directory is new or intentionally resumed, and confirm no Fable row.

- [x] **Step 4: Run one Modal canary.** Materialize a flat Sol/provider config pointing at the already validated smoke task, concurrency one, and a dedicated `logs/experiments/frontier_models_full_2026_07_canary` trials directory. Require a completed agent result, judge scorecard, and no infrastructure exception before starting the 375-trial run.

## Task 3: Execute and monitor 375 trials

- [x] **Step 1: Run the 15 slices in row-major order.** For each emitted command, execute one slice and wait for it to finish before starting the next. Harbor runs the 25 tasks inside the slice with concurrency five and conditional infrastructure retry budget two.
- [x] **Step 2: Checkpoint after every slice.** Require exactly 25 per-trial `result.json` files with `verifier_result`, 25 scorecards, and a healthy judge. Record slice duration, pass count, exception count, known agent cost, judge cost when present, and any provider/rate-limit failures.
- [x] **Step 3: Resume narrowly.** If a slice exits nonzero, classify the failure before retrying. Do not rerun a completed slice. Retry only verified infrastructure/provider-transient failures; preserve genuine agent failures such as max-turn exhaustion or invalid tool names as evaluation outcomes. Before rerunning a partial slice, move its timestamped Harbor output outside the aggregation root; retries create a fresh timestamped job and must never accumulate beside partial results.
- [x] **Step 4: Keep the run auditable.** Preserve raw artifacts under `logs/experiments/frontier_models_full_2026_07/<slice-id>/` and keep canary artifacts outside that tree so they cannot enter final aggregation.

## Parallel task: Add Fable 5 with Claude Code via OpenRouter without disturbing the 375-trial run

- [x] **Keep Fable additive.** Define its one-row, three-domain matrix in
  `configs/experiments/fable5_openrouter_full_2026_07.yaml`; its 75 trials use
  `claude-code` with `anthropic/claude-fable-5` and write only beneath
  `logs/experiments/fable5_openrouter_full_2026_07`. Keep the OpenRouter base URL, token, and
  model aliases agent-scoped so the WorkspaceJudge retains the native Anthropic credential.
- [x] **Canary before paid scale.** Run one Fable/Claude Code/OpenRouter Modal task into a
  dedicated canary output outside both full-evaluation roots, and require a completed agent
  result, judge scorecard, and no infrastructure exception.
- [x] **Use an independent driver.** After the canary passes, run the three Fable domain slices
  from their own driver process and output root. Do not stop, edit, or reuse the live driver or
  outputs for the original 375 non-Fable trials. If a Fable slice has a verified transient
  partial failure, archive that slice directory outside the aggregation root before rerunning it.
- [x] **Combine only after both runs finish.** Verify 75 unique Fable model/task cells and 375
  unique original cells independently, then aggregate the six models jointly; never aggregate
  partial output from either driver.

## Task 4: Aggregate, verify, and report

- [x] **Step 1: Generate repository-native aggregate outputs.**

  ```bash
  uv run python scripts/aggregate.py \
    --trials-dir logs/experiments/frontier_models_full_2026_07 \
    --prices configs/prices.yaml \
    --out-csv logs/experiments/frontier_models_full_2026_07/summary.csv \
    --out-json logs/experiments/frontier_models_full_2026_07/summary.json
  ```

  The Fable root was aggregated independently with the same 1,000-iteration, seed-0 bootstrap.
  The six-row `logs/experiments/frontier_models_six_model_full_2026_07/summary.{csv,json}`
  concatenates the two disjoint native row sets without re-bootstrap, preserving each root's exact
  confidence intervals.

- [x] **Step 2: Generate a domain-aware report.** Include binary and fractional reward by model/domain, per-task failures, agent exceptions, known-cost coverage, judge health/cost, agent wall time, and Modal wall time. Treat exception-path zero usage as unknown. Outputs are under `logs/experiments/frontier_models_six_model_full_2026_07/`, including `report.md`, `report.json`, `domain_summary.csv`, `failures.csv`, and `exceptions.csv`.
- [x] **Step 3: Verify completeness.** Assert exactly 375 unique original model/task cells (75 per model, 125 per domain, five model rows, zero Fable rows, and 375 scorecards), 75 unique Fable cells (25 per domain and 75 scorecards), and 450 joint cells (six models, 150 per domain, 450 scorecards, and no duplicate task within a model).
- [x] **Step 4: Run final code verification and inspect repository state.**

  ```bash
  uv run pytest
  uv run ruff check src/ tests/ scripts/preflight_frontier_models.py
  uv run ruff format --check src/ tests/ scripts/preflight_frontier_models.py
  git diff --check
  git status --short
  ```

- [x] **Step 5: Report results and limitations.** State that this is the leaderboard pass@1 full suite (one attempt per task); paper Table-1 uncertainty/pass@3 requires two additional attempts per task. Link the detailed trial report, aggregate CSV/JSON, config, and execution plan.
