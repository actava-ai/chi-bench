# README Design — chi-Bench OSS Release

**Status:** approved (skeleton). Pending user review of this spec before plan.
**Date:** 2026-05-12
**Target file:** `README.md` (repo root, replaces existing 164-line version)
**Approx. length:** ~195 lines

## 1. Goal

Replace the current `README.md` with a restructured landing page for the OSS release of chi-Bench. The new README serves three audiences in priority order:

1. **Visitor** — researcher/engineer landing from the arXiv paper, a tweet, or a search; deciding in 30 seconds whether to engage.
2. **Submitter** — agent developer who wants to run their agent and get on the leaderboard.
3. **Reproducer** — paper reviewer or researcher reproducing the 5 paper tables.

The README is the only entry point users see before cloning. Deep details (architecture, packet schema, judge internals, full 30-row agent matrix) live under `docs/` and are linked from the README.

## 2. Non-goals

- Not redesigning `docs/architecture.md`, `docs/judge.md`, or `docs/reproduce.md`. Those stay as the deep references.
- Not changing the CLI surface (`chi-bench data | docker | experiment | submission | trial`). Section 5 of the README describes the existing four-command submission flow; it does not propose new commands.
- Not changing the HF dataset, the handbook distribution, or the leaderboard repo. The README describes how to use them.
- Not designing the leaderboard site UI. Submission goes via PR to a sibling leaderboard repo (§5).
- Not creating new figures from scratch. Reuse existing assets from `assets/figures/` and `chi-bench-arxiv-submission/figures/` (rendered to PNG where the paper ships PDF).

## 3. Design constraints

- **Length:** ~200 lines (medium budget). Lean enough to scan, comprehensive enough to actually run all three flows without clicking out for the basics.
- **Visitor-first:** the hook (§1–§2 of the README) lands before any executable step. No fake "try without commitment" demos — the first action is honest setup.
- **Reuse don't rewrite:** preserve existing accurate content (paper-table reproduction table, partial-submission note, pass@k policy note) where it works. Reorganize what doesn't.
- **No emoji.** Standard markdown only.
- **No new code or skills required.** The README documents what exists; if something is missing (e.g., the leaderboard PR template), it's called out as a follow-up artifact in §6 below.

## 4. README section design

The structure is a **linear funnel**: visitor hook → one-time setup → smoke test → submit → reproduce → supplemental. A reader scrolls top-to-bottom and exits at whichever action they came for, without backtracking. Section numbering below is for this spec; the README itself uses H2 headings without numbers.

### §1. Header (~15 lines)

- Centered logo: existing `assets/figures/logo.svg` at width=300.
- H1: title with the `Χ`-Bench glyph rendering and the expanded acronym (Clinical Healthcare In-Situ).
- One-sentence tagline: "Benchmark for long-horizon, policy-rich healthcare workflow agents."
- Badges (left-to-right): arXiv (placeholder ID until paper ID assigned), HF dataset (`actava/chi-bench`), leaderboard (`actava-ai.github.io/chi-bench/leaderboard`), license (Apache-2.0).
- Keeps the existing centered-div HTML pattern from the current README.

### §2. What this benchmark measures (~25 lines)

The hook. Three structural pieces:

1. **Two-paragraph framing.** First paragraph: chi-Bench evaluates end-to-end automation of three U.S. healthcare workflows — provider prior authorization, payer utilization management, and care management. Second paragraph: names the three capabilities the bench stresses (policy density, multi-role composition, multilateral interaction). Wording derived from the paper abstract and `sections/introduction.tex`. Plain language, not paper jargon.
2. **Headline-numbers callout.** Quoted bullet list of the four claims from the paper:
   - Best agent (Claude Code + Opus 4.6): 28.0% overall pass@1.
   - No agent clears 20% on strict pass^3.
   - Marathon (all 25 tasks in one session): 3.8%.
   - End-to-end provider–payer arena: 0% on the best PA agents.
3. **One figure + a three-row domain mini-table.** Figure: PNG render of `chi-bench-arxiv-submission/figures/main_pass_at_1.pdf` (the pass@1 teaser chart). Mini-table: one row per domain (PA-provider / PA-UM / CM), 25 tasks each, one-line description of what the agent does.

### §3. Setup (one-time) (~40 lines)

The honest version of "quickstart". Five numbered steps, each a single fenced block. A visitor who scrolls here has committed to engaging.

1. **Clone + install.** `git clone … && cd chi-bench && uv sync --extra dev`. Prereqs listed inline: Python 3.12+, Docker, [uv](https://github.com/astral-sh/uv).
2. **API keys.** Copy `.env.example` to `.env` and fill in. Required: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN` (for the workspace judge). Optional: `OPENROUTER_API_KEY` (open-stack rows), `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET` (matrix reproduction), `HF_TOKEN` (only if the HF dataset is gated — verify at implementation time and drop this if public). One sentence on what each key is for.
3. **Task fixtures from Hugging Face.** `uv run chi-bench data download --revision chi-bench-v1.0.0`. One-line note on the pinned revision and why the wrapper (vs raw `huggingface-cli`) matters: the revision tag is written to `data/.chi-bench-version` for submission preflight.
4. **Managed-Care Operations Handbook from Google Drive.** Download URL placeholder (`<GOOGLE_DRIVE_SHARE_URL>` — to be replaced before release), tar-extract command. One sentence on why this lives off HF (size + provenance).
5. **Docker image.** `uv run chi-bench docker build` (~5 min, one-time). One sentence on what's bundled (server, judge, agent harness, fixtures).

Ends with `uv run chi-bench data verify` as the success signal. If it returns clean, the user is ready for §4.

**Modal sub-callout (3 lines):** "Modal parallelizes trials across remote sandboxes — recommended for §5 full submissions and §6 paper-table reproduction. `uv run modal token set --profile chi-bench`. Setting it up now means you don't have to later." Not numbered because it's optional.

### §4. Quickstart: run one task (~15 lines)

Single fenced block:

```bash
uv run chi-bench experiment run \
  --dataset data/prior_auth_um/tasks/pa_t008_t008_o002_p01_mdreview_payer \
  --agent codex --model openai/gpt-5.5
```

Followed by ~5 lines explaining: which task this is (a UM medical-director review, picked because it's representative and fast), where the trial output lands (`logs/experiments/.../trial_*/`), and what files to read first (`result.json`, `verifier/scorecard.json`). Closing line: "If you see a verifier scorecard, you're ready to **submit your agent** (§5) or **reproduce the paper** (§6)." Anchors link to those sections.

### §5. Submit your agent (~35 lines)

Four subparts. Tight prose, fenced commands.

1. **The four-command flow.** Copy `configs/submission_example.yaml`, edit the highlighted fields (id, team, contact, agent, model, optionally notes/runtime), then:
   ```bash
   uv run chi-bench submission validate -f my-sub.yaml   # schema + preflight (dataset pin, Modal token/Docker image, agent name)
   uv run chi-bench submission run      -f my-sub.yaml   # runs all 3 domains; trials land under logs/submissions/<id>/
   uv run chi-bench submission status   -f my-sub.yaml   # safe to run while step 2 is in flight
   uv run chi-bench submission package  -f my-sub.yaml   # builds logs/submissions/<id>/<id>.zip (~30–50 MB)
   ```
   Each command gets one comment explaining what it does and what failure it catches. Keep the existing wording from the current README where it's already crisp.
2. **What's in the packet (4 lines + link).** `submission.json` (manifest), `results.csv` (leaderboard row), `sub.yaml` (frozen config), `provenance.json` (git SHA, image digest, timestamps), `trials/<domain>/<trial_id>/...` (per-trial artifacts). Link out: "Full schema and replay instructions in `docs/submission-packet.md`."
3. **Get on the leaderboard.** **New content vs. current README.** Once the zip is built:
   - Fork `actava-ai/chi-bench-leaderboard` (sibling repo to this one).
   - Place the zip under `submissions/<your-id>/<your-id>.zip` and copy `submission.json` and `results.csv` alongside it (so reviewers can scan the manifest without unpacking).
   - Open a PR using the provided template (`.github/PULL_REQUEST_TEMPLATE/submission.md` in the leaderboard repo). The template asks for: a contact, a one-line description, and a confirmation that you ran on the pinned dataset revision.
   - A maintainer verifies provenance (git SHA + image digest match a public commit + a clean run) and merges. Merged PR triggers the leaderboard site rebuild; your row appears within ~1 day.
4. **Policy notes (3 lines).** Partial submissions (`--domain pa | um | cm` on `submission run`) are accepted but flagged as such. Leaderboard is **pass@1 only** — `run.n_attempts: 3` keeps the extra trials on disk for your own analysis without changing the published number.

### §6. Reproduce paper tables (~30 lines)

- Table mapping paper table → config → command (verbatim from current README — it's already correct):
  | Paper | Config | Command |
  | Table 1 (Main matrix) | `table1_main_matrix.yaml` | `./scripts/run_table.sh table1` |
  | Table 2 (E2E arena)   | `table2_e2e_arena.yaml`  | `./scripts/run_table.sh table2` |
  | Table 3 (Marathon)    | `table3_marathon.yaml`   | `./scripts/run_table.sh table3` |
  | Fig 4 (Skill ablation)| `table4_skill_ablation.yaml` | `./scripts/run_table.sh table4` |
  | Table 5 (MCP vs CLI)  | `table5_mcp_vs_cli.yaml` | `./scripts/run_table.sh table5` |
- Aggregate command (verbatim from current README):
  ```bash
  uv run python scripts/aggregate.py \
    --trials-dir logs/experiments/table1_main_matrix \
    --prices configs/prices.yaml \
    --out-csv logs/table1.csv
  ```
- Two-line CSV-columns description + Wilson-CI note. Closes with: "v1 emits the numeric tables; paper figures are out of scope — plot from the CSV. See `docs/reproduce.md` for the figure scripts we used."
- One-line Modal callout: "Add `--modal` to `run_table.sh` for parallel execution; matrix reproduction on a single host takes days."

### §7. Supported agents (~15 lines)

A trimmed 7-row table, one row per harness, with one example model and the column it maps to in Table 1:

| `--agent` | Example `--model` | Paper rows |
| `claude-code` | `anthropic/claude-opus-4-7` | Claude Code |
| `codex` | `openai/gpt-5.5` | Codex |
| `gemini-cli` | `gemini/gemini-3-pro-preview` | Gemini CLI |
| `openclaw` | `anthropic/claude-opus-4-7` | OpenClaw |
| `hermes` | `openrouter/z-ai/glm-5.1` | Hermes |
| `openai-agents` | `deepseek/deepseek-v4-pro` | OAI Agents |
| `deepagents` | `openrouter/x-ai/grok-4.3` | DeepAgents |

One line: "Full 30-row matrix (every model × harness reported in Table 1) lives in `configs/experiments/table1_main_matrix.yaml`."

### §8. Architecture (~10 lines)

Three sentences:
1. A single Python package (`chi_bench`) hosts a FastAPI server, three MCP servers (provider :8020, payer :8100, CM :8200), and an LLM-based workspace judge.
2. Each trial runs in a fresh Docker container that bundles the server, judge, agent harness, and per-task fixtures.
3. The Managed-Care Operations Handbook (1,279 markdown documents) is mounted into the agent's skill directory at trial start.

Followed by links: `docs/architecture.md` (system diagram + module boundaries), `docs/judge.md` (verifier details), `chi-bench-arxiv-submission/sections/approach.tex` (the paper's environment chapter).

### §9. Citation + License (~10 lines)

- BibTeX block: minimal entry pointing at the arXiv ID placeholder. One line above: "If you use chi-Bench, please cite:".
- Footer: "Code under Apache-2.0 (see `LICENSE`). Data licensing on the [HF dataset card](https://huggingface.co/datasets/actava/chi-bench)."

## 5. Reader-journey check

- **Visitor (no commitment):** §1 → §2 → bounces or commits. The teaser figure + headline numbers + three-domain table do the work in roughly the top half of one screen-height.
- **Submitter:** §1 → §2 → §3 (~10 min) → §4 (smoke test, ~5 min) → §5. Linear scroll, no backtracking.
- **Reproducer:** §1 → §2 → §3 → §4 → §6. Same funnel, diverges only at the last branch.
- **Skimmer (returning user):** §7 / §8 are stable bookmarks. §5 and §6 are the canonical "how do I do X" sections.

## 6. Follow-up artifacts (out of scope for this spec, called out so they're not forgotten)

- `docs/submission-packet.md` — full packet schema referenced from §5. Not strictly required for the README to ship; if it doesn't exist yet, §5 either inlines the schema (adds ~10 lines) or drops the link until the doc exists.
- Leaderboard repo (`actava-ai/chi-bench-leaderboard`) with PR template — referenced from §5. If the repo isn't ready, §5 must say so explicitly rather than linking to a 404. Decision point at implementation time: link as-is and hope the repo lands by release, or stub §5 with "submission PR flow coming on $DATE".
- PNG renders of `main_pass_at_1.pdf` (and optionally a screenshot from `healthcare-software-showcase.pdf`) under `assets/figures/`. Existing assets are PDF-only; the README needs PNG (or SVG) for GitHub rendering.
- `.env.example` referenced by §3 — verify it lists all the keys §3 enumerates; if not, update it as part of implementation.
- arXiv ID — current README has the `XXXX.XXXXX` placeholder. The new README keeps the placeholder until the ID is assigned.

## 7. Departures from the current README (deliberate)

1. **"Quickstart" no longer the first action.** Renamed to §4 and placed after Setup. The current "Quickstart" buries the setup gates (keys, Docker, data) inside what claims to be a single quickstart block.
2. **Submission has a defined finish line.** Current README ends submission at `package` (a zip on disk). The new §5 documents the PR-to-leaderboard-repo flow so a submitter knows what "done" looks like.
3. **Trimmed agents table.** Current 7-row table includes example model lists in the body cell, which makes the table hard to scan and quickly stale. New table is one row per harness with a single canonical model + pointer to the matrix YAML.
4. **Visitor hook section is explicit.** Current README has a "What this benchmark measures" section but it's compressed and lacks the figure that earns 30 seconds of scrolling.
5. **Architecture section trimmed.** Current architecture paragraph crams server + MCP + verifier + Docker into one sentence. New §8 splits to three sentences and links the deep reference rather than reproducing it.
