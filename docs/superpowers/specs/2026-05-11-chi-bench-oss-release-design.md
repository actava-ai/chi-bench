# chi-Bench OSS Release — Design Spec

**Date**: 2026-05-11
**Status**: Approved (brainstorm complete)
**Target repo**: `/Users/weiran/Github/chi-bench/`
**Sources** (sibling folders inside the target repo dir, gitignored, not part of release):
- `actava-bench/` — original messy source tree (Python package `healthverse`).
- `chi-bench-arxiv-submission/` — NeurIPS 2026 paper draft. The paper drives scope.

## 1. Goal

Ship a clean, minimal OSS repository that lets a third party reproduce the **main-text tables and figures** of the chi-Bench paper:

- **Table 1** — 30 (harness × model) cells × 75 tasks × 3 trials. Overall + per-domain pass@1 / pass@3 / pass^3, Steps, Cost.
- **Table 2** — chi-Bench-Arena: dual-agent end-to-end PA on 23 tasks.
- **Table 3** — chi-Bench-Marathon: all 25 tasks per domain in one agent session.
- **Skill-ablation figure** — 4 conditions × 75 tasks (full / −Domain / −Medical / −Both).
- **Table 5** — MCP vs. CLI: tool-surface ablation on 75 tasks.

Non-goals for v1: appendix stratification tables, failure-mode taxonomy analyzer, synthesis pipeline, frontend, voice modes, per-row API-key spend isolation.

## 2. Top-level repo layout

```
chi-bench/
├── README.md                  # quickstart + table reproduction (~250 lines)
├── LICENSE                    # Apache-2.0
├── CITATION.cff               # paper citation
├── pyproject.toml             # name=chi-bench, trimmed deps
├── uv.lock                    # pinned
├── .env.example               # ONE shared key per provider (~15 lines)
├── .gitignore                 # ignores data/, logs/, .venv/, actava-bench/, chi-bench-arxiv-submission/
│
├── src/chi_bench/             # renamed from healthverse
│   ├── cli.py
│   ├── core/                  # models, state machines, world store
│   ├── services/              # ~29 domain services + 3 inlined build_* helpers
│   ├── server/                # FastAPI app + routers (no voice_ws.py)
│   ├── mcp/                   # 3 MCP servers (provider, payer, CM)
│   ├── conversation/          # message, patient_simulator, session, persona, guidelines/ ONLY
│   ├── verifier/              # judge, rejudge, stages
│   └── experiment/
│       ├── runner.py          # shells out to harbor
│       ├── config.py
│       ├── docker_env.py      # NEW: ChiBenchDockerEnvironment (single-image)
│       ├── modal_env.py       # opt-in (renamed from healthverse.experiment.modal_env)
│       └── agents/            # 7 paper harnesses + dual_pa_e2e
│
├── docker/
│   ├── Dockerfile             # single image (mirrors current Dockerfile.modal)
│   └── entrypoint.sh          # task-id-driven (mirrors modal-entrypoint.sh)
│
├── configs/
│   ├── prices.yaml            # cost-per-token table
│   └── experiments/
│       ├── table1_main_matrix.yaml
│       ├── table2_e2e_arena.yaml
│       ├── table3_marathon.yaml
│       ├── table4_skill_ablation.yaml
│       └── table5_mcp_vs_cli.yaml
│
├── scripts/
│   ├── run_table.sh           # `./scripts/run_table.sh table1 [filters]`
│   ├── aggregate.py           # trimmed aggregate_results.py → table CSV + JSON
│   └── plot_figures.py        # cost_pareto, passk_descent, skill_ablation, failure_modes
│
├── data/                      # gitignored; user populates from HF + Google Drive
│   ├── prior_auth_provider/{registry.json, shared/, tasks/}
│   ├── prior_auth_um/{registry.json, shared/, tasks/}
│   ├── care_management/{registry.json, shared/, tasks/}
│   ├── prior_auth_e2e/{worlds/, tasks/}
│   ├── marathon/{prior_auth_provider/, prior_auth_um/, care_management/}
│   └── skills/managed-care-operations-handbook/{SKILL.md, references/}
│
├── tests/                     # ~12 tests (unit + smoke)
├── docs/
│   ├── reproduce.md           # table-by-table reproduction guide
│   ├── architecture.md        # services / MCP / verifier overview
│   └── judge.md               # how the LLM judge works
└── .github/
    └── workflows/ci.yml       # lint + unit + docker-build
```

## 3. Code reduction (vs. `actava-bench/`)

### Folders dropped entirely

- `frontend/` (both `healthverse/` and `synth/` UIs)
- `src/healthverse/synth/` (synthesis pipeline; data is pre-generated and downloaded)
- `src/healthverse/seeding/` (synthesis-only; only `seeding/cases.py`'s three helpers `build_case`, `build_line`, `build_policy` survive — inlined into `services/cases.py`)
- `scripts/{synth, one_off, hotfix, dev, smoke, templates}/`
- `configs/{archive, synth, smoke}/`
- `audit/` (29 internal review docs), `audit.json` (1.3 MB dump)
- `notebooks/`, `policies/` (raw corpus, only used by synth)
- `tests/synth/`, `tests/voice_*`, `tests/test_voice_*`, `tests/test_frontend_*`, `tests/test_*_promote_*`, `tests/test_*_canonicalize_*`, `tests/test_*_export_path*`

### Top-level files dropped

- `CLAUDE.md` (47 KB internal), `AGENTS.md` (symlink to it), `.claude/`
- `CHANGELOG.md` (239 KB internal log), `BACKLOG.md`
- `Makefile` (replaced by `scripts/run_table.sh`)
- `.env.experiment.example` (per-row keys all removed)

### Individual files dropped from kept folders

- `src/.../conversation/`: `evaluation.py`, `voice_evaluation.py`, `voice_orchestrator.py`, `voice_patient_simulator.py`, entire `voice/` subdir (~30 files: adapters, synthesis, transcription, utils, audio*, config, personas, retry, shims, tick, voice_models), `guidelines/patient_guidelines_voice.md`
- `src/.../core/`: `audit.py` (0 callers), `service.py` (singular; 0 callers, name collides with `services/`)
- `src/.../server/routers/cm/voice_ws.py` (websocket voice handler; never invoked during benchmark trials)
- `src/.../services/cm_outreach.py`: one stale `from healthverse.conversation.voice.config import SAVE_OUTREACH_RECORDINGS` → inline as `SAVE_OUTREACH_RECORDINGS = False`.
- `src/.../experiment/agents/`: keep 7 paper harnesses (`claude_code_cli_harness.py`, `codex_cli_harness.py`, `gemini_cli_harness.py`, `openclaw_harness.py`, `hermes_harness.py`, `openai_agents_harness.py`, `deepagents_harness.py`) + dual_pa_e2e helpers (`dual_pa_e2e_harness.py`, `dual_pa_e2e_phase_runner.py`, `dual_pa_e2e_relay.py`, `dual_pa_e2e_state.py`) + shared helpers (`openai_agents_runner.py`, `openai_agents_local_tools.py`, `cli_tools_common.py`). Drop nothing else from this dir.

### Verifier compat layer

`src/.../verifier/compat/` and `src/.../verifier/judge_legacy.py` are wired into the active judge through `verifier/judge/pa_um_adapter.py` and `verifier/compat/cm_rubric.py`. Keep in v1; flag in implementation review for a follow-up trim once we confirm no current task fixture takes the legacy code path.

### CLI surface reduction

`healthverse` CLI today has 7 command groups (`serve`, `mcp`, `synth.*`, `experiment.*`, `data.*`, …). The OSS CLI ships:

- `chi-bench serve` — local server (rarely needed by users; useful for debugging).
- `chi-bench mcp` — same.
- `chi-bench experiment run -f config.yaml | --dataset <path>` — primary entry point.
- `chi-bench experiment status --trials-dir <path>` — status summary.
- `chi-bench experiment rejudge --trial-root <path>` — re-run only judge stage.
- `chi-bench data verify` — check `data/` layout matches what the runner expects.
- `chi-bench docker build` — convenience wrapper for `docker build -f docker/Dockerfile .`.

Drop: `synth.*`, `data.import-synthea`, `data.download-policies`, `data.seed-world` (all stubs in current CLI), `synth.catalog.*`, `synth.batch-export`, `synth.hotfix`, `synth.cm`, `synth.ui`.

## 4. Package & naming

Rename `healthverse` → `chi_bench` everywhere:

- Package dir: `src/healthverse/` → `src/chi_bench/`.
- Entry point: `healthverse = healthverse.cli:app` → `chi-bench = chi_bench.cli:app`.
- Env-var prefix: `HEALTHVERSE_*` → `CHI_BENCH_*` (about 35 env vars across the codebase; runtime, fixtures, worlds, payer mode, skills ablation, tool mode, judge model, judge timeout, judge num votes, MCP tool sep, raw-artifact path, workspace root, task ID, copilot mode, FHIR URL, CORS origins, patient-sim model, voice-related ones already dropped).
- MCP URL host in every `task.toml`'s `[[environment.mcp_servers]]` block: `http://healthverse-server:<port>/mcp` → `http://localhost:<port>/mcp`. Single-image means server + agent are co-located in one container; no need for the `healthverse-server` `/etc/hosts` alias the current Modal entrypoint relies on. Done during HF dataset packaging.
- Environment import paths:
  - `healthverse.experiment.modal_env:HealthverseModalEnvironment` → `chi_bench.experiment.modal_env:ChiBenchModalEnvironment` (rename).
  - NEW `chi_bench.experiment.docker_env:ChiBenchDockerEnvironment` — Harbor Environment implementation for the single-image local-Docker path.

## 5. Local Docker as first-class default

### Build model

Single image, mirrors today's `docker/Dockerfile.modal`:

- `python:3.12-slim` base.
- Node 20 + `@anthropic-ai/claude-code@latest` (judge needs `claude` on PATH).
- `uv sync --no-dev` + `playwright install chromium` in `/workspace/.venv`.
- `COPY data/ /opt/chi-bench/data/` — bakes all 4 task domains + worlds + marathon + skills handbook into the image at build time. Build fails (clear error) if `data/` is incomplete; pointer to README's "Download data" section.
- Entrypoint = `/usr/local/bin/entrypoint.sh` (renamed from `modal-entrypoint.sh`, same logic): reads `CHI_BENCH_TASK_ID`, wires `/opt/chi-bench/data/<domain>/tasks/<task_id>/fixtures` → `/fixtures`, starts `chi-bench serve` (HTTP :8023 + 3 MCP threads on :8020/:8100/:8200), waits for all four endpoints to accept traffic, then `exec`s the agent command.

CI builds a `--target ci-skeleton` variant that skips the `COPY data/` step so it doesn't need to download datasets.

### Execution model

`src/chi_bench/experiment/docker_env.py` (NEW) — implements Harbor's `Environment` protocol the same way `modal_env.py` does for Modal. Per trial:

```
docker run --rm \
  -e CHI_BENCH_TASK_ID=<task_id> \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -e GEMINI_API_KEY=$GEMINI_API_KEY \
  -e OPENROUTER_API_KEY=$OPENROUTER_API_KEY \
  -e CHI_BENCH_SKILLS_ABLATE=$CHI_BENCH_SKILLS_ABLATE \
  -e CHI_BENCH_TOOL_MODE=$CHI_BENCH_TOOL_MODE \
  -v <trial_dir>:/logs/artifacts \
  -p <ephemeral>:8023 \
  chi-bench:latest <agent-command>
```

### What goes away from current task fixtures

Every task today carries:

```
data/<domain>/tasks/<task_id>/
├── environment/Dockerfile          ← DROP
├── environment/docker-compose.yaml ← DROP
├── fixtures/
├── instruction.md
├── solution/                       ← keep
├── task.toml                       ← keep; rewrite [[environment.mcp_servers]].url host
├── tests/
└── tool_reference.md               ← keep; entrypoint reads it as a plain file
```

Re-packaging the HF dataset is a one-shot script that runs once during release prep:

1. For each task dir, delete `environment/` (Dockerfile + docker-compose.yaml).
2. Rewrite every `task.toml` MCP URL: `http://healthverse-server:<port>/mcp` → `http://localhost:<port>/mcp`.
3. Verify hash → upload to `actava/chi-bench` on Hugging Face.

The same `environment` cleanup + URL rewrite applies to `prior_auth_e2e/tasks/`, `marathon/<domain>/`.

### Single-task UX preserved

```bash
chi-bench experiment run \
  --dataset data/prior_auth_um/tasks/pa_t008_t008_o002_p01_mdreview_payer \
  --agent codex --model openai/gpt-5.5
```

Same flow as today, just under the new env class. Manual container inspection also supported:

```bash
docker run --rm -it \
  -e CHI_BENCH_TASK_ID=<task_id> -e ANTHROPIC_API_KEY=... \
  -p 8023:8023 -p 8020:8020 -p 8100:8100 -p 8200:8200 \
  chi-bench:latest bash
```

### Modal opt-in

`--environment modal` (or `defaults.environment: modal` in a config) routes through `chi_bench.experiment.modal_env:ChiBenchModalEnvironment`. Modal builds the same single image from `docker/Dockerfile` with repo root as build context. README documents Modal as optional in one short paragraph, pointing at `.env`'s `MODAL_PROFILE`.

## 6. API keys: one shared key per provider

`.env.example` (~15 lines, final form):

```bash
# Judge — always required (claude-opus-4-7 grades every trial regardless of which model is being benchmarked)
ANTHROPIC_API_KEY=

# Agent provider keys — provide whichever you need for your chosen rows
OPENAI_API_KEY=         # Codex rows
GEMINI_API_KEY=         # Gemini CLI rows
OPENROUTER_API_KEY=     # OpenClaw / Hermes / OAI Agents / DeepAgents rows

# Optional (only for Modal)
MODAL_PROFILE=
```

### Code removed from `experiment/runner.py`

- `_PROVIDER_KEY_OVERRIDES` constant.
- `_resolve_agent_key_overrides(cfg, env)` function.
- The `overrides` parameter of `_forward_agent_keys`.
- Logging the "names env var X but it is not set; agent will fall back to the shared Y" warning.

### Code removed from `experiment/config.py`

- `ExperimentConfig` fields: `anthropic_key_env`, `openai_key_env`, `gemini_key_env`, `openrouter_key_env`.

### Config-file shape removed

- `key_groups:` section in every YAML.
- `required_keys`, `optional_keys` lists.
- Per-row `*_key_env` field.

Each row in `table1_main_matrix.yaml` is now 2 lines:

```yaml
- { agent: openclaw, model: openrouter/z-ai/glm-5.1 }
```

vs. today's:

```yaml
- agent: openclaw
  model: openrouter/z-ai/glm-5.1
  key_group: openclaw
  openrouter_key_env: OPENROUTER_API_KEY_OPENCLAW_GLM_5_1
```

## 7. Data hosting (no downloader CLI)

### Sources

- **Hugging Face**: public dataset `actava/chi-bench`, single repo, subdirs per domain.

  ```
  actava/chi-bench/
  ├── prior_auth_provider/        # 25 tasks + shared/worlds   (~14 MB)
  ├── prior_auth_um/              # 25 tasks + shared/worlds   (~23 MB)
  ├── care_management/            # 25 tasks + shared/worlds   (~4.6 MB)
  ├── prior_auth_e2e/             # 23 tasks + worlds          (~5 MB)
  └── marathon/                   # 3 long-horizon tasks (one per domain)  (~135 MB)
                                  #   prior_auth_provider/{instruction.md, task.toml, fixtures/, tests/, tool_reference.md}
                                  #   prior_auth_um/...
                                  #   care_management/...
                                  # Each "task" packs all 25 cases of its domain into a single agent session.
  ```

- **Google Drive**: skills handbook only (~34 MB), one `.tar.gz`, stable share URL in README.

### README "Download data" section

```markdown
## Download data

### 1. Task fixtures (Hugging Face)
huggingface-cli download actava/chi-bench --repo-type dataset --local-dir data/

### 2. Managed-Care Operations Handbook (Google Drive)
Download from: <GOOGLE_DRIVE_SHARE_URL_PLACEHOLDER>
mkdir -p data/skills
tar -xzf managed-care-operations-handbook.tar.gz -C data/skills/

### 3. Verify
chi-bench data verify
```

### `chi-bench data verify`

~50 LoC. Checks `data/{prior_auth_provider,prior_auth_um,care_management,prior_auth_e2e,marathon,skills/managed-care-operations-handbook}` exist, counts tasks per domain (must equal 25/25/25/23/3 + handbook references count), prints actionable error pointing back at README §"Download data" if anything is missing.

No download command. No HF auth. No content hashes embedded in the repo (HF provides those).

## 8. Paper-table configs

Five YAML files under `configs/experiments/`, one per main-text table/figure:

| File | Reproduces | Cells | Tasks per row | Trials |
|---|---|---|---|---|
| `table1_main_matrix.yaml` | Table 1 (Main) | 30 rows | 75 (25 PA-prov + 25 PA-UM + 25 CM) | 3 |
| `table2_e2e_arena.yaml` | Table 2 (E2E) | 1 row (provider=Codex+GPT-5.5, payer=Codex+GPT-5.5) | 23 (prior_auth_e2e) | 3 |
| `table3_marathon.yaml` | Table 3 (Marathon) | 2 rows × 3 domains | 1 marathon task per domain | 3 |
| `table4_skill_ablation.yaml` | Skill-ablation figure | 4 conditions × 1 row | 75 | 3 |
| `table5_mcp_vs_cli.yaml` | Table 5 (MCP vs CLI) | 2 conditions × 1 row | 75 | 3 |

### `table1_main_matrix.yaml` structure

```yaml
name: table1_main_matrix
description: chi-Bench Table 1 — 30 (harness × model) cells across PA-provider, PA-UM, CM.

defaults:
  environment: docker            # Modal is opt-in via --modal / --environment modal
  env_file: .env
  concurrency: 5
  n_attempts: 3
  trials_root: logs/experiments/table1_main_matrix
  agent_timeout_multiplier: 2

domains:
  pa_provider: { dataset: data/prior_auth_provider/tasks, registry_path: data/prior_auth_provider/registry.json }
  pa_um:       { dataset: data/prior_auth_um/tasks,       registry_path: data/prior_auth_um/registry.json }
  cm:          { dataset: data/care_management/tasks,     registry_path: data/care_management/registry.json }

rows:
  - { agent: claude-code, model: anthropic/claude-opus-4-7 }
  - { agent: claude-code, model: anthropic/claude-opus-4-6 }
  - { agent: claude-code, model: anthropic/claude-sonnet-4-6 }
  - { agent: claude-code, model: anthropic/claude-haiku-4-5 }
  - { agent: codex,       model: openai/gpt-5.5 }
  - { agent: codex,       model: openai/gpt-5.4 }
  - { agent: codex,       model: openai/gpt-5.4-mini }
  - { agent: gemini-cli,  model: gemini/gemini-3-pro-preview }
  - { agent: gemini-cli,  model: gemini/gemini-3-flash-preview }
  - { agent: openclaw,      model: anthropic/claude-opus-4-7 }
  - { agent: openclaw,      model: openrouter/deepseek/deepseek-v4-pro }
  - { agent: openclaw,      model: openrouter/z-ai/glm-5.1 }
  - { agent: openclaw,      model: openrouter/moonshotai/kimi-k2.6 }
  - { agent: openclaw,      model: openrouter/qwen/qwen3.6-max-preview }
  - { agent: openclaw,      model: openrouter/x-ai/grok-4.3 }
  - { agent: hermes,        model: openrouter/deepseek/deepseek-v4-pro }
  - { agent: hermes,        model: openrouter/z-ai/glm-5.1 }
  - { agent: hermes,        model: openrouter/moonshotai/kimi-k2.6 }
  - { agent: hermes,        model: openrouter/qwen/qwen3.6-max-preview }
  - { agent: hermes,        model: openrouter/x-ai/grok-4.3 }
  - { agent: openai-agents, model: deepseek/deepseek-v4-pro }
  - { agent: openai-agents, model: z-ai/glm-5.1 }
  - { agent: openai-agents, model: moonshotai/kimi-k2.6 }
  - { agent: openai-agents, model: qwen/qwen3.6-max-preview }
  - { agent: openai-agents, model: x-ai/grok-4.3 }
  - { agent: deepagents,    model: openrouter/deepseek/deepseek-v4-pro }
  - { agent: deepagents,    model: openrouter/z-ai/glm-5.1 }
  - { agent: deepagents,    model: openrouter/moonshotai/kimi-k2.6 }
  - { agent: deepagents,    model: openrouter/qwen/qwen3.6-max-preview }
  - { agent: deepagents,    model: openrouter/x-ai/grok-4.3 }
```

### `table2_e2e_arena.yaml` (dual-agent harness)

```yaml
name: table2_e2e_arena
defaults: { environment: docker, env_file: .env, concurrency: 5, n_attempts: 3, trials_root: logs/experiments/table2_e2e_arena, agent_timeout_multiplier: 2 }
dataset: data/prior_auth_e2e/tasks
registry_path: data/prior_auth_e2e/registry.json
agent: dual-pa-e2e
model: openai/gpt-5.5
provider_agent: codex
provider_model: openai/gpt-5.5
payer_agent: codex
payer_model: openai/gpt-5.5
agent_kwargs:           # required by dual_pa_e2e_phase_runner
  phase_max_turns: "50"
  max_cycles: "6"
  p2p_coordination_cycles: "4"
  p2p_max_turn_pairs: "4"
  p2p_repair_attempts: "1"
```

The `agent_kwargs` values are not optional — they bound the phase runner's turn budget, P2P coordination loops, and repair attempts. Defaults verified against `configs/experiments/curated25_e2e_codex_gpt55.yaml`.

### `table4_skill_ablation.yaml` (driving `CHI_BENCH_SKILLS_ABLATE`)

```yaml
name: table4_skill_ablation
defaults: { environment: docker, env_file: .env, concurrency: 5, n_attempts: 3, trials_root: logs/experiments/table4_skill_ablation }
domains: { pa_provider: ..., pa_um: ..., cm: ... }
conditions:
  - { name: full,       skills_ablate: [] }
  - { name: no_domain,  skills_ablate: [provider-pa, payer-um, care-manager] }
  - { name: no_medical, skills_ablate: [medical-library] }
  - { name: none,       skills_ablate: [provider-pa, payer-um, care-manager, medical-library] }
rows:
  - { agent: codex, model: openai/gpt-5.5 }
```

Reference subdir names (`care-manager`, `medical-library`, `payer-um`, `platform`, `provider-pa`) verified against the source-repo handbook; `platform` is never ablated. Re-confirm after the HF dataset upload.

### `table5_mcp_vs_cli.yaml` (driving `CHI_BENCH_TOOL_MODE`)

```yaml
name: table5_mcp_vs_cli
defaults: { environment: docker, env_file: .env, concurrency: 5, n_attempts: 3, trials_root: logs/experiments/table5_mcp_vs_cli }
domains: { pa_provider: ..., pa_um: ..., cm: ... }
conditions:
  - { name: mcp, tool_mode: mcp }
  - { name: cli, tool_mode: cli }
rows:
  - { agent: codex, model: openai/gpt-5.5 }
```

### Driver script: `scripts/run_table.sh`

One bash entry point. Iterates `rows × domains × conditions` (where applicable), invokes `chi-bench experiment run` per cell, then `python scripts/aggregate.py` and `python scripts/plot_figures.py` to render the table.

```bash
./scripts/run_table.sh table1                            # all 30 rows × 3 domains
./scripts/run_table.sh table1 --agent claude-code        # filter by harness
./scripts/run_table.sh table1 --row 5                    # just the 5th row
./scripts/run_table.sh table1 --domain pa_um             # one domain only
./scripts/run_table.sh table2
./scripts/run_table.sh table3 --domain pa_provider
./scripts/run_table.sh table4 --condition no_domain
./scripts/run_table.sh table5 --condition cli
./scripts/run_table.sh table1 --modal                    # opt into Modal
```

### Aggregation: `scripts/aggregate.py`

Trimmed port of today's `scripts/experiments/aggregate_results.py` (922 LoC) plus the simpler `summarize_curated25_full_matrix.py` (442 LoC). Keep the trial parsing, pass@k / pass^k math, cost computation. Drop the skill-condition / ablation-tag detection regex spaghetti (we now drive these by config name and env vars, not job-name string matching). Drop the appendix-stratification code paths. Target ~500 LoC.

**Wilson 95% CI is missing from both source aggregators** (the source uses bootstrap CIs; the paper uses Wilson). Add `_wilson_score_interval(k, n, z=1.96)` as a ~15-LoC helper and emit `pass@1_lo`, `pass@1_hi`, etc. columns in the CSV. n=225 (75 tasks × 3 trials) for pass@1; n=75 (task-level) for pass@3 and pass^3, matching the paper's footnote.

```bash
python scripts/aggregate.py \
  --trials-dir logs/experiments/table1_main_matrix \
  --registry data/prior_auth_provider/registry.json \
  --registry data/prior_auth_um/registry.json \
  --registry data/care_management/registry.json \
  --prices configs/prices.yaml \
  --out-csv logs/table1.csv \
  --out-json logs/table1.json
```

### Figures: `scripts/plot_figures.py`

**Net-new code, not a port.** Cross-checked: the source repo contains zero matplotlib code — paper figures were authored outside this repo. v1 ships three figures derived from the aggregated CSVs:

- `cost_pareto.pdf` — Table 1's ROI quadrant scatter (x: log-cost, y: pass@1, median crosshairs, Pareto frontier line).
- `passk_descent.pdf` — pass@k vs pass^k for k∈{1,2,3} pooled across 75 tasks.
- `skill_ablation.pdf` — bar chart of 4 conditions × 3 domains for Table 4.

**`failure_modes_main.pdf` is out of scope for v1.** The paper's failure-mode taxonomy was an offline post-hoc analysis of trial transcripts; the verifier does not emit `failure_l1` / `failure_l2` fields, and no analyzer exists in the source repo. Listed in §12 as a deferred follow-up.

## 9. Tests + CI

### Test tree (~12 files)

```
tests/
├── unit/
│   ├── test_runner_argv.py          # ExperimentConfig → harbor argv (no docker shell-out)
│   ├── test_judge_parsing.py        # WorkspaceJudge stdout → scorecard.json
│   ├── test_aggregate.py            # aggregate.py: synthetic trial dir → expected CSV row
│   └── test_state_machines.py       # PA + CM state-machine transitions
└── smoke/
    ├── test_docker_image_builds.py  # `docker build -f docker/Dockerfile --target ci-skeleton`
    ├── test_single_task_pa.py       # 1 PA-UM task × claude-code (skipped without ANTHROPIC_API_KEY)
    ├── test_single_task_cm.py       # 1 CM task   × claude-code (skipped without ANTHROPIC_API_KEY)
    └── test_verify_data_layout.py   # `chi-bench data verify` against a fixture tree
```

Today's 100-file test suite drops to ~12. Dropped subtrees: `tests/synth/`, `tests/voice_*`, `test_voice_*`, voice-router tests, `test_*_promote_*`, `test_*_canonicalize_*`, `test_*_export_path*`, `test_frontend_*`.

### CI: `.github/workflows/ci.yml`

Three jobs:

- **lint** (~30 s): `uv run ruff check src/ tests/` + `ruff format --check`.
- **unit-tests** (~1-2 min): `uv run pytest tests/unit -q`.
- **docker-build** (~5-7 min, only on push to `main`): builds the `ci-skeleton` target (no `COPY data/`).

No live-trial CI job (trials cost real API money). README documents `./scripts/smoke.sh` for local PR validation.

## 10. README skeleton

`README.md` at repo root, ~250 lines, sections in this order:

1. **Header / abstract** — paper title, one-liner, arxiv link, HF dataset link, paper Fig. 1 architecture image.
2. **What this benchmark measures** — 3 bullets, headline numbers ("best agent 28.0%, pass^3 < 20%, marathon 3.8%"), pointer to Table 1.
3. **Quickstart (single task, ~5 min)** — 6 lines: clone → download data → build Docker → run one task → see result.
4. **Full table reproduction** — table linking each paper table to its config + command (from §8).
5. **Supported agents** — 7-row table mapping `--agent`/`--model` strings to paper rows.
6. **Download data** — exact HF + Google Drive commands (from §7).
7. **Architecture** — 1 paragraph + link to `docs/architecture.md`.
8. **Modal (optional)** — 3 lines, points at `.env`'s `MODAL_PROFILE`.
9. **Citation** — BibTeX from `chi-bench-arxiv-submission/references.bib`.
10. **License** — Apache-2.0 (code), data license per HF dataset card.

`docs/` carries the longer reads: `reproduce.md` (per-table commands + cost estimates), `architecture.md` (services/MCP/verifier overview), `judge.md` (why ANTHROPIC_API_KEY is always required).

## 11. Implementation phases (one-line preview)

Detailed plan is the writing-plans step; the phases this spec implies:

1. **Bootstrap repo** — pyproject, .gitignore, LICENSE, CITATION.cff, .env.example, skeleton dirs.
2. **Port + rename source** — `healthverse` → `chi_bench`, delete drop list from §3, inline `seeding/cases.py` helpers, fix the one voice-config stale import in `cm_outreach.py`.
3. **Single-image Docker** — port `Dockerfile.modal` → `Dockerfile`, port `modal-entrypoint.sh` → `entrypoint.sh`, add `ChiBenchDockerEnvironment`.
4. **Strip per-row keys** — remove `key_groups`, `*_key_env`, `_resolve_agent_key_overrides`, related warnings.
5. **HF dataset packaging** — one-shot script to strip `environment/` dirs, rewrite `task.toml` MCP host, upload to `actava/chi-bench`.
6. **Configs + driver** — five table YAMLs, `run_table.sh`, trimmed `aggregate.py`, `plot_figures.py`.
7. **CLI trim** — keep only `serve`, `mcp`, `experiment.{run,status,rejudge}`, `data.verify`, `docker.build`.
8. **Tests + CI** — ~12 tests, three CI jobs.
9. **Docs + README** — write README + 3 `docs/` files. Verify single-task quickstart end-to-end on a clean machine.
10. **Data hosting** — upload HF dataset, host skills handbook .tar.gz on Google Drive, fill placeholders in README.

## 12. Cross-validation against paper draft + actava-bench source

Performed during spec self-review; recording the deltas so implementation doesn't re-discover them.

| Paper claim / source artefact | Cross-check result |
|---|---|
| Table 1 — 30 cells | Source `curated25_full_matrix.yaml` has 28 rows. The remaining 2 (Claude Code + Opus 4.6, OpenClaw + Opus 4.7) live in `extra_claude_code_opus_4_6_*.yaml` and `curated25_openclaw_first_party.yaml`. Spec consolidates all 30 into one `table1_main_matrix.yaml`. |
| Table 2 — E2E | Source ships `curated25_e2e_codex_gpt55.yaml` with `n_attempts: 1` + a `run_e2e_codex_gpt55_pass3_supplement.sh` script that adds 2 more. Spec ships `n_attempts: 3` directly, no supplement needed. `agent_kwargs` (phase_max_turns, max_cycles, p2p_*) are required and listed in §8. |
| Table 3 — Marathon | Source has 3 marathon "tasks" (one per domain), each a single task dir whose fixtures pack all 25 cases. NOT 4. Spec text fixed. |
| Wilson 95% CIs | Paper claims Wilson; both source aggregators use bootstrap or no CI. `scripts/aggregate.py` must add a Wilson helper (~15 LoC). Called out in §8. |
| Failure-mode figure | Verifier emits no `failure_l1` / `failure_l2`; no analyzer in source. Out of scope for v1, declared in §8 + §13. |
| Cost/walltime | `configs/prices.yaml` exists, covers GPT-5.x / Claude 4.x / Gemini 3.x / OpenRouter pricing as of April 2026. Port as-is; verify before release that no model price has shifted. |
| `HEALTHVERSE_TOOL_MODE` env var | Wired through `runner.py` → `modal-entrypoint.sh` for CLI tool mode. Single-image `entrypoint.sh` must port the same `npm install -g mcporter` step. |
| `HEALTHVERSE_SKILLS_ABLATE` env var | Wired through `runner.py` → `modal-entrypoint.sh`. Same: port to `entrypoint.sh`. Reference subdir names verified in §11. |
| Dual-PA-E2E harness | Source: `dual_pa_e2e_harness.py` + `dual_pa_e2e_phase_runner.py` + `dual_pa_e2e_relay.py` + `dual_pa_e2e_state.py`. All four ship; depend on Harbor's `BaseInstalledAgent`. |
| Plotting | Source has zero matplotlib code. `scripts/plot_figures.py` is net-new (~200 LoC). Three figures: cost_pareto, passk_descent, skill_ablation. |
| Modal env import path | Source: `healthverse.experiment.modal_env:HealthverseModalEnvironment`. Renamed in §4. |

## 13. Open items (to settle during implementation, not blockers for the spec)

- **License**: Apache-2.0 assumed; confirm with project owners. Same question for the data license on the HF dataset card.
- **Skills-ablate subdir names**: confirmed in source as `care-manager`, `medical-library`, `payer-um`, `platform`, `provider-pa`. `platform` is never ablated. Re-confirm after the HF handbook upload.
- **`verifier/compat/` + `judge_legacy.py`**: keep in v1; investigate during impl whether any current paper task still hits the legacy code path. If not, drop in a follow-up.
- **Failure-mode figure (`failure_modes_main.pdf`, `failure_l2_topbar.pdf`)**: explicitly out of scope for v1. The verifier emits no `failure_l1` / `failure_l2` fields; the paper's analysis was offline post-hoc and no analyzer exists in the source repo. Deferred until a separate failure-taxonomy classifier is built.
- **`scripts/smoke.sh`**: small wrapper around `chi-bench experiment run` on one task per domain. Trivial to write; called out here so it doesn't get forgotten.
