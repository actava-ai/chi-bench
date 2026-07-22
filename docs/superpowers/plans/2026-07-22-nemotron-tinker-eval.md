# Nemotron 3 Ultra 256K Tinker Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route Nemotron 3 Ultra 256K through Tinker with the existing OpenAI Agents reasoning/tool semantics, then run and report one pass@1 attempt over all 75 headline chi-Bench tasks.

**Architecture:** Add an explicit config-scoped Tinker provider route while preserving current automatic routing, and identify Tinker reasoning replay by endpoint plus API mode rather than model-name prefix. Extend the redacted two-turn provider preflight and add isolated three-task canary and 75-task full matrices. Aggregate the completed Nemotron root independently, then append its native row to the prior six-model report without re-bootstrap.

**Tech Stack:** Python 3.13, pytest, YAML, Harbor 0.6.1, OpenAI Agents SDK 0.13.6, OpenAI Python 2.36.0, Tinker OpenAI-compatible Chat Completions, Modal sandboxes, Anthropic WorkspaceJudge.

---

## File map

- `src/chi_bench/experiment/agents/openai_agents_harness.py`: expose and resolve the explicit Tinker route using `TINKER_API_KEY`.
- `src/chi_bench/experiment/agents/openai_agents_runner.py`: apply Tinker Chat Completions and same-model reasoning replay to any model at the Tinker endpoint.
- `scripts/preflight_frontier_models.py`: classify explicit Tinker rows and allow one-row preflight matrices.
- `tests/unit/test_openai_agents_harness.py`: route selection and missing-key contracts.
- `tests/unit/test_openai_agents_runner_config.py`: endpoint-scoped reasoning replay contracts.
- `tests/unit/test_preflight_frontier_models.py`: one-row classification and two-turn replay contracts.
- `tests/unit/test_frontier_models_smoke_config.py`: reviewed canary/full matrices, slice expansion, and pricing contracts.
- `configs/experiments/nemotron3_ultra_tinker_smoke_2026_07.yaml`: three single-task Modal canaries.
- `configs/experiments/nemotron3_ultra_tinker_full_2026_07.yaml`: three 25-task full-evaluation slices.
- `configs/prices.yaml`: exact run-date Tinker token rates.
- `CLAUDE.md`: preserve the provider-route lesson for future evaluations.
- `docs/superpowers/plans/2026-07-22-nemotron-tinker-eval.md`: checklist and final execution record.

## Task 1: Generalize the established Tinker harness route

**Files:**

- Modify: `tests/unit/test_openai_agents_harness.py`
- Modify: `src/chi_bench/experiment/agents/openai_agents_harness.py`

- [x] **Step 1: Write failing route tests.** Add the exact model constant and tests that request an explicit Tinker route, require the Tinker key, and prove the same model still auto-routes to OpenRouter without the override:

  ```python
  NEMOTRON_MODEL = "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16:peft:262144"


  def test_explicit_tinker_route_preserves_vendor_model_id() -> None:
      env = OpenAIAgentsHarness._resolve_routing(
          NEMOTRON_MODEL,
          {"TINKER_API_KEY": "test-tinker-key"},
          provider_route="tinker",
      )
      assert env == {
          "OPENAI_API_KEY": "test-tinker-key",
          "OPENAI_BASE_URL": OpenAIAgentsHarness.TINKER_BASE_URL,
          "OPENAI_AGENTS_MODEL": NEMOTRON_MODEL,
          "OPENAI_AGENTS_API_MODE": "chat_completions",
      }


  def test_explicit_tinker_route_requires_tinker_key() -> None:
      with pytest.raises(RuntimeError, match="TINKER_API_KEY"):
          OpenAIAgentsHarness._resolve_routing(
              NEMOTRON_MODEL, {}, provider_route="tinker"
          )


  def test_vendor_model_without_explicit_route_remains_openrouter() -> None:
      env = OpenAIAgentsHarness._resolve_routing(
          NEMOTRON_MODEL, {"OPENROUTER_API_KEY": "test-openrouter-key"}
      )
      assert env["OPENAI_BASE_URL"] == OpenAIAgentsHarness.OPENROUTER_BASE_URL
      assert env["OPENAI_API_KEY"] == "test-openrouter-key"
  ```

- [x] **Step 2: Run RED.**

  ```bash
  uv run pytest tests/unit/test_openai_agents_harness.py -v
  ```

  Expected: the first two tests fail because `_resolve_routing` has no `provider_route` argument.

- [x] **Step 3: Add the minimal explicit route.** Add a `provider_route` CLI enum with choices `auto` and `tinker`; add a keyword-only `provider_route` argument to `_resolve_routing`; treat `provider_route == "tinker"` or `thinkingmachines/*` as Tinker; and pass the resolved flag from `run()`:

  ```python
  CliFlag(
      "provider_route",
      cli="--provider-route",
      type="enum",
      choices=["auto", "tinker"],
      env_fallback="OPENAI_AGENTS_PROVIDER_ROUTE",
  )
  ```

  Add the keyword-only argument `provider_route: str | None = None` after `host_env` in the
  existing `_resolve_routing` signature.

  Immediately after the existing `model_name is None` branch, replace the current Tinker
  condition with:

  ```python
  if provider_route == "tinker" or model_name.startswith("thinkingmachines/"):
      tinker_key = host_env.get("TINKER_API_KEY")
      if not tinker_key:
          raise RuntimeError(
              f"Model {model_name!r} requires Tinker routing, but "
              "TINKER_API_KEY is not set in the host environment."
          )
      return {
          "OPENAI_API_KEY": tinker_key,
          "OPENAI_BASE_URL": cls.TINKER_BASE_URL,
          "OPENAI_AGENTS_MODEL": model_name,
          "OPENAI_AGENTS_API_MODE": "chat_completions",
      }
  ```

  Resolve with:

  ```python
  env = self._resolve_routing(
      self.model_name,
      os.environ,
      provider_route=self._resolved_flags.get("provider_route"),
  )
  ```

- [x] **Step 4: Run GREEN and commit.**

  ```bash
  uv run pytest tests/unit/test_openai_agents_harness.py -v
  uv run ruff check src/chi_bench/experiment/agents/openai_agents_harness.py tests/unit/test_openai_agents_harness.py
  uv run ruff format --check src/chi_bench/experiment/agents/openai_agents_harness.py tests/unit/test_openai_agents_harness.py
  git add src/chi_bench/experiment/agents/openai_agents_harness.py tests/unit/test_openai_agents_harness.py
  git commit -m "feat: add explicit Tinker agent route"
  ```

## Task 2: Generalize Tinker reasoning replay by endpoint

**Files:**

- Modify: `tests/unit/test_openai_agents_runner_config.py`
- Modify: `src/chi_bench/experiment/agents/openai_agents_runner.py`

- [x] **Step 1: Write failing runner tests.** Add `NEMOTRON_MODEL`, include `(NEMOTRON_MODEL, "chat_completions", TINKER_BASE_URL, False, True)` in the API-selection cases, and assert the replay hook accepts Nemotron only when `origin_model`, current model, and Tinker base URL match. Keep the existing wrong-base and cross-model assertions.

- [x] **Step 2: Run RED.**

  ```bash
  uv run pytest tests/unit/test_openai_agents_runner_config.py -v
  ```

  Expected: Nemotron remains a plain model string and receives no `separate_reasoning` body.

- [x] **Step 3: Remove model-prefix coupling.** Change route detection to depend only on Chat Completions plus the normalized Tinker endpoint, and change replay to depend only on that endpoint plus exact model equality:

  ```python
  def _is_tinker_chat_route(api_mode: str) -> bool:
      return (
          api_mode == "chat_completions"
          and os.environ.get("OPENAI_BASE_URL", "").rstrip("/") == TINKER_BASE_URL
      )


  def _should_replay_same_model_reasoning_content(context: Any) -> bool:
      reasoning = getattr(context, "reasoning", None)
      model = getattr(context, "model", None)
      base_url = (getattr(context, "base_url", None) or "").rstrip("/")
      return (
          isinstance(model, str)
          and base_url == TINKER_BASE_URL
          and getattr(reasoning, "origin_model", None) == model
      )
  ```

  Update both call sites to `_is_tinker_chat_route(api_mode)`.

- [x] **Step 4: Run GREEN and commit.**

  ```bash
  uv run pytest tests/unit/test_openai_agents_runner_config.py -v
  uv run ruff check src/chi_bench/experiment/agents/openai_agents_runner.py tests/unit/test_openai_agents_runner_config.py
  uv run ruff format --check src/chi_bench/experiment/agents/openai_agents_runner.py tests/unit/test_openai_agents_runner_config.py
  git add src/chi_bench/experiment/agents/openai_agents_runner.py tests/unit/test_openai_agents_runner_config.py
  git commit -m "fix: replay Tinker reasoning for vendor model ids"
  ```

## Task 3: Extend the redacted provider preflight

**Files:**

- Modify: `tests/unit/test_preflight_frontier_models.py`
- Modify: `scripts/preflight_frontier_models.py`

- [x] **Step 1: Write failing classification and replay tests.** Build a temporary one-row config containing the exact Nemotron model and these kwargs:

  ```yaml
  rows:
    - agent: openai-agents
      model: nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16:peft:262144
      agent_kwargs:
        provider_route: tinker
        api_mode: chat_completions
        reasoning_effort: high
  ```

  Assert `load_probe_specs()` returns one Tinker Chat Completions spec using `TINKER_API_KEY`, then run the existing fake two-turn chat response and assert the second request replays the full assistant message with `reasoning_content` and the tool result.

- [x] **Step 2: Run RED.**

  ```bash
  uv run pytest tests/unit/test_preflight_frontier_models.py -v
  ```

  Expected: the loader rejects one row and classification defaults to OpenRouter.

- [x] **Step 3: Honor explicit routing and non-empty matrices.** In `_provider_spec`, check `agent_kwargs.get("provider_route") == "tinker"` before vendor prefixes. In `load_probe_specs`, replace the six-row guard with:

  ```python
  if not isinstance(rows, list) or not rows:
      raise ValueError("frontier preflight requires at least one row")
  ```

  Update the module and function docstrings from “six” to “configured,” without changing redaction, support-model checks, or the two-turn probe.

- [x] **Step 4: Run GREEN and commit.**

  ```bash
  uv run pytest tests/unit/test_preflight_frontier_models.py -v
  uv run ruff check scripts/preflight_frontier_models.py tests/unit/test_preflight_frontier_models.py
  uv run ruff format --check scripts/preflight_frontier_models.py tests/unit/test_preflight_frontier_models.py
  git add scripts/preflight_frontier_models.py tests/unit/test_preflight_frontier_models.py
  git commit -m "feat: preflight explicit Tinker model routes"
  ```

## Task 4: Add contract-tested Nemotron matrices and pricing

**Files:**

- Modify: `tests/unit/test_frontier_models_smoke_config.py`
- Create: `configs/experiments/nemotron3_ultra_tinker_smoke_2026_07.yaml`
- Create: `configs/experiments/nemotron3_ultra_tinker_full_2026_07.yaml`
- Modify: `configs/prices.yaml`
- Modify: `CLAUDE.md`

- [x] **Step 1: Write failing matrix and price contracts.** Require both files, the exact model ID, `openai-agents`, `provider_route: tinker`, `api_mode: chat_completions`, `reasoning_effort: high`, 50 turns, ten SDK retries, and the 100,000-character tool cap. Require the smoke matrix to emit three distinct single-task Modal slices at concurrency one and the full matrix to emit three distinct 25-task Modal slices at concurrency five. Require exact price values `input: 3.32`, `cache: 0.664`, `output: 8.30`.

- [x] **Step 2: Run RED.**

  ```bash
  uv run pytest tests/unit/test_frontier_models_smoke_config.py -v
  ```

  Expected: both matrix files and the price entry are missing.

- [x] **Step 3: Add the smoke matrix.** Use the three existing single-task datasets, Modal, concurrency one, one attempt, two infrastructure retries, timeout multiplier 2.0, and trials root `logs/experiments/nemotron3_ultra_tinker_smoke_2026_07`.

- [x] **Step 4: Add the full matrix.** Use the three 25-task dataset/registry pairs, Modal, concurrency five, one attempt, two infrastructure retries, timeout multiplier 2.0, and trials root `logs/experiments/nemotron3_ultra_tinker_full_2026_07`.

- [x] **Step 5: Add exact pricing and the repo lesson.** Add:

  ```yaml
  nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16:peft:262144:
    input: 3.32
    output: 8.30
    cache: 0.664
  ```

  In `CLAUDE.md` record: “Treat Tinker as an explicit provider route independent of model vendor prefix. Tinker-served `nvidia/*` models use the same `openai-agents` Chat Completions, `TINKER_API_KEY`, separated-reasoning replay path as Inkling; never infer OpenRouter solely from a non-`thinkingmachines/*` ID.”

- [x] **Step 6: Run GREEN and commit.**

  ```bash
  uv run pytest tests/unit/test_frontier_models_smoke_config.py -v
  uv run ruff check tests/unit/test_frontier_models_smoke_config.py
  uv run ruff format --check tests/unit/test_frontier_models_smoke_config.py
  git diff --check
  git add configs/experiments/nemotron3_ultra_tinker_smoke_2026_07.yaml configs/experiments/nemotron3_ultra_tinker_full_2026_07.yaml configs/prices.yaml tests/unit/test_frontier_models_smoke_config.py CLAUDE.md
  git commit -m "chore: add Nemotron Tinker evaluation matrices"
  ```

## Task 5: Verify locally and run both live Tinker probes

- [ ] **Step 1: Run repository verification before paid calls.**

  ```bash
  uv run pytest
  uv run ruff check src/ tests/ scripts/preflight_frontier_models.py
  uv run ruff format --check src/ tests/ scripts/preflight_frontier_models.py
  git diff --check
  uv run cb data verify
  ```

- [ ] **Step 2: Run the high-effort redacted probe.** Write only sanitized metadata to an ignored log root:

  ```bash
  uv run python scripts/preflight_frontier_models.py \
    --config configs/experiments/nemotron3_ultra_tinker_smoke_2026_07.yaml \
    --env-file .env \
    --output logs/experiments/nemotron3_ultra_tinker_preflight_2026_07/high.json
  ```

  Require `success`, `tool_roundtrip`, and `reasoning_metadata` to be true for Nemotron.

- [ ] **Step 3: Run the default-effort redacted probe.** Create an ignored copy of the smoke matrix under `logs/.slices/nemotron3_ultra_tinker_preflight_2026_07/default.yaml` with only the `reasoning_effort: high` line removed, then run the same script to `default.json`. Require the same three booleans.

- [ ] **Step 4: Select the evaluated reasoning setting.** If both pass, keep `high`. If only default passes and high returns a sanitized unsupported-parameter failure, first change the matrix-contract expectation to omit `reasoning_effort`, observe RED, remove it from both matrices, run GREEN, and commit `fix: use Nemotron default Tinker reasoning`. Any other failure blocks paid benchmark trials pending diagnosis.

## Task 6: Run three Modal domain canaries

- [ ] **Step 1: Materialize and audit the smoke slices.**

  ```bash
  uv run python scripts/_emit_run_table_commands.py \
    --config configs/experiments/nemotron3_ultra_tinker_smoke_2026_07.yaml \
    --environment modal
  ```

  Require three generated YAML files, one per domain, with distinct trials directories outside the full root.

- [ ] **Step 2: Run each canary sequentially.** Execute each command emitted by the prior step at concurrency one. Do not inspect process command lines.

- [ ] **Step 3: Gate the full run.** Require exactly three verifier-backed `result.json` files, three `verifier/scorecard.json` files, no infrastructure exceptions, exact Nemotron model identity in each result, and agent logs showing a completed Tinker reasoning/tool conversation. Preserve genuine task failures as valid canary outcomes if the infrastructure and harness are healthy.

## Task 7: Execute and monitor the 75-task full evaluation

- [ ] **Step 1: Materialize the full slices.**

  ```bash
  uv run python scripts/_emit_run_table_commands.py \
    --config configs/experiments/nemotron3_ultra_tinker_full_2026_07.yaml \
    --environment modal
  ```

  Require exactly three generated slice YAMLs and 75 scheduled registry cells.

- [ ] **Step 2: Create a resumable driver.** Adapt the verified frontier driver to `logs/.slices/nemotron3_ultra_tinker_full_2026_07/run_all.sh`, with output root `logs/experiments/nemotron3_ultra_tinker_full_2026_07`, expected slice count three, and the existing 25-result/25-scorecard per-slice gate. Keep its directory lock and refusal to append to a partial slice.

- [ ] **Step 3: Run and monitor.** Run the driver in the Codex task terminal. Monitor `driver.log`, verifier-backed result/scorecard counts, Modal container counts, and terminal output only. Never use `ps`, `pgrep -a`, or any process-command-line dump.

- [ ] **Step 4: Resume narrowly.** Skip completed slices. For a verified provider/infrastructure transient, archive the entire partial slice outside the aggregation root before rerunning. Do not rerun max-turn exhaustion, invalid tool calls, task failures, or other genuine agent outcomes.

## Task 8: Aggregate, verify, and report seven models

- [ ] **Step 1: Aggregate Nemotron independently.**

  ```bash
  uv run python scripts/aggregate.py \
    --trials-dir logs/experiments/nemotron3_ultra_tinker_full_2026_07 \
    --prices configs/prices.yaml \
    --out-csv logs/experiments/nemotron3_ultra_tinker_full_2026_07/summary.csv \
    --out-json logs/experiments/nemotron3_ultra_tinker_full_2026_07/summary.json
  ```

- [ ] **Step 2: Verify completeness.** Require exactly 75 verifier-backed unique `(model, task)` cells, 25 tasks in each domain, 75 scorecards, exact model identity, and no duplicate task for the model.

- [ ] **Step 3: Build the seven-model report.** Copy the verified six-model report generator to the new slice root, add the Nemotron display name and root argument, change its completeness contracts from 450 to 525 trials and from 150 to 175 trials per domain, and write outputs to `logs/experiments/frontier_models_seven_model_full_2026_07/`. Concatenate the independent Nemotron native summary row with the existing six-model native rows without running bootstrap again.

- [ ] **Step 4: Run final code and report verification.**

  ```bash
  uv run pytest
  uv run ruff check src/ tests/ scripts/preflight_frontier_models.py
  uv run ruff format --check src/ tests/ scripts/preflight_frontier_models.py
  git diff --check
  git status --short
  ```

- [ ] **Step 5: Close the execution record.** Mark this plan's completed checkboxes, record the sanitized preflight outcome, 3/3 canary count, 75/75 trial and scorecard count, report locations, and limitations. Commit the plan update and report that this is pass@1, not pass@3.
