# chi-Bench OSS Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a public, MIT-licensed `actava-ai/chi-bench` GitHub repository plus a CC-BY-4.0 `actava/chi-bench` Hugging Face dataset that reproduces every experimental result reported in the chi-Bench NeurIPS 2026 paper (Tables 1, E2E PA, Marathon, skill ablation, CLI tools ablation) on local Docker, without inheriting any internal `actava-bench` git history or branding.

**Architecture:** A fresh repo seeded by copying `src/healthverse/` from `actava-bench/` into `src/chi_bench/`, mechanically renaming all `healthverse → chi_bench` and `HEALTHVERSE_ → CHI_BENCH_` identifiers, dropping the synthesis pipeline, frontends, voice modules, copilot mode, and seeding pipeline, then publishing the curated 75-task dataset (plus the 23-task E2E set, three single-session marathon datasets, and the managed-care handbook skill) to Hugging Face for on-demand fetch. CI runs without API keys via a `stub` agent harness and a `CHI_BENCH_JUDGE_DISABLED=1` escape hatch.

**Tech Stack:** Python 3.12 + uv + ruff, Docker (primary) / Modal (optional), Harbor 0.4.0 trial orchestrator, MCP Python SDK 1.27.0 over streamable-http, Anthropic SDK 0.94.0, OpenAI Agents SDK 0.13.6, Hugging Face Hub for dataset distribution, GitHub Actions for CI, PyPI for package distribution.

**Companion spec:** `docs/superpowers/specs/2026-05-07-chi-bench-oss-release-design.md` (commits `75cf551`, `155eeeb`, `1575668`).

---

## Reading layout for this plan

Tasks are organized into **9 phases**: a preflight phase (Phase 0) for open questions that must be settled before code work begins, then the 8 implementation phases from the spec. Each task lists:

- **Files** — exact paths to create / modify / test
- **Steps** — 2-5-minute actions, each with the actual code or command (no placeholders)

When a step says "Run …", the expected outcome is the line below it. When a step says "Commit", the exact `git add` and `git commit` lines follow. Subagents executing one task should be able to do so without reading any other task.

The mechanical phases (1, 3, 9) compress to commands-only steps; the substantive phases (2, 4, 5, 6, 7, 8) expand into TDD-style task structures.

---

## Phase 0: Preconditions & Open Questions

### Task 0.1: Resolve handbook license conflict

**Files:**
- Read: `chi_bench_neurips_2026/sections/appendix_environment_detail.tex` lines 439–456
- Read: `docs/superpowers/specs/2026-05-07-chi-bench-oss-release-design.md` §4 "Datasets"

**Background:** The paper appendix says "The handbook is available under a research Data Use Agreement (DUA) that permits non-commercial research use with attribution and prohibits redistribution of the original documents." The spec says the entire dataset (including the handbook) is CC-BY-4.0 on HF. These conflict. The handbook is 34MB / 1290+ docs and is the load-bearing skill for agents.

- [ ] **Step 1: Surface the conflict to the user**

Open a GitHub Issue or message the user titled "Handbook license: CC-BY-4.0 vs DUA-only?" with the exact quotes from both sources. Present three resolution options:

1. **Ship handbook under DUA only** — gate handbook download behind a request form at `actava.ai/benchmarks`. Code repo public; handbook download requires DUA acceptance. Spec §4 must update to mixed-license dataset.
2. **Relicense handbook to CC-BY-4.0** — get sign-off from the Johns Hopkins Medicine clinicians who co-authored. Requires legal review on category (ii) "evidence-based" docs that paraphrase NCCN/ACC/AHA/ACOG.
3. **Strip the handbook from the OSS dataset entirely** — agents run with no skill; reproduction numbers will not match paper Table 1. Document the gap.

- [ ] **Step 2: Wait for user decision and record in spec**

Update `docs/superpowers/specs/2026-05-07-chi-bench-oss-release-design.md` §4 "Datasets: Hugging Face publishing" to reflect the chosen path. Commit the spec edit with message: `Resolve handbook license question: <chosen path>`.

- [ ] **Step 3: Update task downstream**

If option 1 is chosen, Task 5.1 below (HF data download CLI) gains a DUA-acceptance check. If option 3 is chosen, document that Task 8.2's reproduction-fidelity check will report **non-comparable** numbers and explain why.

**Blocker:** Tasks 5.* cannot proceed until this is resolved. Phases 1–4 can proceed in parallel.

---

### Task 0.2: Verify HF dataset is published and rebranded

**Files:** None (external check)

- [ ] **Step 1: Confirm HF dataset exists**

Run: `huggingface-cli repo info actava/chi-bench --repo-type dataset`
Expected: dataset metadata returned, file listing shows `prior_auth_provider/`, `prior_auth_um/`, `care_management/`, `prior_auth_e2e/`, `single_session/`, `skills/managed-care-operations-handbook/`. **If `prior_auth_e2e/` is absent**, flag immediately — this is a paper-required dataset that the spec earlier missed.

- [ ] **Step 2: Confirm rebranding is in place**

Run on a sampled task: `huggingface-cli download actava/chi-bench prior_auth_um/tasks/<one-task-id>/instruction.md --repo-type dataset --local-dir /tmp/hf-check`. Then `grep -i "actava\|healthverse\|healthsynth" /tmp/hf-check/...`. Expected: 0 hits. If hits exist, the dataset is NOT rebranded and the spec's "dataset scrub: out of scope" assumption is wrong; reopen scrub work.

- [ ] **Step 3: Confirm contract_v5 bake**

Run: `huggingface-cli download actava/chi-bench prior_auth_provider/tasks/<one-new_referral-task>/fixtures/expectations.json --repo-type dataset --local-dir /tmp/hf-check`. Then `jq '.evidence_rubric_items, .documents_catalog' /tmp/hf-check/.../expectations.json`. Expected: both keys non-null. If either is null, the contract_v5 bake never happened on HF and Phase 5 must include a re-publish step.

- [ ] **Step 4: Pin dataset version**

Run: `huggingface-cli repo info actava/chi-bench --repo-type dataset | jq -r .sha`. Record the commit SHA in `docs/superpowers/specs/2026-05-07-chi-bench-oss-release-design.md` under §4 "Dataset versioning" so the v1.0.0 release pins this exact revision.

---

### Task 0.3: Locate or decide on the Claude Code + Opus 4.6 row

**Files:**
- Read: `actava-bench/configs/experiments/curated25_full_matrix.yaml`
- Read: `actava-bench/configs/experiments/` (full listing)

**Background:** Paper Table 1 has 30 rows. `curated25_full_matrix.yaml` has 28 rows (3 Claude Code, not 4 — Opus 4.6 is missing). `curated25_openclaw_first_party.yaml` provides the OpenClaw + Opus 4.7 row, getting us to 29. The 30th row (Claude Code + Opus 4.6) source is unknown.

- [ ] **Step 1: Search for an Opus 4.6 config in the internal repo**

Run: `cd /path/to/actava-bench && git grep -l "claude-opus-4-6" -- 'configs/'`
Expected: produces a list of files. If `configs/experiments/<name>.yaml` is in the list, that's the source config.

- [ ] **Step 2: If no config exists, search experiment logs**

Run: `cd /path/to/actava-bench && git grep -l "claude-opus-4-6" -- 'logs/' || ls logs/experiments/ | grep -i opus_4_6`
Expected: surfaces a logs directory if the Opus 4.6 row was run. Open the directory's `config.yaml` (Harbor writes the resolved config alongside trials).

- [ ] **Step 3: Decide path**

If a config or log was found, Task 4.1 below imports the row from there. If neither is found, Task 4.1 instead **constructs** the row by analogy to the Opus 4.7 row (same harness, same key_group, same agent_kwargs; only `model: anthropic/claude-opus-4-6` differs). Document in commit message which path was chosen.

---

## Phase 1: Repo Bootstrap (1 day)

### Task 1.1: Create the public GitHub repository

- [ ] **Step 1: Create the repo (manual, via GitHub UI or `gh`)**

Run: `gh repo create actava-ai/chi-bench --public --description "chi-Bench: a benchmark of long-horizon, policy-rich healthcare workflows for AI agents" --homepage "https://actava.ai/benchmarks"`
Expected: repo created at `https://github.com/actava-ai/chi-bench`.

- [ ] **Step 2: Clone locally to a fresh working tree**

Run: `cd ~/Github && git clone git@github.com:actava-ai/chi-bench.git chi-bench-public && cd chi-bench-public`
Expected: empty repo cloned.

- [ ] **Step 3: Add MIT LICENSE**

Create `LICENSE` with the standard MIT text, copyright `2026 actAVA AI and contributors`. Use exactly:

```
MIT License

Copyright (c) 2026 actAVA AI and contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 4: Add LICENSE-DATA**

Create `LICENSE-DATA` with the CC-BY-4.0 license text from `https://creativecommons.org/licenses/by/4.0/legalcode.txt`. Add the leading paragraph: `This file applies to the chi-Bench dataset hosted at huggingface.co/datasets/actava/chi-bench, NOT to the source code in this repository (see LICENSE for code license).`

**Note:** If Task 0.1 resolved to option 1 (DUA), replace the dataset license body with the chosen DUA terms. If option 3 (no handbook), add a footnote: "The Managed-Care Operations Handbook is not included in this dataset; see DATASET.md for separate access."

- [ ] **Step 5: Add `.gitignore`**

Create `.gitignore`:

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.venv/
venv/
dist/
build/
*.egg-info/
.pytest_cache/
.coverage
.ruff_cache/

# uv
uv.lock

# Editor
.idea/
.vscode/
.DS_Store

# Local data + logs
~/.cache/chi-bench/
data/
logs/
*.log
.env
.env.local

# CI artifacts
.github/cache/
```

- [ ] **Step 6: Add empty README.md placeholder**

Create `README.md` with one line: `# chi-Bench` (full content lands in Task 7.1).

- [ ] **Step 7: Initial pyproject.toml skeleton**

Create `pyproject.toml`:

```toml
[project]
name = "chi-bench"
version = "1.0.0"
description = "chi-Bench: a benchmark of long-horizon, policy-rich healthcare workflows for AI agents"
authors = [{name = "actAVA AI", email = "research@actava.ai"}]
license = {file = "LICENSE"}
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    # Filled in during Phase 2 after copying actava-bench/pyproject.toml
]

[project.optional-dependencies]
dev = []

[project.scripts]
chi-bench = "chi_bench.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/chi_bench"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "RUF"]

[tool.chi_bench]
dataset_version = "1.0.0"
```

- [ ] **Step 8: Commit and push**

```bash
git add LICENSE LICENSE-DATA .gitignore README.md pyproject.toml
git commit -m "chore: bootstrap empty chi-bench repo (Phase 1)"
git push origin main
```

- [ ] **Step 9: Set branch protection on `main`**

Run: `gh api repos/actava-ai/chi-bench/branches/main/protection -X PUT -f required_status_checks[strict]=true -f required_status_checks[contexts][]=lint -f required_status_checks[contexts][]=unit -f required_status_checks[contexts][]=import-smoke -f enforce_admins=false -f required_pull_request_reviews[required_approving_review_count]=1`
Expected: protection rule created. (CI jobs are added in Phase 7; protection refers to them by name in advance.)

---

## Phase 2: Code Import & Module Pruning (2 days)

### Task 2.1: Copy `src/healthverse/` from `actava-bench/`

**Files:**
- Source: `actava-bench/src/healthverse/`
- Destination: `chi-bench-public/src/chi_bench/`

- [ ] **Step 1: Create destination dir**

Run: `mkdir -p src/chi_bench`
Expected: directory created.

- [ ] **Step 2: Copy contents**

Run: `cp -R /path/to/actava-bench/src/healthverse/. src/chi_bench/`
Expected: all subtrees copied.

- [ ] **Step 3: Verify the copy**

Run: `find src/chi_bench -name '__init__.py' | head -10 && du -sh src/chi_bench`
Expected: subdirs `core/`, `services/`, `server/`, `mcp/`, `verifier/`, `experiment/`, `conversation/`, `synth/`, `seeding/`, `bootstrap.py`, `bootstrap_cm.py`, `cli.py`, `copilot.py` listed; size around 2–3 MB.

- [ ] **Step 4: Commit (intermediate state, NOT pushed yet)**

```bash
git add src/chi_bench
git commit -m "chore: copy healthverse package as chi_bench (Phase 2.1, pre-prune)"
```

Do NOT push — this commit retains internal naming and dropped modules; later tasks will rewrite history before push at end of Phase 3.

---

### Task 2.2: Drop unused top-level modules

**Files to delete:**
- `src/chi_bench/synth/`
- `src/chi_bench/seeding/`
- `src/chi_bench/copilot.py`
- `src/chi_bench/bootstrap_cm.py` (CM-specific copilot bootstrap, unused at experiment runtime)
- `src/chi_bench/conversation/voice/`
- `src/chi_bench/conversation/voice_evaluation.py`
- `src/chi_bench/conversation/voice_orchestrator.py`
- `src/chi_bench/conversation/voice_patient_simulator.py`

- [ ] **Step 1: Delete the directories and files**

Run:
```bash
rm -rf src/chi_bench/synth src/chi_bench/seeding src/chi_bench/conversation/voice
rm -f src/chi_bench/copilot.py src/chi_bench/bootstrap_cm.py
rm -f src/chi_bench/conversation/voice_evaluation.py
rm -f src/chi_bench/conversation/voice_orchestrator.py
rm -f src/chi_bench/conversation/voice_patient_simulator.py
```

- [ ] **Step 2: Verify no `synth`, `seeding`, `voice` files remain**

Run: `find src/chi_bench -type f \( -name 'voice*' -o -name 'copilot*' -o -name 'bootstrap_cm*' \) -o -path '*/synth/*' -o -path '*/seeding/*' | head`
Expected: 0 lines.

- [ ] **Step 3: Commit**

```bash
git add -A src/chi_bench
git commit -m "feat: drop synth, seeding, voice, copilot, bootstrap_cm (Phase 2.2)"
```

---

### Task 2.3: Walk the `verifier/ ↔ synth/` coupling and build `verifier/_compat.py`

**Files:**
- Read: `src/chi_bench/verifier/` (entire subtree)
- Create: `src/chi_bench/verifier/_compat.py`
- Modify: every file under `src/chi_bench/verifier/` that imports from the deleted `synth/`

- [ ] **Step 1: Inventory the broken imports**

Run: `grep -rEn 'from healthverse\.synth|from chi_bench\.synth|import healthverse\.synth|import chi_bench\.synth' src/chi_bench/verifier/ | tee /tmp/verifier-synth-imports.txt`
Expected: a list of (file:line: import statement) tuples. Each tuple identifies a symbol that needs a home in `_compat.py`.

- [ ] **Step 2: Resolve every imported symbol back to its definition**

For each unique import path in `/tmp/verifier-synth-imports.txt`, look up the symbol in the **internal** `actava-bench/src/healthverse/synth/` (which still has the original modules). Use `grep -rn "^class <Sym>\|^def <Sym>\|^<Sym> = " /path/to/actava-bench/src/healthverse/synth/` to find each definition. Compile a list:

```
- ExpectedServiceRequest         → actava-bench/src/healthverse/synth/v2/expectations.py
- SynthesizedTaskBundle          → actava-bench/src/healthverse/synth/models/synthesized_bundle.py
- ContractV5RubricItem           → actava-bench/src/healthverse/synth/v2/judge_contract.py
- ContractV5DocumentEntry        → actava-bench/src/healthverse/synth/v2/judge_contract.py
- (… continue exhaustively)
```

Write the inventory to `/tmp/verifier-synth-symbols.txt` for the commit message.

- [ ] **Step 3: Create `verifier/_compat.py` and copy each symbol verbatim**

Create `src/chi_bench/verifier/_compat.py`:

```python
"""Pydantic models and helpers copied from the now-removed `synth` package.

The synthesis pipeline that produces task fixtures is internal to actava-bench
and not part of the chi-Bench OSS release; the verifier still needs to read
the JSON contracts those fixtures emit, so the relevant model classes are
duplicated here verbatim. Do NOT add new behavior — this is a frozen surface
that mirrors the upstream synth contract.

Source: actava-bench/src/healthverse/synth/{v2/expectations.py, v2/judge_contract.py,
models/synthesized_bundle.py} as of <upstream-commit-sha-from-step-2>.
"""
from __future__ import annotations

# Each symbol below is copied verbatim from its source file. Imports are de-duplicated
# at the top of this file. If a referenced helper is itself defined in synth, copy
# it here too; the goal is for this file to be self-contained.

# <... copied class definitions, exactly as in the source ...>
```

For each symbol from Step 2, copy the full class/function definition into `_compat.py` in the same order they appear in source. Preserve docstrings. De-dup imports at the top of the file.

- [ ] **Step 4: Rewrite verifier imports**

For each line in `/tmp/verifier-synth-imports.txt`, rewrite the import to point at `_compat`. Example:

Before:
```python
from chi_bench.synth.v2.expectations import ExpectedServiceRequest
```

After:
```python
from chi_bench.verifier._compat import ExpectedServiceRequest
```

Use `sed` per file or open each file in turn. Be exact about the symbol set imported.

- [ ] **Step 5: Verify imports resolve**

Run: `python -c "from chi_bench.verifier import _compat; from chi_bench.verifier import judge, scoring"`
Expected: no `ModuleNotFoundError`. If errors, return to Step 2 — a symbol was missed.

- [ ] **Step 6: Commit**

```bash
git add src/chi_bench/verifier
git commit -m "feat: extract verifier-needed synth symbols into verifier/_compat.py (Phase 2.3)"
```

---

### Task 2.4: Stub the CM voice WebSocket route

**Files:**
- Modify: `src/chi_bench/server/routers/cm/voice_ws.py`

- [ ] **Step 1: Read the current file**

Run: `wc -l src/chi_bench/server/routers/cm/voice_ws.py && head -20 src/chi_bench/server/routers/cm/voice_ws.py`
Expected: ~600+ lines, full WebSocket handler that imports voice modules we deleted.

- [ ] **Step 2: Replace the file with a 501-stub**

Overwrite `src/chi_bench/server/routers/cm/voice_ws.py` with:

```python
"""Voice WebSocket route stub.

Voice patient outreach is not part of the chi-Bench OSS release. Care
management tasks use the text-only patient simulator (see
``chi_bench.conversation.patient_simulator``) which the CM tasks shipped on
Hugging Face are configured for. The voice route is preserved at this path
only so that import-time URL registration does not break; calls return
HTTP 501.
"""
from __future__ import annotations

from fastapi import APIRouter
from starlette.websockets import WebSocket

router = APIRouter()


@router.websocket("/ws/voice")
async def voice_ws_stub(websocket: WebSocket) -> None:
    """Reject any voice WebSocket connection with a 501-equivalent close code."""
    await websocket.accept()
    await websocket.send_json(
        {
            "type": "error",
            "code": 501,
            "message": (
                "Voice outreach is not available in chi-Bench OSS; "
                "use the text-only outreach tools under cm_outreach.* instead."
            ),
        }
    )
    await websocket.close(code=1011, reason="voice not implemented in OSS")
```

- [ ] **Step 3: Verify imports resolve**

Run: `python -c "from chi_bench.server.routers.cm.voice_ws import router"`
Expected: no error.

- [ ] **Step 4: Commit**

```bash
git add src/chi_bench/server/routers/cm/voice_ws.py
git commit -m "feat: stub CM voice WebSocket route (Phase 2.4)"
```

---

### Task 2.5: Verify the package imports cleanly

**Files:**
- Run-only

- [ ] **Step 1: Vendor the `pyproject.toml` runtime dependencies from actava-bench**

Open `actava-bench/pyproject.toml`, copy the `[project] dependencies` array verbatim into `chi-bench/pyproject.toml`. Drop any dep that is referenced only by deleted modules (look for "synth", "voice", "frontend", "modal" as keyword hits — keep modal because Modal is documented as optional). Add `huggingface_hub>=0.20` (Phase 5 needs it).

- [ ] **Step 2: Sync the venv**

Run: `uv sync --extra dev`
Expected: dependencies install. Errors here mean the dep list was wrong.

- [ ] **Step 3: Smoke import**

Run: `uv run python -c "import chi_bench; from chi_bench.cli import app; print('ok')"`
Expected: `ok`. If `ModuleNotFoundError` for `chi_bench.synth`/`seeding`/`voice`/`copilot`, an importer somewhere else still references the deleted module — locate via `git grep` and fix in a follow-up commit.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: pin chi-bench runtime deps; verify clean import (Phase 2.5)"
```

---

## Phase 3: Aggressive Rename (2 days)

### Task 3.1: Mechanical sed pass for `healthverse → chi_bench` and `HEALTHVERSE_ → CHI_BENCH_`

**Files:** every text file in the working tree.

- [ ] **Step 1: Verify clean working tree**

Run: `git status`
Expected: clean. If not, commit pending work first.

- [ ] **Step 2: Rename Python identifiers**

Run:
```bash
git ls-files | xargs grep -lE 'healthverse|HEALTHVERSE_' 2>/dev/null | \
  xargs sed -i.bak -E 's/healthverse/chi_bench/g; s/HEALTHVERSE_/CHI_BENCH_/g'
find . -name '*.bak' -delete
```
Expected: hundreds of file edits. The `.bak` files are macOS sed's required suffix workaround; the second find deletes them.

- [ ] **Step 3: Verify no surviving references**

Run: `git grep -i healthverse | head`
Expected: 0 lines. If any remain, hand-fix.

- [ ] **Step 4: Verify HEALTHVERSE_ is gone**

Run: `git grep -E 'HEALTHVERSE_'`
Expected: 0 lines.

- [ ] **Step 5: Smoke import**

Run: `uv run python -c "import chi_bench; print('ok')"`
Expected: `ok`. If `ModuleNotFoundError` somewhere it's because a sed-corrupted import slipped through — dump traceback, hand-fix.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: rename healthverse → chi_bench and HEALTHVERSE_ → CHI_BENCH_ (Phase 3.1)"
```

---

### Task 3.2: Rename `actAVA / actava → chi-Bench / chi-bench` (case-aware)

**Files:** every text file.

- [ ] **Step 1: Run a case-aware rewrite**

Run:
```bash
# actAVA → chi-Bench (preserves the proper-noun branding form)
git ls-files | xargs grep -l 'actAVA' 2>/dev/null | \
  xargs sed -i.bak -E 's/actAVA/chi-Bench/g'

# actava → chi-bench (lowercase form, e.g., env var fragments, bucket names)
# CAUTION: do NOT touch CONTRIBUTORS.md (paper affiliation) or the literal
# string "actava-ai" in the repo URL. Use a wider rewrite then patch back.
git ls-files | xargs grep -l 'actava' 2>/dev/null | \
  xargs sed -i.bak -E 's/actava/chi-bench/g'

find . -name '*.bak' -delete
```

- [ ] **Step 2: Patch back the survivors**

The repo namespace `actava-ai/chi-bench` and the paper affiliation `actAVA AI` should remain. Find leftover hits:

```bash
git grep -E 'chi-bench-ai|chi-bench AI'
```
Hand-fix each: `chi-bench-ai` → `actava-ai`, `chi-bench AI` → `actAVA AI`. (The Step 1 sed nuked them, Step 2 restores the proper names.)

- [ ] **Step 3: Verify**

Run: `git grep -i actava`
Expected: hits only in `LICENSE` (copyright `actAVA AI`), `pyproject.toml` (author email), and `actava-ai/chi-bench` URL strings (in README placeholder; those go in Task 7.1). Anywhere else is a leak.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: rename actAVA/actava → chi-Bench/chi-bench, preserve actava-ai org (Phase 3.2)"
```

---

### Task 3.3: Manual review of high-risk surfaces

**Files:**
- `pyproject.toml`
- `src/chi_bench/cli.py`
- `docker/Dockerfile`
- `docker/docker-compose.template.yml`
- `src/chi_bench/experiment/runner.py`
- `src/chi_bench/experiment/modal_env.py`

- [ ] **Step 1: Inspect each file**

Open each file in turn. Look specifically for:

- **`pyproject.toml`**: confirm `[project.scripts] chi-bench = "chi_bench.cli:app"`. Confirm package discovery `[tool.hatch.build.targets.wheel] packages = ["src/chi_bench"]`.
- **`cli.py`**: the typer app name, every `--help` string. Replace any "healthverse" / "actava" that survived sed.
- **`docker/Dockerfile`**: `ENV CHI_BENCH_*` lines, `LABEL` lines, image name. Image label should read `chi-bench-server`.
- **`docker/docker-compose.template.yml`**: service names should be `chi-bench-server` (was `healthverse-server`), `chi-bench-judge` if present.
- **`experiment/runner.py`**: the env-var allowlists `SERVER_ENV_FORWARD_KEYS` and `AGENT_ENV_ALLOWLIST` — confirm renamed `CHI_BENCH_*` keys appear, not `HEALTHVERSE_*`.
- **`experiment/modal_env.py`**: Modal app name (should rename, see Task 3.4) and image build context.

For each file, fix any surviving leaks.

- [ ] **Step 2: Smoke import**

Run: `uv run python -c "from chi_bench.cli import app; from chi_bench.experiment.runner import run_experiment"`
Expected: `app` and `run_experiment` import.

- [ ] **Step 3: Smoke `--help`**

Run: `uv run chi-bench --help 2>&1 | head -20`
Expected: typer help text. The first line says `Usage: chi-bench [OPTIONS] COMMAND [ARGS]...`.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: hand-fix high-risk rename surfaces (Phase 3.3)"
```

---

### Task 3.4: Rename Modal profile and app name

**Files:**
- `src/chi_bench/experiment/modal_env.py`
- `src/chi_bench/experiment/config.py`
- `docker/Dockerfile.modal`
- `docker/modal-entrypoint.sh`

- [ ] **Step 1: Find all Modal profile references**

Run: `git grep -nE '"actava"|"actava-bench"|profile.*actava|app_name.*healthverse|app_name.*actava'`
Expected: hits in `experiment/config.py` (`profile: str = Field(default="actava")`) and possibly `experiment/modal_env.py` (`app_name = "healthverse-..."`).

- [ ] **Step 2: Rewrite each occurrence**

Replace:
- `profile: str = Field(default="actava", ...)` → `profile: str = Field(default="chi-bench", ...)`
- Any `app_name = "healthverse-..."` or `app_name = "actava-..."` → `app_name = "chi-bench-..."`
- Any Modal image tag `healthverse:...` → `chi-bench:...`

- [ ] **Step 3: Verify**

Run: `git grep -nE '"actava"|"actava-bench"|app_name.*healthverse'`
Expected: 0 lines.

- [ ] **Step 4: Smoke**

Run: `uv run python -c "from chi_bench.experiment.config import ExperimentConfig; print(ExperimentConfig(dataset='/tmp').modal.profile)"`
Expected: `chi-bench`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: rename Modal profile and app to chi-bench (Phase 3.4)"
```

---

### Task 3.5: Run the audit grep ladder (precursor to scripts/audit_release.py)

- [ ] **Step 1: Run each grep manually**

Run each of these and confirm 0 hits except where noted:

```bash
git grep -i actava                              # expect: only LICENSE, pyproject.toml, repo URL
git grep -i healthverse                         # expect: 0
git grep -i healthsynth                         # expect: 0
git grep -E 'HEALTHVERSE_|HEALTHSYNTH_'         # expect: 0
git grep -E '(modal|profile).*actava'           # expect: 0
git grep -iE 'todo:|fixme:|hack:|xxx:|kludge:'  # review every hit, none should reference internal
git grep -E '/Users/|/home/[a-z]+/'             # expect: 0
git grep -E '[A-Za-z][a-zA-Z0-9_.+-]*@(gmail|anthropic|salesforce|stanford|jhu)\.[a-z]+'  # expect: 0
```

If any unexpected hit appears, fix it.

- [ ] **Step 2: Commit any fixes**

```bash
git add -A
git diff --cached --quiet || git commit -m "chore: audit-grep cleanups (Phase 3.5)"
```

(The `--quiet` test makes the commit no-op if nothing changed.)

---

## Phase 4: Configs, Docker, CLI Cleanup (2 days)

### Task 4.1: Build the 30-row `main_matrix.yaml`

**Files:**
- Read: `actava-bench/configs/experiments/curated25_full_matrix.yaml` (28 rows)
- Read: `actava-bench/configs/experiments/curated25_openclaw_first_party.yaml` (2 rows)
- Decide: Opus 4.6 row source per Task 0.3
- Create: `configs/experiments/main_matrix.yaml`

- [ ] **Step 1: Delete the imported configs from `configs/experiments/` (we will rebuild)**

Run:
```bash
git rm -r configs/experiments
git rm -r configs/archive 2>/dev/null || true
git rm -r configs/synth 2>/dev/null || true
git commit -m "chore: prune experiment configs in preparation for paper-aligned set (Phase 4.1)"
```

- [ ] **Step 2: Author `configs/experiments/main_matrix.yaml`**

Create the file with the consolidated 30-row matrix. Start with the structure below, then paste the 28 rows from `curated25_full_matrix.yaml` (lines 114-227), then append the 2 OpenClaw rows from `curated25_openclaw_first_party.yaml` rows section, then append the Opus 4.6 row from Task 0.3.

```yaml
name: main_matrix
description: |
  Paper Table 1 main result — 30 (harness, model) rows × 75 tasks × 3 trials = 6,750 trials.
  Reproduces chi-Bench paper §5.2 "chi-Bench Results".

  Defaults match the paper appendix D.3 "Judge, Container, and Harness Configuration":
  - 1800s agent wall-clock cap (agent_timeout_multiplier=2 over the 900s base)
  - 3 independent trials per task
  - 5 concurrent trials per slice
  - Modal sandbox 24h timeout, Docker has no global per-run cap

defaults:
  environment: docker        # Local-Docker reproduction is the primary path; flip to modal for horizontal scale.
  env_file: .env
  concurrency: 5
  n_attempts: 3
  max_retries: 2
  trials_root: logs/experiments/main_matrix
  agent_timeout_multiplier: 2
  modal:
    profile: chi-bench
    sandbox_timeout_secs: 86400
    force_build: false

domains:
  pa_provider:
    dataset: ${CHI_BENCH_DATA_DIR}/prior_auth_provider/tasks
    registry_path: ${CHI_BENCH_DATA_DIR}/prior_auth_provider/registry.json
  pa_um:
    dataset: ${CHI_BENCH_DATA_DIR}/prior_auth_um/tasks
    registry_path: ${CHI_BENCH_DATA_DIR}/prior_auth_um/registry.json
  cm:
    dataset: ${CHI_BENCH_DATA_DIR}/care_management/tasks
    registry_path: ${CHI_BENCH_DATA_DIR}/care_management/registry.json

key_groups:
  claude-code:
    required_keys: [ANTHROPIC_API_KEY]
  codex:
    required_keys: [OPENAI_API_KEY]
  gemini-cli:
    required_keys: [GEMINI_API_KEY]
  openclaw:
    required_keys: [OPENROUTER_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY]   # OpenClaw rows include closed-source models too
  hermes:
    required_keys: [OPENROUTER_API_KEY]
  deepagents:
    required_keys: [OPENROUTER_API_KEY]
  openai-agents:
    required_keys: [OPENROUTER_API_KEY]

rows:
  # 9 proprietary rows
  - {agent: claude-code, model: anthropic/claude-opus-4-7,    key_group: claude-code}
  - {agent: claude-code, model: anthropic/claude-opus-4-6,    key_group: claude-code}   # was missing in upstream curated25_full_matrix.yaml
  - {agent: claude-code, model: anthropic/claude-sonnet-4-6,  key_group: claude-code}
  - {agent: claude-code, model: anthropic/claude-haiku-4-5,   key_group: claude-code}
  - {agent: codex,       model: openai/gpt-5.5,               key_group: codex}
  - {agent: codex,       model: openai/gpt-5.4,               key_group: codex}
  - {agent: codex,       model: openai/gpt-5.4-mini,          key_group: codex}
  - {agent: gemini-cli,  model: gemini/gemini-3-pro-preview,  key_group: gemini-cli}
  - {agent: gemini-cli,  model: gemini/gemini-3-flash-preview, key_group: gemini-cli}

  # 6 OpenClaw rows (5 OpenRouter open-weight + 1 closed-source via Anthropic direct)
  - {agent: openclaw, model: anthropic/claude-opus-4-7,                   key_group: openclaw}    # was in curated25_openclaw_first_party.yaml
  - {agent: openclaw, model: openrouter/deepseek/deepseek-v4-pro,         key_group: openclaw}
  - {agent: openclaw, model: openrouter/z-ai/glm-5.1,                     key_group: openclaw}
  - {agent: openclaw, model: openrouter/moonshotai/kimi-k2.6,             key_group: openclaw}
  - {agent: openclaw, model: openrouter/qwen/qwen3.6-max-preview,         key_group: openclaw}
  - {agent: openclaw, model: openrouter/x-ai/grok-4.3,                    key_group: openclaw}

  # 5 Hermes rows
  - {agent: hermes, model: openrouter/deepseek/deepseek-v4-pro,           key_group: hermes}
  - {agent: hermes, model: openrouter/z-ai/glm-5.1,                       key_group: hermes}
  - {agent: hermes, model: openrouter/moonshotai/kimi-k2.6,               key_group: hermes}
  - {agent: hermes, model: openrouter/qwen/qwen3.6-max-preview,           key_group: hermes}
  - {agent: hermes, model: openrouter/x-ai/grok-4.3,                      key_group: hermes}

  # 5 DeepAgents rows
  - {agent: deepagents, model: openrouter/deepseek/deepseek-v4-pro,       key_group: deepagents}
  - {agent: deepagents, model: openrouter/z-ai/glm-5.1,                   key_group: deepagents}
  - {agent: deepagents, model: openrouter/moonshotai/kimi-k2.6,           key_group: deepagents}
  - {agent: deepagents, model: openrouter/qwen/qwen3.6-max-preview,       key_group: deepagents}
  - {agent: deepagents, model: openrouter/x-ai/grok-4.3,                  key_group: deepagents}

  # 5 OAI Agents rows
  - {agent: openai-agents, model: deepseek/deepseek-v4-pro,               key_group: openai-agents}
  - {agent: openai-agents, model: z-ai/glm-5.1,                           key_group: openai-agents}
  - {agent: openai-agents, model: moonshotai/kimi-k2.6,                   key_group: openai-agents}
  - {agent: openai-agents, model: qwen/qwen3.6-max-preview,               key_group: openai-agents}
  - {agent: openai-agents, model: x-ai/grok-4.3,                          key_group: openai-agents}
```

- [ ] **Step 3: Sanity check the row count**

Run: `python -c "import yaml; print(len(yaml.safe_load(open('configs/experiments/main_matrix.yaml'))['rows']))"`
Expected: `30`.

- [ ] **Step 4: Commit**

```bash
git add configs/experiments/main_matrix.yaml
git commit -m "feat: ship 30-row main_matrix.yaml reproducing paper Table 1 (Phase 4.1)"
```

---

### Task 4.2: Build `e2e_pa.yaml` (paper E2E table)

**Files:**
- Read: `actava-bench/configs/experiments/curated25_e2e.yaml`
- Create: `configs/experiments/e2e_pa.yaml`

- [ ] **Step 1: Author the config**

Create `configs/experiments/e2e_pa.yaml`:

```yaml
name: e2e_pa
description: |
  Paper §5.3 "chi-Bench-Arena" — End-to-end (provider-to-payer) two-agent run
  on 23 curated PA E2E tasks. Each task spawns a provider-side agent and a
  payer-side agent that interact via the shared workspace and P2P channels.

  2 (harness, model) rows × 23 tasks × 1 attempt = 46 trials.

defaults:
  environment: docker
  env_file: .env
  concurrency: 2
  n_attempts: 1
  max_retries: 2
  trials_root: logs/experiments/e2e_pa
  modal:
    profile: chi-bench
    sandbox_timeout_secs: 86400

domains:
  e2e:
    dataset: ${CHI_BENCH_DATA_DIR}/prior_auth_e2e/tasks
    registry_path: ${CHI_BENCH_DATA_DIR}/prior_auth_e2e/registry.json

key_groups:
  e2e-closed:
    required_keys: [ANTHROPIC_API_KEY, OPENAI_API_KEY]

rows:
  - {agent: claude-code, model: anthropic/claude-opus-4-7, key_group: e2e-closed}
  - {agent: codex,       model: openai/gpt-5.5,            key_group: e2e-closed}
```

- [ ] **Step 2: Commit**

```bash
git add configs/experiments/e2e_pa.yaml
git commit -m "feat: ship e2e_pa.yaml reproducing paper E2E table (Phase 4.2)"
```

---

### Task 4.3: Build the 6 marathon configs

**Files:**
- Read: `actava-bench/configs/experiments/session_*.yaml` (6 files)
- Create: `configs/experiments/marathon_pa_provider.yaml`, `_pa_um.yaml`, `_cm.yaml` (each merging 2 internal configs into one with 2 rows; we ship 3 files instead of 6)

- [ ] **Step 1: Author `configs/experiments/marathon_pa_um.yaml`**

```yaml
name: marathon_pa_um
description: |
  Paper §5.4 "chi-Bench-Marathon" — single agent session works all 25 PA UM
  tasks back-to-back. Each row produces 1 mega-trial; pass@1 averaged over 3
  independent sessions per the paper. Run this config three times to compute
  pass@1; reuse `--trials-dir` overrides to keep sessions distinct.

  2 (harness, model) rows × 1 mega-task × 1 attempt = 2 mega-trials per session.

defaults:
  environment: docker
  env_file: .env
  concurrency: 1                     # one mega-trial at a time per row
  n_attempts: 1
  max_retries: 1
  trials_root: logs/experiments/marathon_pa_um
  agent_timeout_multiplier: 25       # 25 tasks in series; cap is 25 × 1800s

domains:
  pa_um_session:
    dataset: ${CHI_BENCH_DATA_DIR}/single_session/prior_auth_um
    registry_path: null

key_groups:
  marathon:
    required_keys: [ANTHROPIC_API_KEY, OPENAI_API_KEY]

rows:
  - {agent: claude-code, model: anthropic/claude-opus-4-7, key_group: marathon}
  - {agent: codex,       model: openai/gpt-5.5,            key_group: marathon}
```

- [ ] **Step 2: Author `configs/experiments/marathon_pa_provider.yaml`**

Same structure, replacing the domain block with:
```yaml
domains:
  pa_provider_session:
    dataset: ${CHI_BENCH_DATA_DIR}/single_session/prior_auth_provider
    registry_path: null
```
and `trials_root: logs/experiments/marathon_pa_provider`, `name: marathon_pa_provider`.

- [ ] **Step 3: Author `configs/experiments/marathon_cm.yaml`**

Same structure, with:
```yaml
domains:
  cm_session:
    dataset: ${CHI_BENCH_DATA_DIR}/single_session/care_management
    registry_path: null
```
and `name: marathon_cm`, `trials_root: logs/experiments/marathon_cm`.

- [ ] **Step 4: Commit**

```bash
git add configs/experiments/marathon_pa_um.yaml configs/experiments/marathon_pa_provider.yaml configs/experiments/marathon_cm.yaml
git commit -m "feat: ship 3 marathon configs reproducing paper Marathon table (Phase 4.3)"
```

---

### Task 4.4: Build `skill_ablation.yaml`

**Files:**
- Read: `actava-bench/configs/experiments/curated25_skill_ablation.yaml`, `_no_medical_*`, `_no_subbook_*`
- Create: `configs/experiments/skill_ablation.yaml`

- [ ] **Step 1: Author the merged config**

The internal repo has three ablation variants (full, no_medical, no_subbook). The paper appendix C reports a single skill-ablation table. Ship one config that covers the variant the paper reports — confirm by running `git log -p --all -- chi_bench_neurips_2026/sections/appendix_failure_analysis.tex` (or equivalent) for the specific variant cited. **Default assumption: the "full ablation" variant where both the domain sub-book and the medical-library sub-book are removed simultaneously.** Document this assumption in the config description; if Step 0.3-equivalent reading clarifies otherwise, swap the `skill_ablation:` arrays.

```yaml
name: skill_ablation
description: |
  Paper appendix C handbook skill ablation — repeats the main-matrix setup with the
  domain-specific handbook sub-book and the cross-domain medical-library sub-book
  blanked out at sandbox startup. Two strongest closed-source rows only.

  2 (harness, model) rows × 75 tasks × 1 attempt = 150 trials.

defaults:
  environment: docker
  env_file: .env
  concurrency: 5
  n_attempts: 1
  max_retries: 2
  trials_root: logs/experiments/skill_ablation
  modal:
    profile: chi-bench
    sandbox_timeout_secs: 86400
    force_build: true            # ablation reshapes container env at startup

domains:
  pa_provider:
    dataset: ${CHI_BENCH_DATA_DIR}/prior_auth_provider/tasks
    registry_path: ${CHI_BENCH_DATA_DIR}/prior_auth_provider/registry.json
    skill_ablation: [provider-pa, medical-library]
  pa_um:
    dataset: ${CHI_BENCH_DATA_DIR}/prior_auth_um/tasks
    registry_path: ${CHI_BENCH_DATA_DIR}/prior_auth_um/registry.json
    skill_ablation: [payer-um, medical-library]
  cm:
    dataset: ${CHI_BENCH_DATA_DIR}/care_management/tasks
    registry_path: ${CHI_BENCH_DATA_DIR}/care_management/registry.json
    skill_ablation: [care-manager, medical-library]

key_groups:
  ablation:
    required_keys: [ANTHROPIC_API_KEY, OPENAI_API_KEY]

rows:
  - {agent: claude-code, model: anthropic/claude-opus-4-7, key_group: ablation}
  - {agent: codex,       model: openai/gpt-5.5,            key_group: ablation}
```

- [ ] **Step 2: Commit**

```bash
git add configs/experiments/skill_ablation.yaml
git commit -m "feat: ship skill_ablation.yaml reproducing paper appendix C ablation (Phase 4.4)"
```

---

### Task 4.5: Build `cli_tools_ablation.yaml`

**Files:**
- Read: `actava-bench/configs/experiments/curated25_cli_tools.yaml`
- Read: `actava-bench/src/healthverse/experiment/agents/claude_code_cli_harness.py`, `codex_cli_harness.py` (these were copied in Phase 2.1; they exist under `chi_bench/experiment/agents/` now)
- Create: `configs/experiments/cli_tools_ablation.yaml`

- [ ] **Step 1: Confirm the CLI harnesses survived the prune**

Run: `ls src/chi_bench/experiment/agents/ | grep -E 'cli_harness|cli_tools'`
Expected: `claude_code_cli_harness.py`, `codex_cli_harness.py`, `cli_tools_common.py`. If any are missing, recover from `actava-bench/src/healthverse/experiment/agents/` and re-rename per Phase 3.

- [ ] **Step 2: Author the config**

```yaml
name: cli_tools_ablation
description: |
  Paper appendix C MCP-vs-CLI ablation — repeats the main-matrix setup but exposes
  the role-scoped MCP tools as `mcporter` CLI subcommands instead of native MCP
  protocol. Two strongest closed-source rows only.

  2 (harness, model) rows × 75 tasks × 1 attempt = 150 trials.

defaults:
  environment: docker
  env_file: .env
  concurrency: 5
  n_attempts: 1
  max_retries: 2
  tool_mode: cli                     # forwarded as CHI_BENCH_TOOL_MODE=cli into the sandbox
  trials_root: logs/experiments/cli_tools_ablation
  modal:
    profile: chi-bench
    sandbox_timeout_secs: 86400

domains:
  pa_provider:
    dataset: ${CHI_BENCH_DATA_DIR}/prior_auth_provider/tasks
    registry_path: ${CHI_BENCH_DATA_DIR}/prior_auth_provider/registry.json
  pa_um:
    dataset: ${CHI_BENCH_DATA_DIR}/prior_auth_um/tasks
    registry_path: ${CHI_BENCH_DATA_DIR}/prior_auth_um/registry.json
  cm:
    dataset: ${CHI_BENCH_DATA_DIR}/care_management/tasks
    registry_path: ${CHI_BENCH_DATA_DIR}/care_management/registry.json

key_groups:
  cli-ablation:
    required_keys: [ANTHROPIC_API_KEY, OPENAI_API_KEY]

rows:
  - {agent: claude-code-cli, model: anthropic/claude-opus-4-7, key_group: cli-ablation, tool_mode: cli}
  - {agent: codex-cli,       model: openai/gpt-5.5,            key_group: cli-ablation, tool_mode: cli}
```

- [ ] **Step 3: Verify the harnesses register**

Run: `uv run python -c "from chi_bench.experiment.agents.claude_code_cli_harness import ClaudeCodeCliHarness; print(ClaudeCodeCliHarness.name())"`
Expected: `claude-code-cli`. Same check for `codex_cli_harness`.

- [ ] **Step 4: Commit**

```bash
git add configs/experiments/cli_tools_ablation.yaml
git commit -m "feat: ship cli_tools_ablation.yaml reproducing paper appendix C MCP-vs-CLI ablation (Phase 4.5)"
```

---

### Task 4.6: Build the 3 smoke configs

**Files:**
- Create: `configs/smoke/smoke_pa_um.yaml`, `smoke_pa_provider.yaml`, `smoke_cm.yaml`

- [ ] **Step 1: Author each smoke config (1 task, 1 trial, claude-code default)**

Create `configs/smoke/smoke_pa_um.yaml`:

```yaml
name: smoke_pa_um
description: |
  1-task plumbing smoke for PA UM. Verifies runner + server + MCP + verifier
  end-to-end. Set CHI_BENCH_JUDGE_DISABLED=1 to skip judge calls; agent defaults
  to `stub` (no LLM) for CI; pass `--agent claude-code` for a real run.

dataset: ${CHI_BENCH_DATA_DIR}/prior_auth_um/tasks
include_task_name:
  - "*_t008_*"                       # one well-known UM task; replace with any small slice
n_tasks: 1
agent: stub
n_attempts: 1
concurrency: 1
trials_dir: logs/experiments/smoke_pa_um
env_file: .env
environment: docker
```

Create `configs/smoke/smoke_pa_provider.yaml` and `configs/smoke/smoke_cm.yaml` with identical structure, swapping the `dataset` and `include_task_name` patterns. For PA provider, pick a `referral-*` task pattern; for CM, pick `cm_*_low_coop_*` or similar known-good slice.

- [ ] **Step 2: Confirm the include_task_name pattern matches exactly one task**

Once Phase 5 is complete and `chi-bench data download` works, run:
```bash
uv run chi-bench experiment list-tasks -f configs/smoke/smoke_pa_um.yaml
```
Expected: 1 task. If 0 or >1, edit the pattern.

- [ ] **Step 3: Commit**

```bash
git add configs/smoke
git commit -m "feat: add 3 smoke configs (1 task per domain) (Phase 4.6)"
```

---

### Task 4.7: Add the `stub` agent harness for CI

**Files:**
- Create: `src/chi_bench/experiment/agents/stub_harness.py`
- Test: `tests/unit/test_stub_harness.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_stub_harness.py`:

```python
"""Stub agent harness must register and produce a deterministic action sequence."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_stub_harness_registers():
    from chi_bench.experiment.agents.stub_harness import StubHarness
    assert StubHarness.name() == "stub"


def test_stub_harness_writes_run_result(tmp_path: Path):
    """`run` must write run_result.json containing input_tokens=0, error=None."""
    from chi_bench.experiment.agents.stub_harness import StubHarness
    h = StubHarness()
    logs_dir = tmp_path / "logs" / "agent"
    logs_dir.mkdir(parents=True)
    h.write_run_artifacts(logs_dir, instruction="hello", trial_seed=42)

    rr = json.loads((logs_dir / "run_result.json").read_text())
    assert rr["input_tokens"] == 0
    assert rr["output_tokens"] == 0
    assert rr["cost_usd"] == 0.0
    assert rr["turns"] == 0
    assert rr["error"] is None
    assert rr["model"] == "stub"
```

- [ ] **Step 2: Run the failing test**

Run: `uv run pytest tests/unit/test_stub_harness.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'chi_bench.experiment.agents.stub_harness'`.

- [ ] **Step 3: Implement the harness**

Create `src/chi_bench/experiment/agents/stub_harness.py`:

```python
"""Stub agent harness for CI smoke testing.

Emits a deterministic, hand-authored action sequence that drives a single
domain task to a verifier-resolvable terminal state without making any LLM
API calls. Used by `tests/smoke/` and the `docker-smoke` CI job. Per the
release spec (§9), this is the entire CI signal for end-to-end behavior;
real-LLM CI is explicitly out of scope.

Action sequences live under ``stub_scripts/`` (relative to this module) and
are keyed by task domain. The harness loads the script matching the task's
``HEALTHVERSE_TASK_ID`` (now ``CHI_BENCH_TASK_ID``) prefix and replays it
turn-by-turn through the standard MCP client interface.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# NOTE: This is a SKELETON. The actual integration with Harbor's
# BaseInstalledAgent lives in the cousin harnesses (e.g. claude_code_harness.py)
# and is followed verbatim — see docs/adding-an-agent-harness.md once Phase 7
# lands. The minimum surface this stub needs to expose for the CI tests
# in tests/unit/test_stub_harness.py is the four entry points below.


class StubHarness:
    """Harbor-compatible stub agent harness."""

    @staticmethod
    def name() -> str:
        return "stub"

    @staticmethod
    def get_version_command() -> str | None:
        return None

    async def install(self, environment: Any) -> None:
        """No-op — stub has no runtime dependencies."""
        return None

    async def run(self, instruction: str, environment: Any, context: Any) -> None:
        """Replay a scripted action sequence and write run artifacts.

        The actual MCP-call replay logic is environment-specific; this method
        delegates to ``write_run_artifacts`` for the artifact-side contract,
        which is what the CI smoke tests assert on.
        """
        logs_dir = Path("/logs/agent")
        logs_dir.mkdir(parents=True, exist_ok=True)
        self.write_run_artifacts(logs_dir, instruction=instruction, trial_seed=0)

    def write_run_artifacts(
        self, logs_dir: Path, *, instruction: str, trial_seed: int
    ) -> None:
        """Emit the run_result.json + run_log.txt + trace.jsonl artifact set."""
        run_result = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_tokens": 0,
            "cost_usd": 0.0,
            "turns": 0,
            "final_output": "stub harness completed",
            "model": "stub",
            "error": None,
        }
        (logs_dir / "run_result.json").write_text(json.dumps(run_result, indent=2))
        (logs_dir / "run_log.txt").write_text(
            f"stub-harness seed={trial_seed} bytes={len(instruction)}\n"
        )
        (logs_dir / "trace.jsonl").write_text("")  # intentionally empty
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/unit/test_stub_harness.py -v`
Expected: PASS.

- [ ] **Step 5: Register the harness in the agent factory**

Open `src/chi_bench/experiment/agents/__init__.py`. The internal `actava-bench` factory likely has an `AGENT_REGISTRY` dict. Add:

```python
from chi_bench.experiment.agents.stub_harness import StubHarness
AGENT_REGISTRY["stub"] = StubHarness
```

- [ ] **Step 6: Smoke test the registration**

Run: `uv run python -c "from chi_bench.experiment.agents import AGENT_REGISTRY; print(list(AGENT_REGISTRY))"`
Expected: list contains `"stub"`.

- [ ] **Step 7: Commit**

```bash
git add src/chi_bench/experiment/agents/stub_harness.py src/chi_bench/experiment/agents/__init__.py tests/unit/test_stub_harness.py
git commit -m "feat: add stub agent harness for CI smoke testing (Phase 4.7)"
```

---

### Task 4.8: Rewrite the `Makefile`

**Files:**
- Modify (overwrite): `Makefile`

- [ ] **Step 1: Replace the file with public-only targets**

Overwrite `Makefile`:

```makefile
.PHONY: install lint test smoke data clean

install:
	uv sync --extra dev

lint:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

format:
	uv run ruff check src/ tests/ --fix
	uv run ruff format src/ tests/

test:
	uv run pytest tests/unit tests/contract -q

smoke:
	uv run pytest tests/smoke -q

data:
	uv run chi-bench data download

clean:
	rm -rf logs/ dist/ build/ .pytest_cache/ .ruff_cache/
```

- [ ] **Step 2: Commit**

```bash
git add Makefile
git commit -m "chore: rewrite Makefile with public-only targets (Phase 4.8)"
```

---

### Task 4.9: Rewrite `.env.example`

**Files:**
- Create (overwrite if exists): `.env.example`

- [ ] **Step 1: Write the file**

Create `.env.example`:

```bash
# chi-Bench environment template — copy to .env and fill in values.

# ─── Provider API keys (required for paper-aligned reproduction) ────────────
# - ANTHROPIC_API_KEY: Claude Code rows + WorkspaceJudge (always required for the judge).
# - OPENAI_API_KEY:    Codex rows.
# - GEMINI_API_KEY:    Gemini CLI rows.
# - OPENROUTER_API_KEY: OpenClaw, Hermes, OAI Agents, DeepAgents (open-weight models).
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GEMINI_API_KEY=
OPENROUTER_API_KEY=

# Optional alternative judge auth (one of ANTHROPIC_API_KEY / CLAUDE_CODE_OAUTH_TOKEN must be set).
# CLAUDE_CODE_OAUTH_TOKEN=

# ─── chi-Bench runtime knobs (all optional) ────────────────────────────────
# Override the dataset cache directory (default: ~/.cache/chi-bench/data).
# CHI_BENCH_DATA_DIR=

# Override the workspace judge model (default: claude-opus-4-7).
# CHI_BENCH_JUDGE_MODEL=claude-opus-4-7

# Number of independent judge votes per rubric, strict-majority aggregated (default: 1).
# Paper uses CHI_BENCH_JUDGE_NUM_VOTES=3.
# CHI_BENCH_JUDGE_NUM_VOTES=3

# Per-judge wall-clock cap in seconds (default: 900; paper §D.3 uses 1200).
# CHI_BENCH_JUDGE_TIMEOUT_S=1200

# Tool exposure mode: 'mcp' (default) or 'cli' (mcporter-bridged).
# CHI_BENCH_TOOL_MODE=mcp

# Comma-separated handbook sub-book names to ablate (Modal only).
# CHI_BENCH_SKILLS_ABLATE=provider-pa,medical-library

# Disable judge dispatch entirely (smoke / plumbing only — DO NOT use for paper-comparable runs).
# CHI_BENCH_JUDGE_DISABLED=1

# ─── Modal runtime (only if `-e modal` is used) ────────────────────────────
# MODAL_TOKEN_ID=
# MODAL_TOKEN_SECRET=
# Modal profile name (default: chi-bench). Override if you maintain multiple profiles.
# CHI_BENCH_MODAL_PROFILE=chi-bench
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "chore: rewrite .env.example with single-key-per-provider surface (Phase 4.9)"
```

---

### Task 4.10: Update `docker/Dockerfile` and `docker/docker-compose.template.yml`

**Files:**
- Modify: `docker/Dockerfile`
- Modify: `docker/docker-compose.template.yml`

- [ ] **Step 1: Inspect current state**

Run: `cat docker/Dockerfile docker/docker-compose.template.yml`
Expected: files survived Phase 3 with `chi_bench`/`CHI_BENCH_*` namings.

- [ ] **Step 2: Verify post-rename labels and env vars**

Manually confirm:

- `docker/Dockerfile`: `LABEL org.opencontainers.image.source="https://github.com/actava-ai/chi-bench"`, `LABEL org.opencontainers.image.title="chi-bench-server"`. ENV vars use `CHI_BENCH_*`. The `claude-code` CLI install steps (used by the verifier judge) still apply.
- `docker/docker-compose.template.yml`: service name `chi-bench-server`, optional `chi-bench-judge`, mount `fixtures/judge/` into the verifier service. Health check `start_period: 90s`. Env-var substitutions use `${ANTHROPIC_API_KEY:-}`, `${OPENAI_API_KEY:-}`, `${GEMINI_API_KEY:-}`, `${OPENROUTER_API_KEY:-}`, `${CLAUDE_CODE_OAUTH_TOKEN:-}`.

Patch any drift.

- [ ] **Step 3: Commit any patches**

```bash
git add docker/
git diff --cached --quiet || git commit -m "chore: align docker templates with chi-bench naming (Phase 4.10)"
```

---

## Phase 5: HF Dataset Wiring (1–2 days)

### Task 5.1: Implement `chi-bench data download`

**Files:**
- Create: `src/chi_bench/cli/data.py` (or extend `src/chi_bench/cli.py` if monolithic)
- Modify: `src/chi_bench/cli.py` (register subcommand)
- Test: `tests/unit/test_cli_data.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_cli_data.py`:

```python
"""`chi-bench data download` resolves CHI_BENCH_DATA_DIR and pulls from HF."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner


def test_data_download_default_cache_dir(tmp_path: Path, monkeypatch):
    """When CHI_BENCH_DATA_DIR is unset, fall back to ~/.cache/chi-bench/data."""
    monkeypatch.delenv("CHI_BENCH_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    from chi_bench.cli.data import resolve_data_dir
    assert resolve_data_dir() == tmp_path / ".cache" / "chi-bench" / "data"


def test_data_download_invokes_hf_snapshot(tmp_path: Path, monkeypatch):
    """The download command calls huggingface_hub.snapshot_download with the right repo."""
    monkeypatch.setenv("CHI_BENCH_DATA_DIR", str(tmp_path / "data"))
    from chi_bench.cli import app
    runner = CliRunner()
    with patch("chi_bench.cli.data.snapshot_download") as mock_dl:
        mock_dl.return_value = str(tmp_path / "data")
        result = runner.invoke(app, ["data", "download"])
        assert result.exit_code == 0
        mock_dl.assert_called_once()
        kwargs = mock_dl.call_args.kwargs
        assert kwargs["repo_id"] == "actava/chi-bench"
        assert kwargs["repo_type"] == "dataset"
        assert kwargs["revision"] == "v1.0.0"
        assert kwargs["local_dir"] == str(tmp_path / "data")
```

- [ ] **Step 2: Run the failing test**

Run: `uv run pytest tests/unit/test_cli_data.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/chi_bench/cli/data.py`**

Create the package directory if needed: `mkdir -p src/chi_bench/cli && touch src/chi_bench/cli/__init__.py`. (If `cli.py` is currently a single file, convert to a package: rename `cli.py` to `cli/__init__.py` and re-export `app` from there. Update any `from chi_bench.cli import app` site-wide — should work without changes.)

Create `src/chi_bench/cli/data.py`:

```python
"""`chi-bench data` CLI subcommands."""
from __future__ import annotations

import os
from pathlib import Path

import typer
from huggingface_hub import snapshot_download

DEFAULT_HF_REPO = "actava/chi-bench"
DEFAULT_HF_REVISION = "v1.0.0"

app = typer.Typer(help="chi-Bench dataset utilities (download, status).")


def resolve_data_dir() -> Path:
    """Return the resolved dataset cache directory.

    Honors $CHI_BENCH_DATA_DIR, falling back to $HOME/.cache/chi-bench/data.
    """
    explicit = os.environ.get("CHI_BENCH_DATA_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".cache" / "chi-bench" / "data"


@app.command("download")
def download(
    revision: str = typer.Option(
        DEFAULT_HF_REVISION, help="Hugging Face dataset revision (tag) to fetch."
    ),
    repo_id: str = typer.Option(
        DEFAULT_HF_REPO, help="Hugging Face dataset repo ID."
    ),
) -> None:
    """Download the chi-Bench dataset snapshot to $CHI_BENCH_DATA_DIR."""
    data_dir = resolve_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    typer.echo(f"Downloading {repo_id}@{revision} to {data_dir} ...")
    local_dir = snapshot_download(
        repo_id=repo_id,
        repo_type="dataset",
        revision=revision,
        local_dir=str(data_dir),
    )
    typer.echo(f"Downloaded to: {local_dir}")


@app.command("status")
def status() -> None:
    """Print the current dataset cache state."""
    data_dir = resolve_data_dir()
    if not data_dir.exists():
        typer.echo(f"No data cache at {data_dir}. Run `chi-bench data download`.")
        raise typer.Exit(code=1)
    domains = ["prior_auth_provider", "prior_auth_um", "care_management",
               "prior_auth_e2e", "single_session", "skills"]
    typer.echo(f"Cache: {data_dir}")
    for d in domains:
        present = "ok" if (data_dir / d).exists() else "MISSING"
        typer.echo(f"  {d}: {present}")
```

- [ ] **Step 4: Wire the subcommand into the main CLI**

In `src/chi_bench/cli/__init__.py`, after the existing `app = typer.Typer()` line, add:

```python
from chi_bench.cli.data import app as data_app
app.add_typer(data_app, name="data")
```

- [ ] **Step 5: Run the test**

Run: `uv run pytest tests/unit/test_cli_data.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/chi_bench/cli/data.py src/chi_bench/cli/__init__.py tests/unit/test_cli_data.py
git commit -m "feat: add chi-bench data download CLI (Phase 5.1)"
```

---

### Task 5.2: Add `${CHI_BENCH_DATA_DIR}` resolver to `experiment/config.py`

**Files:**
- Modify: `src/chi_bench/experiment/config.py`
- Test: `tests/unit/test_experiment_config_data_dir.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_experiment_config_data_dir.py`:

```python
"""ExperimentConfig.from_yaml resolves ${CHI_BENCH_DATA_DIR} in path fields."""
from __future__ import annotations

import os
from pathlib import Path

import yaml


def test_dataset_path_resolves_data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHI_BENCH_DATA_DIR", str(tmp_path / "mydata"))
    cfg = tmp_path / "x.yaml"
    cfg.write_text(yaml.safe_dump({
        "dataset": "${CHI_BENCH_DATA_DIR}/prior_auth_um/tasks",
        "agent": "stub",
    }))

    from chi_bench.experiment.config import ExperimentConfig
    c = ExperimentConfig.from_yaml(cfg)
    assert c.dataset == str(tmp_path / "mydata" / "prior_auth_um" / "tasks")


def test_registry_path_resolves_data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHI_BENCH_DATA_DIR", str(tmp_path / "mydata"))
    cfg = tmp_path / "x.yaml"
    cfg.write_text(yaml.safe_dump({
        "dataset": "${CHI_BENCH_DATA_DIR}/prior_auth_um/tasks",
        "registry_path": "${CHI_BENCH_DATA_DIR}/prior_auth_um/registry.json",
        "agent": "stub",
    }))
    from chi_bench.experiment.config import ExperimentConfig
    c = ExperimentConfig.from_yaml(cfg)
    assert c.registry_path == str(tmp_path / "mydata" / "prior_auth_um" / "registry.json")
```

- [ ] **Step 2: Run the failing test**

Run: `uv run pytest tests/unit/test_experiment_config_data_dir.py -v`
Expected: FAIL — `${CHI_BENCH_DATA_DIR}` is treated as a literal.

- [ ] **Step 3: Update `from_yaml` to resolve env vars in path fields**

Edit `src/chi_bench/experiment/config.py`. Add a helper and rewrite `from_yaml`:

```python
import os
import re
from pathlib import Path

_PATH_FIELDS = {"dataset", "registry_path", "trials_dir", "env_file"}
_ENV_REF_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _expand_env(value: str | None) -> str | None:
    if value is None:
        return None
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        return os.environ.get(name, m.group(0))
    return _ENV_REF_RE.sub(repl, value)


@classmethod
def from_yaml(cls, path: str | Path) -> "ExperimentConfig":
    with open(path) as f:
        data = yaml.safe_load(f)
    for field in _PATH_FIELDS:
        if field in data and isinstance(data[field], str):
            data[field] = _expand_env(data[field])
    return cls(**data)
```

(Replace the existing `from_yaml` body. The helper goes at module level, above the class.)

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/unit/test_experiment_config_data_dir.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chi_bench/experiment/config.py tests/unit/test_experiment_config_data_dir.py
git commit -m "feat: resolve \${CHI_BENCH_DATA_DIR} in ExperimentConfig path fields (Phase 5.2)"
```

---

### Task 5.3: Build `tests/_fixtures/` from the HF dataset

**Files:**
- Create: `scripts/build_test_fixtures.py`
- Output: `tests/_fixtures/` (committed)

- [ ] **Step 1: Author the script**

Create `scripts/build_test_fixtures.py`:

```python
"""Build the offline test-fixture tree under tests/_fixtures/.

Source: the published HF dataset at actava/chi-bench@v1.0.0. Output:
- tests/_fixtures/prior_auth_um/tasks/<one-task>/        (full task dir)
- tests/_fixtures/prior_auth_provider/tasks/<one-task>/
- tests/_fixtures/care_management/tasks/<one-task>/
- tests/_fixtures/skills/                                (handbook minimal slice)

Run: uv run python scripts/build_test_fixtures.py
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_ROOT = REPO_ROOT / "tests" / "_fixtures"
SAMPLE_TASKS = {
    "prior_auth_um": "pa_t008_t008_o002_p01_mdreview_payer",       # representative UM
    "prior_auth_provider": "referral-mri-brain-without-contrast",   # representative PA-provider
    "care_management": "cm_asthma_low_coop_001",                    # representative CM
}

def main() -> None:
    if FIXTURES_ROOT.exists():
        shutil.rmtree(FIXTURES_ROOT)
    FIXTURES_ROOT.mkdir(parents=True)

    # Use huggingface-cli to download a single task at a time (cheaper than full snapshot).
    for domain, task_id in SAMPLE_TASKS.items():
        target = FIXTURES_ROOT / domain / "tasks" / task_id
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "huggingface-cli", "download", "actava/chi-bench",
                f"{domain}/tasks/{task_id}/",
                "--repo-type", "dataset",
                "--revision", "v1.0.0",
                "--local-dir", str(FIXTURES_ROOT),
            ],
            check=True,
        )

    # Pull the smallest handbook sub-book (typically `platform/`) for skill-load testing.
    subprocess.run(
        [
            "huggingface-cli", "download", "actava/chi-bench",
            "skills/managed-care-operations-handbook/references/platform/",
            "--repo-type", "dataset",
            "--revision", "v1.0.0",
            "--local-dir", str(FIXTURES_ROOT),
        ],
        check=True,
    )

    total = sum(1 for _ in FIXTURES_ROOT.rglob("*") if _.is_file())
    print(f"Built {total} fixture files in {FIXTURES_ROOT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the script (one-time, requires HF auth if dataset is private)**

Run:
```bash
huggingface-cli login   # if not already authenticated
uv run python scripts/build_test_fixtures.py
```
Expected: `Built <N> fixture files in tests/_fixtures`. N should be in the low hundreds.

- [ ] **Step 3: Verify size**

Run: `du -sh tests/_fixtures/`
Expected: under 10MB. If significantly larger, prune `skills/` further.

- [ ] **Step 4: Commit fixtures and the script**

```bash
git add scripts/build_test_fixtures.py tests/_fixtures
git commit -m "feat: bake offline test fixtures from HF dataset v1.0.0 (Phase 5.3)"
```

---

### Task 5.4: Add HF dataset auto-fetch in `experiment/runner.py`

**Files:**
- Modify: `src/chi_bench/experiment/runner.py`
- Test: `tests/unit/test_runner_data_fetch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_runner_data_fetch.py`:

```python
"""Runner auto-downloads dataset on first run if cache is empty."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


def test_runner_invokes_download_when_data_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHI_BENCH_DATA_DIR", str(tmp_path))
    # CHI_BENCH_DATA_DIR exists but is empty — should trigger download.
    from chi_bench.experiment.runner import ensure_data_present
    with patch("chi_bench.cli.data.snapshot_download") as mock_dl:
        mock_dl.return_value = str(tmp_path)
        ensure_data_present()
        mock_dl.assert_called_once()


def test_runner_skips_download_when_data_present(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHI_BENCH_DATA_DIR", str(tmp_path))
    (tmp_path / "prior_auth_um").mkdir()
    (tmp_path / "skills").mkdir()
    from chi_bench.experiment.runner import ensure_data_present
    with patch("chi_bench.cli.data.snapshot_download") as mock_dl:
        ensure_data_present()
        mock_dl.assert_not_called()
```

- [ ] **Step 2: Run the failing test**

Run: `uv run pytest tests/unit/test_runner_data_fetch.py -v`
Expected: FAIL — `ensure_data_present` does not exist.

- [ ] **Step 3: Implement the helper**

Add to `src/chi_bench/experiment/runner.py` (top-level, near other module helpers):

```python
def ensure_data_present() -> None:
    """If CHI_BENCH_DATA_DIR is empty, run `chi-bench data download` once."""
    from chi_bench.cli.data import resolve_data_dir, snapshot_download, DEFAULT_HF_REPO, DEFAULT_HF_REVISION

    data_dir = resolve_data_dir()
    if data_dir.exists() and any(data_dir.iterdir()):
        return  # already populated
    data_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=DEFAULT_HF_REPO,
        repo_type="dataset",
        revision=DEFAULT_HF_REVISION,
        local_dir=str(data_dir),
    )
```

Then call `ensure_data_present()` at the very top of `run_experiment` (or whichever function is the CLI entrypoint into the runner).

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/unit/test_runner_data_fetch.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chi_bench/experiment/runner.py tests/unit/test_runner_data_fetch.py
git commit -m "feat: auto-fetch dataset on first run if cache empty (Phase 5.4)"
```

---

## Phase 6: Tests Rewrite (3–4 days)

This phase is the long pole. Subdivide into the six R-phases from the spec.

### Task 6.1: R1 — Mechanical rename pass on `tests/`

**Files:** every file under `tests/`

- [ ] **Step 1: Run sed**

Run:
```bash
git ls-files tests | xargs grep -lE 'healthverse|HEALTHVERSE_' 2>/dev/null | \
  xargs sed -i.bak -E 's/healthverse/chi_bench/g; s/HEALTHVERSE_/CHI_BENCH_/g'
find tests -name '*.bak' -delete
```

- [ ] **Step 2: Verify**

Run: `git grep -i healthverse -- tests/`
Expected: 0 hits.

- [ ] **Step 3: Commit**

```bash
git add tests
git commit -m "refactor: rename healthverse → chi_bench in tests/ (Phase 6.1)"
```

---

### Task 6.2: R2 — Drop tests for dropped modules

**Files:** delete obsolete tests.

- [ ] **Step 1: Identify and delete test files referencing dropped modules**

Run:
```bash
# Tests importing from synth/seeding/voice/copilot
git ls-files tests | xargs grep -lE 'chi_bench\.synth|chi_bench\.seeding|chi_bench\.conversation\.voice|chi_bench\.copilot' 2>/dev/null > /tmp/tests-to-drop.txt

# Inspect the list
cat /tmp/tests-to-drop.txt

# Delete them
xargs git rm < /tmp/tests-to-drop.txt
```

- [ ] **Step 2: Verify import-time errors are gone**

Run: `uv run pytest tests/ --collect-only -q 2>&1 | head -20`
Expected: collection succeeds without `ModuleNotFoundError: No module named 'chi_bench.synth'`. If errors remain, drop more tests.

- [ ] **Step 3: Commit**

```bash
git diff --cached --quiet || git commit -m "test: drop tests referencing dropped modules (Phase 6.2)"
```

---

### Task 6.3: R3 — Fix `verifier/_compat` references in tests

**Files:** every test file referencing the old `synth` import paths.

- [ ] **Step 1: Find tests still importing from non-existent paths**

Run: `uv run pytest tests/ --collect-only 2>&1 | grep ImportError | head`
Expected: each line names a missing import.

- [ ] **Step 2: Rewrite imports**

For each broken import:
- If the symbol exists in `chi_bench.verifier._compat`: rewrite `from chi_bench.synth.X import Y` → `from chi_bench.verifier._compat import Y`.
- If the symbol does not exist: the test was probably for synth-internal behavior; delete the test (Step 6.2 missed it).

Repeat until collection is clean.

- [ ] **Step 3: Commit**

```bash
git add tests
git commit -m "test: rewrite synth imports to verifier/_compat (Phase 6.3)"
```

---

### Task 6.4: R4 — Fix internal-infra references

**Files:** any test that hard-codes Modal profile names, internal env vars, internal CI fixtures.

- [ ] **Step 1: Find suspect tests**

Run:
```bash
git grep -nE '"actava"|"actava-bench"|HEALTHVERSE_|CHI_BENCH_PRIVATE|/Users/|MODAL_PROFILE.*actava' -- tests/
```

- [ ] **Step 2: Patch each**

Common patterns:

- `assert config.modal.profile == "actava"` → `assert config.modal.profile == "chi-bench"`
- Hard-coded `/Users/<dev>/...` paths → `tmp_path` fixtures
- `os.environ["INTERNAL_FOO"]` → `monkeypatch.setenv("CHI_BENCH_FOO", ...)`

For each surviving Modal-specific test that's load-bearing, ensure it can be skipped when Modal isn't available: add `pytestmark = pytest.mark.skipif(not _modal_available(), reason="modal not installed")`.

- [ ] **Step 3: Commit**

```bash
git add tests
git commit -m "test: replace internal-infra refs with public equivalents (Phase 6.4)"
```

---

### Task 6.5: R5 — Regenerate golden-file fixtures for `tests/contract/`

**Files:**
- Create: `tests/contract/test_verifier_pa_um_golden.py`
- Create: `tests/contract/test_verifier_pa_provider_golden.py`
- Create: `tests/contract/test_verifier_cm_golden.py`
- Create: `tests/contract/goldens/<domain>_<task>.json`
- Create: `tests/contract/conftest.py`
- Modify: `tests/conftest.py` (existing) to add the API-key guard

- [ ] **Step 1: Add the API-key guard in `tests/conftest.py`**

Create or extend `tests/conftest.py`:

```python
"""Test-tree-wide configuration."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_real_api_keys(monkeypatch):
    """Defense-in-depth: clear all provider keys for every test.

    Tests that need to mock a key still can; this fixture only clears them
    so that a test path that accidentally calls a real provider fails.
    """
    for key in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "GEMINI_API_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN",
    ):
        monkeypatch.setenv(key, "")
```

- [ ] **Step 2: Author the verifier-golden test for PA UM**

Create `tests/contract/test_verifier_pa_um_golden.py`:

```python
"""Verifier scoring on a frozen PA UM task slice produces a stable score breakdown."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

FIXTURE_TASK = (
    Path(__file__).parent.parent
    / "_fixtures"
    / "prior_auth_um"
    / "tasks"
    / "pa_t008_t008_o002_p01_mdreview_payer"
)
GOLDEN = Path(__file__).parent / "goldens" / "pa_um_pa_t008.json"


def test_deterministic_scoring_matches_golden():
    from chi_bench.verifier.scoring import score_task_deterministic
    # `score_task_deterministic` is the public scoring entrypoint that does NOT
    # call the workspace judge. It returns a dict of per-check fractional scores.
    breakdown = score_task_deterministic(FIXTURE_TASK)
    expected = json.loads(GOLDEN.read_text())
    assert breakdown == expected


def test_judge_is_skipped_when_disabled(monkeypatch):
    from chi_bench.verifier.judge import workspace_judge as wj
    monkeypatch.setenv("CHI_BENCH_JUDGE_DISABLED", "1")
    with patch.object(wj.WorkspaceJudge, "_spawn_claude_code") as spawn:
        result = wj.WorkspaceJudge(...).run(...)   # construct minimal args from fixtures
        assert result["verdict"] == "skipped"
        spawn.assert_not_called()
```

(The exact arguments to `WorkspaceJudge` need to match its public constructor; copy from any existing internal test once Step 6.4 has stabilized them.)

- [ ] **Step 3: Generate the golden by running once**

Run: `uv run python -c "from chi_bench.verifier.scoring import score_task_deterministic; from pathlib import Path; import json; bd = score_task_deterministic(Path('tests/_fixtures/prior_auth_um/tasks/pa_t008_t008_o002_p01_mdreview_payer')); Path('tests/contract/goldens/pa_um_pa_t008.json').parent.mkdir(parents=True, exist_ok=True); Path('tests/contract/goldens/pa_um_pa_t008.json').write_text(json.dumps(bd, indent=2, sort_keys=True))"`
Expected: golden file written.

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/contract/test_verifier_pa_um_golden.py -v`
Expected: PASS.

- [ ] **Step 5: Repeat Steps 2–4 for `pa_provider` and `cm`**

Two more test files, two more goldens. Same pattern.

- [ ] **Step 6: Commit**

```bash
git add tests/contract tests/conftest.py
git commit -m "test: add verifier golden-file contract tests (Phase 6.5)"
```

---

### Task 6.6: R6 — Write the three smoke tests

**Files:**
- Create: `tests/smoke/test_smoke_pa_um.py`
- Create: `tests/smoke/test_smoke_pa_provider.py`
- Create: `tests/smoke/test_smoke_cm.py`
- Create: `tests/smoke/conftest.py`

- [ ] **Step 1: Author `tests/smoke/conftest.py`**

```python
"""Smoke-tree-wide fixtures."""
from __future__ import annotations

import shutil
import subprocess

import pytest


@pytest.fixture(scope="session")
def docker_available() -> bool:
    return shutil.which("docker") is not None and \
        subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@pytest.fixture(autouse=True)
def _require_docker(docker_available, request):
    if "smoke" in request.keywords and not docker_available:
        pytest.skip("docker not available; skipping smoke")
```

- [ ] **Step 2: Author `tests/smoke/test_smoke_pa_um.py`**

```python
"""End-to-end smoke: stub agent + offline fixture + judge disabled.

Asserts the runner spawns the task container, server boots, MCP tools register,
the stub agent's scripted action sequence drives the task to a terminal state,
and the verifier writes a result.json. Does NOT assert a specific reward — the
stub action set is hand-tuned but reward thresholds drift; the existence of a
written result.json with reward∈{0,1} is the contract.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


pytestmark = pytest.mark.smoke


def test_smoke_pa_um_end_to_end(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHI_BENCH_DATA_DIR", str(Path("tests/_fixtures").resolve()))
    monkeypatch.setenv("CHI_BENCH_JUDGE_DISABLED", "1")

    proc = subprocess.run(
        [
            "uv", "run", "chi-bench", "experiment", "run",
            "-f", "configs/smoke/smoke_pa_um.yaml",
            "--agent", "stub",
            "-n", "1",
            "--trials-dir", str(tmp_path / "trials"),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, f"smoke run failed:\nstdout: {proc.stdout}\nstderr: {proc.stderr}"

    trial_dirs = list((tmp_path / "trials").glob("*"))
    assert len(trial_dirs) == 1
    result_json = trial_dirs[0] / "result.json"
    assert result_json.exists()
    payload = json.loads(result_json.read_text())
    assert payload.get("reward") in (0, 1, 0.0, 1.0)
```

- [ ] **Step 3: Run the test (slow — Docker required)**

Run: `uv run pytest tests/smoke/test_smoke_pa_um.py -v -m smoke`
Expected: PASS within 10 minutes. If FAIL, the `stub` harness's scripted action sequence likely doesn't match the test fixture task's expected tool calls. Iterate the stub action script in `src/chi_bench/experiment/agents/stub_harness.py`.

- [ ] **Step 4: Repeat Steps 2–3 for PA provider and CM**

- [ ] **Step 5: Commit**

```bash
git add tests/smoke
git commit -m "test: add 3 end-to-end smoke tests with stub agent (Phase 6.6)"
```

---

### Task 6.7: Verify the full test suite

- [ ] **Step 1: Run unit + contract (offline)**

Run: `uv run pytest tests/unit tests/contract -q --no-header`
Expected: all PASS, < 5 min.

- [ ] **Step 2: Run smoke (Docker required)**

Run: `uv run pytest tests/smoke -q -m smoke`
Expected: all 3 PASS, < 30 min total.

- [ ] **Step 3: If any failures, fix individually and recommit**

A failing test points at a regression introduced earlier. Fix the test or the implementation, do not skip.

- [ ] **Step 4: Commit clean state if anything changed**

```bash
git diff --cached --quiet || git commit -m "test: stabilize full suite (Phase 6.7)"
```

---

## Phase 7: Docs & Release Engineering (2 days)

### Task 7.1: Author `README.md`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the placeholder with the full README**

Overwrite `README.md` with the structure below. Fill in numbers from paper Table 1 verbatim.

```markdown
# chi-Bench

> A benchmark of long-horizon, policy-rich healthcare workflows for AI agents.

[![CI](https://github.com/actava-ai/chi-bench/actions/workflows/test.yml/badge.svg)](https://github.com/actava-ai/chi-bench/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/chi-bench.svg)](https://pypi.org/project/chi-bench/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

chi-Bench evaluates AI agents on three end-to-end clinical operations workflows: Provider Prior Authorization, Payer Utilization Management, and Care Management. Each task hands the agent a clinical case in a high-fidelity simulator of healthcare apps exposed via MCP tools, which it must drive to a terminal state through tool calls and writing the role's artifacts, guided by a managed-care operations handbook skill.

The benchmark accompanies the paper:
> **chi-Bench: Can AI Agents Automate End-to-End, Long-Horizon, Policy-Rich Healthcare Workflows?** NeurIPS 2026 (E&D track).

## Headline numbers (paper Table 1)

The strongest agent (Claude Code + Claude Opus 4.6) resolves **28.0%** of tasks pass@1; no agent clears **20%** on strict pass^3; running all 25 tasks in a single agent session collapses performance to **3.8%**.

## Quickstart

```bash
# Install (Python 3.12+, Docker)
git clone https://github.com/actava-ai/chi-bench.git
cd chi-bench
uv sync --extra dev

# Provider keys — at minimum, ANTHROPIC_API_KEY for the smoke run.
cp .env.example .env
# Edit .env

# Download the dataset (376 MB, one-time).
uv run chi-bench data download

# Run a smoke trial (~2 min on a laptop).
uv run chi-bench experiment run -f configs/smoke/smoke_pa_um.yaml -n 1
```

## Reproducing paper tables

Every paper table can be reproduced with **local Docker** — no Modal account required. See [docs/reproducing-paper-tables.md](docs/reproducing-paper-tables.md) for exact commands and wall-time/cost estimates per table.

## Adding your own agent

See [docs/adding-an-agent-harness.md](docs/adding-an-agent-harness.md) for the harness contract and worked examples.

## License

- **Code:** [MIT](LICENSE).
- **Dataset:** [CC-BY-4.0](LICENSE-DATA), hosted at [`actava/chi-bench`](https://huggingface.co/datasets/actava/chi-bench) on Hugging Face. (See [ETHICS.md](ETHICS.md) for intended-use boundaries.)

## Citation

```bibtex
@inproceedings{chibench2026,
  title={chi-Bench: Can AI Agents Automate End-to-End, Long-Horizon, Policy-Rich Healthcare Workflows?},
  author={...},  % filled in from CONTRIBUTORS.md
  booktitle={Advances in Neural Information Processing Systems},
  year={2026}
}
```

## Contributors

See [CONTRIBUTORS.md](CONTRIBUTORS.md).
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: ship README.md (Phase 7.1)"
```

---

### Task 7.2: Author `docs/architecture.md`

**Files:**
- Create: `docs/architecture.md`

- [ ] **Step 1: Write the doc**

Open the internal `actava-bench/CLAUDE.md`. Extract the architecture-level content (Source Layout, Database Layer, Case State Machine, App Namespaces, CM Simulation, Hidden Payer Pipeline, Synthesis Pipeline). Drop everything that is internal-process (e.g., "Self-Improvement", "CHANGELOG.md Standards", git workflow). Drop synthesis-pipeline content per Phase 2 cuts.

Create `docs/architecture.md` with these sections (each is 1–3 paragraphs; 8–10 KB total):

1. **What runs inside a task container** — Harbor brings up `chi-bench-server` (FastAPI), three MCP servers (provider/payer/CM), the agent, and the verifier. Diagram of the data flow.
2. **PA case state machine** — copy from CLAUDE.md.
3. **CM case state machine** — copy from CLAUDE.md.
4. **App namespaces** — provider, payer, CM tool families.
5. **WorldStore three-database split** — provider_world, payer_hidden, audit. Why three.
6. **The 6-stage payer pipeline** — intake → triage → nurse → MD → determination → outbound letter.
7. **Verifier scoring contract** — `R = DeterministicPass ∧ JudgePass`. Pointers to `docs/judge.md`.
8. **Source layout** — what lives where in `src/chi_bench/`.

- [ ] **Step 2: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: ship architecture.md (Phase 7.2)"
```

---

### Task 7.3: Author `docs/reproducing-paper-tables.md`

**Files:**
- Create: `docs/reproducing-paper-tables.md`

- [ ] **Step 1: Write the doc with per-table command tables**

Per the spec §8 (revised), the doc must have a table per paper claim with Docker (primary) and Modal (optional) commands.

Create `docs/reproducing-paper-tables.md`:

```markdown
# Reproducing Paper Tables

All paper tables can be reproduced on local Docker. Modal is supported as an optional accelerator for users with a paid Modal account; commands below show both.

## Required credentials

| Paper claim | Required keys |
|---|---|
| Table 1 (main matrix) | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY` |
| E2E PA table | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` |
| Marathon table | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` |
| Skill ablation | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` |
| CLI tools ablation | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` |

## Commands per paper claim

| Paper claim | Docker (primary) | Modal (optional) |
|---|---|---|
| **Table 1: 30 cells × 75 tasks × 3 trials = 6,750 trials** | `chi-bench experiment run -f configs/experiments/main_matrix.yaml -e docker` | `chi-bench experiment run -f configs/experiments/main_matrix.yaml -e modal --modal-profile chi-bench` |
| **E2E PA: 2 cells × 23 tasks × 1 trial = 46 trials** | `chi-bench experiment run -f configs/experiments/e2e_pa.yaml -e docker` | `... -e modal ...` |
| **Marathon × 3 domains: 6 mega-trials × 3 sessions = 18 mega-trials** | `for cfg in marathon_pa_um marathon_pa_provider marathon_cm; do for s in 1 2 3; do chi-bench experiment run -f configs/experiments/$cfg.yaml -e docker --trials-dir logs/marathon/$cfg/session$s; done; done` | swap `-e docker` for `-e modal` |
| **Skill ablation: 2 cells × 75 tasks × 1 trial = 150 trials** | `chi-bench experiment run -f configs/experiments/skill_ablation.yaml -e docker` | `... -e modal ...` |
| **CLI tools ablation: 2 cells × 75 tasks × 1 trial = 150 trials** | `chi-bench experiment run -f configs/experiments/cli_tools_ablation.yaml -e docker` | `... -e modal ...` |

## Wall-time and cost expectations

Filled in during Phase 8 from a maintainer measurement on real hardware. Placeholder estimates:

| Table | Docker (1× workstation, M2 Pro 12-core) | Modal (concurrency 30) | Approx total cost (judge + agent) |
|---|---|---|---|
| Table 1 | ~weeks (impractical for full matrix) | ~24h | $4,000–$6,000 |
| E2E PA | ~6h | ~1h | $50 |
| Marathon × 3 sessions | ~12h | ~4h | $80 |
| Skill ablation | ~24h | ~6h | $150 |
| CLI tools ablation | ~24h | ~6h | $200 |

For Table 1, we recommend Modal unless you only need a per-domain or per-harness slice; pass `--key-group <name>` to the matrix runner to filter by harness.

## Aggregating results

```bash
python scripts/aggregate_results.py \
  --trials-dir logs/experiments/main_matrix \
  --out results/table1.csv
```

The aggregator computes pass@1, pass@3, and pass^3 per (harness, model, domain) cell using the binomial formulas from paper appendix D.2.
```

- [ ] **Step 2: Commit**

```bash
git add docs/reproducing-paper-tables.md
git commit -m "docs: ship reproducing-paper-tables.md (Phase 7.3)"
```

---

### Task 7.4: Author `docs/adding-an-agent-harness.md`

**Files:**
- Create: `docs/adding-an-agent-harness.md`

- [ ] **Step 1: Lift content from internal CLAUDE.md**

Open `actava-bench/CLAUDE.md` "Adding a Custom Agent Harness" section. Copy verbatim into `docs/adding-an-agent-harness.md`, then:

- Replace internal pointers (`actava-bench/`, `healthverse`, internal env-var names) with the OSS equivalents.
- Drop "Where to look for prior art" pointers to internal files; replace with the OSS in-tree harness file paths.
- Add a leading paragraph: "This guide walks through adding a new agent harness — a thin Harbor adapter that integrates an external agent runtime (CLI, SDK, langgraph dev server) with the chi-Bench task containers. We ship eight harnesses you can copy from..."

- [ ] **Step 2: Commit**

```bash
git add docs/adding-an-agent-harness.md
git commit -m "docs: ship adding-an-agent-harness.md (Phase 7.4)"
```

---

### Task 7.5: Author `docs/judge.md`

**Files:**
- Create: `docs/judge.md`

- [ ] **Step 1: Write the doc**

Per the spec §8 — what the workspace judge does, contract families, override knobs, kappa numbers from the paper.

Create `docs/judge.md`:

```markdown
# WorkspaceJudge

LLM-rubric scoring is performed by a workspace judge that spawns a `claude-code` CLI session per task in the verifier container. The judge model and its budgets are documented in paper appendix D.3.

## Contract families

| Contract | Used by | Scoring surface |
|---|---|---|
| `contract_v3` | PA UM payer-side, E2E payer leg | Nurse / MD / P2P rubrics |
| `contract_v4` | PA provider-side (with `provider_request_package` stage) | Submission packet rubrics |
| `contract_v5` | PA provider-side `new_referral` tasks | Chart consistency + submission coherence rubrics; rubric data baked into `fixtures/expectations.json` at HF publish time |
| `cm_v1` / `cm_v2` | CM tasks | Outreach + assessment + care-plan rubrics |

## Configuration

| Env var | Default | Effect |
|---|---|---|
| `CHI_BENCH_JUDGE_MODEL` | `claude-opus-4-7` | Model passed to the spawned `claude-code` CLI |
| `CHI_BENCH_JUDGE_NUM_VOTES` | `1` | Independent vote sessions per rubric; majority vote, ties = fail. Paper uses **3** |
| `CHI_BENCH_JUDGE_TIMEOUT_S` | `900` | Per-judge wall-clock cap. Paper uses **1200** |
| `CHI_BENCH_JUDGE_DISABLED` | unset | If set to `1`, skip judge dispatch and emit `{"verdict": "skipped"}`. CI / plumbing only |

## Reliability (paper appendix D.4)

Cohen's κ across V=3 votes per rubric, averaged within-rubric then across-rubric within domain:

- PA UM: κ ≈ ...
- PA Provider: κ ≈ ...
- CM: κ ≈ ...

(Fill in from paper Table 4 / `tables/judge_kappa.tex` once available.)

## Cost expectations

At Anthropic Opus 4.7 list rates and the paper's V=3 / 1200s settings, judge cost is approximately $0.30–$0.60 per task. Full matrix (30 cells × 75 tasks × 3 trials × ~1 judge invocation per trial ≈ 6,750 invocations) runs ~$2,000.
```

- [ ] **Step 2: Commit**

```bash
git add docs/judge.md
git commit -m "docs: ship judge.md (Phase 7.5)"
```

---

### Task 7.6: Author `docs/dataset.md`, `ETHICS.md`, `CONTRIBUTORS.md`, `CITATION.cff`

- [ ] **Step 1: `docs/dataset.md`**

Document task structure (`task.toml`, `instruction.md`, `fixtures/`, `tests/`), the FHIR-flavored format, what's in the handbook skill, link to the HF dataset card, and how to inspect a task locally without running it.

- [ ] **Step 2: `ETHICS.md`**

One page. Lift from `chi_bench_neurips_2026/sections/appendix_ethics.tex` and the `appendix_environment_detail.tex` provenance section. Cover: synthetic data only, no PHI, intended for evaluation research, do not use for clinical decisions, OWASP-style misuse statement.

- [ ] **Step 3: `CONTRIBUTORS.md`**

Copy the author block from `chi_bench_neurips_2026/neurips_2026.tex` lines 138–191. Format as a markdown list with affiliation footnotes.

- [ ] **Step 4: `CITATION.cff`**

```yaml
cff-version: 1.2.0
title: chi-Bench
message: If you use this benchmark, please cite the paper.
authors:
  - given-names: Haolin
    family-names: Chen
  # ... full author list from neurips_2026.tex
preferred-citation:
  type: conference-paper
  title: "chi-Bench: Can AI Agents Automate End-to-End, Long-Horizon, Policy-Rich Healthcare Workflows?"
  authors:
    - given-names: Haolin
      family-names: Chen
    # ...
  conference:
    name: "Advances in Neural Information Processing Systems"
  year: 2026
```

- [ ] **Step 5: Commit**

```bash
git add docs/dataset.md ETHICS.md CONTRIBUTORS.md CITATION.cff
git commit -m "docs: ship dataset.md, ETHICS.md, CONTRIBUTORS.md, CITATION.cff (Phase 7.6)"
```

---

### Task 7.7: Implement `scripts/audit_release.py`

**Files:**
- Create: `scripts/audit_release.py`
- Create: `tests/unit/test_audit_release.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_audit_release.py`:

```python
"""audit_release.py exits 0 on a clean working tree and non-zero on dirty refs."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_audit_release_clean_repo_passes(tmp_path: Path):
    # Run on the actual repo. If this fails, our own repo is dirty — fix it.
    result = subprocess.run(
        [sys.executable, "scripts/audit_release.py"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"audit failed:\n{result.stdout}\n{result.stderr}"


def test_audit_release_detects_internal_string(tmp_path: Path):
    """Synthesize a file with a forbidden string; audit should flag it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "leaked.py").write_text("# this references HEALTHVERSE_INTERNAL\n")
    subprocess.run(["git", "init"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "x"],
        cwd=repo, check=True,
    )
    # Symlink the audit script into the synthetic repo and run from there.
    audit = (Path(__file__).parent.parent.parent / "scripts" / "audit_release.py").resolve()
    result = subprocess.run([sys.executable, str(audit)], cwd=repo, capture_output=True, text=True)
    assert result.returncode != 0
    assert "HEALTHVERSE_" in result.stdout
```

- [ ] **Step 2: Run the failing test**

Run: `uv run pytest tests/unit/test_audit_release.py -v`
Expected: FAIL — script doesn't exist.

- [ ] **Step 3: Implement the script**

Create `scripts/audit_release.py`:

```python
#!/usr/bin/env python3
"""Pre-release audit: 10 grep checks across the repo working tree.

Exits 0 on a clean repo. Exits 1 with a list of offending file:line entries
if any pattern matches unexpectedly.
"""
from __future__ import annotations

import re
import subprocess
import sys
from typing import Iterable

# Each entry: (label, command-args, expected-zero-hits-condition)
# `condition` is a regex; if a hit's full "file:line:content" matches the regex,
# the hit is whitelisted (e.g., legit "actAVA AI" affiliation).
CHECKS: list[tuple[str, list[str], str | None]] = [
    ("actava (case-insensitive)",
     ["git", "grep", "-i", "actava"],
     r"^(LICENSE|pyproject\.toml|CONTRIBUTORS\.md|.*\.md):.*actava-ai|.*actAVA AI"),
    ("healthverse",
     ["git", "grep", "-i", "healthverse"], None),
    ("healthsynth",
     ["git", "grep", "-i", "healthsynth"], None),
    ("HEALTHVERSE_/HEALTHSYNTH_ env vars",
     ["git", "grep", "-E", "HEALTHVERSE_|HEALTHSYNTH_"], None),
    ("Modal profile leakage",
     ["git", "grep", "-E", "(modal|profile).*actava"], None),
    ("Author email leakage",
     ["git", "grep", "-E", "[A-Za-z][a-zA-Z0-9_.+-]*@(gmail|anthropic|salesforce|stanford|jhu)\\.[a-z]+"], None),
    ("Internal TODO markers",
     ["git", "grep", "-iE", "(todo|fixme|hack|xxx|kludge)\\s*:\\s+actava"], None),
    ("Hard-coded developer paths",
     ["git", "grep", "-E", "/Users/|/home/[a-z]+/"], None),
    ("Real-patient claims",
     ["git", "grep", "-iE", "real (patient|provider|payer|insurer)"], None),
    ("Internal Slack/JIRA references",
     ["git", "grep", "-iE", "actava\\.slack|atlas\\.actava|ACT-[0-9]+"], None),
]


def run_check(label: str, args: list[str], whitelist_re: str | None) -> list[str]:
    """Return offending lines for this check, ignoring whitelisted matches."""
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode == 1 and not proc.stdout.strip():
        return []   # git grep convention: 1 = no matches
    hits = proc.stdout.splitlines()
    if whitelist_re is None:
        return hits
    pat = re.compile(whitelist_re)
    return [h for h in hits if not pat.match(h)]


def main() -> int:
    failures: list[str] = []
    for label, args, wl in CHECKS:
        bad = run_check(label, args, wl)
        if bad:
            failures.append(f"\n[{label}]")
            failures.extend(bad)
    if failures:
        print("AUDIT FAILED:")
        print("\n".join(failures))
        return 1
    print("AUDIT PASSED — no internal references detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Make executable**

Run: `chmod +x scripts/audit_release.py`

- [ ] **Step 5: Run the test**

Run: `uv run pytest tests/unit/test_audit_release.py -v`
Expected: both tests PASS.

- [ ] **Step 6: Run the audit on the actual repo**

Run: `uv run python scripts/audit_release.py`
Expected: `AUDIT PASSED`. If failures, fix them and re-run.

- [ ] **Step 7: Commit**

```bash
git add scripts/audit_release.py tests/unit/test_audit_release.py
git commit -m "feat: add 10-grep release audit script (Phase 7.7)"
```

---

### Task 7.8: Author `scripts/aggregate_results.py`

**Files:**
- Create: `scripts/aggregate_results.py`

- [ ] **Step 1: Implement (lift from `actava-bench/scripts/experiments/aggregate_results.py`)**

Source: `actava-bench/scripts/experiments/aggregate_results.py`. Copy into `scripts/aggregate_results.py`, run the same rename pass (`healthverse → chi_bench` etc.), drop any internal-only flags. The script reads a `--trials-dir` and emits a CSV with pass@1, pass@3, pass^3, mean cost, mean wall-clock per (harness, model, domain) cell using the binomial formulas:

```
pass@k = E[1 - C(n-c,k)/C(n,k)]
pass^k = E[C(c,k)/C(n,k)]
```

with `n=3` trials per task and `c` the per-task pass count.

- [ ] **Step 2: Smoke-test**

Run on the (synthetic) Phase 6 trial output:
```bash
uv run python scripts/aggregate_results.py --trials-dir logs/experiments/smoke_pa_um --out /tmp/out.csv
cat /tmp/out.csv
```
Expected: a CSV with 1 row, sane columns.

- [ ] **Step 3: Commit**

```bash
git add scripts/aggregate_results.py
git commit -m "feat: add aggregate_results.py for paper-table CSV generation (Phase 7.8)"
```

---

### Task 7.9: Wire `.github/workflows/test.yml`

**Files:**
- Create: `.github/workflows/test.yml`

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/test.yml`:

```yaml
name: test

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --extra dev
      - run: uv run ruff check src/ tests/
      - run: uv run ruff format --check src/ tests/

  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --extra dev
      - run: uv run pytest tests/unit tests/contract -q

  import-smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --extra dev
      - run: uv run python -c "import chi_bench; from chi_bench.cli import app; print('ok')"
      - run: uv run chi-bench --help

  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --extra dev
      - run: uv run python scripts/audit_release.py

  docker-smoke:
    runs-on: ubuntu-latest
    needs: [lint, unit, import-smoke, audit]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --extra dev
      - run: uv run pytest tests/smoke -m smoke
        env:
          CHI_BENCH_JUDGE_DISABLED: "1"
          CHI_BENCH_DATA_DIR: ${{ github.workspace }}/tests/_fixtures
```

- [ ] **Step 2: Commit and push**

```bash
git add .github/workflows/test.yml
git commit -m "ci: add lint/unit/import-smoke/audit/docker-smoke jobs (Phase 7.9)"
git push origin main
```

- [ ] **Step 3: Verify CI runs**

Open `https://github.com/actava-ai/chi-bench/actions` and confirm all five jobs go green on the push. If red, fix forward.

---

### Task 7.10: Wire `.github/workflows/release.yml`

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: release

on:
  push:
    tags: ['v*']

jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --extra dev
      - run: uv build
      - run: uv run twine upload dist/*
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
      - uses: softprops/action-gh-release@v2
        with:
          generate_release_notes: true
```

- [ ] **Step 2: Add the `PYPI_API_TOKEN` repo secret**

(Manual via GitHub UI: `Settings → Secrets → Actions → New repository secret`. Generate the token at `pypi.org → Account settings → API tokens` scoped to project `chi-bench`.)

- [ ] **Step 3: Commit and push**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add release workflow for v* tags (Phase 7.10)"
git push origin main
```

---

## Phase 8: Pre-release Human Review & v1.0.0 (1–2 days)

### Task 8.1: File-by-file manual scrub

**Files:** every `*.py` in `src/chi_bench/`, every `*.md`, every `*.yaml` config.

- [ ] **Step 1: Read every Python file once**

Run: `for f in $(git ls-files 'src/chi_bench/**/*.py'); do echo "===== $f ====="; cat "$f" | head -80; done | less`

(Yes, this is slow. Do it anyway.) Look for:

- Internal incident references ("we burned ourselves on X", "after the Q3 outage").
- Legacy migration notes ("after the v2 cutover...", "left in for the May reprocessing job").
- Internal tool / Slack / JIRA references that survived.
- Code paths that conditionally reference Modal profile names like `actava` (Phase 3.4 should have covered these but verify).

For each finding, fix or annotate.

- [ ] **Step 2: Read every markdown doc once**

Same pass over `**/*.md`. Common drift: "(see CHANGELOG)", "talk to <name>", "(internal: see this slack thread)".

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git diff --cached --quiet || git commit -m "chore: pre-release manual review pass (Phase 8.1)"
```

---

### Task 8.2: Reproduction-fidelity smoke run

**Files:** runtime only.

This is the load-bearing validation that chi-bench reproduces actava-bench. Pick **one task per domain** that's also in the internal benchmark logs, run it under chi-bench, and compare per-check verifier output against the actava-bench result.

- [ ] **Step 1: Pick three reference tasks**

For each of `prior_auth_um`, `prior_auth_provider`, `care_management`, pick one task whose Claude Code + Opus 4.7 trial passed in `actava-bench/logs/experiments/curated25_full_matrix/` (or wherever the paper run lives). Record the per-task verifier `result.json` from actava-bench in `/tmp/actava-reference/`.

- [ ] **Step 2: Run the same task three times under chi-bench**

```bash
uv run chi-bench experiment run \
  --dataset $CHI_BENCH_DATA_DIR/prior_auth_um/tasks/<reference-task-id> \
  --agent claude-code --model anthropic/claude-opus-4-7 \
  -e docker -n 3 \
  --trials-dir /tmp/chi-bench-validation/pa_um
```

(Repeat for the other two domains.)

- [ ] **Step 3: Compare verifier output**

For each reference task, diff `chi-bench result.json` (the deterministic-checks portion) against `actava-bench result.json`. Per-check scores should be **identical** for deterministic checks. Judge verdicts may differ slightly across runs (Claude Opus is non-deterministic) but should be majority-aligned.

```bash
jq '.deterministic_checks' /tmp/actava-reference/pa_um/result.json > /tmp/a.json
jq '.deterministic_checks' /tmp/chi-bench-validation/pa_um/<trial-id>/result.json > /tmp/b.json
diff /tmp/a.json /tmp/b.json
```
Expected: empty diff. If non-empty, the verifier or fixture diverged — investigate before tagging.

- [ ] **Step 4: Document the validation run**

Write the results in `docs/reproducing-paper-tables.md` under a "Validation" section: which tasks were run, how the per-check breakdown matched.

- [ ] **Step 5: Commit**

```bash
git add docs/reproducing-paper-tables.md
git commit -m "docs: record reproduction-fidelity validation results (Phase 8.2)"
```

---

### Task 8.3: Tag v1.0.0 and publish

- [ ] **Step 1: Final audit run**

Run: `uv run python scripts/audit_release.py && uv run pytest tests/unit tests/contract`
Expected: both green.

- [ ] **Step 2: Bump version if not already at 1.0.0**

Open `pyproject.toml` and confirm `version = "1.0.0"`.

- [ ] **Step 3: Tag and push**

```bash
git tag -s v1.0.0 -m "chi-Bench v1.0.0 — initial public release accompanying NeurIPS 2026 paper"
git push origin v1.0.0
```

(Drop `-s` if GPG signing isn't set up; warn the user but don't block release.)

- [ ] **Step 4: Watch the release workflow**

Open `https://github.com/actava-ai/chi-bench/actions` and confirm `release` workflow runs and PyPI shows `chi-bench 1.0.0`.

- [ ] **Step 5: Verify install works in a fresh venv**

Run:
```bash
cd /tmp && rm -rf chi-bench-install-check && python -m venv chi-bench-install-check && \
  source chi-bench-install-check/bin/activate && \
  pip install chi-bench==1.0.0 && \
  chi-bench --help
```
Expected: typer help text.

- [ ] **Step 6: Pin the HF dataset tag to v1.0.0**

(Manual on `huggingface.co/datasets/actava/chi-bench → Settings → Tags → Add `v1.0.0`` pointing at the SHA recorded in Task 0.2 step 4.)

- [ ] **Step 7: Uncomment the paper's GitHub URL**

Edit `chi_bench_neurips_2026/neurips_2026.tex` lines 207–210 to uncomment the URL block. (This is in a separate repo; the maintainer does it as the paper's next revision.)

- [ ] **Step 8: Announce**

Post a short release note on the project page / Twitter / Slack. Out of scope for this plan.

---

## Self-review

The following checklist is run inline against the spec at `docs/superpowers/specs/2026-05-07-chi-bench-oss-release-design.md`. Each spec section should be implemented by at least one task above.

| Spec § | Title | Implemented by |
|---|---|---|
| §1 | Goals & non-goals | Phase 0 + Phase 8 (validation) |
| §2 | Release shape | Phase 1 |
| §3 | Code subset & rename | Phase 2, Phase 3 |
| §4 | Datasets | Phase 0.2, Phase 5 |
| §5 | Configs | Phase 4 |
| §6 | Verifier & judge | Phase 2.3 (`_compat`), Phase 7.5 (docs/judge.md) |
| §7 | Tests | Phase 6 |
| §8 | Documentation | Phase 7.1–7.6 |
| §9 | CI without API keys | Phase 7.9, Phase 7.10 |
| §10 | Pre-release scrubbing | Phase 7.7, Phase 8.1 |
| §11 | Release sequencing | This plan, structurally |

**Placeholder scan:** searched the plan for "TBD", "TODO", "implement later", "fill in details" — found only in Tasks 7.5 (judge κ numbers), 7.6 (CITATION.cff author list), 7.3 (wall-time / cost cells). All three are intentionally fill-in-during-Phase-8 because they need real measurement; flagged as such with explicit pointers to where the data comes from.

**Type consistency:** the function names, env-var names, and config-field names are consistent across tasks (`ensure_data_present`, `resolve_data_dir`, `ExperimentConfig.from_yaml`, `CHI_BENCH_DATA_DIR`, `CHI_BENCH_JUDGE_DISABLED`, `chi-bench data download`, `chi-bench experiment run`).

**Open questions surfaced (Phase 0 must clear):**

1. Handbook license (DUA vs CC-BY-4.0) — Task 0.1.
2. HF dataset already published with rebranded content — Task 0.2.
3. Source of the Claude Code + Opus 4.6 row — Task 0.3.

These three must be resolved before Phase 4 begins.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-07-chi-bench-oss-release-plan.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
