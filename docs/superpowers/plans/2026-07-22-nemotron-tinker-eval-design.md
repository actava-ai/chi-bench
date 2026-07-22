# Nemotron 3 Ultra 256K on Tinker: Evaluation Design

**Date:** 2026-07-22

**Status:** Approved

## Objective

Evaluate `nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16:peft:262144` on the
same chi-Bench leaderboard pass@1 protocol used for the six-model frontier run: one attempt over
all 75 headline tasks, split evenly across provider prior authorization, payer utilization
management, and care management. Keep the run independent and append its completed row to the
existing six-model reports.

## Harness and provider route

Use the repository's `openai-agents` harness and Tinker's OpenAI-compatible Chat Completions
endpoint. This is the same runtime pattern used for Inkling: the harness reads `TINKER_API_KEY`
from `.env`, maps it to the OpenAI SDK's expected `OPENAI_API_KEY` variable inside the agent
process, sends the exact model ID to Tinker, requests separated reasoning, and replays reasoning
only to the exact model that produced it.

The current implementation infers Tinker solely from a `thinkingmachines/` model prefix. That
works for Inkling but misroutes Nemotron's `nvidia/` ID to OpenRouter. Add an explicit
`provider_route: tinker` agent option. Explicit Tinker routing wins over automatic vendor-prefix
routing, requires `TINKER_API_KEY`, forces the Tinker base URL and Chat Completions, and preserves
the model ID verbatim. Existing configurations without the option retain their current routing.

Inside the runner, recognize a Tinker Chat Completions route from the normalized Tinker base URL
and API mode rather than the model vendor prefix. The same endpoint guard, plus equality between
the current model and the reasoning item's origin model, protects reasoning replay.

## Preflight and reasoning gates

Teach the redacted frontier preflight to honor `provider_route: tinker` and accept a non-empty
one-row evaluation matrix. Its two-turn probe must force one tool call, replay the full assistant
message (including separated reasoning) with the tool result, require final text, and record only
sanitized operational metadata.

Run the live probe twice before any benchmark trial:

1. With `reasoning_effort: high`.
2. With `reasoning_effort` omitted, which asks Tinker for Nemotron's default full-reasoning mode.

Use `high` for the benchmark only if Tinker accepts it and both calls return a clean tool
round-trip with non-empty `reasoning_content`. Otherwise use the omitted setting when that probe
passes. Do not send NVIDIA's self-hosting-only `chat_template_kwargs` unless the Tinker canary
demonstrates they are required.

## Evaluation matrices and execution

Create a three-single-task smoke matrix and a separate full matrix. Both use the exact 256K model
ID, `openai-agents`, explicit Tinker routing, Chat Completions, 50 maximum turns, ten SDK retries,
and a 100,000-character tool-return cap. The full matrix uses Modal, concurrency five, one
attempt, two Harbor infrastructure retries, a 2.0 agent-timeout multiplier, and the same three
25-task registries as the previous frontier run.

After both direct probes pass, run one Modal task from each domain at concurrency one. Require an
agent result, verifier scorecard, correct model identity, Tinker routing evidence, successful
reasoning/tool replay, and no infrastructure exception. Treat concurrency five as provisional;
reduce it only if the canaries or provider responses show capacity or rate-limit pressure.

Materialize the three full domain slices beneath
`logs/.slices/nemotron3_ultra_tinker_full_2026_07/` and write results only beneath
`logs/experiments/nemotron3_ultra_tinker_full_2026_07/`. The resumable driver skips verified
complete slices. Before retrying a transient partial slice, archive its entire directory outside
the aggregation root. Genuine agent failures remain evaluation outcomes and are never rerun.

## Pricing, aggregation, and reporting

Add Tinker's current run-date rates for the exact 256K ID to `configs/prices.yaml`: $3.32 per
million input tokens, $0.664 per million cached input tokens, and $8.30 per million sampled output
tokens. These are Tinker's documented limited-time discounted prices on 2026-07-22.

Aggregate the Nemotron root independently with the repository-native bootstrap. Verify exactly 75
unique model/task cells and 75 scorecards. Then concatenate that native row with the existing six
native rows without re-bootstrap, preserving confidence intervals. Regenerate the domain-aware
report for seven models and state that the result is pass@1; it is not the paper's three-attempt
pass@3 protocol.

## Safety and auditability

Never print credentials or process command lines: Harbor arguments contain raw agent environment
values. Monitor only driver logs, verifier-backed result and scorecard counts, Modal container
counts, and the Codex task terminal. Keep direct probes, three-task canaries, and full results in
disjoint roots so no canary can enter final aggregation.
