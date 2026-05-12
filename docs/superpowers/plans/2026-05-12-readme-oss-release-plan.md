# README OSS Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `/Users/weiran/Github/chi-bench/README.md` with a restructured ~195-line linear-funnel landing page for the OSS release, serving visitor > submitter > reproducer in that priority order.

**Architecture:** Single-file replacement of `README.md`. Auxiliary tasks: render one figure from PDF to PNG, verify `.env.example` covers the keys the README enumerates, and verify all referenced doc/asset links resolve. Sibling artifacts called out in the spec but not in scope (leaderboard repo, `docs/submission-packet.md`) get explicit fallbacks where the README references them — link with a clear "coming soon" or stub.

**Tech Stack:** Markdown, GitHub-flavored. `pdftoppm` (poppler) for PDF→PNG. Plain `git` for commits. No code dependencies; this is documentation work.

**Spec reference:** `docs/superpowers/specs/2026-05-12-readme-oss-release-design.md`

---

## Pre-flight findings (already gathered, recorded so the implementer doesn't repeat)

- `.env.example` **exists** at repo root. Task 1 inspects it.
- `docs/architecture.md`, `docs/judge.md`, `docs/reproduce.md` **exist**. README links to all three.
- `docs/submission-packet.md` **does not exist**. Task 4, step 6 inlines a brief schema instead of linking to a 404.
- `assets/figures/logo.svg` **exists**.
- `chi-bench-arxiv-submission/figures/main_pass_at_1.pdf` is the teaser figure to render.
- `pdftoppm` is available at `/opt/homebrew/bin/pdftoppm` for PDF→PNG.
- HF dataset gating: unverified at plan time. Task 1 checks; if the dataset is public, drop `HF_TOKEN` from the README.
- Leaderboard repo `actava-ai/chi-bench-leaderboard`: unverified at plan time. Task 1 checks; if missing or empty, Task 4 step 5 swaps the PR-flow instructions for a "submission upload coming with the v1.0 release — watch this repo" stub.

---

## Task 1: Pre-flight verification (no commits)

**Files:** none modified. Output: a written record of findings used by Tasks 2–5.

**Why:** The spec calls out three load-bearing assumptions that the implementer must verify before writing the README: HF dataset gating, leaderboard repo readiness, and `.env.example` coverage. Verifying first prevents writing prose that links to 404s or asks for keys that aren't needed.

- [ ] **Step 1: Read current `.env.example`**

```bash
cat /Users/weiran/Github/chi-bench/.env.example
```

Compare the listed keys against the README's `§3 step 2` enumeration. Required by the README:
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `CLAUDE_CODE_OAUTH_TOKEN`

Optional by the README:
- `OPENROUTER_API_KEY`
- `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`

Record: which of these are present in `.env.example`, which are missing. Findings feed Task 3.

- [ ] **Step 2: Check HF dataset gating**

```bash
curl -sI https://huggingface.co/datasets/actava/chi-bench | head -1
```

If the response is `HTTP/2 200`, the dataset card is public. To confirm files are also public (gating is separate from card visibility):

```bash
curl -sI 'https://huggingface.co/api/datasets/actava/chi-bench' | head -1
```

Record: `public` or `gated`. If gated, README §3 step 2 keeps `HF_TOKEN` in the optional list. If public, README §3 step 2 drops `HF_TOKEN` entirely.

- [ ] **Step 3: Check leaderboard repo readiness**

```bash
curl -sI https://github.com/actava-ai/chi-bench-leaderboard | head -1
```

If `HTTP/2 200`, the repo exists. Then check the PR template:

```bash
curl -sI https://raw.githubusercontent.com/actava-ai/chi-bench-leaderboard/main/.github/PULL_REQUEST_TEMPLATE/submission.md | head -1
```

Record one of three states:
- `repo_ready` — repo exists and PR template exists. README §5 step 4 uses the full PR-flow text from Task 4 step 5.
- `repo_exists_no_template` — repo exists but no template. README §5 step 4 drops the template reference but keeps PR instructions.
- `repo_missing` — repo doesn't exist. README §5 step 4 uses the stub text from Task 4 step 5 (alternate text).

- [ ] **Step 4: Verify referenced docs and assets resolve**

```bash
cd /Users/weiran/Github/chi-bench
for p in docs/architecture.md docs/judge.md docs/reproduce.md \
         configs/experiments/table1_main_matrix.yaml \
         configs/submission_example.yaml \
         configs/prices.yaml \
         scripts/run_table.sh scripts/aggregate.py \
         assets/figures/logo.svg \
         chi-bench-arxiv-submission/sections/approach.tex \
         chi-bench-arxiv-submission/figures/main_pass_at_1.pdf \
         LICENSE; do
  test -e "$p" && echo "OK  $p" || echo "MISS $p"
done
```

Expected: all `OK`. If any is `MISS`, the README cannot link to it as-is; record the gap and adjust Task 4 step 4 / step 6 / step 7 / step 9 to drop or stub the offending link.

- [ ] **Step 5: Sanity-check the headline numbers against the paper**

Verify the four headline numbers used in README §2 are accurate per `chi-bench-arxiv-submission/sections/experiments.tex`:

```bash
grep -E "28\.0|3\.8|0%|pass\^3" /Users/weiran/Github/chi-bench/chi-bench-arxiv-submission/sections/experiments.tex | head -20
```

Confirm: Claude Code + Opus 4.6 = 28.0% pass@1; no agent ≥ 20% pass^3; marathon best = 3.8%; arena best = 0%. These appear verbatim in §2 callout — they must not drift from the paper.

---

## Task 2: Render the teaser figure to PNG

**Files:**
- Create: `assets/figures/main_pass_at_1.png`

**Why:** GitHub-flavored markdown does not inline PDFs. The spec specifies this exact figure as the §2 visual hook. Render at 150 DPI for a sharp ~780-px-wide display.

- [ ] **Step 1: Render PDF → PNG at 150 DPI**

```bash
cd /Users/weiran/Github/chi-bench
pdftoppm -png -r 150 \
  chi-bench-arxiv-submission/figures/main_pass_at_1.pdf \
  assets/figures/main_pass_at_1
# pdftoppm emits assets/figures/main_pass_at_1-1.png — normalize the name:
mv assets/figures/main_pass_at_1-1.png assets/figures/main_pass_at_1.png
```

- [ ] **Step 2: Verify PNG exists and is non-trivial**

```bash
ls -lh /Users/weiran/Github/chi-bench/assets/figures/main_pass_at_1.png
file /Users/weiran/Github/chi-bench/assets/figures/main_pass_at_1.png
```

Expected: file size between 50 KB and 2 MB; `file` reports `PNG image data`. If size is < 10 KB the render likely failed silently — re-run Step 1.

- [ ] **Step 3: Eyeball the image**

Open `assets/figures/main_pass_at_1.png` in the IDE preview or `open` (macOS). Confirm it shows the pass@1 chart with the three domain panels readable. If the image is rotated or cropped, re-run Step 1 with `-r 200` for a denser raster.

- [ ] **Step 4: Commit the asset**

```bash
cd /Users/weiran/Github/chi-bench
git add assets/figures/main_pass_at_1.png
git commit -m "$(cat <<'EOF'
docs: add PNG render of pass@1 teaser figure for README

Rendered from chi-bench-arxiv-submission/figures/main_pass_at_1.pdf via
pdftoppm at 150 DPI. Used as the visual hook in README §2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Patch `.env.example` (conditional)

**Files:**
- Modify (conditional): `/Users/weiran/Github/chi-bench/.env.example`

**Why:** §3 step 2 of the README enumerates the keys the user needs. If `.env.example` is missing any of them, the README's "Copy `.env.example` to `.env` and fill in" instruction breaks. Skip this task entirely if Task 1 Step 1 confirmed all keys are present.

- [ ] **Step 1: Read current `.env.example`**

```bash
cat /Users/weiran/Github/chi-bench/.env.example
```

- [ ] **Step 2: Add only the missing keys**

For each key the README enumerates that is missing from `.env.example`, append a commented entry. Use this format (paste only the lines you need):

```bash
# Required: Anthropic models (Claude Code harness, Anthropic-served rows)
ANTHROPIC_API_KEY=

# Required: OpenAI models (Codex, OAI Agents)
OPENAI_API_KEY=

# Required: workspace judge (the verifier calls Claude)
CLAUDE_CODE_OAUTH_TOKEN=

# Optional: open-weight models served via OpenRouter (Hermes/OpenClaw/OAI Agents/DeepAgents open rows)
OPENROUTER_API_KEY=

# Optional: Modal parallelization (recommended for full submissions + matrix reproduction)
MODAL_TOKEN_ID=
MODAL_TOKEN_SECRET=
```

Apply only the lines for keys that were missing in Step 1.

- [ ] **Step 3: Verify the file**

```bash
cat /Users/weiran/Github/chi-bench/.env.example
```

Confirm: every README-enumerated key now has an entry (commented description + empty value).

- [ ] **Step 4: Commit (only if changes were made)**

```bash
cd /Users/weiran/Github/chi-bench
git add .env.example
git commit -m "$(cat <<'EOF'
chore: backfill .env.example with keys enumerated by README §3

Adds entries for ANTHROPIC_API_KEY, OPENAI_API_KEY,
CLAUDE_CODE_OAUTH_TOKEN, OPENROUTER_API_KEY, MODAL_TOKEN_ID,
MODAL_TOKEN_SECRET — whichever were not already present.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

If Step 2 made no edits, skip the commit and proceed to Task 4.

---

## Task 4: Replace README.md with the new linear-funnel structure

**Files:**
- Modify: `/Users/weiran/Github/chi-bench/README.md` (full rewrite)

**Why:** This is the core deliverable. The plan provides the exact markdown for each section so the implementer does not re-derive prose. Two pre-flight conditional swaps:

1. **If Task 1 Step 2 reported `public`:** drop the `HF_TOKEN` bullet from §3 step 2.
2. **If Task 1 Step 3 reported `repo_missing`:** in §5 step 5, use the **alternate stub** (provided in that step) instead of the full PR-flow text.

- [ ] **Step 1: Open the existing README**

```bash
cat /Users/weiran/Github/chi-bench/README.md | wc -l
```

Confirm current line count is ~164. Backup not needed (git history preserves it).

- [ ] **Step 2: Write the new README in one shot**

Replace the entire contents of `/Users/weiran/Github/chi-bench/README.md` with the markdown below. The block is the complete file from top to bottom. Apply the conditional swaps from the task header before writing.

````markdown
<div align="center">
  <img src="assets/figures/logo.svg" alt="Χ-Bench" width="300"/>
  <h1><b>C</b>linical <b>H</b>ealthcare <b>I</b>n-Situ</h1>
  <p><b>Benchmark for long-horizon, policy-rich healthcare workflow agents.</b></p>
  <p>
    <a href="https://arxiv.org/abs/XXXX.XXXXX"><img src="https://img.shields.io/badge/arXiv-XXXX.XXXXX-b31b1b.svg" alt="arXiv"/></a>
    <a href="https://huggingface.co/datasets/actava/chi-bench"><img src="https://img.shields.io/badge/HF_Dataset-chi--bench-yellow" alt="Dataset"/></a>
    <a href="https://actava-ai.github.io/chi-bench/leaderboard"><img src="https://img.shields.io/badge/Leaderboard-chi--bench-blue" alt="Leaderboard"/></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-purple.svg" alt="License"/></a>
  </p>
</div>

## What this benchmark measures

chi-Bench evaluates AI agents on end-to-end U.S. healthcare workflows across three long-horizon domains: provider prior authorization, payer utilization management, and population care management. Each task hands the agent a clinical case in a high-fidelity simulator of 20 healthcare apps exposed over MCP, with a 1,279-document Managed-Care Operations Handbook skill, and asks it to drive the case to a terminal state through tool calls and artifact authoring.

The benchmark stresses three capabilities under-represented in coding-style agent benchmarks: **policy density** (decisions grounded in a large library of medical, insurance, and operational rules), **multi-role composition** (a single workflow spans clinician, UM nurse, medical director, and care manager handoffs that cannot be re-run), and **multilateral interaction** (some steps are multi-turn dialogs — peer-to-peer review, patient outreach — not tool calls).

> **Headline numbers from the paper:**
> - Best agent (Claude Code + Claude Opus 4.6): **28.0%** overall pass@1
> - No agent clears **20%** on strict pass^3
> - Marathon (all 25 tasks in one session): best is **3.8%**
> - End-to-end provider–payer arena: **0%** on the best PA agents

<p align="center">
  <img src="assets/figures/main_pass_at_1.png" alt="pass@1 across the three chi-Bench environments" width="780"/>
</p>

| Domain | Tasks | What the agent does |
| --- | --- | --- |
| **Prior Authorization — Provider** | 25 | Verify coverage, gather evidence, submit the PA packet, work the response (RFIs, peer-to-peer, appeals) |
| **Prior Authorization — UM (Payer)** | 25 | Intake the request, check plan policy, escalate through nurse and physician reviewers, issue determination |
| **Care Management** | 25 | Review the chart, contact the patient, administer assessments, author a care plan |

## Setup (one-time)

**Prereqs:** Python 3.12+, Docker, [uv](https://github.com/astral-sh/uv).

**1. Clone and install.**

```bash
git clone https://github.com/actava-ai/chi-bench && cd chi-bench
uv sync --extra dev
```

**2. API keys.** Copy `.env.example` to `.env` and fill in:

- `ANTHROPIC_API_KEY` — required for Anthropic-family agent harnesses
- `OPENAI_API_KEY` — required for Codex / OAI Agents
- `CLAUDE_CODE_OAUTH_TOKEN` — required; the workspace judge calls Claude
- `OPENROUTER_API_KEY` — optional, only if running the open-stack agent rows
- `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` — optional, recommended for matrix reproduction (see §"Reproduce paper tables")
- `HF_TOKEN` — only if the HF dataset is gated (skip if not)

**3. Task fixtures from Hugging Face.**

```bash
uv run chi-bench data download --revision chi-bench-v1.0.0
```

The wrapper writes the revision tag to `data/.chi-bench-version`; submission preflight verifies this against your config's `dataset.version`. Use the wrapper rather than raw `huggingface-cli` so the version pin works.

**4. Managed-Care Operations Handbook (Google Drive).**

Download the handbook tarball from: **<GOOGLE_DRIVE_SHARE_URL>**

```bash
mkdir -p data/skills
tar -xzf managed-care-operations-handbook.tar.gz -C data/skills/
```

The handbook (1,279 markdown documents) lives off HF because of size and the curation provenance with clinical collaborators.

**5. Build the Docker image.** (~5 min, one-time)

```bash
uv run chi-bench docker build
```

The image bundles the FastAPI server, the workspace judge, the agent harness, and per-task fixtures.

**Verify setup:**

```bash
uv run chi-bench data verify
```

A clean run means you're ready for the quickstart.

> **Modal (optional, recommended).** Modal parallelizes trials across remote sandboxes. Set it up now and you won't have to later:
>
> ```bash
> uv run modal token set --profile chi-bench
> ```

## Quickstart: run one task

Smoke-test that everything is wired up with a single UM medical-director-review task:

```bash
uv run chi-bench experiment run \
  --dataset data/prior_auth_um/tasks/pa_t008_t008_o002_p01_mdreview_payer \
  --agent codex --model openai/gpt-5.5
```

Trial output lands under `logs/experiments/.../trial_*/`. Read `result.json` for the verifier reward and `verifier/scorecard.json` for per-check verdicts.

If you see a scorecard, you're ready to [submit your agent](#submit-your-agent) or [reproduce the paper tables](#reproduce-paper-tables).

## Submit your agent

Submitting to the [leaderboard](https://actava-ai.github.io/chi-bench/leaderboard) is a four-command flow over one YAML.

**1. Configure.** Copy `configs/submission_example.yaml` to `configs/submissions/<your-id>.yaml` and edit the highlighted fields (`id`, `team`, `contact`, `agent`, `model`; optionally `notes` and `run.*`).

**2. Run the four commands.**

```bash
# Schema + preflight: dataset pin, Modal token / Docker image, agent name.
uv run chi-bench submission validate -f configs/submissions/<your-id>.yaml

# Run all 3 domains. Default: one trial per task (pass@1). Trials land under logs/submissions/<id>/.
uv run chi-bench submission run      -f configs/submissions/<your-id>.yaml

# Check progress; safe to run while `submission run` is in flight.
uv run chi-bench submission status   -f configs/submissions/<your-id>.yaml

# Build the upload-ready zip (~30–50 MB) at logs/submissions/<id>/<id>.zip.
uv run chi-bench submission package  -f configs/submissions/<your-id>.yaml
```

**3. Packet contents.**

```
submission.json     # manifest: agent, model, results, per_domain, provenance
results.csv         # leaderboard row
sub.yaml            # frozen copy of your config
provenance.json     # git SHA, image digest, timestamps
trials/<domain>/<trial_id>/...
    result.json                 # Harbor reward + agent metadata
    verifier/scorecard.json     # per-check verdicts
    verifier/reward.json        # verifier's reward breakdown
    agent/trajectory.json       # full agent message trace
```

Workspace artifacts and Harbor scratch files are deliberately excluded so the zip stays uploadable while remaining sufficient for a human to replay any trial.

**4. Get on the leaderboard.** Open a PR to the leaderboard repo:

1. Fork [`actava-ai/chi-bench-leaderboard`](https://github.com/actava-ai/chi-bench-leaderboard).
2. Add your packet at `submissions/<your-id>/<your-id>.zip` and copy `submission.json` and `results.csv` alongside it (so reviewers can scan the manifest without unpacking).
3. Open a PR using the submission template (`.github/PULL_REQUEST_TEMPLATE/submission.md` in the leaderboard repo). It asks for a contact, a one-line description, and confirmation that you ran against the pinned dataset revision.
4. A maintainer verifies provenance (git SHA + image digest match a public commit and a clean run) and merges. Merged PRs trigger the leaderboard site rebuild; your row appears within ~1 day.

**Policy notes.**

- **Partial submissions** (`--domain pa | um | cm` on `submission run`) are accepted but flagged as partial on the leaderboard.
- **Leaderboard is pass@1 only.** Set `run.n_attempts: 3` to keep extra trials on disk for your own pass@3 / pass^3 analysis — the manifest still publishes pass@1.

## Reproduce paper tables

| Paper | Config | Command |
| --- | --- | --- |
| Table 1 (Main matrix)    | `table1_main_matrix.yaml`    | `./scripts/run_table.sh table1` |
| Table 2 (E2E arena)      | `table2_e2e_arena.yaml`      | `./scripts/run_table.sh table2` |
| Table 3 (Marathon)       | `table3_marathon.yaml`       | `./scripts/run_table.sh table3` |
| Fig. 4 (Skill ablation)  | `table4_skill_ablation.yaml` | `./scripts/run_table.sh table4` |
| Table 5 (MCP vs CLI)     | `table5_mcp_vs_cli.yaml`     | `./scripts/run_table.sh table5` |

After all slices finish, aggregate:

```bash
uv run python scripts/aggregate.py \
  --trials-dir logs/experiments/table1_main_matrix \
  --prices configs/prices.yaml \
  --out-csv logs/table1.csv
```

CSV columns: `agent, model, n_trials, n_tasks, pass_at_1, pass_at_1_lo, pass_at_1_hi, pass_at_3, ..., pass_pow_3, pass_pow_3_hi, mean_cost_usd, mean_walltime_s` with Wilson 95% CIs. v1 emits the numeric tables; paper figures are out of scope — plot from the CSV. See [`docs/reproduce.md`](docs/reproduce.md) for the figure scripts we used.

> Add `--modal` to `run_table.sh` for parallel execution on Modal — matrix reproduction on a single host takes days.

## Supported agents

| `--agent` | Example `--model` | Paper rows |
| --- | --- | --- |
| `claude-code`   | `anthropic/claude-opus-4-7`   | Claude Code |
| `codex`         | `openai/gpt-5.5`              | Codex |
| `gemini-cli`    | `gemini/gemini-3-pro-preview` | Gemini CLI |
| `openclaw`      | `anthropic/claude-opus-4-7`   | OpenClaw |
| `hermes`        | `openrouter/z-ai/glm-5.1`     | Hermes |
| `openai-agents` | `deepseek/deepseek-v4-pro`    | OAI Agents |
| `deepagents`    | `openrouter/x-ai/grok-4.3`    | DeepAgents |

The full 30-row matrix (every model × harness reported in Table 1) lives in [`configs/experiments/table1_main_matrix.yaml`](configs/experiments/table1_main_matrix.yaml).

## Architecture

A single Python package (`chi_bench`) hosts a FastAPI server, three MCP servers (provider :8020, payer :8100, CM :8200), and an LLM-based workspace judge. Each trial runs in a fresh Docker container that bundles the server, the judge, the agent harness, and the per-task fixtures. The Managed-Care Operations Handbook (1,279 markdown documents) is mounted into the agent's skill directory at trial start.

System diagram and module boundaries: [`docs/architecture.md`](docs/architecture.md). Verifier details: [`docs/judge.md`](docs/judge.md). Environment chapter from the paper: [`chi-bench-arxiv-submission/sections/approach.tex`](chi-bench-arxiv-submission/sections/approach.tex).

## Citation

If you use chi-Bench, please cite:

```bibtex
@article{chen2026chibench,
  title   = {chi-Bench: Can AI Agents Automate End-to-End, Long-Horizon, Policy-Rich Healthcare Workflows?},
  author  = {Chen, Haolin and Metelski, Deon and Qi, Leon and others},
  journal = {arXiv preprint arXiv:XXXX.XXXXX},
  year    = {2026}
}
```

## License

Code: Apache-2.0 (see [`LICENSE`](LICENSE)). Data licensing on the [HF dataset card](https://huggingface.co/datasets/actava/chi-bench).
````

- [ ] **Step 3: Apply conditional swap — `HF_TOKEN` (if Task 1 Step 2 = `public`)**

If Task 1 Step 2 reported the HF dataset is public, delete this bullet from §"Setup (one-time)" step 2:

```markdown
- `HF_TOKEN` — only if the HF dataset is gated (skip if not)
```

Leave the rest of the bullet list intact. If Task 1 Step 2 reported `gated`, keep the bullet as written.

- [ ] **Step 4: Apply conditional swap — leaderboard PR flow (if Task 1 Step 3 = `repo_missing`)**

If Task 1 Step 3 reported the leaderboard repo does not exist, replace this entire numbered list under `**4. Get on the leaderboard.**`:

```markdown
1. Fork [`actava-ai/chi-bench-leaderboard`](https://github.com/actava-ai/chi-bench-leaderboard).
2. Add your packet at `submissions/<your-id>/<your-id>.zip` and copy `submission.json` and `results.csv` alongside it (so reviewers can scan the manifest without unpacking).
3. Open a PR using the submission template (`.github/PULL_REQUEST_TEMPLATE/submission.md` in the leaderboard repo). It asks for a contact, a one-line description, and confirmation that you ran against the pinned dataset revision.
4. A maintainer verifies provenance (git SHA + image digest match a public commit and a clean run) and merges. Merged PRs trigger the leaderboard site rebuild; your row appears within ~1 day.
```

with this stub paragraph:

```markdown
The leaderboard submission repo (`actava-ai/chi-bench-leaderboard`) and its PR template will be published alongside the v1.0 release. Until then, keep the packet zip on disk and watch this repo for the announcement — no submissions are accepted yet.
```

If Task 1 Step 3 reported `repo_ready` or `repo_exists_no_template`, leave the numbered list as written. (For `repo_exists_no_template`, the PR template reference is harmless — the maintainer can still review without a template.)

- [ ] **Step 5: Verify line count is in budget**

```bash
wc -l /Users/weiran/Github/chi-bench/README.md
```

Expected: between 180 and 230 lines. If outside this range, do not auto-trim — flag in the Task 5 review.

- [ ] **Step 6: Visual render check**

Open `README.md` in the IDE preview (or push to a scratch GitHub gist) and confirm:
- Logo renders centered at the top.
- The `main_pass_at_1.png` figure renders inline.
- The four tables (domains, packet contents, paper tables, supported agents) render as tables, not as raw pipes.
- The blockquote callouts (headline numbers, Modal callout, Modal-for-reproduction callout) render as blockquotes.
- Section anchors `#submit-your-agent` and `#reproduce-paper-tables` from the Quickstart paragraph resolve to the right H2s.

If any item fails, fix it inline before committing.

- [ ] **Step 7: Commit the README replacement**

```bash
cd /Users/weiran/Github/chi-bench
git add README.md
git commit -m "$(cat <<'EOF'
docs: restructure README for OSS release (linear funnel)

Replaces the previous quickstart-first layout with a visitor-first
linear funnel: hook + headline numbers -> one-time setup -> single-task
smoke test -> submit-to-leaderboard -> reproduce-paper-tables ->
supporting reference (agents, architecture, citation).

Documents the PR-based leaderboard submission flow as the defined
finish line for `chi-bench submission package`.

Spec: docs/superpowers/specs/2026-05-12-readme-oss-release-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Validate the README against the spec

**Files:** none modified unless gaps are found. Output: a list of any required follow-up edits.

**Why:** The plan's "Self-Review" gate. Walk every section of the spec and confirm the README implements it. Catch placeholder leakage, broken links, and content drift.

- [ ] **Step 1: Spec coverage walkthrough**

Open the spec at `docs/superpowers/specs/2026-05-12-readme-oss-release-design.md` and the new `README.md` side by side. For each spec §4 subsection (§1 Header through §9 Citation+License), confirm the README contains a corresponding section with the listed content. Record any gaps.

Specifically check that all of these spec-mandated items appear in the README:
- Logo, four badges, one-sentence tagline (spec §4.1)
- Two-paragraph framing + four headline-numbers bullets + figure + three-row domain table (spec §4.2)
- Five-step setup + Modal sub-callout + `data verify` success signal (spec §4.3)
- Single-command smoke test + cross-link to §5 and §6 (spec §4.4)
- Four-command flow + packet contents + leaderboard PR flow + policy notes (spec §4.5)
- Paper-table mapping table + aggregate command + Modal callout (spec §4.6)
- 7-row agents table + pointer to matrix YAML (spec §4.7)
- 3-sentence architecture + three links (spec §4.8)
- BibTeX block + license footer (spec §4.9)

- [ ] **Step 2: Placeholder scan**

```bash
grep -nE "TBD|TODO|FIXME|XXX|<placeholder>|<your" /Users/weiran/Github/chi-bench/README.md
```

Expected matches (intentional, called out in spec §6 follow-ups):
- `<GOOGLE_DRIVE_SHARE_URL>` in §"Setup" step 4
- `<your-id>` in §"Submit your agent" command examples
- `XXXX.XXXXX` arXiv ID in the header badge and the BibTeX block

Any other match is unintentional — fix inline before continuing.

- [ ] **Step 3: Internal link sanity**

```bash
cd /Users/weiran/Github/chi-bench
grep -oE '\(([^)]+\.(md|yaml|svg|png|tex|sh|py))\)' README.md \
  | sed -E 's/^\(|\)$//g' \
  | sort -u \
  | while read p; do
      test -e "$p" && echo "OK  $p" || echo "MISS $p"
    done
```

Expected: every link resolves to an existing repo path. If any `MISS` appears:
- For `docs/submission-packet.md`: the spec already accepts this gap. Either delete the link from the README §5 step 3 (replace `Full schema in [docs/submission-packet.md](docs/submission-packet.md).` with `Full schema documented alongside the v1.0 release.`) or create a minimal `docs/submission-packet.md` stub.
- For any other miss: stop and resolve before continuing.

- [ ] **Step 4: Anchor link check**

The Quickstart paragraph contains two same-page anchors: `#submit-your-agent` and `#reproduce-paper-tables`. Confirm they match the GitHub-rendered slugs:

```bash
grep -E '^## ' /Users/weiran/Github/chi-bench/README.md
```

Expected H2 lines include `## Submit your agent` and `## Reproduce paper tables`. GitHub slugifies these to `#submit-your-agent` and `#reproduce-paper-tables` — confirm exact spelling. If a heading was renamed, update both the heading and the anchor.

- [ ] **Step 5: Optional fix commit**

If Steps 1–4 surfaced gaps, fix them inline and commit:

```bash
cd /Users/weiran/Github/chi-bench
git add README.md
git commit -m "$(cat <<'EOF'
docs: fix README issues caught by post-write review

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

If no issues were found, skip this step — no empty commits.

---

## Task 6: Update `MEMORY.md` index (optional, only if memories were touched)

This plan does not write any memories. Skip unless the implementer adds a memory during execution (e.g., a feedback memory about README style preferences). If they do, follow the auto-memory section in the system prompt.

---

## Self-review notes

**Spec coverage check (after writing this plan):**
- Spec §4.1 Header → Task 4 Step 2 (full markdown block)
- Spec §4.2 What this benchmark measures → Task 4 Step 2 (full markdown block); figure rendered in Task 2
- Spec §4.3 Setup → Task 4 Step 2 (full markdown block); HF_TOKEN handled by Task 4 Step 3 conditional swap; `.env.example` covered by Task 3
- Spec §4.4 Quickstart → Task 4 Step 2 (full markdown block)
- Spec §4.5 Submit → Task 4 Step 2 (full markdown block); leaderboard repo state handled by Task 4 Step 4 conditional swap
- Spec §4.6 Reproduce → Task 4 Step 2 (full markdown block)
- Spec §4.7 Supported agents → Task 4 Step 2 (full markdown block)
- Spec §4.8 Architecture → Task 4 Step 2 (full markdown block)
- Spec §4.9 Citation + License → Task 4 Step 2 (full markdown block)
- Spec §6 follow-ups: PNG render → Task 2; `.env.example` update → Task 3; submission-packet doc gap → Task 5 Step 3 has the resolution path; leaderboard repo gap → Task 4 Step 4 conditional swap; arXiv ID placeholder → Task 5 Step 2 acknowledges it as intentional

**Placeholder scan (this plan):**
- `<GOOGLE_DRIVE_SHARE_URL>`, `<your-id>`, `XXXX.XXXXX` are intentional and called out as expected matches in Task 5 Step 2.
- No `TODO` / `TBD` / `implement later` remaining.

**Type consistency:**
- Section heading names (`## What this benchmark measures`, `## Setup (one-time)`, `## Quickstart: run one task`, `## Submit your agent`, `## Reproduce paper tables`, `## Supported agents`, `## Architecture`, `## Citation`, `## License`) are referenced identically in Task 4 Step 2 and the anchor check in Task 5 Step 4.
- File paths (`assets/figures/main_pass_at_1.png`, `configs/submission_example.yaml`, `configs/experiments/table1_main_matrix.yaml`, `docs/architecture.md`, `docs/judge.md`, `docs/reproduce.md`) appear consistently across Tasks 2, 4, and 5.
