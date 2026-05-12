# Leaderboard repo — design

**Status:** spec, awaiting approval before implementation plan
**Date:** 2026-05-12
**Repos touched:** `actava-ai/chi-bench` (this repo), `actava-ai/leaderboard` (new, currently empty submodule at `leaderboard/`)
**Drives:** README §4 "Submit your agent" rewrite; replacement of `cb submission package` with `cb submission prepare`; first published version of the leaderboard repo

## 1. Goal

Stand up a public `actava-ai/leaderboard` repo that:

- Accepts benchmark submissions via PR (no zip uploads, no web form).
- Stores the full audit packet (manifests + per-trial verifier evidence + compressed trajectories) as plain files in git so reviewers can inspect any submission directly from the PR diff.
- Is **extensible to multiple benchmarks** — chi-bench at v1, swe-bench / agent-bench / etc. later — without cross-cutting edits.
- Stays **loosely coupled** to producer repos like chi-bench: producers emit a packet conforming to a documented contract; the leaderboard owns the directory layout, schema, validation, and PR workflow.
- Runs schema + integrity validation automatically on every PR; humans still review and merge.
- Itself serves as data-only (no rendered HTML); the rendered board is consumed by `actava.ai/benchmarks` reading `results.csv` files out of this repo.

Non-goals:

- Rendering an HTML leaderboard in this repo (out of scope; `actava.ai` handles it).
- Re-judging submissions in CI (trust-the-evidence model at v1; spot-rejudges are manual).
- A custom upload UI, fork-on-our-behalf bot, or merge automation beyond label-on-validate.

## 2. Architecture

### 2.1 Two repos, one packet contract

```
┌─────────────────────────┐         packet contract          ┌──────────────────────────┐
│   chi-bench (producer)  │ ───── /tmp/.../packet/ ─────►   │  leaderboard (consumer)  │
│                         │                                  │                          │
│   cb submission prepare │                                  │   scripts/submit.py      │
│   - curate files        │                                  │   - validate locally     │
│   - compress trajs      │                                  │   - copy into subtree    │
│   - generate manifest   │                                  │   - branch / commit      │
│   - generate README     │                                  │   - fork / push / PR     │
│                         │                                  │                          │
│   knows nothing about   │                                  │   knows nothing about    │
│   the leaderboard repo  │                                  │   chi-bench internals    │
└─────────────────────────┘                                  └──────────────────────────┘
```

The packet contract — what files appear in what shape inside a `<date>-<slug>/` directory — is the only thing crossing the boundary. Documented in `chi-bench:docs/submission-packet.md`. Future benchmarks publish their own `<benchmark> submission prepare` (or equivalent) command that emits a packet matching the same contract; the leaderboard's submit tooling is benchmark-agnostic and auto-detects which benchmark a packet belongs to by reading `submission.json:dataset.name`.

### 2.2 Leaderboard repo layout

```
leaderboard/                         # github.com/actava-ai/leaderboard (public)
├── README.md                        # what this is, how to submit, list of benchmarks
├── CONTRIBUTING.md                  # PR conventions, reviewer checklist
├── LICENSE                          # Apache-2.0
├── .gitattributes                   # minimal — no LFS needed (zstd already binary)
├── .gitignore                       # /tmp/, *.zip, *.bak
│
├── benchmarks/                      # one subtree per benchmark, self-contained
│   ├── README.md                    # cross-benchmark contract for adding a new benchmark
│   └── chi-bench/                   # first and only benchmark at v1.0 release
│       ├── README.md                # chi-bench-specific submission notes
│       ├── schema/
│       │   ├── submission-v1.json   # JSON Schema (cross-benchmark envelope + chi-bench results)
│       │   ├── known-versions.txt   # soft check: chi-bench-v1.0.0
│       │   └── README.md            # what's stable, backward-compat policy
│       └── submissions/
│           └── <YYYY-MM-DD>-<slug>/ # one dir per accepted submission (see §2.3)
│
├── scripts/
│   ├── submit.py                    # optional one-command helper (auto-detects benchmark)
│   └── validate.py                  # 5-line shim invoking the CI validator
│
└── .github/
    ├── workflows/
    │   └── validate.yml             # runs on every PR touching benchmarks/**
    ├── PULL_REQUEST_TEMPLATE/
    │   └── submission.md            # auto-populates for submission PRs
    └── scripts/
        └── validate_submission.py   # the validator; reused by scripts/validate.py
```

### 2.3 Submission directory contents

```
benchmarks/chi-bench/submissions/2026-05-12-actava-claude-code-opus-4-6/
├── submission.json                  # manifest (validated by JSON Schema)
├── results.csv                      # leaderboard rows (one per domain + overall)
├── sub.yaml                         # frozen copy of submitter's config
├── provenance.json                  # git SHA, image digest, timestamps
├── README.md                        # auto-generated; headline metrics + inspect snippet
└── trials/
    └── <domain>/                    # pa_provider | pa_um | cm
        └── <trial_id>/
            ├── result.json          # Harbor reward + agent metadata
            ├── verifier/
            │   ├── scorecard.json   # per-rubric-check verdicts
            │   └── reward.json      # verifier's reward breakdown
            └── agent/
                └── trajectory.jsonl.zst   # full trace, zstd level 19
```

Directory naming: `<YYYY-MM-DD>-<submission.id>/`, regex `^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9_-]{0,63}$`. Slug part equals `submission.id` from the YAML. Date ≤ today (UTC).

No Git LFS. Trajectories are stored as `agent/trajectory.jsonl.zst` (each message on its own line, zstd-compressed at level 19) which typically reduces a 30 MB raw trace to 2–5 MB — small enough for plain git. Reviewers inspect via `zstdcat trajectory.jsonl.zst | jq .`.

Auto-generated `README.md` template (rendered per submission):

```markdown
# <team> · <agent> · <model>

Submitted: <date> · <benchmark> <dataset_version> · pass@1: **<overall>%**

| Domain | pass@1 | n_trials |
|---|---|---|
| pa_provider | <pct>% | <n> |
| pa_um       | <pct>% | <n> |
| cm          | <pct>% | <n> |

Inspect a trajectory:

    zstdcat trials/pa_provider/<trial_id>/agent/trajectory.jsonl.zst | jq .

See `submission.json` for the full manifest, `provenance.json` for reproducibility info.
```

### 2.4 Size budget enforced by CI

| File | Soft (warn) | Hard (fail) |
| --- | --- | --- |
| `submission.json`, `results.csv`, `sub.yaml`, `provenance.json` | 100 KB | 1 MB |
| `verifier/scorecard.json`, `verifier/reward.json`, `result.json` | 200 KB | 2 MB |
| `agent/trajectory.jsonl.zst` | 10 MB | 50 MB |
| Total submission directory | 100 MB | 500 MB |

## 3. Manifest + JSON Schema

### 3.1 `submission.json` — top-level manifest

Outer envelope is **stable across benchmarks**; `results.*` is benchmark-specific.

```json
{
  "schema": "chi-bench/submission/v1",
  "submission": {
    "id": "actava-claude-code-opus-4-6",
    "team": "Actava",
    "contact": "redacted@actava.ai",
    "agent": "claude-code",
    "model": "anthropic/claude-opus-4-6",
    "notes": "Default config; no custom prompting.",
    "submitted_at": "2026-05-12T14:03:11Z"
  },
  "dataset": {
    "name": "chi-bench",
    "version": "chi-bench-v1.0.0",
    "domains": ["pa_provider", "pa_um", "cm"]
  },
  "results": {
    "overall": { "pass_at_1": 0.280, "pass_at_1_lo": 0.241, "pass_at_1_hi": 0.322, "n_trials": 75, "n_tasks": 75 },
    "per_domain": {
      "pa_provider": { "pass_at_1": 0.304, "pass_at_1_lo": 0.158, "pass_at_1_hi": 0.500, "n_trials": 25, "n_tasks": 25 },
      "pa_um":       { "pass_at_1": 0.316, "pass_at_1_lo": 0.168, "pass_at_1_hi": 0.514, "n_trials": 25, "n_tasks": 25 },
      "cm":          { "pass_at_1": 0.220, "pass_at_1_lo": 0.097, "pass_at_1_hi": 0.422, "n_trials": 25, "n_tasks": 25 }
    },
    "mean_cost_usd": 4.21,
    "mean_walltime_s": 612.0
  },
  "provenance": {
    "chi_bench_git_sha": "50da4192c0...",
    "image_digest": "sha256:9f1a...",
    "judge_model": "claude-opus-4-7",
    "judge_num_votes": 1,
    "harness_version": "1.0.0",
    "submitted_from_host": "redacted"
  }
}
```

### 3.2 Cross-benchmark contract (the part stable as benchmarks accrete)

Required for any benchmark's `submission.json`:

| Field | Type | Purpose |
|---|---|---|
| `schema` | string | `"<benchmark>/submission/v<N>"` — selects the validator file |
| `submission.id` | slug | Directory name suffix; primary key |
| `dataset.name` | string | Must equal the benchmark slug under `benchmarks/<name>/` |

Everything else (results shape, provenance keys, per-domain breakdowns) is benchmark-local and lives in the per-benchmark schema.

### 3.3 Schema resolution + versioning

- Validator splits the manifest's `schema:` field on `/`, picks `benchmarks/<benchmark>/schema/submission-v<N>.json`.
- v1 is frozen at release; v2 lands alongside it once introduced — old submissions keep validating against v1 forever (the v1 schema file is never edited or removed).
- Per-benchmark schemas (not one shared schema with discriminated unions) because results shapes diverge heavily across benchmarks. The envelope contract above is enforced by a shared utility, not a shared schema file.

### 3.4 `results.csv`

One row per domain plus an `overall` row. Columns (additions vs. `scripts/aggregate.py` today: `benchmark`, `dataset_version`):

```csv
benchmark,dataset_version,submission_id,team,agent,model,domain,pass_at_1,pass_at_1_lo,pass_at_1_hi,n_trials,n_tasks,mean_cost_usd,mean_walltime_s,submitted_at
chi-bench,chi-bench-v1.0.0,actava-claude-code-opus-4-6,Actava,claude-code,anthropic/claude-opus-4-6,overall,0.280,0.241,0.322,75,75,4.21,612.0,2026-05-12T14:03:11Z
chi-bench,chi-bench-v1.0.0,actava-claude-code-opus-4-6,Actava,claude-code,anthropic/claude-opus-4-6,pa_provider,0.304,0.158,0.500,25,25,4.10,580.0,2026-05-12T14:03:11Z
...
```

`benchmark` and `dataset_version` promoted to columns so a multi-benchmark consumer (`actava.ai/benchmarks`) can `cat */results.csv` without losing rows. Requires a small change to `scripts/aggregate.py` in chi-bench.

### 3.5 `provenance.json`

Already produced today; kept as-is. Schema validates required fields (`chi_bench_git_sha`, `image_digest`, `judge_model`, `harness_version`) but allows extras (`additionalProperties: true`) so harness implementers can add debug info.

## 4. Validation CI

One workflow at the leaderboard repo root, runs on every PR touching `benchmarks/**`. Schema + integrity only — no API keys, no agent re-runs.

### 4.1 `.github/workflows/validate.yml`

```yaml
name: validate submission
on:
  pull_request:
    paths: ["benchmarks/**"]
permissions:
  contents: read
  pull-requests: write
  issues: write
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 2 }
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - name: Install validator deps
        run: pip install jsonschema zstandard pyyaml
      - name: Validate
        run: |
          python .github/scripts/validate_submission.py \
            --base-ref ${{ github.event.pull_request.base.sha }} \
            --head-ref ${{ github.event.pull_request.head.sha }} \
            --report-md $GITHUB_STEP_SUMMARY \
            --report-json /tmp/report.json
      - name: Comment + label
        if: always()
        uses: actions/github-script@v7
        with:
          script: |
            // upsert sticky validation comment + apply label
            // (valid-submission / invalid-submission / needs-review)
```

### 4.2 What `validate_submission.py` checks

**Structural — fails the PR:**

1. **Diff scope.** PR touches exactly one new directory under `benchmarks/<name>/submissions/`. Touching anything else (schemas, READMEs, other benchmarks, root files) requires a `meta:` label applied by a maintainer.
2. **Directory naming.** Matches `^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9_-]{0,63}$`. Slug equals `submission.id`. Date ≤ today (UTC).
3. **Required files present.** `submission.json`, `results.csv`, `sub.yaml`, `provenance.json`, `README.md`, at least one `trials/<domain>/<trial_id>/result.json`.
4. **No unexpected files.** Reject `*.zip`, `*.bak`, hidden files except `.gitkeep`, any path traversal (`..`), any binary outside the `.zst` allowlist.

**Schema — fails the PR:**

5. `submission.json` validates against `benchmarks/<bench>/schema/submission-v<N>.json` (resolved from manifest `schema:` field). If schema file missing, fail.
6. `results.csv` rows match the manifest exactly: each per-domain row's numeric fields equal `results.per_domain.<domain>.*` (no tolerance — both are written by the same `write_manifest` call); the `overall` row equals `results.overall.*`; `submission_id` column equals `submission.id`; row count equals `len(per_domain) + 1`.
7. `provenance.json` has required keys per the benchmark's schema.

**Integrity — fails the PR:**

8. Each `trials/<domain>/<trial_id>/` contains exactly the expected file set.
9. `trajectory.jsonl.zst` is valid zstd and valid JSONL (stream-decode + parse-per-line; don't retain decompressed bytes).
10. Trial counts in the tree match `results.per_domain.<domain>.n_trials`.
11. Size limits (§2.4); soft → warning, hard → fail.

**Soft — warning only:**

12. `dataset.version` is listed in `benchmarks/<bench>/schema/known-versions.txt`. Unknown version → warn (file is updated in a follow-up PR).
13. Duplicate `submission.id` across existing submission directories → comment ("looks like a resubmission of `<existing>`; reviewer please confirm intent").

### 4.3 PR labels

- ✅ `valid-submission` — all checks passed.
- ❌ `invalid-submission` — hard check failed; submitter needs to fix.
- ⚠️ `needs-review` — soft warnings only; reviewer judgment call.

`meta:` is a separate label (maintainer-applied, not a validation result) that overrides rule 1's diff-scope check so a maintainer can land a combined "submission + small repo fix" PR when needed.

### 4.4 Sticky PR comment

One comment per PR, upserted on each push. Table of check ✅/❌, headline metrics row, inspect-a-trial snippet. On failure: per-failed-check diagnostic in a code block.

### 4.5 Local invocation

`scripts/validate.py` is a 5-line shim:

```python
#!/usr/bin/env python3
import runpy, sys
sys.argv[0] = ".github/scripts/validate_submission.py"
runpy.run_path(".github/scripts/validate_submission.py", run_name="__main__")
```

Lets submitters run `python scripts/validate.py benchmarks/chi-bench/submissions/<dir>` before opening the PR. Same code path as CI.

## 5. Producer-side change: `cb submission prepare`

Replaces `cb submission package` in chi-bench. Strictly produces a packet; no leaderboard knowledge.

### 5.1 Command

```bash
uv run cb submission prepare -f configs/submissions/<id>.yaml [FLAGS]
```

| Flag | Default | Purpose |
|---|---|---|
| `--out` | `logs/submissions/<id>/packet/` | Where to write the packet |
| `--date` | today (UTC) | Override the directory date prefix |
| `--force` | false | Overwrite an existing packet at the output path |

### 5.2 Steps

1. Re-run `write_manifest()` so `submission.json` + `results.csv` are fresh.
2. Create `<out>/<YYYY-MM-DD>-<submission.id>/` — already correctly named so the user's `cp` is one line, no manual rename.
3. Copy curated top-level files (`submission.json`, `results.csv`, `sub.yaml`, `provenance.json`).
4. Copy per-trial files (`result.json`, `verifier/scorecard.json`, `verifier/reward.json`).
5. Recode `agent/trajectory.json` → `agent/trajectory.jsonl.zst` (streaming JSONL re-serialization + zstd level 19).
6. Generate `README.md` from the manifest using the §2.3 template.
7. Print the final packet path + a one-line pointer to `https://github.com/actava-ai/leaderboard`.

### 5.3 Removed from chi-bench

- `cb submission package` subcommand (deleted, no alias).
- `package_submission()` in `src/chi_bench/experiment/submission.py:865` (deleted).
- All `.zip` writing logic; `import zipfile`.
- README §4 prose mentioning zip / upload-ready packet / leaderboard placeholder.

### 5.4 Retained

- `_PACKET_TOP_LEVEL_FILES`, `_PACKET_TRIAL_FILES` (Section 2 curation rules — reused by `prepare`).
- `cb submission validate | run | status` (unchanged).
- `write_manifest()`, `build_manifest()`, `_iter_trial_dirs()` (unchanged).

### 5.5 New supporting doc

`docs/submission-packet.md` — single page documenting the cross-benchmark packet contract (directory layout, required envelope fields, trajectory compression convention, "any producer matching this contract is submittable to actava-ai/leaderboard"). Linked from chi-bench's `README.md` §4 and from the leaderboard's `benchmarks/README.md`.

## 6. Leaderboard-side submission flow

Two paths, both documented in the leaderboard's `README.md`:

### 6.1 Manual (the baseline)

```bash
# After `cb submission prepare` ran on the chi-bench side:
git clone https://github.com/<you>/leaderboard && cd leaderboard       # your fork
cp -r ~/chi-bench/logs/submissions/<id>/packet/2026-05-12-<slug>/ \
      benchmarks/chi-bench/submissions/
python scripts/validate.py benchmarks/chi-bench/submissions/2026-05-12-<slug>/
git checkout -b sub/chi-bench/2026-05-12-<slug>
git add benchmarks/chi-bench/submissions/2026-05-12-<slug>/
git commit -m "chi-bench: <team> · <agent> · <model>"
git push origin sub/chi-bench/2026-05-12-<slug>
gh pr create --base main   # or open in browser via the printed URL
```

### 6.2 Helper (the convenience)

```bash
python scripts/submit.py ~/chi-bench/logs/submissions/<id>/packet/2026-05-12-<slug>/
```

Behavior:

1. Read packet's `submission.json:dataset.name` to infer the target benchmark (`chi-bench`, `swe-bench`, …). No per-benchmark code in the helper.
2. Run `.github/scripts/validate_submission.py` against the proposed directory before doing anything destructive.
3. Copy packet into `benchmarks/<benchmark>/submissions/<dir-name>/` (`<dir-name>` already correct from the producer).
4. `git checkout -b sub/<benchmark>/<dir-name>` — fail with conflict prompt if branch exists.
5. `git add <subtree>` + commit with auto-generated message and body from the manifest.
6. Resolve the push target. By default: `gh repo fork actava-ai/leaderboard --clone=false --remote=false` (idempotent, no-op if fork exists), then `git push <fork-url>`. `--no-fork` overrides for org members.
7. `gh pr create -R actava-ai/leaderboard --base main --head <user>:<branch> --title ... --body ...` using the PR template.
8. Print PR URL.

Flags:

| Flag | Default | Purpose |
|---|---|---|
| `--no-fork` | false | Push directly to `actava-ai/leaderboard` (org members) |
| `--no-open-pr` | false | Push branch only; skip `gh pr create` |
| `--on-conflict` | (interactive prompt) | `abandon` \| `replace` \| `bump-date`; required for non-TTY |
| `--leaderboard-repo` | `actava-ai/leaderboard` | Override target (testing) |

### 6.3 Preflight failures (helper mode)

```
ERROR: Cannot submit. Resolve before retrying:

  [✗] gh CLI authenticated      → run `gh auth login`
  [✓] git on PATH
  [✗] git user.email configured → run `git config --global user.email <you>`

Once these pass, re-run this command.
```

### 6.4 Resubmission semantics

- New date prefix → new directory, new branch, new PR. Old submission stays; reviewers decide whether to remove the old in a follow-up.
- Same date + same slug already exists on `main` → helper prompts `abandon | replace | bump-date` (or honors `--on-conflict`). Validator soft warning (§4.2 rule 13) catches it from the reviewer side too.

### 6.5 Idempotency

- Packet generation rebuilds the staging tree every run — safe to re-run after any failure.
- Helper's leaderboard checkout lives at `~/.cache/leaderboard-checkout/`, reused across runs.
- Crash after commit / before push → re-run picks up at push. Crash after push / before PR → re-run picks up at `gh pr create`.

## 7. Documentation footprint

### 7.1 chi-bench (changes)

| File | Change |
|---|---|
| `README.md` §4 "Submit your agent" | Rewrite: 4-command flow (validate, run, status, prepare) + pointer to leaderboard repo. Remove all zip / upload-ready references and the "until v1.0 release" placeholder. |
| `docs/submission-packet.md` | **New.** Cross-benchmark packet contract; ~80 lines. |
| `docs/cli.md` | Replace `cb submission package` entry with `cb submission prepare`. |
| `CLAUDE.md` Commands section | Same swap. |

### 7.2 leaderboard (new files, all v1)

| File | Purpose | Approx length |
|---|---|---|
| `README.md` | What this is; how to submit (both manual + helper); benchmarks tracked; link to rendered board at `actava.ai/benchmarks` | ~150 lines |
| `CONTRIBUTING.md` | Reviewer checklist; what CI catches vs. what reviewers verify; resubmission policy | ~80 lines |
| `LICENSE` | Apache-2.0 | — |
| `.gitattributes` | Minimal (no LFS) | ~5 lines |
| `.gitignore` | `/tmp/`, `*.zip`, `*.bak` | ~10 lines |
| `benchmarks/README.md` | Cross-benchmark contract for adding a new benchmark | ~50 lines |
| `benchmarks/chi-bench/README.md` | chi-bench-specific notes; link to producer repo; how to inspect a trajectory | ~60 lines |
| `benchmarks/chi-bench/schema/submission-v1.json` | The JSON Schema | data |
| `benchmarks/chi-bench/schema/known-versions.txt` | `chi-bench-v1.0.0` | data |
| `benchmarks/chi-bench/schema/README.md` | Schema versioning + backward-compat policy | ~30 lines |
| `.github/workflows/validate.yml` | §4.1 workflow | ~60 lines |
| `.github/scripts/validate_submission.py` | The validator (reused by `scripts/validate.py`) | ~400 lines |
| `.github/PULL_REQUEST_TEMPLATE/submission.md` | Submitter checklist for submission PRs | ~30 lines |
| `scripts/submit.py` | Optional one-command helper (§6.2) | ~250 lines |
| `scripts/validate.py` | 5-line shim invoking the CI validator locally | ~5 lines |

### 7.3 Leaderboard `README.md` outline

1. **What this is** — one paragraph. Data-only record of submissions to actava benchmarks. Rendered board at `actava.ai/benchmarks`.
2. **Benchmarks tracked** — table: name → version → producer repo → submission count.
3. **Submit a result**
   - *Quick (helper):* `python scripts/submit.py <packet>` — preconditions, what happens, printed PR URL.
   - *Manual:* the 5-command flow from §6.1, copy-pasteable.
   - Both reference `python scripts/validate.py <dir>` for local pre-check.
4. **Adding a new benchmark** — link to `benchmarks/README.md`; 3-line summary.
5. **Reviewer / maintainer notes** — link to `CONTRIBUTING.md`.

## 8. Open questions deferred to implementation

These were considered and intentionally deferred — calling out explicitly so the implementation plan can decide:

- **Whether `scripts/submit.py` should be installed via `pip install` from the leaderboard repo, or stay as a standalone script.** Leaning standalone (the helper is leaderboard-internal, not a library); revisit if multiple consumers want to import it.
- **Whether `validate_submission.py` should grow a `--strict` mode that treats soft warnings as failures.** Useful for CI in producer repos to pre-validate before submission; out of scope for v1.
- **Whether the leaderboard repo should publish a machine-readable aggregate (e.g. `aggregates/<benchmark>/ranked.json`) regenerated on every merge.** Section 1 decision was "data-only, no aggregates"; revisit if `actava.ai/benchmarks` finds crawling all `results.csv` files painful.
- **Whether actava-ai org members should auto-skip the fork step.** §6.2 has it as a `--no-fork` flag; auto-detect via `gh api user/memberships/orgs` is possible but adds preflight latency. Keeping the flag explicit at v1.

## 9. Out of scope for this spec

- Backfilling existing paper-table results (`table1_main_matrix.yaml` runs) as historical submissions — separate spec if/when we want them on the leaderboard.
- Re-judge tooling beyond what `cb` already provides — manual command, not part of CI.
- A second benchmark — the architecture supports it but adding `swe-bench` (or any other) is its own spec following the §2.1 contract.
- Frontend rendering at `actava.ai/benchmarks` — owned by that property.
- Trust / Goodhart resistance beyond reviewer judgment + occasional manual rejudges. If the leaderboard ever needs hardened anti-tampering, that's a v2 conversation.

## 10. Acceptance

This spec is accepted when:

- chi-bench: `cb submission prepare` produces a packet that survives `python scripts/validate.py <packet>` against the leaderboard's validator, end-to-end, with no zip in sight.
- leaderboard: a freshly-cloned fork can run `python scripts/submit.py <packet>`, open a PR, have CI's `validate` job pass, and the PR can be merged by a reviewer who understands the directory.
- leaderboard: adding `benchmarks/swe-bench/{schema,submissions,README.md}/` is sufficient to start accepting swe-bench submissions — no edits to `validate.yml`, no edits to `scripts/submit.py`, no edits to existing benchmark subtrees.
- Both repos: README and docs as listed in §7 are in place and cross-reference each other consistently.
