# The chi-Bench Judge

The verifier ("WorkspaceJudge") scores every trial. It is implemented as
an `claude-code`-based agent that reads:

- The original expectations at `/opt/chi-bench/tasks/<task_id>/fixtures/expectations.json`, or the task verifier's explicit expectations path. This file exists only in the trusted simulator/verifier filesystem.
- The rubrics for this task.
- The full trial workspace (every file the agent wrote).

Before verification, the source runner stops the agent container, closes tool admission, and waits for admitted calls to finish. A stop or drain failure prevents verification. It uploads `/tests` only to the trusted container and executes the verifier there. Exports require the per-trial control token; the verifier sends it through authenticated HTTP headers. Neither the token nor verifier inputs are installed in the agent container.

Native Hub exports use Harbor's separate verifier environment and a trusted simulator-side collection hook. The hook captures final state after the agent service stops. The verifier requires this snapshot through `--exported-state-input`; it does not contact an agent-controlled endpoint. This mode is also supported by the marathon session verifier.

It then produces `verdicts.json` with per-rubric `pass: bool` and
`evidence_refs: list` fields. The leaderboard trial reward is the AND of all
non-N/A rubric verdicts in every domain. The scorecard also records
`fractional_reward = passed_checks / total_checks` for diagnostics, including
Care Management; fractional reward is not the published leaderboard axis.

Required judge verdicts that are missing because of an outage, timeout, or
incomplete output make the trial **invalid**, rather than N/A or an agent
failure. The verifier exits with code 2 and writes `validity.json` alongside
the scorecard. Its numeric Harbor reward is 0 as a transport placeholder;
it is not a scored zero. Fractional reward is null. Aggregation and submission
preparation reject invalid trials until they are rejudged or rerun, and
submission status lists them separately. Marathon sessions are invalid if
any constituent task could not be scored. Intentional N/A checks retain their
usual meaning. Current E2E requires a Provider submission; legacy no-submit
E2E artifacts cannot be scored or aggregated under the current protocol.
The small validity record contains no judge prompts or private case answers.

Judge output must contain exactly the requested rubric IDs, each once. Every
verdict requires a JSON boolean, a nonblank explanation, and a nonempty list of
nonblank string evidence references. Duplicate JSON keys, unknown IDs, malformed
values, or partial output invalidate the response. Strings such as `"false"`
are never interpreted as passing booleans.

A denial for failed member eligibility can use the completed intake record as
its source. The stage verifier checks that the record belongs to the same case,
that `decision_member_eligible` is false, and that the final decision is `denied`.
The task must also require the denial letter. A clinical review record is not
required for this intake result.

## Why a single judge model?

All paper numbers were collected with `claude-opus-4-7` as the judge.
For reproducibility, the OSS release pins the same judge model.
`CHI_BENCH_JUDGE_MODEL` is honored if set but deviates from the paper's
protocol.

## API key requirements

`ANTHROPIC_API_KEY` is **always required**, even if the agent under
test is not an Anthropic model (e.g. running Codex or OpenClaw still
needs the Anthropic key to power the judge). Verifier runs cost approx
$0.05-$0.30 per trial on top of agent costs.

## Determinism

The judge is non-deterministic (LLM-based). The paper averages over
3 trials per task; we recommend the same. To smooth further, set
`CHI_BENCH_JUDGE_NUM_VOTES > 1`: the judge runs N times per trial and
majority-votes per rubric.

## Re-judging without re-running agents

```bash
cb experiment rejudge --trial-root logs/experiments/<run> -e local
```

This re-invokes only the judge against retained trial artifacts. It writes
side-by-side results to `verifier_rejudge/` by default, including a small
`validity.json`. Required missing or degraded verdicts make the rejudge
invalid and its fractional reward null. Intentional CM gate-failed skips remain
valid. Legacy or unversioned E2E artifacts are rejected before rejudging.

Rejudging uses the live verifier's judge eligibility and CM manifest/world
resolution, including `CHI_BENCH_WORLDS_DIR`. Contracts with no required
judge step keep their deterministic scores without a model call.

Rejudging preserves the canonical `verifier/`, `result.json`, and reward
files. Review the new scorecard and provenance before incorporating a
rejudged result into an evaluation. The command does not replace canonical
results or change what aggregation reads; running it alone does not make
an invalid original trial eligible for aggregation or submission.
Output paths that target canonical files, and existing output files linked
through symlinks or hardlinks, are rejected before the judge runs.

Full flag-by-flag reference: [`docs/cli.md`](cli.md#cb-experiment-rejudge).

## Trusted reference controls

Provider new-referral and single-role UM tasks have a trusted reference
workflow. A host controller can call
`await chi_bench.verifier.reference_oracle.run_reference_control(environment)`
after starting a fresh environment and before starting a model harness. The
helper invokes the authenticated oracle endpoint, executes normal workflow
services, and then freezes the environment for the normal verifier lifecycle.
Its execution result explicitly says that semantic verification has not run;
run the verifier to assess the resulting outputs. Single-role P2P references
invoke the configured counterpart model through the normal conversation service.

E2E references require `workflow_v2`. They preserve the original Provider
disposition as an observation, submit available chart documents, and process
that packet through ordinary payer services. P2P reference turns are explicitly
labeled scripted relay turns. These are trusted service controls, not blind
model trajectories or independent confirmation of clinical gold. Missing authored
inputs are listed in `unresolved_reference_content`.

CM returns 25 authored static answers based on each persona, hidden path and
final gold. Each answer includes source bindings, an ideal outreach dialogue,
assessment and care plan. Its metadata says `reference_mode: static_answer`,
`executed: false`, and `observed: false`. Reading an answer does not run the
patient simulator, write a conversation, freeze the environment, or invoke the
CM verifier. Static authoring is not an observed patient interaction.

Marathon composes constituent references in manifest order. Provider and UM
workflows use the same shared world and freeze once after the final task. CM
Marathon returns a static collection of the constituent answers.

This API does not give the clean agent a control token or private package.
Stock Harbor oracle execution inside the clean agent cannot use this protected
entrypoint. Unknown reference contracts or missing authored answers return an
explicit unsupported error; they do not synthesize an interview or report success.

## Versioned E2E scoring

`workflow_v2` is the only supported protocol and the default for new E2E runs.
It requires Provider-to-Payer handoff with separate model role contexts. The
version is retained in trusted exported state, scorecards, and aggregate rows.
Explicit legacy settings are rejected before execution. Verification, rejudging,
and aggregation reject legacy or unversioned E2E artifacts rather than relabeling
them. Existing historical artifacts remain unchanged. Original task evidence
and gold remain read-only inputs to the current verifier.

In `workflow_v2`, Provider is scored on target identity, request fields and
truthfulness to its source chart. The standalone submit/no-submit disposition is
an audit observation. Provider must submit the best available truthful packet,
including known gaps. No submission fails the required handoff checks.

Payer is scored against the actual submitted packet and governing policy.
The original expected clinical outcome is retained as an observation rather
than imposed on a changed packet. A final determination or a substantiated pend
can complete the downstream episode. `pended_action_required` is a case status,
not a final-determination decision. Nurse and MD checks apply to reached stages;
documented lawful early exits do not create failures for unreached stages.
Both Provider source fidelity and Payer actual-packet policy rubrics remain
required, including when a legacy task's stage list omits them.

E2E P2P uses separate Provider and Payer model turns. The controller downloads
each role's output from the agent container before parsing and relaying it.
Read-only `p2p_session.get_context` is allowed; `send_turn` and `submit_summary`
cannot replace the two-role relay with a simulated conversation or summary.

The private relay receipt retains each role turn's final position and readiness,
plus the position summaries derived from those turns. Both explicitly linked and
reindexed workspace transcripts must match that complete receipt. A changed
workspace transcript fails the integrity check. A matching private receipt with
missing or invalid scoring fields makes verification refuse scoring and require
a rerun; this includes older `workflow_v2` receipts that retained only actors and
messages. Writable artifacts cannot supply missing trusted proof, and retained
episodes remain unchanged.
