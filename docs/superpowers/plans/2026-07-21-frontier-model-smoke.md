# Frontier Model Smoke Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Every behavior change follows test-driven development; live API calls happen only after local tests pass.

**Goal:** Add reproducible chi-Bench configuration and provider routing for Fable 5, GPT-5.6 Sol/Terra/Luna, Kimi K3, and TML Inkling 256K. After the user deferred Fable 5, validate the five remaining model cells with a minimal tool-use preflight, then run a 15-trial smoke matrix spanning one task in each benchmark domain.

**Architecture:** Keep first-party models on their native harnesses (`claude-code` and `codex`) and route all third-party models through the existing `openai-agents` harness. Extend that harness with an explicit Tinker route and Chat Completions mode; preserve OpenRouter behavior for Kimi. Store the reviewed six-row matrix in one experiment YAML, store current prices in the shared price table, and write redacted preflight evidence before launching benchmark trials.

**Tech Stack:** Python 3.13, pytest, Ruff, Harbor, OpenAI Agents SDK 0.13.6, Anthropic/Claude Code, OpenAI Codex, OpenRouter, Tinker, Docker, YAML.

---

## Reviewed matrix

| Cell | Harness | Model identifier | Provider route |
|---|---|---|---|
| Fable 5 | `claude-code` | `anthropic/claude-fable-5` | Anthropic native |
| GPT-5.6 Sol | `codex` | `openai/gpt-5.6-sol` | OpenAI native |
| GPT-5.6 Terra | `codex` | `openai/gpt-5.6-terra` | OpenAI native |
| GPT-5.6 Luna | `codex` | `openai/gpt-5.6-luna` | OpenAI native |
| Kimi K3 | `openai-agents` | `moonshotai/kimi-k3` | OpenRouter |
| Inkling 256K | `openai-agents` | `thinkingmachines/Inkling:peft:262144` | Tinker OpenAI-compatible Chat Completions |

## Task 1: Extend `openai-agents` routing and runner controls (TDD)

**Files:**

- Modify: `src/chi_bench/experiment/agents/openai_agents_harness.py`
- Modify: `src/chi_bench/experiment/agents/openai_agents_runner.py`
- Modify: `src/chi_bench/experiment/agents/registry.py`
- Modify/Create tests under: `tests/unit/`

- [x] Add failing unit tests proving `thinkingmachines/*` selects the Tinker endpoint, requires `TINKER_API_KEY`, preserves the exact model ID, and sets Chat Completions mode.
- [x] Add failing tests proving `api_mode` and `reasoning_effort` are forwarded to the runner while existing OpenAI/OpenRouter routes remain unchanged.
- [x] Observe the targeted tests fail for the intended missing behavior.
- [x] Implement the smallest routing and runner-provider changes that pass those tests.
- [x] Add `TINKER_API_KEY` to the runtime forwarding/registry metadata without exposing its value.
- [x] Run targeted tests and Ruff checks.
- [x] Add a regression test and explicit Chat Completions model hook so Inkling reasoning content
  is replayed across tool turns; Agents SDK 0.13.6 defaults this replay to DeepSeek models only.

## Task 2: Add the reviewed experiment matrix and prices

**Files:**

- Create: `configs/experiments/frontier_models_smoke_2026_07.yaml`
- Modify: `configs/prices.yaml`
- Modify/Create tests under: `tests/unit/`

- [x] Add a failing config test that loads the matrix and asserts exactly six rows, the approved harness/model mapping, the three single-task domain paths, Docker execution, timeout multiplier, and per-row reasoning/provider options.
- [x] Add a failing price-table test for all six exact model keys and current rates.
- [x] Observe failures, then add only the reviewed YAML and price entries.
- [x] Verify the matrix emitter expands the YAML to exactly 18 unique trial commands.
- [x] Run targeted tests and Ruff checks.

## Task 3: Build a redacted live preflight (TDD)

**Files:**

- Create: `scripts/preflight_frontier_models.py`
- Create: `tests/unit/test_preflight_frontier_models.py`

- [x] Add failing tests for config loading, provider dispatch, a two-turn no-op tool exchange, redaction, continue-on-error behavior, structured JSON output, and nonzero exit on any failed cell.
- [x] Implement adapters for Anthropic Messages, OpenAI Responses, OpenRouter/Tinker OpenAI-compatible APIs, and the two support-model checks (`claude-opus-4-7`, `claude-sonnet-5`).
- [x] Ensure no secret values can appear in stdout, stderr, or the report.
- [x] Run targeted tests, the full default test suite, and Ruff checks.

## Task 4: Run live preflight and resolve only exact-ID/provider issues

- [x] Run `uv run python scripts/preflight_frontier_models.py --config configs/experiments/frontier_models_smoke_2026_07.yaml --env-file .env --output logs/preflight/frontier_models_2026_07.json`.
- [x] Record request IDs, tool-roundtrip success, reasoning metadata presence, usage, latency, and sanitized errors.
- [x] Do not silently substitute another model if Fable access or the exact Inkling identifier is rejected; investigate the provider's exact accepted identifier and report any remaining access block.
- [x] After the user deferred Fable 5's retention-policy-gated cell, require all five in-scope evaluated cells plus judge and patient-simulator support checks to pass before launching trials.

## Task 5: Build runtime image and execute the 15-trial smoke (Fable deferred)

- [x] Build the current worktree image with `uv run cb docker build`.
- [x] Filter out the deferred Fable row and verify exactly 15 trials (five rows times three single-task datasets).
- [x] Run sequentially to avoid provider-rate-limit confounding.
- [x] Preserve final raw logs/results under `logs/experiments/frontier_models_smoke_2026_07`, with superseded infrastructure-only attempts retained in sibling audit directories.
- [x] Aggregate reward, rubric outcomes, token usage, latency, cost, and failure categories by model and domain.

## Task 6: Final verification and report

- [x] Run `uv run pytest`.
- [x] Run `uv run ruff check src/ tests/ scripts/` and `uv run ruff format --check src/ tests/ scripts/` for changed Python files/scopes supported by repository config.
- [x] Inspect `git diff --check`, `git status`, and the generated preflight/trial artifacts.
- [x] Report exact passes/failures and limitations, including the one-task-per-domain sample size and unavailable exception-path usage for three model failures.
- [x] Mention the `CLAUDE.md` self-improvement notes added for the corrected third-party harness convention, unsupported Claude Code thinking flag, qualified Docker task names, and paired OpenAI SDK pin.
