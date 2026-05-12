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

Χ-Bench evaluates AI agents on end-to-end U.S. healthcare workflows across three long-horizon domains: provider prior authorization, payer utilization management, and population care management. Each task hands the agent a clinical case in a high-fidelity simulator of 20 healthcare apps exposed over MCP, with a 1,279-document Managed-Care Operations Handbook skill, and asks it to drive the case to a terminal state through tool calls and artifact authoring.

The benchmark stresses three capabilities under-represented in coding-style agent benchmarks: **policy density** (decisions grounded in a large library of medical, insurance, and operational rules), **multi-role composition** (a single workflow spans clinician, UM nurse, medical director, and care manager handoffs that cannot be re-run), and **multilateral interaction** (some steps are multi-turn dialogs — peer-to-peer review, patient outreach — not tool calls).

> **Headline numbers from the paper:**
> - Best agent (Claude Code + Claude Opus 4.6): **28.0%** overall pass@1
> - No agent clears **20%** on strict pass^3
> - Marathon (all 25 tasks in one session): best is **3.8%**
> - End-to-end provider–payer arena: **0%** on the best PA agents

<p align="center">
  <img src="assets/figures/main_pass_at_1.png" alt="pass@1 across the three Χ-Bench environments" width="780"/>
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

- `ANTHROPIC_API_KEY` — **required**. The workspace judge (`claude-opus-4-7`) grades every trial; also used by Claude Code agent rows.
- `OPENAI_API_KEY` — required for Codex and OAI Agents rows.
- `GEMINI_API_KEY` — required for Gemini CLI rows.
- `OPENROUTER_API_KEY` — required for the open-stack rows (Hermes / OpenClaw / OAI Agents / DeepAgents on open-weight models).
- `CLAUDE_CODE_OAUTH_TOKEN` — required when running the Claude Code agent harness.
- `HF_TOKEN` — **required** to download the gated Χ-Bench dataset.
- `MODAL_PROFILE` — optional, name of a Modal profile registered via `modal token set --profile <name>`; recommended for matrix reproduction.

Provide whichever provider keys you need for the rows you intend to run.

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

**5. Build the Docker image** (~5 min, one-time).

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
>
> Then set `MODAL_PROFILE=chi-bench` in `.env`.

## Quickstart: run one task

Smoke-test that everything is wired up with a single UM medical-director-review task:

```bash
uv run chi-bench experiment run \
  --dataset data/prior_auth_um/tasks/pa_t008_t008_o002_p01_mdreview_payer \
  --agent codex --model openai/gpt-5.5
```

Trial output lands under `logs/experiments/.../trial_*/`. Read `result.json` for the verifier reward and `verifier/scorecard.json` for per-check verdicts.

If you see a scorecard, you're ready to [submit your agent](#submit-your-agent) or [reproduce the paper](#reproduce-paper-tables).

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
trials/<domain>/<trial_id>/
    result.json                 # Harbor reward + agent metadata
    verifier/scorecard.json     # per-check verdicts
    verifier/reward.json        # verifier's reward breakdown
    agent/trajectory.json       # full agent message trace
```

Workspace artifacts and Harbor scratch files are deliberately excluded so the zip stays uploadable while remaining sufficient for a human to replay any trial.

**4. Get on the leaderboard.** The leaderboard submission repo and its PR template will be published alongside the v1.0 release. Until then, keep the packet zip on disk and watch this repo for the announcement — no submissions are accepted yet.

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
