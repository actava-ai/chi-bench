# chi-Bench OSS Release Design

**Date:** 2026-05-07
**Status:** Draft, pending user approval
**Owner:** Weiran Yao
**Spec scope:** Open-source release of the experiment-running subset of `actava-bench` to accompany the chi-Bench NeurIPS 2026 (E&D track) paper. Output is a public repository at `actava-ai/chi-bench` plus a Hugging Face dataset at `actava/chi-bench`. Single artifact, single tag (`v1.0.0`).

## 1. Goals & non-goals

### Goals

1. A reader of the paper can `git clone` the public repo, install via `uv sync`, run `chi-bench data download`, and execute a Docker smoke trial in under five minutes on a laptop.
2. A researcher with Anthropic API credentials can reproduce paper Tables 1, the E2E PA table, the Marathon table, the skill-ablation table, and the CLI-tools-ablation table from configs shipped in the repo, **using local Docker only — no Modal account required**. Modal is supported as an optional accelerator (`-e modal`) for users who want horizontal scaling, but every paper config runs end-to-end on a single Docker host. README and `docs/reproducing-paper-tables.md` document realistic wall-time and cost expectations for both modes (Docker is meaningfully slower for the full 30×3×75 matrix; smaller paper tables like E2E and Marathon are tractable on a workstation).
3. A researcher with their own agent harness can plug it in by following `docs/adding-an-agent-harness.md` and adding a `<harness>_harness.py` file alongside the seven harnesses we ship.
4. The release exposes zero internal-only context: no `actAVA` branding outside the affiliations block, no internal incident notes, no internal env-var names, no internal Slack/JIRA/email references, no internal commit history.

### Non-goals

- Renaming the internal `actava-bench` repo or its `healthverse` package.
- Open-sourcing the synthesis pipeline (`synth/`), the React frontends, the voice patient simulator, the copilot mode, or the deterministic seeding pipeline.
- Migrating internal CI/CD to consume the public package.
- A pluggable, multi-vendor judge (Claude only, per the paper).
- A `--no-judge` softer fallback for users without Anthropic credentials.
- Re-scrubbing the curated dataset on Hugging Face — that work happened at HF publish time and is frozen.

## 2. Release shape

A new public GitHub repo at **`actava-ai/chi-bench`** with no inherited git history. Squashed initial commit. MIT-licensed code, CC-BY-4.0-licensed dataset.

The Python package renames `healthverse → chi_bench`. The CLI binary becomes `chi-bench`. Datasets live at **`actava/chi-bench`** on Hugging Face and are pulled on demand by `chi-bench data download` into `~/.cache/chi-bench/data/` (overridable via `CHI_BENCH_DATA_DIR`).

Top-level layout:

```
chi-bench/
  README.md
  LICENSE                       # MIT
  LICENSE-DATA                  # CC-BY-4.0 (dataset license, also linked from HF)
  CITATION.cff
  ETHICS.md
  CONTRIBUTORS.md
  pyproject.toml                # [project.scripts] chi-bench = "chi_bench.cli:app"
  src/chi_bench/
    __init__.py
    cli.py
    bootstrap.py
    core/
    services/
    server/
    mcp/
    verifier/
      _compat.py                # symbols copied from synth/v2 that the verifier reads
      judge/
      scoring/
    experiment/
      agents/                   # claude-code, codex, gemini-cli, openclaw, hermes,
                                # openai-agents, deepagents, stub
      config.py
      runner.py
    conversation/               # text-only patient simulator + persona + session;
                                # voice/, voice_*.py dropped
  configs/
    experiments/                # 7 paper configs (see §6)
    smoke/                      # 3 smoke configs, one per domain
    prices.yaml
  docker/
    Dockerfile
    docker-compose.template.yml
    Dockerfile.modal             # kept, documented as optional
    modal-entrypoint.sh
  scripts/
    download_data.py
    aggregate_results.py
    run_paper_matrix.sh
    run_paper_e2e.sh
    run_paper_marathon.sh
    audit_release.py
    build_test_fixtures.py
  tests/
    smoke/
    unit/
    contract/
    _fixtures/                  # ~5MB, frozen, sourced from HF dataset
    conftest.py
  docs/
    architecture.md
    reproducing-paper-tables.md
    adding-an-agent-harness.md
    judge.md
    dataset.md
  .github/workflows/
    test.yml
    release.yml
```

## 3. Code subset & rename mechanics

### Modules retained (renamed throughout)

- `core/`, `services/`, `server/`, `mcp/`, `verifier/`, `experiment/`, `conversation/` (text-only), `bootstrap.py`, `cli.py`, `__init__.py`.

### Modules dropped

- `src/healthverse/synth/`
- `src/healthverse/seeding/`
- `src/healthverse/copilot.py`
- `src/healthverse/conversation/voice/`
- `src/healthverse/conversation/voice_evaluation.py`
- `src/healthverse/conversation/voice_orchestrator.py`
- `src/healthverse/conversation/voice_patient_simulator.py`
- `src/healthverse/server/routers/cm/voice_ws.py` (replaced with a 501-not-implemented stub at the same route)
- `frontend/`
- `notebooks/`
- `scripts/synth/`, `scripts/dev/start_synth.sh`, `scripts/hotfix/`, `scripts/one_off/`, `scripts/templates/`

### `verifier/` ↔ `synth/` decoupling

`verifier/` currently imports from `chi_bench.synth.*` (mainly `synth/v2/expectations.py` and `synth/models/synthesized_bundle.py`). These imports are walked exhaustively, the symbols actually used are copied verbatim into `src/chi_bench/verifier/_compat.py`, and the verifier's imports are rewritten to `from chi_bench.verifier._compat import …`. After this, `synth/` is unreachable from any retained module and gets deleted.

### Aggressive rename (per Q3 = A)

Mechanical pass:

```
git grep -l healthverse | xargs sed -i 's/healthverse/chi_bench/g'
git grep -l HEALTHVERSE_ | xargs sed -i 's/HEALTHVERSE_/CHI_BENCH_/g'
git grep -l 'actAVA\|actava' | <case-aware sed for actAVA → chi-Bench, actava → chi-bench>
```

Five high-risk surfaces require manual review after the mechanical pass:

1. `pyproject.toml` `[project.scripts]` entrypoint
2. `cli.py` typer app name and command names
3. `docker/Dockerfile` env vars and image labels
4. `docker/docker-compose.template.yml` mounts and env vars
5. `experiment/runner.py` env-var allowlists (`SERVER_ENV_FORWARD_KEYS`, `AGENT_ENV_ALLOWLIST`)
6. Every `task.toml` template and example under `tests/_fixtures/` and configs

The Modal profile name `actava` becomes `chi-bench`. No backwards-compatibility aliases are kept — `HEALTHVERSE_*` env vars and `healthverse` imports do not work in the public release.

## 4. Datasets: Hugging Face publishing & on-demand fetch

### HF dataset layout

`actava/chi-bench` (single dataset repo, no per-domain config split):

```
actava/chi-bench (HF dataset repo)
├── README.md
├── prior_auth_provider/{tasks/, shared/, registry.json}
├── prior_auth_um/{tasks/, shared/, registry.json}
├── care_management/{tasks/, shared/, registry.json}
├── single_session/{prior_auth_provider/, prior_auth_um/, care_management/}
└── skills/managed-care-operations-handbook/
```

The HF dataset is the post-bake artifact. Specifically, `contract_v5` rubric data has already been baked into every PA `new_referral` task's `fixtures/expectations.json`; the verifier never reaches for `synthesized_bundle.json` at runtime.

### On-demand fetch

A new `chi-bench data download` CLI command (and equivalent first-run auto-fetch on `chi-bench experiment run`) calls `huggingface_hub.snapshot_download` to materialize the dataset under `~/.cache/chi-bench/data/`. Override via `CHI_BENCH_DATA_DIR=/path`. All shipped configs reference task paths through a `${CHI_BENCH_DATA_DIR}/...` resolver implemented in `experiment/config.py`.

`huggingface_hub` is added as a runtime dependency. Snapshot download is one-shot (no streaming, no `datasets` library) — task fixtures are heterogeneous JSON/YAML/SQLite, not tabular records.

### Dataset versioning

The HF dataset is tagged `v1.0.0` to match the paper. The code reads the expected dataset version from `pyproject.toml` (`tool.chi_bench.dataset_version = "1.0.0"`) and prints a warning on mismatch but does not error — users may pin older code against newer dataset revisions.

### Dataset card on HF

Documents task count per domain, file format (FHIR-flavored JSON), evaluation contract families, license (CC-BY-4.0), citation BibTeX, ethics statement, and the exact code repo + commit that consumes it.

## 5. Configs: paper-aligned set

### Surviving paper configs

| File | Paper claim | Notes |
|---|---|---|
| `configs/experiments/main_matrix.yaml` | Table 1: 30 rows × 3 trials × 75 tasks | Renamed from `curated25_full_matrix.yaml`. `environment: docker` default; Modal block kept commented. `optional_keys` (per-row API key override) blocks dropped. |
| `configs/experiments/e2e_pa.yaml` | E2E two-agent PA table | Renamed from `curated25_e2e.yaml`. |
| `configs/experiments/marathon_pa_um.yaml` | Marathon PA UM | Merged from `session_pa_um_claude_code_opus47.yaml` + `_codex_gpt55.yaml`. |
| `configs/experiments/marathon_pa_provider.yaml` | Marathon PA provider | Same merge pattern. |
| `configs/experiments/marathon_cm.yaml` | Marathon CM | Same merge pattern. |
| `configs/experiments/skill_ablation.yaml` | Handbook skill ablation appendix | Merged from `curated25_skill_ablation*.yaml` family. |
| `configs/experiments/cli_tools_ablation.yaml` | CLI-tools ablation appendix | Merged from `curated25_cli_tools*.yaml` family. |
| `configs/smoke/smoke_pa_um.yaml` | Plumbing smoke | 1 task, 1 trial, claude-code default. |
| `configs/smoke/smoke_pa_provider.yaml` | Plumbing smoke | Same. |
| `configs/smoke/smoke_cm.yaml` | Plumbing smoke | Same. |
| `configs/prices.yaml` | Cost lookups | Unchanged. |

### Dropped configs

Everything else under `configs/experiments/` (~33 files), plus `configs/archive/` and `configs/synth/`.

### Config rewriting work

1. Replace dataset paths from `datasets/...` to `${CHI_BENCH_DATA_DIR}/...`.
2. Replace `env_file: .env.experiment` with `.env`.
3. Drop the per-row `optional_keys` blocks. The four `required_keys` (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`) are the entire credential surface external users need.
4. Set `environment: docker` as default. The `-e modal` override is documented in `docs/reproducing-paper-tables.md`.
5. Drop `actava` Modal profile references; users supply their own profile.
6. Keep API model ids (e.g. `anthropic/claude-opus-4-7`) — that's what the runner consumes; pretty names live in the paper's tables only.

### Convenience wrappers

- `scripts/run_paper_matrix.sh` wraps the main matrix command with sensible defaults and a banner about the run cost.
- `scripts/run_paper_e2e.sh` and `scripts/run_paper_marathon.sh` follow the same pattern.
- No script for ablations — `chi-bench experiment run -f configs/experiments/skill_ablation.yaml` is direct enough.

## 6. Verifier & judge integration

The verifier path matches the internal repo: deterministic checks (case status, attachments, audit actions) emit per-check fractional scores; LLM-rubric checks are scored by `WorkspaceJudge` which spawns `claude-code` CLI inside the verifier container. Per Q6 (A), there is no softer no-judge fallback.

### Shipped components

- `verifier/judge/` — `judge.py`, `workspace_judge.py`, `sanitization.py`, the rubric prompt templates, and the contract-aware dispatchers (`contract_v3`, `contract_v4`, `contract_v5`, `cm_v1`, `cm_v2`).
- `verifier/scoring/` — deterministic check implementations.
- `verifier/_compat.py` — the small set of model classes copied from `synth/v2/expectations.py` etc. (per §3).

### Judge runtime requirements

Documented in `README.md` and `docs/judge.md`:

- `claude-code` CLI installed inside the verifier container (handled by `docker/Dockerfile`).
- `ANTHROPIC_API_KEY` (or `CLAUDE_CODE_OAUTH_TOKEN`) present in `.env`.
- Default judge model `claude-opus-4-7`, overridable via `CHI_BENCH_JUDGE_MODEL`.
- Majority-vote enabled via `CHI_BENCH_JUDGE_NUM_VOTES>1`.

`README.md` includes a one-line judge-cost estimate per task and per full matrix run.

### Compose mounts

`docker-compose.template.yml` mounts `fixtures/judge/` into the verifier service (post the internal `patch_judge_compose_mounts.py` patcher's effects). The patcher itself is not shipped — we ship the post-patch template directly.

### CI escape hatch

`CHI_BENCH_JUDGE_DISABLED=1` short-circuits `WorkspaceJudge.run` to return `{"verdict": "skipped"}`. Used only by the `docker-smoke` CI job (§8) and by users plumbing-testing locally without credentials. Documented as "for plumbing tests only, do not use for paper-comparable scoring."

## 7. Tests: rewrite plan

Per Q10 (B), tests get rewritten to pass against the renamed/pruned code, not preserved verbatim.

### Inclusion principle

A test ships if (a) it exercises a module we ship, AND (b) it doesn't depend on dropped modules, AND (c) it adds credibility for a benchmark reader (verifier scoring math, harness-adapter contract, runner config parsing, MCP tool registration).

### Three-tier structure

**`tests/smoke/`** — three end-to-end tests, one per domain:

- `test_smoke_pa_um.py` — runs `chi-bench experiment run -f configs/smoke/smoke_pa_um.yaml --agent stub -n 1` against a single task with a stub agent that emits a known-good action sequence; verifier runs deterministic checks only (judge disabled via `CHI_BENCH_JUDGE_DISABLED=1`); reward asserted ≥ a recorded threshold.
- `test_smoke_pa_provider.py` — same shape.
- `test_smoke_cm.py` — same shape; uses the text-only patient simulator (no voice).

Marked `@pytest.mark.smoke`. Skipped in the default `pytest tests/` if Docker isn't available; run by the `docker-smoke` CI job.

**`tests/unit/`** — fast offline unit tests:

- `test_core_models.py`, `test_core_state_machine.py`, `test_core_store.py`
- `test_services_pa.py`, `test_services_cm.py`
- `test_verifier_scoring.py` (mocks `WorkspaceJudge`)
- `test_verifier_compat.py`
- `test_experiment_config.py`
- `test_experiment_runner.py`
- `test_agents_<harness>.py` for each shipped harness
- `test_mcp_tool_names.py`

Total runtime ≈ 5 minutes.

**`tests/contract/`** — golden-file tests: run the verifier on `tests/_fixtures/` task slices and assert the score breakdown matches a checked-in golden JSON. ~3 tests, ~10s each.

### Fixtures strategy

`tests/_fixtures/` holds tiny slices of curated tasks (~5MB), checked in, frozen. Sourced from the published HF dataset via a one-shot `scripts/build_test_fixtures.py`. After the script is run once and the result is committed, the fixtures are static; an HF dataset revision triggers a re-run and a corresponding test-fixture bump.

### `tests/conftest.py` API-key guard

An autouse fixture sets all provider env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`) to empty strings during tests so that any test path that accidentally calls a real provider fails fast.

### Rewrite phases

- **R1 — Rename pass:** every `from healthverse` → `from chi_bench`, `HEALTHVERSE_*` → `CHI_BENCH_*`. Mechanical.
- **R2 — Drop tests for dropped modules:** `tests/synth/*`, `tests/conversation/test_voice_*`, `tests/test_seeding_*`, `tests/test_copilot_*`. Mechanical.
- **R3 — Fix `_compat` references:** replace `from chi_bench.synth.v2 import …` → `from chi_bench.verifier._compat import …` where applicable.
- **R4 — Fix internal-infra references:** replace Modal profile names, internal env vars, internal CI fixtures. Rewrite to mock where appropriate.
- **R5 — Golden regeneration:** `tests/contract/` goldens generated from one canonical run, then frozen.
- **R6 — Smoke writing:** three `tests/smoke/` tests written from scratch (the internal repo doesn't have direct equivalents). Includes the `stub` agent harness in `src/chi_bench/experiment/agents/stub_harness.py`.

After all six phases, `pytest tests/unit/ tests/contract/` is green offline; `pytest tests/smoke/` is green with Docker.

## 8. Documentation set

### `README.md` (top-level)

- One-paragraph what-is-chi-bench (lifted from paper abstract, pronoun-rewritten).
- Headline numbers from Table 1 in a small table.
- Five-minute Quickstart: clone → `uv sync` → `chi-bench data download` → `chi-bench experiment run -f configs/smoke/smoke_pa_um.yaml`.
- Pointers to `docs/reproducing-paper-tables.md` and `docs/adding-an-agent-harness.md`.
- Citation block (BibTeX), license summary, contributors link.

### `docs/architecture.md`

Condensed from the internal `CLAUDE.md` architecture section. Covers what runs inside a task container (server + MCP servers + agent + verifier), the 6-stage payer pipeline, the case state machines (PA + CM), app namespaces, the WorldStore three-database split, the verifier judge contract families. Roughly 8–10 KB, written for an external researcher rather than an internal contributor.

### `docs/reproducing-paper-tables.md`

Exact commands per paper claim. Each table has a Docker command (primary) and a Modal command (optional accelerator), with wall-time and cost columns for both:

| Paper claim | Docker command | Modal command | Docker wall-time / cost | Modal wall-time / cost |
|---|---|---|---|---|
| Table 1 (main matrix) | `chi-bench experiment run -f configs/experiments/main_matrix.yaml -e docker` | `... -e modal` | (long, document realistic estimate) | (much shorter) |
| E2E PA | `... -f configs/experiments/e2e_pa.yaml -e docker` | `... -e modal` | (workstation-tractable) | (faster) |
| Marathon ×3 | three commands | three commands | (workstation-tractable) | (faster) |
| Skill ablation | one command | one command | — | — |
| CLI-tools ablation | one command | one command | — | — |

Aggregation step (mode-agnostic): `python scripts/aggregate_results.py --trials-dir logs/experiments/main_matrix --out results/table1.csv`.

Doc explicitly states that Docker requires no Modal account, no extra setup beyond a working Docker daemon and the four provider API keys, and that Modal is opt-in for users who want horizontal scaling. Wall-time and cost cells are filled in during Phase 8 from a real measurement on the maintainer's hardware (not estimated in the spec).

### `docs/adding-an-agent-harness.md`

Condensed from the internal CLAUDE.md "Adding a Custom Agent Harness" section. The architecture pattern, the four required methods on `BaseInstalledAgent`, the artifact contract (`run_result.json`, `trace.jsonl`, ATIF trajectory), the common gotchas (env-var override, MCP tool-name regex, vendor-prefix conventions, cost reporting). Pointers to the in-tree harnesses as living examples.

### `docs/judge.md`

What the workspace judge does, contract families, how to override the judge model, majority-vote setup, expected per-task cost, kappa numbers from the paper appendix.

### `docs/dataset.md`

Task structure on disk (`task.toml`, `instruction.md`, `fixtures/`, `tests/`), the FHIR-flavored format, what's in the handbook skill, link to HF dataset card, how to inspect a task locally without running it.

### `ETHICS.md`

One page: synthetic data only, no PHI, intended for evaluation research, do not use for clinical decisions, OWASP-style misuse statement. Lifted from `appendix_ethics.tex`.

### `CONTRIBUTORS.md`

Paper author list with affiliations.

### Dropped from internal repo

`BACKLOG.md`, `CHANGELOG.md` (replaced by GitHub Releases), `CLAUDE.md`, `docs/pa-judge-and-exporter-alignment-backlog.md`, `docs/judge-prompt-index.md` (consumed and condensed), `audit.json`, `notebooks/`, all internal planning-prompt docs.

## 9. CI without API keys

### `.github/workflows/test.yml`

On every PR and push to `main`. No secrets required. Runs from forks identically.

- **`lint`:** `uv run ruff check` + `uv run ruff format --check`. ~30s.
- **`unit`:** `uv run pytest tests/unit/ tests/contract/ -q`. ~5 min. Tests are offline by construction. The `tests/conftest.py` autouse fixture clears all provider env vars so any accidental real-provider call fails immediately.
- **`import-smoke`:** `python -c "import chi_bench; from chi_bench.cli import app"` plus `chi-bench --help` exits 0. ~10s.
- **`docker-smoke`:** builds the task image, runs `chi-bench experiment run -f configs/smoke/smoke_pa_um.yaml -e docker --agent stub -n 1` with `CHI_BENCH_JUDGE_DISABLED=1`. ~10 min. Catches end-to-end regressions in the runner / server / MCP / deterministic-verifier path.

The `--agent stub` mode is the entire CI signal for end-to-end behavior. No real-LLM CI gates; no `ANTHROPIC_API_KEY_CI` secret.

### `.github/workflows/release.yml`

Triggered on `v*` tags:

- Builds the package wheel.
- Publishes to PyPI as `chi-bench` using the `PYPI_API_TOKEN` secret (the only secret the public repo holds).
- Generates GitHub Release notes from `git log` since the previous tag.

Release CI does not touch the HF dataset; cross-platform tagging on first release is manual.

### Branch protection

`main` requires PR + 1 approval + green `lint`, `unit`, `import-smoke` before merge. `docker-smoke` is required only for PRs touching `src/chi_bench/experiment/`, `src/chi_bench/server/`, `src/chi_bench/mcp/`, `src/chi_bench/verifier/`, or `docker/`.

## 10. Pre-release scrubbing & sanitization

### Hard removals from working tree

`audit.json`, `BACKLOG.md`, `CLAUDE.md`, `AGENTS.md` symlink, `notebooks/`, the entire internal `docs/` tree, `.env.experiment.example`, `frontend/`, `src/healthverse/synth/`, `src/healthverse/conversation/voice/` and `voice_*.py`, `src/healthverse/copilot.py`, `src/healthverse/seeding/`, `src/healthverse/server/routers/cm/voice_ws.py`, all `scripts/synth/`, `scripts/dev/start_synth.sh`, `scripts/hotfix/`, `scripts/one_off/`, `scripts/templates/`. The `Makefile` is rewritten from scratch (only public targets); `.env.example` is written from scratch (only the four provider keys + `CLAUDE_CODE_OAUTH_TOKEN` + `CHI_BENCH_*` runtime knobs).

### String-level scrub via `scripts/audit_release.py`

Run on every PR after the rename phase lands; fails non-zero on any unexpected hit. Manual re-run on the pre-release checklist.

| # | Pattern | Expected |
|---|---|---|
| 1 | `git grep -i actava` | 0 hits in code; only `actAVA AI` as an affiliation in `CONTRIBUTORS.md`. |
| 2 | `git grep -i healthverse` | 0 hits anywhere. |
| 3 | `git grep -i healthsynth` | 0 hits. |
| 4 | `git grep -E "HEALTHVERSE_\|HEALTHSYNTH_"` | 0 hits. |
| 5 | `git grep -E "(modal\|profile).*actava"` | 0 hits. |
| 6 | `git grep -E "@(actava\|anthropic\|salesforce\|stanford)" -- '*.py' '*.md' '*.yaml'` | 0 hits except `CONTRIBUTORS.md` author affiliations. |
| 7 | `git grep -iE "internal\|todo:\|fixme:\|hack:\|xxx:\|kludge:"` | Reviewed manually; `TODO: actava-internal-...` style hits forbidden. |
| 8 | `git grep -E "logs/\|/Users/\|/home/[a-z]+/"` | No hard-coded developer paths. |
| 9 | `git grep -E "[A-Z][a-zA-Z]+@[a-z.]+\.(com\|org\|edu)"` | No leaked emails. |
| 10 | `git grep -iE "real (patient\|provider\|payer\|insurer)"` | No claims that synthetic data references real entities. |

### Dataset scrub: out of scope

The HF dataset at `actava/chi-bench` is published with the rebranded/scrubbed content from the internal `sanitize_benchmark_branding.py` run, finalized at HF publish time. The OSS code release does not re-scrub the dataset. `tests/_fixtures/` slices are sourced from the published HF dataset via `scripts/build_test_fixtures.py`, run once, output committed and frozen.

### Manual review before `v1.0.0`

A maintainer reads through every `*.py` in `src/chi_bench/`, every `.md` shipping in the repo, and every YAML config — looking for internal-context comments that survived the mechanical rename (incident references, legacy migration notes, "we burned ourselves on X" remarks). The internal `CLAUDE.md` is full of this; some of it carried into source-file docstrings and config comments.

## 11. Release sequencing

Eight phases. Estimated ~15 working days for one full-time engineer; phases 2–6 are the long pole.

### Phase 1 — Repo bootstrap (1 day)

Create empty public repo `actava-ai/chi-bench` on GitHub, MIT license file, `.gitignore`, branch protection skeleton, empty `README.md`, `pyproject.toml` skeleton with `chi-bench` package name and CLI entrypoint.

**DoD:** empty repo exists, branch protection on `main`.

### Phase 2 — Code import & module pruning (2 days)

Copy `src/healthverse/` → `src/chi_bench/`, drop the seven modules from §3, rip out `verifier/ ↔ synth/` coupling into `verifier/_compat.py`, neutralize `server/routers/cm/voice_ws.py` to a 501 stub.

**DoD:** `python -c "import chi_bench"` succeeds; no remaining imports of `chi_bench.synth`, `chi_bench.seeding`, `chi_bench.copilot`, or voice modules.

### Phase 3 — Aggressive rename (2 days)

Mechanical `healthverse → chi_bench`, `HEALTHVERSE_ → CHI_BENCH_`, `actAVA / actava → chi-Bench` (case-aware), Modal profile rename. Five high-risk surfaces from §3 reviewed manually.

**DoD:** `git grep -i healthverse` returns 0 hits; `git grep -i actava` returns hits only in `CONTRIBUTORS.md`; `chi-bench --help` exits 0.

### Phase 4 — Configs, docker, CLI cleanup (2 days)

Pare `configs/experiments/` down to the 7 paper configs (§5); drop `optional_keys`/per-row API key blocks; switch defaults to Docker; rename smoke configs into `configs/smoke/`. Rewrite `Makefile`, `.env.example`, `docker/Dockerfile`, `docker-compose.template.yml`.

Precondition (not Phase 4 work): the HF dataset already contains `contract_v5` rubric data baked into every PA `new_referral` task's `fixtures/expectations.json` — that bake happened pre-publish and is frozen on HF. If a future dataset revision drops this property, Phase 4 expands to include the bake step.

**DoD:** `chi-bench experiment run -f configs/smoke/smoke_pa_um.yaml -e docker --agent stub -n 1` runs end-to-end against bundled `tests/_fixtures/` and exits with a written trial dir.

### Phase 5 — HF dataset wiring (1–2 days)

Implement `chi-bench data download` (§4); add `${CHI_BENCH_DATA_DIR}` resolver to `experiment/config.py`; verify the published HF dataset works end-to-end via the auto-fetch path; build `tests/_fixtures/` via `scripts/build_test_fixtures.py`; pin HF dataset version `v1.0.0`.

**DoD:** `chi-bench data download` populates the cache; smoke config reads from the cache; `tests/_fixtures/` is checked in and frozen.

### Phase 6 — Tests rewrite (3–4 days)

Execute Phases R1–R6 from §7. Iterate until `pytest tests/unit/ tests/contract/` is green offline; `pytest tests/smoke/` is green with Docker.

**DoD:** full unit + contract suite passes locally without API keys; one smoke test passes locally with Docker.

### Phase 7 — Docs & release engineering (2 days)

Write the seven docs from §8 (`README.md`, `architecture.md`, `reproducing-paper-tables.md`, `adding-an-agent-harness.md`, `judge.md`, `dataset.md`, `ETHICS.md`), plus `CONTRIBUTORS.md` and `CITATION.cff`. Wire `.github/workflows/test.yml`, `release.yml`, `scripts/audit_release.py` (the 10-grep audit from §10), pre-release checklist template.

**DoD:** CI green on a real PR; `scripts/audit_release.py` exits 0; `pip install dist/chi_bench-1.0.0-*.whl && chi-bench --help` works in a clean venv.

### Phase 8 — Pre-release human review & v1.0.0 (1–2 days)

Manual file-by-file scrub (§10 last paragraph). One full smoke run with real `ANTHROPIC_API_KEY` to confirm the judge path works. Tag `v1.0.0`, push, publish PyPI release, announce.

**DoD:** tag pushed, GitHub Release posted, PyPI shows `chi-bench 1.0.0`, HF dataset card pinned to `v1.0.0`, paper's `\href{https://github.com/actava-ai/chi-bench}{...}` line uncommented in the next paper revision.

## 12. Risks & open questions

- **`verifier/ ↔ synth/` coupling deeper than expected.** If the `_compat.py` move turns up imports beyond the model classes, Phase 2 expands. Mitigation: walk `from chi_bench.synth` and `from chi_bench.healthsynth` exhaustively *before* starting the rename; estimate from that count.
- **Test rewrite churn on dropped modules.** Tests for retained modules may transitively import dropped modules through fixture builders. Mitigation: Phase R2 (mechanical drop) is followed by Phase R3 (compile error sweep) before Phase R4 (substantive fixes).
- **Modal profile rename in `experiment/modal_env.py`.** The Modal SDK caches sandbox app names; renaming may force a one-time rebuild. Out of scope for Docker-default smoke testing, but the maintainer running Phase 8's full matrix verification needs to know.
- **HF dataset bandwidth.** A 376MB pull on first run is non-trivial; users on flaky connections may need retries. The `chi-bench data download` CLI uses `huggingface_hub.snapshot_download`'s built-in retry/resume, no custom logic.
- **Paper de-anonymization timing.** The release URL `actava-ai/chi-bench` and HF dataset `actava/chi-bench` are not anonymous. If the paper venue requires double-blind review for the supplementary material, we need a parallel `chi-bench-anonymous/chi-bench-anonymous` mirror with author info stripped — out of scope per Q1 (B), but flagged.

## 13. References

- Paper: `chi_bench_neurips_2026/neurips_2026.tex` (NeurIPS 2026 E&D track).
- Internal source: `actava-bench/` (private repo).
- Internal architecture context: `actava-bench/CLAUDE.md`, `actava-bench/README.md`.
- Hugging Face dataset: `actava/chi-bench` (already published, frozen at v1.0.0).
