# Nemotron 3 Ultra 256K Tinker Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route Nemotron 3 Ultra 256K through Tinker with the existing OpenAI Agents reasoning/tool semantics, then run and report one pass@1 attempt over all 75 headline chi-Bench tasks.

**Architecture:** Add an explicit config-scoped Tinker provider route while preserving current automatic routing, and identify Tinker reasoning replay by endpoint plus API mode rather than model-name prefix. For the exact Nemotron-on-Tinker route, adapt strict XML-only tool calls into standard Agents SDK function calls and normalize replay arguments back to the mapping required by Nemotron's chat template. Exercise the same pure protocol adapter in the redacted two-turn preflight, then run isolated three-task canary and 75-task full matrices. Aggregate the completed Nemotron root independently, then append its native row to the prior six-model report without re-bootstrap.

**Tech Stack:** Python 3.13, pytest, YAML, Harbor 0.6.1, OpenAI Agents SDK 0.13.6, OpenAI Python 2.36.0, Tinker OpenAI-compatible Chat Completions, Modal sandboxes, Anthropic WorkspaceJudge.

---

## File map

- `src/chi_bench/experiment/agents/openai_agents_harness.py`: expose and resolve the explicit Tinker route using `TINKER_API_KEY`.
- `src/chi_bench/experiment/agents/openai_agents_runner.py`: apply Tinker Chat Completions and same-model reasoning replay to any model at the Tinker endpoint.
- `src/chi_bench/experiment/agents/nemotron_tool_protocol.py`: strictly parse Nemotron tool XML and normalize historical call arguments without SDK dependencies.
- `src/chi_bench/experiment/agents/nemotron_tinker_model.py`: bridge the exact Nemotron-on-Tinker route to standard Agents SDK response items.
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

## Task 5: Add a strict Nemotron XML tool protocol adapter

**Files:**

- Create: `src/chi_bench/experiment/agents/nemotron_tool_protocol.py`
- Create: `tests/unit/test_nemotron_tool_protocol.py`

- [x] **Step 1: Write failing pure-protocol tests.** Define the exact model constant and a
  `NemotronToolCall` value object. Require the parser to accept one or multiple complete calls,
  preserve multiline strings, decode JSON objects/lists/numbers/booleans, and generate stable
  call IDs. Require it to reject trailing prose, malformed tags, duplicate parameters, invalid
  names, and text with no calls. Require replay normalization to copy inputs, decode function-call
  argument strings to mappings, preserve unrelated items, and reject invalid or non-object JSON.

- [x] **Step 2: Run RED.**

  ```bash
  uv run pytest tests/unit/test_nemotron_tool_protocol.py -v
  ```

  Expected: collection fails because `nemotron_tool_protocol` does not exist.

- [x] **Step 3: Implement the pure fail-closed protocol.** Export this interface without any SDK
  imports so the runner and redacted preflight share it:

  ```python
  NEMOTRON_ULTRA_256K_MODEL = (
      "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16:peft:262144"
  )


  @dataclass(frozen=True)
  class NemotronToolCall:
      call_id: str
      name: str
      arguments: dict[str, object]


  def parse_nemotron_tool_calls(content: str) -> tuple[NemotronToolCall, ...] | None:
      """Parse only complete XML-only Nemotron tool responses; otherwise return None."""


  def normalize_nemotron_replay_input(
      request_input: str | list[dict[str, object]],
  ) -> str | list[dict[str, object]]:
      """Copy replay items and decode function-call argument JSON into mappings."""
  ```

- [x] **Step 4: Run GREEN and commit.**

  ```bash
  uv run pytest tests/unit/test_nemotron_tool_protocol.py -v
  uv run ruff check src/chi_bench/experiment/agents/nemotron_tool_protocol.py tests/unit/test_nemotron_tool_protocol.py
  uv run ruff format --check src/chi_bench/experiment/agents/nemotron_tool_protocol.py tests/unit/test_nemotron_tool_protocol.py
  git diff --check
  git add src/chi_bench/experiment/agents/nemotron_tool_protocol.py tests/unit/test_nemotron_tool_protocol.py
  git commit -m "feat: parse Nemotron Tinker tool protocol"
  ```

## Task 6: Integrate the exact-route adapter and redacted preflight

**Files:**

- Create: `src/chi_bench/experiment/agents/nemotron_tinker_model.py`
- Create: `tests/unit/test_nemotron_tinker_model.py`
- Modify: `src/chi_bench/experiment/agents/openai_agents_runner.py`
- Modify: `tests/unit/test_openai_agents_runner_config.py`
- Modify: `scripts/preflight_frontier_models.py`
- Modify: `tests/unit/test_preflight_frontier_models.py`
- Modify: `configs/experiments/nemotron3_ultra_tinker_smoke_2026_07.yaml`
- Modify: `configs/experiments/nemotron3_ultra_tinker_full_2026_07.yaml`
- Modify: `tests/unit/test_frontier_models_smoke_config.py`

- [x] **Step 1: Write failing model-adapter tests.** Require a
  `NemotronTinkerChatCompletionsModel` subclass to normalize replay input before calling the pinned
  `OpenAIChatCompletionsModel`, preserve reasoning items, replace an XML-only assistant output
  message with standard function-call items, and leave normal final text or malformed XML
  unchanged. Require the runner to select it only for the exact Nemotron model at the Tinker Chat
  Completions route; Inkling and other Tinker models retain the standard wrapper.

- [x] **Step 2: Run model-adapter RED.**

  ```bash
  uv run pytest tests/unit/test_nemotron_tinker_model.py tests/unit/test_openai_agents_runner_config.py -v
  ```

- [x] **Step 3: Implement the model subclass and exact selection.** Override non-streaming
  `get_response`, call the pinned parent with `normalize_nemotron_replay_input(input)`, then convert
  only `ResponseOutputMessage` values whose entire text parses through
  `parse_nemotron_tool_calls`. Construct `ResponseFunctionToolCall` items with the parser's stable
  IDs and JSON-string arguments so the rest of the Agents SDK remains standard. The next call is
  normalized back to mappings only at the Tinker boundary.

- [x] **Step 4: Write failing preflight and matrix tests.** Change the exact Nemotron fake first
  response to raw XML with no `tool_calls`; require the shared parser to construct the historical
  assistant call with mapping arguments, replay the tool result, and obtain final text. First
  change matrix expectations to omit `reasoning_effort`, observe RED, then remove it from both
  committed matrices because the live endpoint returned HTTP 400 for that parameter.

- [x] **Step 5: Implement preflight conversion and default reasoning.** Apply XML conversion only
  when `spec.provider == "tinker"` and the exact model matches. Structured Inkling calls continue
  to replay byte-for-byte. Persist no XML, prompt, reasoning, or response body in the report.

- [x] **Step 6: Run GREEN and commit.**

  ```bash
  uv run pytest tests/unit/test_nemotron_tinker_model.py tests/unit/test_openai_agents_runner_config.py tests/unit/test_preflight_frontier_models.py tests/unit/test_frontier_models_smoke_config.py -v
  uv run ruff check src/ tests/ scripts/preflight_frontier_models.py
  uv run ruff format --check src/ tests/ scripts/preflight_frontier_models.py
  git diff --check
  git add src/chi_bench/experiment/agents/nemotron_tinker_model.py src/chi_bench/experiment/agents/openai_agents_runner.py scripts/preflight_frontier_models.py tests/unit/test_nemotron_tinker_model.py tests/unit/test_openai_agents_runner_config.py tests/unit/test_preflight_frontier_models.py configs/experiments/nemotron3_ultra_tinker_smoke_2026_07.yaml configs/experiments/nemotron3_ultra_tinker_full_2026_07.yaml tests/unit/test_frontier_models_smoke_config.py
  git commit -m "feat: adapt Nemotron tools on Tinker"
  ```

## Task 7: Re-run local verification and the live Tinker gate

- [x] **Step 1: Re-run repository verification before paid benchmark calls.**

  ```bash
  uv run pytest
  uv run ruff check src/ tests/ scripts/preflight_frontier_models.py
  uv run ruff format --check src/ tests/ scripts/preflight_frontier_models.py
  git diff --check
  uv run cb data verify
  ```

- [x] **Step 2: Run the committed default-reasoning redacted probe.**

  ```bash
  uv run python scripts/preflight_frontier_models.py \
    --config configs/experiments/nemotron3_ultra_tinker_smoke_2026_07.yaml \
    --env-file .env \
    --output logs/experiments/nemotron3_ultra_tinker_preflight_2026_07/adapter.json
  ```

  Require the Nemotron row to report `success`, `tool_roundtrip`, and `reasoning_metadata` true;
  require both Anthropic support checks to pass. Treat the prior `high.json` HTTP 400 as the
  evidence for selecting default reasoning, not as an evaluation result.

Execution record: the redacted default-reasoning probe passed all three gates. The exact
Nemotron row reported `success`, `tool_roundtrip`, and `reasoning_metadata` true with 728 input,
92 output, 512 cached, and 820 total tokens; both Anthropic support checks passed. After the
empty-argument replay correction in `ba49f78`, repository verification passed with 234 tests,
one deselected test, Ruff check/format, `git diff --check`, and `cb data verify` all clean.

## Task 8: Run three Modal domain canaries

- [x] **Step 1: Materialize and audit the smoke slices.**

  ```bash
  uv run python scripts/_emit_run_table_commands.py \
    --config configs/experiments/nemotron3_ultra_tinker_smoke_2026_07.yaml \
    --environment modal
  ```

  Require three generated YAML files, one per domain, with distinct trials directories outside the full root.

- [x] **Step 2: Run each canary sequentially.** Execute each command emitted by the prior step at concurrency one. Do not inspect process command lines.

- [x] **Step 3: Gate the full run.** Require exactly three verifier-backed `result.json` files, three `verifier/scorecard.json` files, no infrastructure exceptions, exact Nemotron model identity in each result, and agent logs showing a completed Tinker reasoning/tool conversation. Preserve genuine task failures as valid canary outcomes if the infrastructure and harness are healthy.

First-attempt incident: the provider canary completed two same-turn tool calls, one with seven
arguments and one with none, then Tinker returned HTTP 400 while rendering replay history. A
redacted live diagnostic proved two non-empty parallel mappings succeed, while an exact local SDK
reproduction showed the pinned Agents converter changed the empty mapping back to the string
`"{}"`. Commit `ba49f78` preserves empty arguments as a private truthy mapping until the SDK's
wire serializer emits an ordinary `{}` and adds a real `Runner`/HTTP regression for the mixed
non-empty/empty case. The failed slice was preserved outside the aggregation root before the
force-built provider rerun.

Canary record: all three domain slices produced verifier-backed results and scorecards with the
exact model identity. Provider and care-management completed normally; their canary rewards were
both 0. The payer-UM canary exhausted the configured 50-turn agent budget and was preserved as a
genuine model outcome. No canary retained an adapter, provider, Modal, or verifier infrastructure
failure after the archived first provider attempt.

## Task 9: Execute and monitor the 75-task full evaluation

- [x] **Step 1: Materialize the full slices.**

  ```bash
  uv run python scripts/_emit_run_table_commands.py \
    --config configs/experiments/nemotron3_ultra_tinker_full_2026_07.yaml \
    --environment modal
  ```

  Require exactly three generated slice YAMLs and 75 scheduled registry cells.

- [x] **Step 2: Create a resumable driver.** Adapt the verified frontier driver to `logs/.slices/nemotron3_ultra_tinker_full_2026_07/run_all.sh`, with output root `logs/experiments/nemotron3_ultra_tinker_full_2026_07`, expected slice count three, and the existing 25-result/25-scorecard per-slice gate. Keep its directory lock and refusal to append to a partial slice.

- [x] **Step 3: Run and monitor.** Run the driver in the Codex task terminal. Monitor `driver.log`, verifier-backed result/scorecard counts, Modal container counts, and terminal output only. Never use `ps`, `pgrep -a`, or any process-command-line dump.

- [x] **Step 4: Resume narrowly.** Skip completed slices. For a verified provider/infrastructure transient, archive the entire partial slice outside the aggregation root before rerunning. Do not rerun max-turn exhaustion, invalid tool calls, task failures, or other genuine agent outcomes.

Execution record: the uninterrupted driver completed all three 25-task slices with 75
verifier-backed results and 75 scorecards. Provider contained one `MaxTurnsExceeded` agent outcome,
which was preserved; payer UM and care management had no execution exceptions. No full-evaluation
slice required archival or rerun.

## Task 10: Aggregate, verify, and report seven models

- [x] **Step 1: Aggregate Nemotron independently.**

  ```bash
  uv run python scripts/aggregate.py \
    --trials-dir logs/experiments/nemotron3_ultra_tinker_full_2026_07 \
    --prices configs/prices.yaml \
    --out-csv logs/experiments/nemotron3_ultra_tinker_full_2026_07/summary.csv \
    --out-json logs/experiments/nemotron3_ultra_tinker_full_2026_07/summary.json
  ```

- [x] **Step 2: Verify completeness.** Require exactly 75 verifier-backed unique `(model, task)` cells, 25 tasks in each domain, 75 scorecards, exact model identity, and no duplicate task for the model.

- [x] **Step 3: Build the seven-model report.** Copy the verified six-model report generator to the new slice root, add the Nemotron display name and root argument, change its completeness contracts from 450 to 525 trials and from 150 to 175 trials per domain, and write outputs to `logs/experiments/frontier_models_seven_model_full_2026_07/`. Concatenate the independent Nemotron native summary row with the existing six-model native rows without running bootstrap again.

- [x] **Step 4: Run final code and report verification.**

  ```bash
  uv run pytest
  uv run ruff check src/ tests/ scripts/preflight_frontier_models.py
  uv run ruff format --check src/ tests/ scripts/preflight_frontier_models.py
  git diff --check
  git status --short
  ```

- [x] **Step 5: Close the execution record.** Mark this plan's completed checkboxes, record the sanitized preflight outcome, 3/3 canary count, 75/75 trial and scorecard count, report locations, and limitations. Commit the plan update and report that this is pass@1, not pass@3.

Final execution record:

- Nemotron native pass@1 was 0/75 with mean fractional reward 0.216844; domain fractional
  means were 0.112390 provider PA, 0.244745 payer UM, and 0.293397 care management.
- The only execution exception was one provider `MaxTurnsExceeded` at the configured 50-turn
  limit. It was preserved as a genuine agent outcome; there were no provider/infrastructure
  failures in the completed full root.
- Usage was 36,717,929 input tokens (33,434,624 cached) and 279,098 output tokens. Cost coverage
  was 74/75 trials with $35.417676 known Nemotron agent spend; the native mean across all 75 was
  $0.472236 per trial.
- The seven-model report is under
  `logs/experiments/frontier_models_seven_model_full_2026_07/` with `report.md`, `report.json`,
  native `summary.csv`/`summary.json`, and detailed model/domain/failure/exception CSVs.
- Independent verification found 525 unique model/task trials, 525 scorecards, 175 trials per
  domain, exact model identities, no duplicates, and no score/reward integrity discrepancies.
- Final repository verification passed 234 tests (one deselected), Ruff check/format,
  `git diff --check`, and `cb data verify`.
- This run is leaderboard pass@1: one attempt per task. It is not paper pass@3 or pass^3; those
  require two additional attempts per model/task cell.
