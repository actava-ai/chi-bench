# The chi-Bench Judge

The verifier ("WorkspaceJudge") scores every trial. It is implemented as
an `claude-code`-based agent that reads:

- The expectations file at `/fixtures/expectations.json` (hidden from the
  agent under test).
- The rubrics for this task.
- The full trial workspace (every file the agent wrote).

It then produces `verdicts.json` with per-rubric `pass: bool` and
`evidence_refs: list` fields. The trial reward is the AND of all rubric
verdicts (or, for CM, a continuous score over rubrics).

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

This re-invokes only the judge against existing workspaces — useful
when the judge prompt is tuned mid-experiment.

Full flag-by-flag reference: [`docs/cli.md`](cli.md#cb-experiment-rejudge).
