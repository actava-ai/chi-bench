# chi-Bench OSS Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the messy internal `actava-bench` repository into a clean, minimal OSS release at `/Users/weiran/Github/chi-bench/` that reproduces the chi-Bench paper's main-text tables (Table 1, Table 2/E2E, Table 3/Marathon, Skill ablation, Table 5/MCP-vs-CLI) using local Docker by default.

**Architecture:** One Python package (`chi_bench`) wrapping a Harbor-driven trial runner. Single prebuilt Docker image carries the FastAPI server, three MCP servers, the LLM judge, and all task fixtures. Modal is opt-in via a separate Environment class. Data lives on Hugging Face + Google Drive; users download into a gitignored `data/` directory. Five paper-table YAMLs drive `chi-bench experiment run`, which produces JSON trial outputs that `scripts/aggregate.py` rolls up into CSV tables with Wilson 95% CIs.

**Tech Stack:** Python 3.12, `uv` for dependency mgmt, FastAPI + MCP + Pydantic, Harbor 0.4+ as the trial orchestrator, Docker, `huggingface_hub` (CLI only — users download manually), `pytest` + `ruff`.

**Source spec:** `docs/superpowers/specs/2026-05-11-chi-bench-oss-release-design.md`.

**Working directory throughout:** `/Users/weiran/Github/chi-bench/`. The two source directories `actava-bench/` and `chi-bench-arxiv-submission/` are siblings inside this dir, gitignored, never modified.

---

## File Structure Overview

**Top-level (NEW files in target repo):**
- `pyproject.toml`, `uv.lock`, `.env.example`, `.gitignore`, `LICENSE`, `CITATION.cff`, `README.md`

**`src/chi_bench/`** — renamed from `actava-bench/src/healthverse/`, with these subtrees dropped: `synth/`, `seeding/` (except 3 helpers inlined into `services/cases.py`), `conversation/voice*` files + entire `voice/` subdir + `evaluation.py`, `core/audit.py`, `core/service.py`, `server/routers/cm/voice_ws.py`.

**`src/chi_bench/experiment/`** — NEW: `docker_env.py` (ChiBenchDockerEnvironment for single-image local Docker). MODIFY: `runner.py`, `config.py` (strip per-row keys), `modal_env.py` (renamed class).

**`docker/`** — `Dockerfile` (ported from `Dockerfile.modal`, drop `.modal` suffix) + `entrypoint.sh` (ported from `modal-entrypoint.sh`).

**`configs/`** — `prices.yaml` (ported as-is) + 5 paper-table YAMLs.

**`scripts/`** — `run_table.sh`, `aggregate.py`, `package_hf_dataset.py` (release-prep, not user-facing).

**`tests/`** — `unit/{test_runner_argv.py, test_judge_parsing.py, test_aggregate.py, test_state_machines.py}` + `smoke/{test_docker_image_builds.py, test_single_task_pa.py, test_single_task_cm.py, test_verify_data_layout.py}`.

**`docs/`** — `reproduce.md`, `architecture.md`, `judge.md`.

**`.github/workflows/ci.yml`** — lint + unit-tests + docker-build.

---

## Phase A — Repo bootstrap

### Task A1: Add `.gitignore` for sources and runtime artifacts

**Files:**
- Modify: `/Users/weiran/Github/chi-bench/.gitignore`

- [ ] **Step 1: Append the OSS-release ignores**

Edit `/Users/weiran/Github/chi-bench/.gitignore` to ensure these entries are present (the file already exists; add anything missing). Show the final content:

```gitignore
# Source repos (gitignored siblings — not part of release)
actava-bench/
chi-bench-arxiv-submission/

# Downloaded data (users populate via HF + Google Drive)
data/

# Runtime
.venv/
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.ruff_cache/

# Experiment outputs
logs/
trials/

# Editor
.idea/
.vscode/
.DS_Store

# Secrets
.env
.env.local
```

- [ ] **Step 2: Verify the gitignore works**

Run: `cd /Users/weiran/Github/chi-bench && git status --short | grep -E "actava-bench|chi-bench-arxiv|^.. data/"`
Expected: empty output (those paths are now ignored).

- [ ] **Step 3: Commit**

```bash
cd /Users/weiran/Github/chi-bench
git add .gitignore
git commit -m "chore: gitignore sources, data, runtime artifacts"
```

### Task A2: Add LICENSE (Apache-2.0)

**Files:**
- Create: `/Users/weiran/Github/chi-bench/LICENSE`

- [ ] **Step 1: Create LICENSE**

Fetch the canonical Apache-2.0 text and write to `/Users/weiran/Github/chi-bench/LICENSE`. Copyright line:

```
Copyright 2026 actAVA.ai and the chi-Bench authors

Licensed under the Apache License, Version 2.0 (the "License");
...
```

(Full text from https://www.apache.org/licenses/LICENSE-2.0.txt, lines 1-202.)

- [ ] **Step 2: Commit**

```bash
git add LICENSE
git commit -m "chore: add Apache-2.0 LICENSE"
```

### Task A3: Create `pyproject.toml`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/pyproject.toml`

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "chi-bench"
version = "0.1.0"
description = "chi-Bench: long-horizon, policy-rich healthcare workflows for AI agents."
readme = "README.md"
requires-python = ">=3.12"
license = { file = "LICENSE" }
authors = [
    { name = "chi-Bench authors" },
]
dependencies = [
    "pydantic>=2.8.0",
    "sqlmodel>=0.0.24",
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
    "httpx>=0.27.0",
    "mcp>=1.0.0",
    "jinja2>=3.1.0",
    "pyyaml>=6.0",
    "typer>=0.12.0",
    "python-dotenv>=1.0.0",
    "pypdf>=5.3.0",
    "anthropic>=0.40.0",
    "loguru>=0.7.0",
    "numpy>=1.26.0",
    "scipy>=1.12.0",
    "tenacity>=8.2.0",
    "requests>=2.32.0",
    "audioop-lts>=0.2.0; python_version>='3.13'",
    "deepagents>=0.5.2",
    "markdown-it-py>=3.0.0",
    "playwright>=1.48.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.4.0",
    "harbor>=0.4.0",
]
modal = [
    "modal>=1.4.2",
]
openai-agents = [
    "openai-agents>=0.13.0,<0.14",
]
deepagents-cli = [
    "deepagents-cli",
]

[project.scripts]
chi-bench = "chi_bench.cli:app"

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
chi_bench = [
    "conversation/guidelines/*.md",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "requires_anthropic_key: smoke tests that hit the live judge",
]
addopts = "-m 'not requires_anthropic_key'"

[tool.ruff]
line-length = 100
```

- [ ] **Step 2: Lockfile**

Run: `cd /Users/weiran/Github/chi-bench && uv sync --extra dev`
Expected: `.venv/` and `uv.lock` created; `chi-bench` script entry resolves (will fail at runtime since `src/chi_bench/` doesn't exist yet — that's fine for now, sync just resolves deps).

If `uv sync` errors because `src/chi_bench/cli.py` is missing, ignore — we add that in Phase B. Re-verify after Phase B.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: pyproject.toml for chi-bench package"
```

### Task A4: Create `.env.example`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/.env.example`

- [ ] **Step 1: Write the file**

```bash
# Judge — always required.
# claude-opus-4-7 grades every trial regardless of which model is being
# benchmarked. Without this key, all runs fail at the verifier stage.
ANTHROPIC_API_KEY=

# Agent provider keys — provide whichever you need for your chosen rows.
OPENAI_API_KEY=         # Codex rows
GEMINI_API_KEY=         # Gemini CLI rows
OPENROUTER_API_KEY=     # OpenClaw / Hermes / OAI Agents / DeepAgents rows

# Optional (only when running on Modal)
MODAL_PROFILE=
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "chore: .env.example with one shared key per provider"
```

### Task A5: Create `CITATION.cff`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/CITATION.cff`

- [ ] **Step 1: Write the file**

Pull author list and title from `chi-bench-arxiv-submission/neurips_2026.tex` lines 168-231. Format as CFF:

```yaml
cff-version: 1.2.0
message: "If you use chi-Bench, please cite the following paper."
title: "chi-Bench: Can AI Agents Automate End-to-End, Long-Horizon, Policy-Rich Healthcare Workflows?"
authors:
  - family-names: Chen
    given-names: Haolin
  - family-names: Metelski
    given-names: Deon
  # ... copy the full author list from neurips_2026.tex \author{} entries
  - family-names: Yao
    given-names: Weiran
preferred-citation:
  type: conference-paper
  conference: "NeurIPS 2026 (Datasets and Benchmarks track)"
  year: 2026
  title: "chi-Bench: Can AI Agents Automate End-to-End, Long-Horizon, Policy-Rich Healthcare Workflows?"
url: "https://github.com/actava-ai/chi-bench"
```

- [ ] **Step 2: Commit**

```bash
git add CITATION.cff
git commit -m "chore: CITATION.cff"
```

---

## Phase B — Source migration (healthverse → chi_bench)

### Task B1: Copy source tree, drop forbidden subtrees

**Files:**
- Create (by copy): `/Users/weiran/Github/chi-bench/src/chi_bench/` from `actava-bench/src/healthverse/`

- [ ] **Step 1: Copy the source tree**

```bash
cd /Users/weiran/Github/chi-bench
mkdir -p src
cp -r actava-bench/src/healthverse src/chi_bench
```

- [ ] **Step 2: Drop synth + seeding + voice + dead files**

```bash
cd /Users/weiran/Github/chi-bench/src/chi_bench

# Synthesis pipeline (data is pre-generated)
rm -rf synth

# Synthesis-only seeding (3 helpers will be inlined into services/cases.py in B2)
# Keep cases.py temporarily for the inline step
mv seeding/cases.py /tmp/chi_bench_seeding_cases.py
rm -rf seeding

# Voice + evaluation paths
rm -rf conversation/voice
rm -f conversation/evaluation.py
rm -f conversation/voice_evaluation.py
rm -f conversation/voice_orchestrator.py
rm -f conversation/voice_patient_simulator.py
rm -f conversation/guidelines/patient_guidelines_voice.md

# Core dead files
rm -f core/audit.py
rm -f core/service.py

# Voice websocket route
rm -f server/routers/cm/voice_ws.py

# Bootstrap CM is synthesis-time only — drop
rm -f bootstrap_cm.py
```

- [ ] **Step 3: Verify dropped layout**

```bash
cd /Users/weiran/Github/chi-bench/src/chi_bench
ls
```

Expected output (no `synth`, no `seeding`):
```
__init__.py
bootstrap.py
cli.py
conversation
copilot.py
core
experiment
mcp
server
services
verifier
```

- [ ] **Step 4: Stage but do not commit yet**

```bash
cd /Users/weiran/Github/chi-bench
git add src/chi_bench
```

(We'll commit after the rename in B2.)

### Task B2: Rename `healthverse` → `chi_bench` across the package

**Files:**
- Modify: `/Users/weiran/Github/chi-bench/src/chi_bench/**/*.py` (~150 files)

- [ ] **Step 1: Mass-rewrite Python identifiers**

```bash
cd /Users/weiran/Github/chi-bench

# Module references inside source
grep -rlZ "healthverse" src/chi_bench/ \
  | xargs -0 sed -i.bak 's/\bhealthverse\b/chi_bench/g'

# Env-var prefix
grep -rlZ "HEALTHVERSE_" src/chi_bench/ \
  | xargs -0 sed -i.bak 's/\bHEALTHVERSE_/CHI_BENCH_/g'

# Drop the .bak files
find src/chi_bench -name "*.bak" -delete
```

- [ ] **Step 2: Inline the three `seeding.cases` helpers into `services/cases.py`**

Open `/tmp/chi_bench_seeding_cases.py` (saved in B1). Copy the bodies of `build_case`, `build_line`, and `build_policy` into the top of `src/chi_bench/services/cases.py` (after existing imports). Their imports (`AppealOutcome, CaseStatus, ...`, `HiddenCasePolicy, ...`, `decision_due_at`) must be added to the file's import block if missing.

Then in `src/chi_bench/services/cases.py`, remove the line:
```python
from chi_bench.seeding.cases import build_case, build_line, build_policy
```
(or `from healthverse.seeding.cases ...` if the rename in step 1 missed it — also fine to remove).

- [ ] **Step 3: Fix the voice-config stale import in `cm_outreach.py`**

In `src/chi_bench/services/cm_outreach.py` find the line `from chi_bench.conversation.voice.config import SAVE_OUTREACH_RECORDINGS` (was `healthverse.conversation.voice.config`). Replace with a module-level constant:

```python
# Voice outreach recordings are disabled in the benchmark build.
SAVE_OUTREACH_RECORDINGS = False
```

Place at the top of the file (after existing imports). Remove the old `from chi_bench.conversation.voice.config import ...` line.

- [ ] **Step 4: Rename the Modal environment class**

In `src/chi_bench/experiment/modal_env.py` find `class HealthverseModalEnvironment` (or the post-step-1 form `class chi_benchModalEnvironment` — note the sed could have rewritten `Healthverse` → `chi_bench` only if I matched word boundary `\b`; verify) and rename to `ChiBenchModalEnvironment`.

```bash
cd /Users/weiran/Github/chi-bench
grep -rln "HealthverseModalEnvironment\|chi_benchModalEnvironment" src/chi_bench/ \
  | xargs -I{} sed -i.bak \
    -e 's/HealthverseModalEnvironment/ChiBenchModalEnvironment/g' \
    -e 's/chi_benchModalEnvironment/ChiBenchModalEnvironment/g' {}
find src/chi_bench -name "*.bak" -delete
```

- [ ] **Step 5: Verify no `healthverse` strings remain**

```bash
cd /Users/weiran/Github/chi-bench
grep -rn "healthverse\|HEALTHVERSE_\|Healthverse" src/chi_bench/ | grep -v "^Binary"
```

Expected: empty (or only unrelated comments that legitimately use the word "healthverse"; review by eye).

- [ ] **Step 6: Verify imports resolve**

```bash
cd /Users/weiran/Github/chi-bench
uv run python -c "import chi_bench; import chi_bench.cli; import chi_bench.experiment.runner; import chi_bench.verifier.judge.workspace_judge; print('OK')"
```

Expected: `OK`. If `ImportError`, fix by inspecting the trace (likely a missed sed substitution).

- [ ] **Step 7: Commit**

```bash
git add -A src/chi_bench
git commit -m "feat: port healthverse package as chi_bench with rename + drops"
```

### Task B3: Trim the CLI to only what we ship

**Files:**
- Modify: `/Users/weiran/Github/chi-bench/src/chi_bench/cli.py`

- [ ] **Step 1: Drop the synth + data-stub commands**

Open `src/chi_bench/cli.py`. Remove these whole functions and their `@*_app.command(...)` decorators:

- `synth_run`, `synth_export`, `synth_hotfix`, `synth_batch_export`, `synth_status`, `synth_ui`, `synth_cm`
- `synth_catalog_build`, `synth_catalog_package`, `synth_catalog_package_e2e`
- `data_import_synthea`, `data_download_policies`, `data_seed_world`

Also remove the `synth_app`, `catalog_app`, `data_app` typer instances (the latter will be rebuilt in Task E2 for `chi-bench data verify`).

Remove related imports at the top of the file:

```python
from chi_bench.synth.v2.pipeline.log_format import configure_synth_logging
```

(any `chi_bench.synth.*` import will dangle — delete it.)

Replace `_configure_logging`'s `synth=True` branch with a no-op, since synth is gone:

```python
def _configure_logging(level: str) -> None:
    import logging
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
```

(Drop the `synth: bool = False` parameter entirely; update its callers.)

- [ ] **Step 2: Verify the trimmed CLI still imports**

```bash
cd /Users/weiran/Github/chi-bench
uv run chi-bench --help
```

Expected: shows `serve`, `mcp`, `experiment` subcommands; does NOT show `synth` or `data`.

- [ ] **Step 3: Commit**

```bash
git add src/chi_bench/cli.py
git commit -m "feat: drop synth + data-stub commands from CLI"
```

### Task B4: Verify all remaining test fixtures + tests load

**Files:**
- Verify only.

- [ ] **Step 1: Collect tests (dry run)**

We haven't ported `tests/` yet; this task is a sanity check that imports work end-to-end before we add new code.

```bash
cd /Users/weiran/Github/chi-bench
uv run python -c "
import chi_bench.core.models
import chi_bench.core.cm_models
import chi_bench.services.cases  # build_case, build_line, build_policy inlined here
from chi_bench.services.cases import build_case, build_line, build_policy
import chi_bench.experiment.runner
import chi_bench.experiment.modal_env
from chi_bench.experiment.modal_env import ChiBenchModalEnvironment
import chi_bench.verifier.judge.workspace_judge
print('All imports OK')
"
```

Expected: `All imports OK`.

If anything fails, fix the import / missing inline / rename and re-run.

- [ ] **Step 2: No commit needed if step 1 already passes; otherwise commit fixes**

---

## Phase C — Single-image local Docker

### Task C1: Port `Dockerfile.modal` → `docker/Dockerfile` (new path)

**Files:**
- Create: `/Users/weiran/Github/chi-bench/docker/Dockerfile`
- Reference: `actava-bench/docker/Dockerfile.modal`

- [ ] **Step 1: Copy Dockerfile.modal as the basis**

```bash
mkdir -p /Users/weiran/Github/chi-bench/docker
cp /Users/weiran/Github/chi-bench/actava-bench/docker/Dockerfile.modal \
   /Users/weiran/Github/chi-bench/docker/Dockerfile
```

- [ ] **Step 2: Rewrite chi-bench-specific references inside Dockerfile**

Open `/Users/weiran/Github/chi-bench/docker/Dockerfile`. Make these changes:

1. The `COPY datasets/...` block currently references the old layout. Replace the entire block:

   FROM:
   ```dockerfile
   ARG DATASET_CACHE_BUST=2026-05-02-add-e2e-dataset
   COPY datasets/prior_auth_provider/shared/worlds /opt/healthverse/worlds
   COPY datasets/prior_auth_provider/tasks /opt/healthverse/tasks
   COPY datasets/prior_auth_um/tasks /opt/healthverse/tasks
   COPY datasets/care_management/shared/worlds /opt/healthverse/worlds
   COPY datasets/care_management/tasks /opt/healthverse/tasks
   COPY datasets/prior_auth_e2e/worlds /opt/healthverse/worlds
   COPY datasets/prior_auth_e2e/tasks /opt/healthverse/tasks
   COPY datasets/skills/managed-care-operations-handbook /workspace/skills/managed-care-operations-handbook
   RUN mkdir -p /opt/healthverse-task-assets
   COPY datasets/care_management/shared/tool_reference.md /opt/healthverse-task-assets/tool_reference.md
   ```

   TO:
   ```dockerfile
   ARG DATASET_CACHE_BUST=2026-05-11-oss-v1
   COPY data/prior_auth_provider/shared/worlds /opt/chi-bench/worlds
   COPY data/prior_auth_provider/tasks /opt/chi-bench/tasks
   COPY data/prior_auth_um/tasks /opt/chi-bench/tasks
   COPY data/care_management/shared/worlds /opt/chi-bench/worlds
   COPY data/care_management/tasks /opt/chi-bench/tasks
   COPY data/prior_auth_e2e/worlds /opt/chi-bench/worlds
   COPY data/prior_auth_e2e/tasks /opt/chi-bench/tasks
   COPY data/marathon /opt/chi-bench/tasks/marathon
   COPY data/skills/managed-care-operations-handbook /workspace/skills/managed-care-operations-handbook
   RUN mkdir -p /opt/chi-bench-task-assets
   COPY data/care_management/shared/tool_reference.md /opt/chi-bench-task-assets/tool_reference.md
   ```

2. Replace every other `healthverse` → `chi-bench` (or `chi_bench` for env-var prefixes) by `sed -i.bak`:

   ```bash
   cd /Users/weiran/Github/chi-bench/docker
   sed -i.bak \
     -e 's|/opt/healthverse|/opt/chi-bench|g' \
     -e 's|/opt/healthverse-task-assets|/opt/chi-bench-task-assets|g' \
     -e 's|HEALTHVERSE_|CHI_BENCH_|g' \
     -e 's|judge-harness:claude-code|judge-harness:claude-code|g' \
     -e 's|modal-entrypoint\.sh|entrypoint.sh|g' \
     Dockerfile
   rm Dockerfile.bak
   ```

3. Add the `ci-skeleton` build target so CI can build without `data/`. Add at the top of the file:

   ```dockerfile
   # syntax=docker/dockerfile:1.7
   ```

   And split the COPY data block under a stage label:

   ```dockerfile
   FROM python:3.12-slim AS base
   # ... existing apt/uv/playwright steps ...
   # ... existing COPY pyproject.toml ..., COPY src/ ..., RUN uv sync ...

   FROM base AS ci-skeleton
   # No data baked in; for CI build-check only.

   FROM base AS runtime
   # The COPY data/... block goes here (the rewritten block from step 2 part 1).
   # ... plus the entrypoint setup ...
   ```

   Concretely, restructure the existing single-stage Dockerfile so:
   - everything BEFORE the `COPY data/...` block is in `FROM ... AS base`,
   - the data COPY + entrypoint setup is in `FROM base AS runtime`,
   - a sentinel `FROM base AS ci-skeleton` immediately after `base` (no extra steps).

   The default target (when `--target` is unspecified) must be `runtime` — express by leaving `runtime` as the last `FROM` stage.

- [ ] **Step 3: Verify the Dockerfile parses**

```bash
cd /Users/weiran/Github/chi-bench
docker build -f docker/Dockerfile --target ci-skeleton -t chi-bench:ci-test .
```

Expected: build succeeds without needing `data/`. If it fails on a `COPY data/...` line during ci-skeleton, the stage split is wrong — fix and retry.

- [ ] **Step 4: Commit**

```bash
git add docker/Dockerfile
git commit -m "feat: docker/Dockerfile (multi-stage; ci-skeleton + runtime)"
```

### Task C2: Port `modal-entrypoint.sh` → `docker/entrypoint.sh`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/docker/entrypoint.sh`
- Reference: `actava-bench/docker/modal-entrypoint.sh`

- [ ] **Step 1: Copy and rename**

```bash
cp /Users/weiran/Github/chi-bench/actava-bench/docker/modal-entrypoint.sh \
   /Users/weiran/Github/chi-bench/docker/entrypoint.sh
chmod +x /Users/weiran/Github/chi-bench/docker/entrypoint.sh
```

- [ ] **Step 2: Rewrite paths and env-var names**

```bash
cd /Users/weiran/Github/chi-bench/docker
sed -i.bak \
  -e 's|HEALTHVERSE_|CHI_BENCH_|g' \
  -e 's|/opt/healthverse|/opt/chi-bench|g' \
  -e 's|/opt/healthverse-task-assets|/opt/chi-bench-task-assets|g' \
  -e 's|healthverse-server|chi-bench-server|g' \
  -e 's|healthverse serve|chi-bench serve|g' \
  -e 's|python -m healthverse\.bootstrap|python -m chi_bench.bootstrap|g' \
  -e 's|modal-entrypoint:|entrypoint:|g' \
  entrypoint.sh
rm entrypoint.sh.bak
```

- [ ] **Step 3: Replace the `/etc/hosts` alias with a no-op**

The original adds `127.0.0.1 chi-bench-server` to `/etc/hosts` because Modal task.toml files reference `http://chi-bench-server:.../mcp`. After HF dataset repackaging (Phase G) those URLs become `localhost`, so the hosts entry is unnecessary. To keep the entrypoint robust during the transition window, leave the block in place — it's a no-op when nothing references the alias.

- [ ] **Step 4: Verify the script parses**

```bash
bash -n /Users/weiran/Github/chi-bench/docker/entrypoint.sh
echo "Exit: $?"
```

Expected: `Exit: 0`.

- [ ] **Step 5: Commit**

```bash
git add docker/entrypoint.sh
git commit -m "feat: docker/entrypoint.sh (single-image, task-id-driven)"
```

### Task C3: Test — Wilson CI helper for aggregate.py (TDD)

Before adding `docker_env.py` we hit one well-bounded new piece of code that's easy to TDD: the Wilson CI helper that aggregate.py needs. Doing this now keeps Phase F simpler.

**Files:**
- Create: `/Users/weiran/Github/chi-bench/scripts/__init__.py`
- Create: `/Users/weiran/Github/chi-bench/scripts/_wilson.py`
- Create: `/Users/weiran/Github/chi-bench/tests/unit/test_wilson.py`
- Create: `/Users/weiran/Github/chi-bench/tests/__init__.py`
- Create: `/Users/weiran/Github/chi-bench/tests/unit/__init__.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_wilson.py`:
```python
from scripts._wilson import wilson_score_interval


def test_wilson_zero_successes():
    lo, hi = wilson_score_interval(k=0, n=10)
    assert lo == 0.0
    assert 0.25 < hi < 0.35  # paper-typical floor


def test_wilson_full_successes():
    lo, hi = wilson_score_interval(k=10, n=10)
    assert 0.65 < lo < 0.75
    assert hi == 1.0


def test_wilson_half_successes_symmetric():
    lo, hi = wilson_score_interval(k=5, n=10)
    # 95% CI for p=0.5 with n=10 is roughly (0.237, 0.763)
    assert 0.20 < lo < 0.28
    assert 0.72 < hi < 0.80


def test_wilson_paper_example_pass1():
    # Paper Table 1: pass@1 = 28.0% on n=225 trials (75 tasks × 3 trials)
    # Wilson 95% CI: [-5.5, +6.2] from paper -> 22.5% to 34.2%
    lo, hi = wilson_score_interval(k=63, n=225)  # 28.0% × 225 ≈ 63
    assert 0.22 < lo < 0.24
    assert 0.34 < hi < 0.36


def test_wilson_n_zero_returns_zero_zero():
    lo, hi = wilson_score_interval(k=0, n=0)
    assert lo == 0.0
    assert hi == 0.0
```

Also create the empty `__init__.py` files so pytest finds the package:

```bash
touch /Users/weiran/Github/chi-bench/scripts/__init__.py
touch /Users/weiran/Github/chi-bench/tests/__init__.py
touch /Users/weiran/Github/chi-bench/tests/unit/__init__.py
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
cd /Users/weiran/Github/chi-bench
uv run pytest tests/unit/test_wilson.py -v
```

Expected: `ModuleNotFoundError: No module named 'scripts._wilson'`.

- [ ] **Step 3: Implement `scripts/_wilson.py`**

```python
"""Wilson score 95% confidence interval for binomial proportions.

Used by scripts/aggregate.py to render the per-cell CIs in paper Table 1
(footnote: "Wilson on n=225 trials for pass@1 and n=75 tasks for pass@3 /
pass^3"). Matches https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval#Wilson_score_interval.
"""

from __future__ import annotations

import math


def wilson_score_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Return (low, high) of the Wilson 95% CI for k successes in n trials."""
    if n <= 0:
        return (0.0, 0.0)
    p_hat = k / n
    denom = 1 + z * z / n
    centre = p_hat + z * z / (2 * n)
    margin = z * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n))
    lo = (centre - margin) / denom
    hi = (centre + margin) / denom
    return (max(0.0, lo), min(1.0, hi))
```

- [ ] **Step 4: Run the test and verify it passes**

```bash
cd /Users/weiran/Github/chi-bench
uv run pytest tests/unit/test_wilson.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/__init__.py scripts/_wilson.py tests/__init__.py tests/unit/__init__.py tests/unit/test_wilson.py
git commit -m "feat: Wilson 95% CI helper for aggregate.py (TDD)"
```

### Task C4: Strip per-row API-key overrides from runner + config

**Files:**
- Modify: `/Users/weiran/Github/chi-bench/src/chi_bench/experiment/runner.py`
- Modify: `/Users/weiran/Github/chi-bench/src/chi_bench/experiment/config.py`

- [ ] **Step 1: Write a regression test for the simplified `_forward_agent_keys`**

`tests/unit/test_runner_argv.py` (will grow in later tasks):
```python
import pytest
from chi_bench.experiment.runner import _forward_agent_keys


def test_forward_agent_keys_emits_present_only():
    env = {
        "ANTHROPIC_API_KEY": "ak-anthropic",
        "OPENAI_API_KEY": "ak-openai",
        # GEMINI_API_KEY absent
        "OPENROUTER_API_KEY": "ak-openrouter",
        "IRRELEVANT": "x",
    }
    flags = _forward_agent_keys(env)
    assert "--ae" in flags
    pairs = [flags[i + 1] for i, x in enumerate(flags) if x == "--ae"]
    assert "ANTHROPIC_API_KEY=ak-anthropic" in pairs
    assert "OPENAI_API_KEY=ak-openai" in pairs
    assert "OPENROUTER_API_KEY=ak-openrouter" in pairs
    assert not any(p.startswith("GEMINI_API_KEY=") for p in pairs)
    assert not any("IRRELEVANT" in p for p in pairs)


def test_forward_agent_keys_no_overrides_signature():
    """_forward_agent_keys MUST be a single-argument function — per-row override path removed."""
    import inspect
    sig = inspect.signature(_forward_agent_keys)
    assert list(sig.parameters.keys()) == ["env"], (
        f"per-row override 'overrides' param must be gone; got {list(sig.parameters)}"
    )
```

Run: `uv run pytest tests/unit/test_runner_argv.py -v`
Expected: second test FAILS (current `_forward_agent_keys` still has an `overrides` parameter).

- [ ] **Step 2: Simplify `_forward_agent_keys`**

In `src/chi_bench/experiment/runner.py`, replace the `_forward_agent_keys` function with:

```python
def _forward_agent_keys(env: Mapping[str, str]) -> list[str]:
    """Return Harbor --ae flags for every allowlisted key present in env."""
    flags: list[str] = []
    for key in AGENT_ENV_ALLOWLIST:
        value = env.get(key)
        if value:
            flags += ["--ae", f"{key}={value}"]
    return flags
```

- [ ] **Step 3: Delete dead per-row override code**

In `src/chi_bench/experiment/runner.py`, delete:
- The `_PROVIDER_KEY_OVERRIDES` dict (constant).
- The whole `_resolve_agent_key_overrides(cfg, env)` function.

In `_build_harbor_command`, remove these lines (near where `_forward_agent_keys` is called):

```python
overrides = _resolve_agent_key_overrides(cfg, env)
cmd += _forward_agent_keys(env, overrides=overrides)
```

Replace with:

```python
cmd += _forward_agent_keys(env)
```

- [ ] **Step 4: Drop the four `*_key_env` fields from `ExperimentConfig`**

In `src/chi_bench/experiment/config.py`, remove these fields from the `ExperimentConfig` dataclass / Pydantic model (whichever it is):

```python
anthropic_key_env: str | None = None
openai_key_env: str | None = None
gemini_key_env: str | None = None
openrouter_key_env: str | None = None
```

Also remove any field aliases like `key_group`, `required_keys`, `optional_keys` from the same model (they appear in the YAML schema but are not consumed by code paths we keep).

- [ ] **Step 5: Run the tests, verify all pass**

```bash
cd /Users/weiran/Github/chi-bench
uv run pytest tests/unit/test_runner_argv.py -v
```

Expected: both tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/chi_bench/experiment/runner.py src/chi_bench/experiment/config.py tests/unit/test_runner_argv.py
git commit -m "feat: drop per-row API key overrides; one shared key per provider"
```

### Task C5: Add `ChiBenchDockerEnvironment`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/src/chi_bench/experiment/docker_env.py`
- Reference (read-only): `/Users/weiran/Github/chi-bench/src/chi_bench/experiment/modal_env.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_docker_env.py`:
```python
from pathlib import Path

import pytest

from chi_bench.experiment.docker_env import ChiBenchDockerEnvironment


def test_docker_env_resolves_task_id_from_task_path():
    # task_path matches the dataset layout: data/<domain>/tasks/<task_id>/
    task_path = Path("/repo/data/prior_auth_um/tasks/pa_t008_t008_o002_p01_mdreview_payer")
    env = ChiBenchDockerEnvironment(task_path=task_path, image="chi-bench:latest")
    assert env.task_id == "pa_t008_t008_o002_p01_mdreview_payer"


def test_docker_env_builds_docker_run_argv():
    task_path = Path("/repo/data/care_management/tasks/cm_afib_moderate_anxious_001")
    env = ChiBenchDockerEnvironment(
        task_path=task_path,
        image="chi-bench:latest",
        host_env={
            "ANTHROPIC_API_KEY": "ak-anthropic",
            "OPENROUTER_API_KEY": "ak-openrouter",
        },
        trial_artifacts_dir=Path("/tmp/trial-xyz"),
    )
    argv = env.build_docker_run_argv(agent_command=["sleep", "1"])
    assert argv[:2] == ["docker", "run"]
    assert "--rm" in argv
    flat = " ".join(argv)
    assert "-e CHI_BENCH_TASK_ID=cm_afib_moderate_anxious_001" in flat
    assert "-e ANTHROPIC_API_KEY=ak-anthropic" in flat
    assert "-e OPENROUTER_API_KEY=ak-openrouter" in flat
    assert "chi-bench:latest" in argv
    # The agent command appears verbatim at the tail.
    assert argv[-2:] == ["sleep", "1"]
```

Run: `uv run pytest tests/unit/test_docker_env.py -v` — expect `ModuleNotFoundError`.

- [ ] **Step 2: Implement `docker_env.py`**

```python
"""Local-Docker Harbor Environment for the chi-Bench single-image layout.

Mirrors ChiBenchModalEnvironment but runs a fresh local `docker run` per
trial. Wires the per-task fixtures by injecting CHI_BENCH_TASK_ID into the
container env; the in-container entrypoint resolves /opt/chi-bench/tasks/<id>
based on that variable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


FORWARDED_ENV_KEYS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "CHI_BENCH_SKILLS_ABLATE",
    "CHI_BENCH_TOOL_MODE",
)


@dataclass
class ChiBenchDockerEnvironment:
    task_path: Path
    image: str = "chi-bench:latest"
    host_env: Mapping[str, str] = field(default_factory=dict)
    trial_artifacts_dir: Path | None = None

    @property
    def task_id(self) -> str:
        return self.task_path.name

    def build_docker_run_argv(self, agent_command: list[str]) -> list[str]:
        argv: list[str] = ["docker", "run", "--rm"]
        argv += ["-e", f"CHI_BENCH_TASK_ID={self.task_id}"]
        for key in FORWARDED_ENV_KEYS:
            value = self.host_env.get(key)
            if value:
                argv += ["-e", f"{key}={value}"]
        if self.trial_artifacts_dir is not None:
            argv += ["-v", f"{self.trial_artifacts_dir}:/logs/artifacts"]
        argv += [self.image]
        argv += list(agent_command)
        return argv
```

Harbor's `Environment` protocol (lifecycle methods like `setup`, `agent_command`, `teardown`) will be added incrementally — for the TDD step above, only the docker-run argv assembly is needed. The harness file will be filled out further once we wire it into `runner.py`'s `MODAL_ENVIRONMENT_IMPORT_PATH`-style hook.

- [ ] **Step 3: Run the tests**

```bash
cd /Users/weiran/Github/chi-bench
uv run pytest tests/unit/test_docker_env.py -v
```

Expected: 2 passed.

- [ ] **Step 4: Wire docker_env into the runner**

In `src/chi_bench/experiment/runner.py`:

Add at the top:
```python
DOCKER_ENVIRONMENT_IMPORT_PATH = "chi_bench.experiment.docker_env:ChiBenchDockerEnvironment"
```

In `_build_harbor_command`, find the existing `if cfg.environment == "modal":` block and add a peer:

```python
if cfg.environment == "docker":
    cmd += ["--environment-import-path", DOCKER_ENVIRONMENT_IMPORT_PATH]
elif cfg.environment == "modal":
    # ... existing modal lines stay ...
```

(Today `docker` falls through and Harbor's default docker engine handles it via per-task docker-compose; after this change `docker` uses our single-image Environment class.)

- [ ] **Step 5: Verify runner still imports**

```bash
uv run python -c "from chi_bench.experiment.runner import _build_harbor_command; print('OK')"
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add src/chi_bench/experiment/docker_env.py tests/unit/test_docker_env.py src/chi_bench/experiment/runner.py
git commit -m "feat: ChiBenchDockerEnvironment + runner wiring for single-image local Docker"
```

---

## Phase D — Paper-table configs + driver

### Task D1: Port `prices.yaml`

**Files:**
- Create (by copy): `/Users/weiran/Github/chi-bench/configs/prices.yaml` from `actava-bench/configs/prices.yaml`

- [ ] **Step 1: Copy as-is**

```bash
mkdir -p /Users/weiran/Github/chi-bench/configs
cp /Users/weiran/Github/chi-bench/actava-bench/configs/prices.yaml \
   /Users/weiran/Github/chi-bench/configs/prices.yaml
```

- [ ] **Step 2: Update the header comment**

Open `configs/prices.yaml` and replace the first line:

```yaml
# USD per 1M tokens. Used by scripts/experiments/aggregate_results.py to compute ROI.
```

with:

```yaml
# USD per 1M tokens. Used by scripts/aggregate.py to compute paper Table 1's Cost column.
```

- [ ] **Step 3: Commit**

```bash
cd /Users/weiran/Github/chi-bench
git add configs/prices.yaml
git commit -m "chore: configs/prices.yaml"
```

### Task D2: Write `configs/experiments/table1_main_matrix.yaml`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/configs/experiments/table1_main_matrix.yaml`

- [ ] **Step 1: Write the file**

```bash
mkdir -p /Users/weiran/Github/chi-bench/configs/experiments
```

Then write the file:

```yaml
name: table1_main_matrix
description: chi-Bench Table 1 — 30 (harness × model) cells across PA-provider, PA-UM, CM.

defaults:
  environment: docker
  env_file: .env
  concurrency: 5
  n_attempts: 3
  max_retries: 2
  trials_root: logs/experiments/table1_main_matrix
  agent_timeout_multiplier: 2

domains:
  pa_provider:
    dataset: data/prior_auth_provider/tasks
    registry_path: data/prior_auth_provider/registry.json
  pa_um:
    dataset: data/prior_auth_um/tasks
    registry_path: data/prior_auth_um/registry.json
  cm:
    dataset: data/care_management/tasks
    registry_path: data/care_management/registry.json

rows:
  - { agent: claude-code,  model: anthropic/claude-opus-4-7 }
  - { agent: claude-code,  model: anthropic/claude-opus-4-6 }
  - { agent: claude-code,  model: anthropic/claude-sonnet-4-6 }
  - { agent: claude-code,  model: anthropic/claude-haiku-4-5 }
  - { agent: codex,        model: openai/gpt-5.5 }
  - { agent: codex,        model: openai/gpt-5.4 }
  - { agent: codex,        model: openai/gpt-5.4-mini }
  - { agent: gemini-cli,   model: gemini/gemini-3-pro-preview }
  - { agent: gemini-cli,   model: gemini/gemini-3-flash-preview }
  - { agent: openclaw,     model: anthropic/claude-opus-4-7 }
  - { agent: openclaw,     model: openrouter/deepseek/deepseek-v4-pro }
  - { agent: openclaw,     model: openrouter/z-ai/glm-5.1 }
  - { agent: openclaw,     model: openrouter/moonshotai/kimi-k2.6 }
  - { agent: openclaw,     model: openrouter/qwen/qwen3.6-max-preview }
  - { agent: openclaw,     model: openrouter/x-ai/grok-4.3 }
  - { agent: hermes,       model: openrouter/deepseek/deepseek-v4-pro }
  - { agent: hermes,       model: openrouter/z-ai/glm-5.1 }
  - { agent: hermes,       model: openrouter/moonshotai/kimi-k2.6 }
  - { agent: hermes,       model: openrouter/qwen/qwen3.6-max-preview }
  - { agent: hermes,       model: openrouter/x-ai/grok-4.3 }
  - { agent: openai-agents, model: deepseek/deepseek-v4-pro }
  - { agent: openai-agents, model: z-ai/glm-5.1 }
  - { agent: openai-agents, model: moonshotai/kimi-k2.6 }
  - { agent: openai-agents, model: qwen/qwen3.6-max-preview }
  - { agent: openai-agents, model: x-ai/grok-4.3 }
  - { agent: deepagents,   model: openrouter/deepseek/deepseek-v4-pro }
  - { agent: deepagents,   model: openrouter/z-ai/glm-5.1 }
  - { agent: deepagents,   model: openrouter/moonshotai/kimi-k2.6 }
  - { agent: deepagents,   model: openrouter/qwen/qwen3.6-max-preview }
  - { agent: deepagents,   model: openrouter/x-ai/grok-4.3 }
```

- [ ] **Step 2: Verify it parses to a valid `ExperimentConfig`**

```bash
cd /Users/weiran/Github/chi-bench
uv run python -c "
from chi_bench.experiment.config import ExperimentConfig
import yaml
data = yaml.safe_load(open('configs/experiments/table1_main_matrix.yaml'))
print('rows:', len(data['rows']))
assert len(data['rows']) == 30, f\"expected 30 rows, got {len(data['rows'])}\"
print('OK')
"
```

Expected: `rows: 30` then `OK`.

- [ ] **Step 3: Commit**

```bash
git add configs/experiments/table1_main_matrix.yaml
git commit -m "feat: configs/experiments/table1_main_matrix.yaml (30 cells)"
```

### Task D3: Write `configs/experiments/table2_e2e_arena.yaml`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/configs/experiments/table2_e2e_arena.yaml`

- [ ] **Step 1: Write the file**

```yaml
name: table2_e2e_arena
description: chi-Bench Table 2 — Dual-agent end-to-end PA, Codex + GPT-5.5 on both sides.

defaults:
  environment: docker
  env_file: .env
  concurrency: 5
  n_attempts: 3
  max_retries: 2
  trials_root: logs/experiments/table2_e2e_arena
  agent_timeout_multiplier: 2

dataset: data/prior_auth_e2e/tasks
registry_path: data/prior_auth_e2e/registry.json

agent: dual-pa-e2e
model: openai/gpt-5.5
provider_agent: codex
provider_model: openai/gpt-5.5
payer_agent: codex
payer_model: openai/gpt-5.5

agent_kwargs:
  phase_max_turns: "50"
  max_cycles: "6"
  p2p_coordination_cycles: "4"
  p2p_max_turn_pairs: "4"
  p2p_repair_attempts: "1"
```

- [ ] **Step 2: Commit**

```bash
git add configs/experiments/table2_e2e_arena.yaml
git commit -m "feat: configs/experiments/table2_e2e_arena.yaml"
```

### Task D4: Write `configs/experiments/table3_marathon.yaml`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/configs/experiments/table3_marathon.yaml`

- [ ] **Step 1: Write the file**

```yaml
name: table3_marathon
description: chi-Bench Table 3 — Marathon (all 25 tasks per domain in one session).

defaults:
  environment: docker
  env_file: .env
  concurrency: 1            # marathon tasks are long-horizon; one at a time
  n_attempts: 3
  max_retries: 1
  trials_root: logs/experiments/table3_marathon
  agent_timeout_multiplier: 2

domains:
  pa_provider:
    dataset: data/marathon/prior_auth_provider
    registry_path: data/marathon/prior_auth_provider/registry.json
  pa_um:
    dataset: data/marathon/prior_auth_um
    registry_path: data/marathon/prior_auth_um/registry.json
  cm:
    dataset: data/marathon/care_management
    registry_path: data/marathon/care_management/registry.json

rows:
  - { agent: claude-code, model: anthropic/claude-opus-4-7 }
  - { agent: codex,       model: openai/gpt-5.5 }
```

- [ ] **Step 2: Commit**

```bash
git add configs/experiments/table3_marathon.yaml
git commit -m "feat: configs/experiments/table3_marathon.yaml"
```

### Task D5: Write `configs/experiments/table4_skill_ablation.yaml`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/configs/experiments/table4_skill_ablation.yaml`

- [ ] **Step 1: Write the file**

```yaml
name: table4_skill_ablation
description: |
  Skill-ablation results (paper Fig. 4 source) — 4 conditions × 75 tasks.
  Drives CHI_BENCH_SKILLS_ABLATE (comma-separated list of references/<subdir>).

defaults:
  environment: docker
  env_file: .env
  concurrency: 5
  n_attempts: 3
  max_retries: 2
  trials_root: logs/experiments/table4_skill_ablation
  agent_timeout_multiplier: 2

domains:
  pa_provider:
    dataset: data/prior_auth_provider/tasks
    registry_path: data/prior_auth_provider/registry.json
  pa_um:
    dataset: data/prior_auth_um/tasks
    registry_path: data/prior_auth_um/registry.json
  cm:
    dataset: data/care_management/tasks
    registry_path: data/care_management/registry.json

conditions:
  - { name: full,       skills_ablate: [] }
  - { name: no_domain,  skills_ablate: [provider-pa, payer-um, care-manager] }
  - { name: no_medical, skills_ablate: [medical-library] }
  - { name: none,       skills_ablate: [provider-pa, payer-um, care-manager, medical-library] }

rows:
  - { agent: codex, model: openai/gpt-5.5 }
```

- [ ] **Step 2: Commit**

```bash
git add configs/experiments/table4_skill_ablation.yaml
git commit -m "feat: configs/experiments/table4_skill_ablation.yaml"
```

### Task D6: Write `configs/experiments/table5_mcp_vs_cli.yaml`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/configs/experiments/table5_mcp_vs_cli.yaml`

- [ ] **Step 1: Write the file**

```yaml
name: table5_mcp_vs_cli
description: |
  MCP vs CLI tool-surface ablation (paper Table 5) — 2 conditions × 75 tasks.
  Drives CHI_BENCH_TOOL_MODE (mcp | cli).

defaults:
  environment: docker
  env_file: .env
  concurrency: 5
  n_attempts: 3
  max_retries: 2
  trials_root: logs/experiments/table5_mcp_vs_cli
  agent_timeout_multiplier: 2

domains:
  pa_provider:
    dataset: data/prior_auth_provider/tasks
    registry_path: data/prior_auth_provider/registry.json
  pa_um:
    dataset: data/prior_auth_um/tasks
    registry_path: data/prior_auth_um/registry.json
  cm:
    dataset: data/care_management/tasks
    registry_path: data/care_management/registry.json

conditions:
  - { name: mcp, tool_mode: mcp }
  - { name: cli, tool_mode: cli }

rows:
  - { agent: codex, model: openai/gpt-5.5 }
```

- [ ] **Step 2: Commit**

```bash
git add configs/experiments/table5_mcp_vs_cli.yaml
git commit -m "feat: configs/experiments/table5_mcp_vs_cli.yaml"
```

### Task D7: Write `scripts/run_table.sh`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/scripts/run_table.sh`

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# scripts/run_table.sh — drive one paper-table reproduction end to end.
#
# Usage:
#   ./scripts/run_table.sh tableN [filters...]
#
# Where tableN ∈ {table1, table2, table3, table4, table5} and filters can be
# any of:
#   --agent <name>          : run only rows with this --agent
#   --row <int>             : 1-based index into rows[] (table1, table3)
#   --domain <name>         : pa_provider | pa_um | cm
#   --condition <name>      : skill-ablation / mcp-vs-cli condition name
#   --modal                 : opt into Modal (default is local docker)
#   --dry-run               : print commands without executing
#
# After all trials finish, run `python scripts/aggregate.py` to produce CSV.

set -euo pipefail

usage() {
  sed -n '2,/^set -e/p' "${BASH_SOURCE[0]}" | sed -n '2,/Where tableN/p'
  exit 1
}

TABLE="${1:-}"
shift || usage

case "$TABLE" in
  table1|table2|table3|table4|table5) ;;
  *) usage ;;
esac

CONFIG="configs/experiments/${TABLE}_*.yaml"
CONFIG_PATH=$(ls $CONFIG 2>/dev/null | head -n1)
if [[ -z "$CONFIG_PATH" ]]; then
  echo "No config found for $TABLE under configs/experiments/" >&2
  exit 1
fi

AGENT_FILTER=""
ROW_FILTER=""
DOMAIN_FILTER=""
CONDITION_FILTER=""
ENVIRONMENT_FLAG=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent)      AGENT_FILTER="$2"; shift 2;;
    --row)        ROW_FILTER="$2"; shift 2;;
    --domain)     DOMAIN_FILTER="$2"; shift 2;;
    --condition)  CONDITION_FILTER="$2"; shift 2;;
    --modal)      ENVIRONMENT_FLAG="--environment modal"; shift;;
    --dry-run)    DRY_RUN=1; shift;;
    -h|--help)    usage;;
    *) echo "Unknown flag: $1" >&2; exit 1;;
  esac
done

# Delegate iteration to a Python helper because YAML × row/domain/condition
# matrices are easier to parse there. The helper prints one shell command per
# trial slice on stdout; we exec each in turn.
PY_DRIVER="$(dirname "${BASH_SOURCE[0]}")/_emit_run_table_commands.py"

python "$PY_DRIVER" \
  --config "$CONFIG_PATH" \
  ${AGENT_FILTER:+--agent "$AGENT_FILTER"} \
  ${ROW_FILTER:+--row "$ROW_FILTER"} \
  ${DOMAIN_FILTER:+--domain "$DOMAIN_FILTER"} \
  ${CONDITION_FILTER:+--condition "$CONDITION_FILTER"} \
  ${ENVIRONMENT_FLAG} \
  | while IFS= read -r cmd; do
      echo "▶ $cmd"
      if [[ "$DRY_RUN" -eq 0 ]]; then
        eval "$cmd"
      fi
    done

echo "All slices for $TABLE completed."
echo "Run: python scripts/aggregate.py --table $TABLE  to produce CSV."
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x /Users/weiran/Github/chi-bench/scripts/run_table.sh
```

- [ ] **Step 3: Commit (helper script in next task)**

Will commit together with the Python helper.

### Task D8: Write `scripts/_emit_run_table_commands.py` (helper for run_table.sh)

**Files:**
- Create: `/Users/weiran/Github/chi-bench/scripts/_emit_run_table_commands.py`

- [ ] **Step 1: Write the script**

```python
"""Emit one `chi-bench experiment run` command per (row × domain × condition) slice.

Read by scripts/run_table.sh; one command per line on stdout.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

import yaml


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--agent", default=None)
    ap.add_argument("--row", type=int, default=None)
    ap.add_argument("--domain", default=None)
    ap.add_argument("--condition", default=None)
    ap.add_argument("--environment", default=None)
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    rows = cfg.get("rows")
    if rows is None and "agent" in cfg:
        # single-row config (table2) — wrap as a one-element list.
        rows = [{k: cfg[k] for k in ("agent", "model") if k in cfg}]

    domains = cfg.get("domains")
    if domains is None and "dataset" in cfg:
        domains = {"_single": {"dataset": cfg["dataset"], "registry_path": cfg.get("registry_path")}}

    conditions = cfg.get("conditions") or [{"name": None}]

    if args.row is not None:
        rows = [rows[args.row - 1]]
    if args.agent:
        rows = [r for r in rows if r.get("agent") == args.agent]
    if args.domain:
        domains = {k: v for k, v in domains.items() if k == args.domain}
    if args.condition:
        conditions = [c for c in conditions if c.get("name") == args.condition]

    env_flag = f"--environment {args.environment}" if args.environment else ""

    for row in rows:
        for dom_name, dom_cfg in domains.items():
            for cond in conditions:
                parts = ["chi-bench", "experiment", "run", "-f", args.config]
                parts += ["--agent", row["agent"]]
                if row.get("model"):
                    parts += ["--model", row["model"]]
                parts += ["--dataset", dom_cfg["dataset"]]
                if env_flag:
                    parts += env_flag.split()
                # Pass-through env vars for ablation conditions:
                shell = " ".join(shlex.quote(p) for p in parts)
                prefixes = []
                if cond.get("skills_ablate"):
                    prefixes.append(
                        f"CHI_BENCH_SKILLS_ABLATE={','.join(cond['skills_ablate'])}"
                    )
                if cond.get("tool_mode"):
                    prefixes.append(f"CHI_BENCH_TOOL_MODE={cond['tool_mode']}")
                if prefixes:
                    shell = " ".join(prefixes) + " " + shell
                print(shell)

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Sanity check with a dry-run**

```bash
cd /Users/weiran/Github/chi-bench
./scripts/run_table.sh table1 --row 1 --domain pa_um --dry-run
```

Expected output (one line, then the "completed" footer):
```
▶ chi-bench experiment run -f configs/experiments/table1_main_matrix.yaml --agent claude-code --model anthropic/claude-opus-4-7 --dataset data/prior_auth_um/tasks
```

- [ ] **Step 3: Commit**

```bash
git add scripts/run_table.sh scripts/_emit_run_table_commands.py
git commit -m "feat: scripts/run_table.sh + emit helper (one config per paper table)"
```

### Task D9: Write `scripts/aggregate.py`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/scripts/aggregate.py`
- Reference (read-only): `actava-bench/scripts/experiments/aggregate_results.py`, `actava-bench/scripts/experiments/summarize_curated25_full_matrix.py`

- [ ] **Step 1: Write a failing test for the CSV row shape**

`tests/unit/test_aggregate.py`:
```python
import json
import csv
from pathlib import Path

import pytest


def _make_trial(tmp: Path, name: str, reward: float, n_in: int, n_out: int, cache: int, walltime: float, model: str = "openai/gpt-5.5", agent: str = "codex") -> None:
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "result.json").write_text(json.dumps({
        "verifier_result": {"rewards": {"reward": reward}},
        "agent_result": {
            "input_tokens": n_in, "output_tokens": n_out,
            "n_cache_tokens": cache, "wall_clock_seconds": walltime,
        },
        "agent_info": {"model_info": {"provider": model.split("/")[0], "name": model.split("/", 1)[1]}},
        "task": {"path": f"data/prior_auth_um/tasks/{name.split('__')[0]}"},
    }))
    # reward.txt sentinel — aggregate.py checks for completion.
    (d / "reward.txt").write_text(str(reward))


def test_aggregate_produces_pass_at_1_and_wilson(tmp_path):
    from scripts.aggregate import aggregate

    trials = tmp_path / "trials"
    # 3 tasks × 3 attempts each. 4/9 pass.
    _make_trial(trials, "t1__abc", 1.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t1__def", 1.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t1__ghi", 0.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t2__abc", 1.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t2__def", 0.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t2__ghi", 0.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t3__abc", 1.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t3__def", 0.0, 1000, 500, 0, 10.0)
    _make_trial(trials, "t3__ghi", 0.0, 1000, 500, 0, 10.0)

    out_csv = tmp_path / "table.csv"
    aggregate(trials_dir=trials, prices_path=None, out_csv=out_csv, out_json=None)

    rows = list(csv.DictReader(out_csv.open()))
    assert len(rows) == 1
    r = rows[0]
    assert r["agent"] == "codex"
    assert r["model"] == "openai/gpt-5.5"
    # pass@1: 4/9 ≈ 0.4444
    assert abs(float(r["pass_at_1"]) - 4 / 9) < 1e-6
    # Wilson lo/hi columns present and within [0,1]
    assert 0.0 <= float(r["pass_at_1_lo"]) < float(r["pass_at_1"])
    assert float(r["pass_at_1"]) < float(r["pass_at_1_hi"]) <= 1.0
    # pass@3 per-task: 2/3 (t1 + t3 each have ≥1 pass; t2 has 0)
    assert abs(float(r["pass_at_3"]) - 2 / 3) < 1e-6
    # pass^3 per-task: 0/3 (no task has all 3 attempts passing)
    assert abs(float(r["pass_pow_3"]) - 0.0) < 1e-6
```

Run: `uv run pytest tests/unit/test_aggregate.py -v`
Expected: `ImportError: cannot import name 'aggregate' from 'scripts.aggregate'`.

- [ ] **Step 2: Implement `scripts/aggregate.py`**

```python
"""Aggregate Harbor trial outputs into a paper-table CSV row per (agent, model).

Reads result.json under --trials-dir, groups by (agent, model), emits pass@1 /
pass@3 / pass^3 with Wilson 95% CIs, plus cost / wall-clock.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml

from scripts._wilson import wilson_score_interval


@dataclass
class Trial:
    task_name: str
    agent: str
    model: str
    reward: float
    input_tokens: int
    output_tokens: int
    cache_tokens: int
    wall_clock_seconds: float


def _parse_trial(result_path: Path) -> Trial | None:
    data = json.loads(result_path.read_text())
    vr = data.get("verifier_result") or {}
    rb = vr.get("rewards") if isinstance(vr, dict) else None
    reward = float((rb or {}).get("reward", 0.0)) if rb else float(vr.get("reward", 0.0))
    ar = data.get("agent_result") or {}
    info = (data.get("agent_info") or {}).get("model_info") or {}
    provider = info.get("provider") or "unknown"
    name = info.get("name") or "unknown"
    model = f"{provider}/{name}"
    agent = (data.get("agent_info") or {}).get("agent", info.get("agent", "unknown"))
    if agent == "unknown":
        # fall back: trial dir name carries no agent; rely on task config later
        # for the OSS aggregator we always rely on agent_info written by harbor.
        agent = data.get("agent") or "unknown"
    task_path = (data.get("task") or {}).get("path") or ""
    task_name = Path(task_path).name or result_path.parent.name.split("__", 1)[0]
    return Trial(
        task_name=task_name,
        agent=agent,
        model=model,
        reward=reward,
        input_tokens=int(ar.get("input_tokens", 0)),
        output_tokens=int(ar.get("output_tokens", 0)),
        cache_tokens=int(ar.get("n_cache_tokens", 0)),
        wall_clock_seconds=float(ar.get("wall_clock_seconds", 0.0)),
    )


def _load_prices(path: Path | None) -> dict[str, dict[str, float]]:
    if path is None or not path.exists():
        return {}
    return yaml.safe_load(path.read_text()).get("prices", {})


def _cost(trial: Trial, prices: dict[str, dict[str, float]]) -> float:
    p = prices.get(trial.model) or {}
    inp = p.get("input", 0.0)
    out = p.get("output", 0.0)
    cache = p.get("cache", inp * 0.1)
    return (
        trial.input_tokens / 1_000_000.0 * inp
        + trial.output_tokens / 1_000_000.0 * out
        + trial.cache_tokens / 1_000_000.0 * cache
    )


def aggregate(
    *,
    trials_dir: Path,
    prices_path: Path | None,
    out_csv: Path,
    out_json: Path | None,
) -> None:
    trials: list[Trial] = []
    for result_json in trials_dir.rglob("result.json"):
        t = _parse_trial(result_json)
        if t is not None:
            trials.append(t)

    prices = _load_prices(prices_path)

    groups: dict[tuple[str, str], list[Trial]] = defaultdict(list)
    for t in trials:
        groups[(t.agent, t.model)].append(t)

    rows: list[dict[str, object]] = []
    for (agent, model), gs in sorted(groups.items()):
        # pass@1: fraction of trials that pass (k/n at trial granularity)
        k1 = sum(1 for x in gs if x.reward >= 1.0)
        n1 = len(gs)

        # pass@3 (per task: at-least-one of attempts passes) / pass^3 (all pass)
        by_task: dict[str, list[Trial]] = defaultdict(list)
        for x in gs:
            by_task[x.task_name].append(x)
        k3 = sum(1 for ts in by_task.values() if any(x.reward >= 1.0 for x in ts))
        kpow3 = sum(1 for ts in by_task.values() if len(ts) >= 3 and all(x.reward >= 1.0 for x in ts))
        nT = len(by_task)

        pass1_lo, pass1_hi = wilson_score_interval(k1, n1)
        pass3_lo, pass3_hi = wilson_score_interval(k3, nT)
        passpow3_lo, passpow3_hi = wilson_score_interval(kpow3, nT)

        total_cost = sum(_cost(x, prices) for x in gs)
        mean_walltime = sum(x.wall_clock_seconds for x in gs) / max(1, n1)

        rows.append({
            "agent": agent,
            "model": model,
            "n_trials": n1,
            "n_tasks": nT,
            "pass_at_1": k1 / max(1, n1),
            "pass_at_1_lo": pass1_lo,
            "pass_at_1_hi": pass1_hi,
            "pass_at_3": k3 / max(1, nT),
            "pass_at_3_lo": pass3_lo,
            "pass_at_3_hi": pass3_hi,
            "pass_pow_3": kpow3 / max(1, nT),
            "pass_pow_3_lo": passpow3_lo,
            "pass_pow_3_hi": passpow3_hi,
            "mean_cost_usd": total_cost / max(1, n1),
            "mean_walltime_s": mean_walltime,
        })

    if rows:
        with out_csv.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        if out_json is not None:
            out_json.write_text(json.dumps(rows, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials-dir", type=Path, required=True)
    ap.add_argument("--prices", type=Path, default=Path("configs/prices.yaml"))
    ap.add_argument("--out-csv", type=Path, required=True)
    ap.add_argument("--out-json", type=Path, default=None)
    args = ap.parse_args()
    aggregate(trials_dir=args.trials_dir, prices_path=args.prices, out_csv=args.out_csv, out_json=args.out_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run the test, verify it passes**

```bash
cd /Users/weiran/Github/chi-bench
uv run pytest tests/unit/test_aggregate.py -v
```

Expected: 1 passed.

- [ ] **Step 4: Commit**

```bash
git add scripts/aggregate.py tests/unit/test_aggregate.py
git commit -m "feat: scripts/aggregate.py with Wilson 95% CIs"
```

---

## Phase E — `chi-bench data verify`

### Task E1: Test the `data verify` command (TDD)

**Files:**
- Create: `/Users/weiran/Github/chi-bench/tests/smoke/__init__.py`
- Create: `/Users/weiran/Github/chi-bench/tests/smoke/test_verify_data_layout.py`

- [ ] **Step 1: Write the failing test**

```bash
mkdir -p /Users/weiran/Github/chi-bench/tests/smoke
touch /Users/weiran/Github/chi-bench/tests/smoke/__init__.py
```

`tests/smoke/test_verify_data_layout.py`:
```python
import subprocess
from pathlib import Path

import pytest


def _make_complete_data_tree(root: Path) -> None:
    """Create the minimum directory tree that `chi-bench data verify` accepts."""
    for domain, n in [
        ("prior_auth_provider", 25),
        ("prior_auth_um", 25),
        ("care_management", 25),
    ]:
        (root / domain / "shared" / "worlds").mkdir(parents=True, exist_ok=True)
        (root / domain / "registry.json").write_text("{}")
        for i in range(n):
            tdir = root / domain / "tasks" / f"task_{i:03d}"
            tdir.mkdir(parents=True, exist_ok=True)
            (tdir / "task.toml").write_text("version = \"1.0\"\n")
    for i in range(23):
        tdir = root / "prior_auth_e2e" / "tasks" / f"e2e_task_{i:03d}"
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "task.toml").write_text("")
    (root / "prior_auth_e2e" / "worlds").mkdir(parents=True, exist_ok=True)
    for dom in ("prior_auth_provider", "prior_auth_um", "care_management"):
        (root / "marathon" / dom).mkdir(parents=True, exist_ok=True)
        (root / "marathon" / dom / "task.toml").write_text("")
    (root / "skills" / "managed-care-operations-handbook" / "references" / "platform").mkdir(parents=True, exist_ok=True)
    (root / "skills" / "managed-care-operations-handbook" / "SKILL.md").write_text("# handbook")


def test_data_verify_succeeds_on_complete_tree(tmp_path, monkeypatch):
    _make_complete_data_tree(tmp_path)
    monkeypatch.chdir(tmp_path.parent)
    # data/ in current dir
    (tmp_path.parent / "data").symlink_to(tmp_path)
    res = subprocess.run(["chi-bench", "data", "verify"], capture_output=True, text=True)
    assert res.returncode == 0, f"stderr: {res.stderr}"
    assert "OK" in (res.stdout + res.stderr)


def test_data_verify_fails_on_missing_marathon(tmp_path, monkeypatch):
    _make_complete_data_tree(tmp_path)
    # Remove marathon to break the layout
    import shutil
    shutil.rmtree(tmp_path / "marathon")
    monkeypatch.chdir(tmp_path.parent)
    (tmp_path.parent / "data").symlink_to(tmp_path)
    res = subprocess.run(["chi-bench", "data", "verify"], capture_output=True, text=True)
    assert res.returncode != 0
    assert "marathon" in (res.stdout + res.stderr).lower()
```

Run: `uv run pytest tests/smoke/test_verify_data_layout.py -v`
Expected: FAIL — `chi-bench data verify` command doesn't exist yet.

### Task E2: Implement `chi-bench data verify`

**Files:**
- Modify: `/Users/weiran/Github/chi-bench/src/chi_bench/cli.py`

- [ ] **Step 1: Add the `data` typer app + `verify` command**

In `src/chi_bench/cli.py`, after the existing `app.add_typer(experiment_app, name="experiment")` line, add:

```python
data_app = typer.Typer(help="Data layout commands.", no_args_is_help=True)
app.add_typer(data_app, name="data")


@data_app.command("verify")
def data_verify(
    data_dir: Path = typer.Option(Path("data"), "--data-dir", help="Root of the downloaded dataset tree."),
) -> None:
    """Check that the downloaded data tree matches what the runner expects."""
    EXPECTED_TASKS = {
        "prior_auth_provider": 25,
        "prior_auth_um": 25,
        "care_management": 25,
        "prior_auth_e2e": 23,
    }
    missing: list[str] = []
    bad_counts: list[str] = []

    for dom, n_expected in EXPECTED_TASKS.items():
        tasks_dir = data_dir / dom / "tasks"
        if not tasks_dir.exists():
            missing.append(str(tasks_dir))
            continue
        n_actual = sum(1 for p in tasks_dir.iterdir() if p.is_dir())
        if n_actual != n_expected:
            bad_counts.append(f"{tasks_dir}: expected {n_expected}, got {n_actual}")

    for dom in ("prior_auth_provider", "prior_auth_um", "care_management"):
        m = data_dir / "marathon" / dom
        if not m.exists():
            missing.append(str(m))

    handbook = data_dir / "skills" / "managed-care-operations-handbook"
    if not (handbook / "SKILL.md").exists():
        missing.append(str(handbook))

    if missing or bad_counts:
        typer.echo("Data layout INCOMPLETE — see README §'Download data' for setup steps.", err=True)
        for path in missing:
            typer.echo(f"  missing: {path}", err=True)
        for line in bad_counts:
            typer.echo(f"  count mismatch: {line}", err=True)
        raise typer.Exit(1)

    typer.echo("OK — data layout matches expectations.")
```

Add `from pathlib import Path` at the top of `cli.py` if not already present.

- [ ] **Step 2: Run the tests**

```bash
cd /Users/weiran/Github/chi-bench
uv run pytest tests/smoke/test_verify_data_layout.py -v
```

Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add src/chi_bench/cli.py tests/smoke/__init__.py tests/smoke/test_verify_data_layout.py
git commit -m "feat: chi-bench data verify"
```

### Task E3: Add `chi-bench docker build` convenience

**Files:**
- Modify: `/Users/weiran/Github/chi-bench/src/chi_bench/cli.py`

- [ ] **Step 1: Add the command**

In `src/chi_bench/cli.py`, after the `data_app` definitions, add:

```python
docker_app = typer.Typer(help="Docker image commands.", no_args_is_help=True)
app.add_typer(docker_app, name="docker")


@docker_app.command("build")
def docker_build(
    tag: str = typer.Option("chi-bench:latest", "--tag", "-t", help="Image tag."),
    target: str = typer.Option("runtime", "--target", help="Build stage: runtime | ci-skeleton."),
) -> None:
    """Build the chi-bench single-image container."""
    import subprocess
    cmd = ["docker", "build", "-f", "docker/Dockerfile", "--target", target, "-t", tag, "."]
    typer.echo(f"$ {' '.join(cmd)}")
    raise typer.Exit(subprocess.call(cmd))
```

- [ ] **Step 2: Smoke check**

```bash
cd /Users/weiran/Github/chi-bench
uv run chi-bench docker build --help
```

Expected: shows `--tag` and `--target` options.

- [ ] **Step 3: Commit**

```bash
git add src/chi_bench/cli.py
git commit -m "feat: chi-bench docker build"
```

---

## Phase F — HF dataset packaging (release-prep script)

### Task F1: Stage data from actava-bench into `data/`

**Files:**
- Create (by copy): `/Users/weiran/Github/chi-bench/data/`

- [ ] **Step 1: Copy datasets into staging**

```bash
cd /Users/weiran/Github/chi-bench
mkdir -p data
cp -r actava-bench/datasets/prior_auth_provider data/
cp -r actava-bench/datasets/prior_auth_um      data/
cp -r actava-bench/datasets/care_management    data/
cp -r actava-bench/datasets/prior_auth_e2e     data/
mkdir -p data/marathon
cp -r actava-bench/datasets/single_session/prior_auth_provider data/marathon/prior_auth_provider
cp -r actava-bench/datasets/single_session/prior_auth_um       data/marathon/prior_auth_um
cp -r actava-bench/datasets/single_session/care_management     data/marathon/care_management
mkdir -p data/skills
cp -r actava-bench/datasets/skills/managed-care-operations-handbook data/skills/
```

- [ ] **Step 2: Verify the layout**

```bash
uv run chi-bench data verify
```

Expected: `OK — data layout matches expectations.`

If counts don't match: inspect mismatched dirs by hand and copy any missing tasks. Do not commit `data/` — it's gitignored.

### Task F2: Write `scripts/package_hf_dataset.py`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/scripts/package_hf_dataset.py`

- [ ] **Step 1: Write the script**

```python
"""Repackage the staged data/ tree for Hugging Face upload.

Operates in place under `data/`:
  1. Removes every task's `environment/` subdir (Dockerfile + docker-compose.yaml).
  2. Rewrites task.toml MCP URLs:  http://chi-bench-server:<port>/mcp  →  http://localhost:<port>/mcp
                                   http://healthverse-server:<port>/mcp →  http://localhost:<port>/mcp
                                   (catches both pre- and post-rename source trees)

After this script runs, the data/ tree is ready to:
  - upload to HF as `actava/chi-bench`
  - bake into the Docker image
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DATA_ROOT = Path("data")
URL_PATTERN = re.compile(r"http://(healthverse|chi-bench)-server:(\d+)/mcp")


def repackage_task_dir(task_dir: Path) -> tuple[bool, bool]:
    """Returns (env_removed, toml_rewritten)."""
    env_removed = False
    env_dir = task_dir / "environment"
    if env_dir.exists():
        import shutil
        shutil.rmtree(env_dir)
        env_removed = True

    toml_rewritten = False
    toml = task_dir / "task.toml"
    if toml.exists():
        text = toml.read_text()
        new_text = URL_PATTERN.sub(lambda m: f"http://localhost:{m.group(2)}/mcp", text)
        if new_text != text:
            toml.write_text(new_text)
            toml_rewritten = True

    return env_removed, toml_rewritten


def walk_tasks(root: Path):
    for task_toml in root.rglob("task.toml"):
        yield task_toml.parent


def main() -> int:
    if not DATA_ROOT.exists():
        print(f"ERROR: {DATA_ROOT}/ does not exist; run from repo root.", file=sys.stderr)
        return 1
    env_count = 0
    toml_count = 0
    for task_dir in walk_tasks(DATA_ROOT):
        env_removed, toml_rewritten = repackage_task_dir(task_dir)
        if env_removed:
            env_count += 1
        if toml_rewritten:
            toml_count += 1
    print(f"Removed environment/ from {env_count} task dirs.")
    print(f"Rewrote MCP URLs in {toml_count} task.toml files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Dry-run on staged data**

```bash
cd /Users/weiran/Github/chi-bench
uv run python scripts/package_hf_dataset.py
```

Expected: prints non-zero counts for both env and toml.

- [ ] **Step 3: Verify a few transformations**

```bash
ls data/prior_auth_um/tasks/pa_t008_*/environment 2>&1 || echo "environment/ correctly absent"
grep "localhost" data/prior_auth_um/tasks/pa_t008_*/task.toml | head
```

Expected: first command prints "correctly absent"; second prints `localhost` URLs.

- [ ] **Step 4: Commit (script only — data/ stays gitignored)**

```bash
git add scripts/package_hf_dataset.py
git commit -m "feat: scripts/package_hf_dataset.py (release-prep)"
```

---

## Phase G — Tests + CI

### Task G1: Add `tests/unit/test_state_machines.py`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/tests/unit/test_state_machines.py`

- [ ] **Step 1: Write small state-machine sanity tests**

Reference the existing source-repo test if any — check `actava-bench/tests/test_state_machine.py` for naming conventions. Port the simplest 2-3 transitions:

```python
"""Smoke tests for PA + CM state-machine transitions.

These pin core legal transitions for the verifier; full coverage lives
in the source-repo test tree which we deliberately did NOT port.
"""

import pytest

from chi_bench.core.state_machine import PriorAuthStateMachine, PA_INITIAL_STATUS
from chi_bench.core.enums import CaseStatus


def test_pa_initial_status_is_intake():
    assert PA_INITIAL_STATUS == CaseStatus.INTAKE


def test_pa_intake_to_triage_is_legal():
    sm = PriorAuthStateMachine()
    assert sm.can_transition(CaseStatus.INTAKE, CaseStatus.TRIAGE)


def test_pa_intake_to_approved_is_illegal():
    sm = PriorAuthStateMachine()
    assert not sm.can_transition(CaseStatus.INTAKE, CaseStatus.APPROVED)
```

Adjust the import names if the actual symbols differ — check by running:

```bash
uv run python -c "import chi_bench.core.state_machine as sm; print(dir(sm))"
```

Use whatever the actual public surface is.

- [ ] **Step 2: Run**

```bash
cd /Users/weiran/Github/chi-bench
uv run pytest tests/unit/test_state_machines.py -v
```

Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_state_machines.py
git commit -m "test: PA state-machine transitions"
```

### Task G2: Add `tests/unit/test_judge_parsing.py`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/tests/unit/test_judge_parsing.py`

- [ ] **Step 1: Write a parsing test**

Inspect `src/chi_bench/verifier/judge/workspace_judge.py:_parse_verdicts` for input shape, then:

```python
"""Verify WorkspaceJudge.parse_verdicts emits the expected verdict shape."""

import json
from pathlib import Path

import pytest

from chi_bench.verifier.judge.workspace_judge import WorkspaceJudge


def test_parse_verdicts_minimal(tmp_path):
    workspace_dir = tmp_path
    verdicts = {
        "rubric_verdicts": {
            "r_clinical_decision": {"passed": True, "evidence": "MD review approved"},
            "r_documentation": {"passed": False, "evidence": "missing chart note"},
        },
        "session_metadata": {"model": "claude-opus-4-7", "n_turns": 12},
    }
    (workspace_dir / "verdicts.json").write_text(json.dumps(verdicts))

    judge = WorkspaceJudge.__new__(WorkspaceJudge)  # no init
    parsed = judge._parse_verdicts(
        workspace_dir=workspace_dir,
        case_identifier="test-case",
        rubrics={
            "r_clinical_decision": {"description": "..."},
            "r_documentation": {"description": "..."},
        },
        unavailable_reason=None,
    )
    assert "r_clinical_decision" in parsed.verdicts
    assert parsed.verdicts["r_clinical_decision"].passed is True
    assert parsed.verdicts["r_documentation"].passed is False
```

Method name and signature may need adjustment — print `WorkspaceJudge._parse_verdicts.__code__.co_varnames` to see the actual params and adjust the test accordingly.

- [ ] **Step 2: Run**

```bash
uv run pytest tests/unit/test_judge_parsing.py -v
```

Expected: 1 passed. If it fails because of signature mismatch, fix the test to match the actual code (do NOT change `workspace_judge.py`).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_judge_parsing.py
git commit -m "test: WorkspaceJudge verdict parsing"
```

### Task G3: Add `tests/unit/test_runner_argv.py` — argv assembly

**Files:**
- Modify: `/Users/weiran/Github/chi-bench/tests/unit/test_runner_argv.py` (already created in Task C4)

- [ ] **Step 1: Add a higher-level test for `_build_harbor_command`**

Append to the existing file:

```python
from chi_bench.experiment.config import ExperimentConfig
from chi_bench.experiment.runner import _build_harbor_command


def test_build_harbor_command_docker_default(tmp_path):
    # Minimal config: docker env, single dataset, codex+gpt-5.5
    cfg = ExperimentConfig(
        dataset=str(tmp_path),
        agent="codex",
        model="openai/gpt-5.5",
        concurrency=1,
        environment="docker",
    )
    # Need a task.toml inside dataset to trigger single-trial path
    (tmp_path / "task.toml").write_text("")
    cmd = _build_harbor_command(cfg, env={"OPENAI_API_KEY": "ak-test"})
    s = " ".join(cmd)
    assert "trials start" in s
    assert "-a codex" in s
    assert "-m openai/gpt-5.5" in s
    assert "--environment-import-path chi_bench.experiment.docker_env:ChiBenchDockerEnvironment" in s
    assert "--ae OPENAI_API_KEY=ak-test" in s


def test_build_harbor_command_modal_keeps_modal_path(tmp_path):
    cfg = ExperimentConfig(
        dataset=str(tmp_path),
        agent="codex",
        model="openai/gpt-5.5",
        concurrency=1,
        environment="modal",
    )
    (tmp_path / "task.toml").write_text("")
    cmd = _build_harbor_command(cfg, env={"OPENAI_API_KEY": "ak-test"})
    s = " ".join(cmd)
    assert "chi_bench.experiment.modal_env:ChiBenchModalEnvironment" in s
    assert "chi_bench.experiment.docker_env" not in s
```

- [ ] **Step 2: Run all tests**

```bash
cd /Users/weiran/Github/chi-bench
uv run pytest tests/unit -q
```

Expected: all pass (Wilson, runner argv, docker_env, aggregate, state machines, judge parsing).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_runner_argv.py
git commit -m "test: runner argv for docker + modal environments"
```

### Task G4: Add `.github/workflows/ci.yml`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/.github/workflows/ci.yml`

- [ ] **Step 1: Write CI workflow**

```yaml
name: CI
on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --extra dev
      - run: uv run ruff check src/ tests/
      - run: uv run ruff format --check src/ tests/

  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --extra dev
      - run: uv run pytest tests/unit -q

  docker-build:
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      - name: Build ci-skeleton target
        run: docker build -f docker/Dockerfile --target ci-skeleton -t chi-bench:ci .
```

- [ ] **Step 2: Commit**

```bash
mkdir -p /Users/weiran/Github/chi-bench/.github/workflows
git add .github/workflows/ci.yml
git commit -m "ci: lint + unit-tests + docker-build"
```

---

## Phase H — README + docs

### Task H1: Write `README.md`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/README.md`

- [ ] **Step 1: Write the README**

Pull paper abstract one-liner and architecture from `chi-bench-arxiv-submission/neurips_2026.tex` and `sections/introduction.tex`.

```markdown
# chi-Bench

> **C**linical **H**ealthcare **I**n-Situ Environment and Evaluation **Bench**mark — long-horizon, policy-rich healthcare workflows for AI agents.

- Paper: [arXiv link — fill in once posted]
- Dataset: https://huggingface.co/datasets/actava/chi-bench
- Skills handbook (separate download): <GOOGLE_DRIVE_SHARE_URL_PLACEHOLDER>

## What this benchmark measures

75 tasks across 3 healthcare domains:

- **Prior Authorization — Provider** (25 tasks): provider agent prepares + submits PA packets.
- **Prior Authorization — UM** (25 tasks): payer agent triages, reviews, and decides.
- **Care Management** (25 tasks): conversational outreach + assessment + care plans.

Headline numbers from the paper:
- Best agent (Claude Code + Opus 4.6): **28.0%** overall pass@1.
- No agent clears **20%** on strict pass^3.
- In a single-session marathon (all 25 tasks at once), best is **3.8%**.

## Quickstart (single task)

```bash
git clone https://github.com/actava-ai/chi-bench && cd chi-bench
uv sync --extra dev
# 1. Download data (see "Download data" below)
chi-bench data verify
# 2. Build the docker image (~5 min, one-time)
chi-bench docker build
# 3. Run one task as a smoke check
cp .env.example .env  # then fill in ANTHROPIC_API_KEY + OPENAI_API_KEY
chi-bench experiment run \
  --dataset data/prior_auth_um/tasks/pa_t008_t008_o002_p01_mdreview_payer \
  --agent codex --model openai/gpt-5.5
```

## Full table reproduction

| Paper | Config | Command |
|---|---|---|
| Table 1 (Main) | `table1_main_matrix.yaml` | `./scripts/run_table.sh table1` |
| Table 2 (E2E) | `table2_e2e_arena.yaml` | `./scripts/run_table.sh table2` |
| Table 3 (Marathon) | `table3_marathon.yaml` | `./scripts/run_table.sh table3` |
| Fig. 4 (Skill ablation) | `table4_skill_ablation.yaml` | `./scripts/run_table.sh table4` |
| Table 5 (MCP vs CLI) | `table5_mcp_vs_cli.yaml` | `./scripts/run_table.sh table5` |

After all slices finish:

```bash
python scripts/aggregate.py \
  --trials-dir logs/experiments/table1_main_matrix \
  --prices configs/prices.yaml \
  --out-csv logs/table1.csv
```

CSV columns: `agent, model, n_trials, n_tasks, pass_at_1, pass_at_1_lo, pass_at_1_hi, pass_at_3, ..., pass_pow_3, pass_pow_3_hi, mean_cost_usd, mean_walltime_s` (with Wilson 95% CIs). v1 emits only the numeric table — paper figures are out of scope (users plot from the CSV).

## Supported agents

| `--agent` | `--model` examples | Maps to paper rows |
|---|---|---|
| `claude-code` | `anthropic/claude-opus-4-7`, `anthropic/claude-sonnet-4-6` | Claude Code |
| `codex` | `openai/gpt-5.5`, `openai/gpt-5.4` | Codex |
| `gemini-cli` | `gemini/gemini-3-pro-preview` | Gemini CLI |
| `openclaw` | `openrouter/deepseek/deepseek-v4-pro`, `anthropic/claude-opus-4-7` | OpenClaw |
| `hermes` | `openrouter/z-ai/glm-5.1`, ... | Hermes |
| `openai-agents` | `deepseek/deepseek-v4-pro`, ... | OAI Agents |
| `deepagents` | `openrouter/x-ai/grok-4.3`, ... | DeepAgents |

(See `configs/experiments/table1_main_matrix.yaml` for the full 30-row matrix.)

## Download data

### 1. Task fixtures (Hugging Face)

```bash
pip install -U huggingface_hub[cli]
huggingface-cli download actava/chi-bench --repo-type dataset --local-dir data/
```

### 2. Managed-Care Operations Handbook (Google Drive)

Download from: **<GOOGLE_DRIVE_SHARE_URL_PLACEHOLDER>**

```bash
mkdir -p data/skills
tar -xzf managed-care-operations-handbook.tar.gz -C data/skills/
```

### 3. Verify

```bash
chi-bench data verify
```

## Architecture

A single Python package (`chi_bench`) wraps a FastAPI server + 3 MCP servers (provider :8020, payer :8100, CM :8200) + an LLM-based verifier ("workspace judge"). Each trial runs in a fresh Docker container that bundles the server, the judge, the agent harness, and the per-task fixtures. See `docs/architecture.md`.

## Modal (optional)

```bash
modal token set --profile chi-bench
chi-bench experiment run -f configs/experiments/table1_main_matrix.yaml --environment modal
```

## Citation

(see `CITATION.cff`)

## License

Code: Apache-2.0 (`LICENSE`).
Data: see the HF dataset card.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README.md"
```

### Task H2: Write `docs/reproduce.md`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/docs/reproduce.md`

- [ ] **Step 1: Write the file**

```markdown
# Paper Table Reproduction

Each table has one config and one driver command. After trials complete,
`scripts/aggregate.py` rolls them up into a CSV with Wilson 95% CIs.

## Cost expectations

The headline run (all of Table 1) is **30 cells × 75 tasks × 3 trials = 6,750 trials**.
At an average per-trial cost from `configs/prices.yaml`, expect **$3,000-6,000 USD** of API spend
plus 24-72 hours of wall time at concurrency=5 per harness. The Quickstart single-task run is
under $1 and a few minutes.

## Table 1 — Main matrix

```bash
./scripts/run_table.sh table1
# Filter slices when iterating:
./scripts/run_table.sh table1 --agent claude-code
./scripts/run_table.sh table1 --row 5 --domain pa_um
# Aggregate:
python scripts/aggregate.py \
  --trials-dir logs/experiments/table1_main_matrix \
  --out-csv logs/table1.csv
```

## Table 2 — E2E arena

```bash
./scripts/run_table.sh table2
python scripts/aggregate.py --trials-dir logs/experiments/table2_e2e_arena --out-csv logs/table2.csv
```

## Table 3 — Marathon

```bash
./scripts/run_table.sh table3
python scripts/aggregate.py --trials-dir logs/experiments/table3_marathon --out-csv logs/table3.csv
```

## Skill-ablation (Fig. 4 numbers)

```bash
./scripts/run_table.sh table4
python scripts/aggregate.py --trials-dir logs/experiments/table4_skill_ablation --out-csv logs/table4.csv
```

## Table 5 — MCP vs CLI

```bash
./scripts/run_table.sh table5
python scripts/aggregate.py --trials-dir logs/experiments/table5_mcp_vs_cli --out-csv logs/table5.csv
```

## Common flags

- `--modal` — opt into Modal sandboxes (default: local Docker).
- `--dry-run` — print commands without executing.
- `--row N` (table1, table3) — run only the N-th row of `rows[]`.
- `--agent <name>` — run only rows with this harness.
- `--domain pa_provider | pa_um | cm` — restrict to one domain.
- `--condition <name>` (table4, table5) — restrict to one ablation cell.
```

- [ ] **Step 2: Commit**

```bash
mkdir -p /Users/weiran/Github/chi-bench/docs
git add docs/reproduce.md
git commit -m "docs: reproduce.md"
```

### Task H3: Write `docs/architecture.md`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/docs/architecture.md`

- [ ] **Step 1: Write the file**

```markdown
# chi-Bench Architecture

## Components

```
┌──────────────────────────────────────────────────────────────┐
│           chi-bench:latest (single image)                    │
│                                                              │
│   ┌─────────────────┐    ┌────────────────────────────────┐  │
│   │  Agent harness  │    │  chi-bench serve               │  │
│   │  (codex,        │◄──►│   • FastAPI :8023              │  │
│   │   claude-code,  │    │   • provider MCP :8020         │  │
│   │   openclaw, ...)│    │   • payer MCP :8100            │  │
│   └─────────────────┘    │   • CM MCP :8200               │  │
│                          └────────────────────────────────┘  │
│                                                              │
│   ┌─────────────────┐                                        │
│   │  Verifier       │ ──► writes /logs/artifacts/...         │
│   │  (WorkspaceJudge│                                        │
│   │   on Claude     │                                        │
│   │   Opus 4.7)     │                                        │
│   └─────────────────┘                                        │
└──────────────────────────────────────────────────────────────┘
```

## Layers (`src/chi_bench/`)

- **core/** — domain models (`PriorAuthCase`, `CMOutreachTask`, ...), state machines, world store.
- **services/** — ~29 HTTP/MCP-backed domain services (chart, coverage, intake, p2p, ...).
- **server/** — FastAPI app exposing the services as REST endpoints under `/api/...`.
- **mcp/** — three MCP servers wrapping the services (provider, payer, CM).
- **conversation/** — patient simulator + P2P-session orchestration.
- **verifier/** — pluggable judge (WorkspaceJudge by default) + per-stage rubrics.
- **experiment/** — Harbor-driven trial runner + 7 agent harnesses + `dual-pa-e2e`.

## Trial lifecycle

1. `chi-bench experiment run -f <config>` shells out to Harbor.
2. Harbor spawns one container per trial via `ChiBenchDockerEnvironment` (or `ChiBenchModalEnvironment` for `-e modal`).
3. The container entrypoint:
   - reads `CHI_BENCH_TASK_ID`, wires `/opt/chi-bench/tasks/<task_id>/fixtures` → `/fixtures`;
   - starts the unified server (HTTP + 3 MCP threads);
   - waits for all four endpoints to accept traffic;
   - exec's the agent harness's CLI.
4. Agent harness runs the agent against the MCP tools.
5. After the agent stops (success / timeout / abstain), Harbor invokes the verifier in the same container.
6. Verifier writes `verifier/scorecard.json` and `verifier/verdicts.json`; Harbor produces `result.json`.

## Why the LLM judge needs Anthropic credits

The verifier always uses `claude-opus-4-7` (configurable but paper-faithful default).
See `docs/judge.md`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: architecture.md"
```

### Task H4: Write `docs/judge.md`

**Files:**
- Create: `/Users/weiran/Github/chi-bench/docs/judge.md`

- [ ] **Step 1: Write the file**

```markdown
# The chi-Bench Judge

The verifier ("WorkspaceJudge") scores every trial. It is implemented as
an `claude-code`-based agent that reads:

- The expectations file at `/fixtures/expectations.json` (hidden from the
  agent under test).
- The rubrics for this task.
- The full trial workspace (every file the agent wrote).

It then produces `verdicts.json` with per-rubric `passed: bool` and
`evidence: str` fields. The trial reward is the AND of all rubric
verdicts (or, for CM, a continuous score over rubrics).

## Why a single judge model?

All paper numbers were collected with `claude-opus-4-7` as the judge.
For reproducibility, the OSS release pins the same judge model.
`HEALTHVERSE_JUDGE_MODEL` (renamed: `CHI_BENCH_JUDGE_MODEL`) is honored
if set but deviates from the paper's protocol.

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
chi-bench experiment rejudge --trial-root logs/experiments/<run> -e local
```

This re-invokes only the judge against existing workspaces — useful
when the judge prompt is tuned mid-experiment.
```

- [ ] **Step 2: Commit**

```bash
git add docs/judge.md
git commit -m "docs: judge.md"
```

---

## Phase I — Smoke validation + final cleanup

### Task I1: Run a single-task smoke trial end to end

**Files:**
- None modified; this is a validation step.

- [ ] **Step 1: Build the image**

```bash
cd /Users/weiran/Github/chi-bench
chi-bench docker build
```

Expected: image `chi-bench:latest` exists. If `docker images` doesn't show it, the build failed — fix and retry.

- [ ] **Step 2: Run one PA-UM task with codex**

```bash
cd /Users/weiran/Github/chi-bench
# Source the .env you populated in Phase H Step 1
set -a; source .env; set +a
chi-bench experiment run \
  --dataset data/prior_auth_um/tasks/pa_t008_t008_o002_p01_mdreview_payer \
  --agent codex --model openai/gpt-5.5
```

Expected: a single trial completes; `logs/experiments/.../result.json` exists with `verifier_result.rewards.reward` set.

If failure: inspect `logs/.../healthverse-server.log` and `logs/.../trial-*/stderr.log`, fix the underlying issue (probably a missed rename or a path mismatch).

- [ ] **Step 3: Run aggregate on the single trial**

```bash
python scripts/aggregate.py \
  --trials-dir logs/experiments/<run-id> \
  --out-csv /tmp/smoke.csv
cat /tmp/smoke.csv
```

Expected: a single CSV row with `agent=codex, model=openai/gpt-5.5`.

- [ ] **Step 4: Commit if any fixes were needed**

If you had to fix code, commit with a clear message like:

```bash
git add -A
git commit -m "fix: <whatever the issue was>"
```

### Task I2: Verify no `healthverse` strings leaked into the OSS code

**Files:**
- Verify only.

- [ ] **Step 1: Grep for any survivors**

```bash
cd /Users/weiran/Github/chi-bench
grep -rn "healthverse\|HEALTHVERSE_\|Healthverse" \
  src/chi_bench/ docker/ scripts/ configs/ tests/ docs/ README.md \
  | grep -v "actava-bench" \
  | grep -v "chi-bench-arxiv-submission" \
  | head
```

Expected: empty. Any hits are leaks — replace them.

- [ ] **Step 2: Verify the CLI shows only the trimmed surface**

```bash
uv run chi-bench --help
uv run chi-bench experiment --help
uv run chi-bench data --help
uv run chi-bench docker --help
```

Expected: only the documented commands appear; no `synth`, no `data import-synthea`, etc.

- [ ] **Step 3: Run the full unit test suite once more**

```bash
uv run pytest tests/unit -q
```

Expected: all green.

- [ ] **Step 4: Commit anything that needed fixing**

If you found and fixed leaks:
```bash
git add -A
git commit -m "chore: scrub residual healthverse references"
```

### Task I3: Verify .gitignore + final git state

**Files:**
- Verify only.

- [ ] **Step 1: Make sure data/ and logs/ aren't tracked**

```bash
cd /Users/weiran/Github/chi-bench
git status --short
```

Expected: no `data/`, `logs/`, `actava-bench/`, or `chi-bench-arxiv-submission/` entries.

- [ ] **Step 2: Show the final repo size + top-level**

```bash
du -sh src tests docs scripts configs docker 2>/dev/null
ls
```

Expected sizes (rough): src ~3MB, tests <1MB, docs <100KB, scripts <100KB, configs <100KB, docker <50KB.

- [ ] **Step 3: Show git log of the migration**

```bash
git log --oneline | head -40
```

Expected: 30-50 small, focused commits — bootstrap, port + rename, docker, keys, configs, scripts, tests, docs.

---

## Phase J — Release (out of code scope; manual steps)

The implementation is complete after Phase I. The remaining release steps are operational:

- Upload `data/{prior_auth_provider, prior_auth_um, care_management, prior_auth_e2e, marathon}/` to Hugging Face as `actava/chi-bench`. Pre-run `scripts/package_hf_dataset.py` if you re-stage.
- Upload `data/skills/managed-care-operations-handbook` as a `.tar.gz` to Google Drive, fetch a stable shareable link, replace `<GOOGLE_DRIVE_SHARE_URL_PLACEHOLDER>` in `README.md` and `docs/reproduce.md`.
- Confirm Apache-2.0 with project owners; revise `LICENSE` and the `pyproject.toml` license field if a different license is chosen.
- Push to `github.com/actava-ai/chi-bench`; tag `v0.1.0`.

---

## Self-Review Checklist

Performed after writing the plan; capturing here for traceability.

**Spec coverage** — every spec section maps to at least one task:

- §1 Goal → Tasks D2-D6 (paper-table configs).
- §2 Layout → Tasks A1-A5 + B1-B3 (top-level files + src) + C1-C2 (docker) + D7-D9 (scripts) + E1-E3 (CLI) + G1-G4 (tests + CI) + H1-H4 (docs).
- §3 Code reduction → B1 (drops), B2 (rename + inline), B3 (CLI trim).
- §4 Naming → B2 (mass rename).
- §5 Single-image Docker → C1, C2, C5.
- §6 API keys → A4 (.env.example), C4 (runner + config trim).
- §7 Data hosting → F1 (stage), F2 (HF packaging), E2 (verify), H1 (README §"Download data").
- §8 Configs + driver + aggregator → D2-D9.
- §9 Tests + CI → G1-G4.
- §10 README → H1.
- §11 Phases → covered by phases A-J of this plan.
- §12 Cross-validation deltas — each delta is in the task it materially affects:
  - 30 rows consolidated → D2.
  - Marathon = 3 tasks → D4 + F1.
  - Wilson CI → C3 (TDD'd) + D9 (used by aggregate).
  - Failure-mode out of scope → no task.
  - E2E agent_kwargs required → D3.
  - Plotting out of scope → no task (deliberate).

**Placeholder scan** — searched for "TBD", "TODO", "fill in details", "Similar to Task N":
- `<GOOGLE_DRIVE_SHARE_URL_PLACEHOLDER>` in H1 + H2 → intentional, user fills at release time, called out in Phase J.
- "[arXiv link — fill in once posted]" in README → intentional, paper not yet on arXiv.
- No other placeholders.

**Type consistency** — checked function names cross-task:
- `_forward_agent_keys(env)` (C4) is referenced consistently — no `overrides` param after C4.
- `wilson_score_interval(k, n, z=1.96)` is the name in C3 + used by D9 (`scripts/aggregate.py`).
- `ChiBenchDockerEnvironment` (C5) is referenced in C5's runner wiring + G3's test + cli `docker_app`.
- `aggregate(trials_dir, prices_path, out_csv, out_json)` (D9) matches the signature called from D7's stdout commands.

No fixes needed beyond what's already in the plan.
