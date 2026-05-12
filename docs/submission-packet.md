# Submission packet contract

This document specifies the format of a **submission packet** — the directory a benchmark producer hands to the actava-ai/leaderboard repo. Any benchmark that emits packets matching this contract is submittable via the leaderboard's `scripts/submit.py` (or the manual flow); the leaderboard's CI validator (`.github/scripts/validate_submission.py`) enforces it.

chi-bench produces packets via `cb submission prepare`. New benchmarks publish their own equivalent.

## Directory shape

```
<YYYY-MM-DD>-<submission_id>/
├── submission.json
├── results.csv
├── sub.yaml
├── provenance.json
├── README.md
└── trials/
    └── <domain>/
        └── <trial_id>/
            ├── result.json
            ├── verifier/
            │   ├── scorecard.json
            │   └── reward.json
            └── agent/
                └── trajectory.jsonl.zst
```

- Directory name regex: `^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9_-]{0,63}$`. The slug part equals `submission.json:submission.id`. The date is UTC and must be ≤ today.
- No additional files. No `.zip`, no `.bak`, no hidden files (except `.gitkeep`). The validator rejects anything outside the allowlist.

## Required `submission.json` envelope

The outer envelope is **stable across benchmarks**. Validators rely on these three fields:

| Field | Type | Purpose |
|---|---|---|
| `schema` | string | `"<benchmark>/submission/v<N>"` — selects the per-benchmark JSON Schema |
| `submission.id` | slug | Lowercase letters, digits, `-`, `_`. Equals the directory's slug suffix. |
| `dataset.name` | string | The benchmark slug under `benchmarks/<name>/` in the leaderboard repo |

Everything inside `results.*` is benchmark-specific and lives in the per-benchmark schema. chi-bench's `results` shape:

```json
{
  "results": {
    "overall":    { "pass_at_1": 0.28, "n_trials": 75, "n_tasks": 75 },
    "per_domain": {
      "pa_provider": { "pass_at_1": 0.30, "n_trials": 25, "n_tasks": 25 },
      "pa_um":       { "pass_at_1": 0.32, "n_trials": 25, "n_tasks": 25 },
      "cm":          { "pass_at_1": 0.22, "n_trials": 25, "n_tasks": 25 }
    },
    "mean_cost_usd": 4.21,
    "mean_walltime_s": 612.0
  }
}
```

## Trajectory format

`agent/trajectory.jsonl.zst` is zstd-compressed JSONL (level 19). Line 1 is a header object:

```json
{"_atif_header": {"schema_version": "...", "session_id": "...", "agent": {...}}}
```

Lines 2..N are individual step / message objects. The validator stream-decodes the file and parses each line; full-file buffering is not required (and not recommended for large trajectories).

Reviewers inspect with:

```bash
zstdcat trials/<domain>/<trial_id>/agent/trajectory.jsonl.zst | jq .
```

## `results.csv` columns

The CSV mirrors `submission.json` but in a flat, multi-benchmark-friendly shape. Stable leading columns across benchmarks:

| Column | Source |
|---|---|
| `benchmark` | `dataset.name` |
| `dataset_version` | `dataset.version` |
| `submission_id` | `submission.id` |
| `team`, `agent`, `model`, `submitted_at` | `submission.*` |
| `domain` | `"overall"` plus one row per `per_domain` key |
| `pass_at_1`, `n_trials`, `n_tasks`, `mean_cost_usd`, `mean_walltime_s` | per-domain (or overall) score block |

A multi-benchmark consumer can `cat */results.csv` without losing rows.

## Size budget (enforced by the leaderboard validator)

| File | Soft (warn) | Hard (fail) |
|---|---|---|
| `submission.json`, `results.csv`, `sub.yaml`, `provenance.json` | 100 KB | 1 MB |
| `verifier/scorecard.json`, `verifier/reward.json`, `result.json` | 200 KB | 2 MB |
| `agent/trajectory.jsonl.zst` | 10 MB | 50 MB |
| Total submission directory | 100 MB | 500 MB |

## Producing a packet for a new benchmark

1. Pick a benchmark slug; reserve `benchmarks/<slug>/` in the leaderboard repo.
2. Write a JSON Schema at `benchmarks/<slug>/schema/submission-v1.json` covering the envelope above plus your benchmark-specific `results.*` shape.
3. Build your tooling to emit a packet directory matching the layout above. Reuse `cb submission prepare` as a reference implementation if helpful (`src/chi_bench/experiment/submission.py:prepare_packet`).
4. Open a PR against the leaderboard repo adding `benchmarks/<slug>/{schema/,submissions/,README.md}`; submissions follow normally thereafter.

`scripts/submit.py` in the leaderboard repo is benchmark-agnostic — it reads `submission.json:dataset.name` to route the packet into the right subtree, so once the schema is registered no further leaderboard-side code is needed.
