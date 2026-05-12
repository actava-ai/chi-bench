<div align="center">
  <img src="assets/figures/logo.svg" alt="Χ-Bench" width="300"/>
  <h1><ins>C</ins>linical <ins>H</ins>ealthcare <ins>I</ins>n-Situ Environment</h1>
  <p><b>Benchmark for long-horizon, policy-rich healthcare workflow agents</b></p>
  <p>
    <a href="https://arxiv.org/abs/XXXX.XXXXX"><img src="https://img.shields.io/badge/arXiv-XXXX.XXXXX-b31b1b.svg" alt="arXiv"/></a>
    <a href="https://huggingface.co/datasets/actava/chi-bench"><img src="https://img.shields.io/badge/HF_Dataset-chi--bench-yellow" alt="Dataset"/></a>
    <a href="https://actava.ai/benchmarks"><img src="https://img.shields.io/badge/Leaderboard-chi--bench-blue" alt="Leaderboard"/></a>
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

- `ANTHROPIC_API_KEY` — **required**. The workspace judge (`claude-opus-4-7`) grades every trial; also the default credential for the Claude Code agent harness.
- `OPENAI_API_KEY` — required for Codex and OAI Agents rows.
- `GEMINI_API_KEY` — required for Gemini CLI rows.
- `OPENROUTER_API_KEY` — required for the open-stack rows (Hermes / OpenClaw / OAI Agents / DeepAgents on open-weight models).
- `CLAUDE_CODE_OAUTH_TOKEN` — *optional*, cheaper alternative for smoke-testing the Claude Code harness. When set, Claude Code authenticates via OAuth instead of `ANTHROPIC_API_KEY`.

Provide whichever provider keys you need for the rows you intend to run. Hugging Face and Modal credentials are handled by their respective CLIs (see steps 3 and the Modal note below) — no tokens go in `.env`.

**3. Task fixtures from Hugging Face.** Authenticate once with the CLI, then download the gated dataset:

```bash
uv run huggingface-cli login

REV=chi-bench-v1.0.0
uv run huggingface-cli download actava/chi-bench --repo-type dataset --revision "$REV" --local-dir data/
echo "$REV" > data/.chi-bench-version
```

The `data/.chi-bench-version` pin is what submission preflight verifies against your config's `dataset.version`; write it whenever you change revisions.

**4. Managed-Care Operations Handbook (Google Drive).**

Download the handbook tarball from: **<GOOGLE_DRIVE_SHARE_URL>**

```bash
mkdir -p data/skills
tar -xzf managed-care-operations-handbook.tar.gz -C data/skills/
```

The handbook (1,279 markdown documents) lives off HF because of size and the curation provenance with clinical collaborators.

**5. Build the Docker image** (~5 min, one-time).

```bash
uv run cb docker build
```

> `cb` is the short alias for `chi-bench`; both commands resolve to the same CLI. Pick whichever you prefer (the rest of this README uses `cb`). If your shell already aliases `cb` to something else (e.g. a clipboard tool), use `chi-bench`. For the full command surface and flag reference, read [`docs/cli.md`](docs/cli.md).

The image bundles the FastAPI server, the workspace judge, the agent harness, and per-task fixtures.

**Verify setup:**

```bash
uv run cb data verify
```

A clean run means you're ready for the quickstart.

> **Modal (optional, recommended).** Modal parallelizes trials across remote sandboxes. Set it up now and you won't have to later:
>
> ```bash
> uv run modal setup                            # default profile, or:
> uv run modal token set --profile chi-bench    # (optional) named profile
> ```
>
> If you use a named profile, export `MODAL_PROFILE=chi-bench` in your shell before running the matrix.

## Quickstart: run one task

Smoke-test that everything is wired up with a single UM medical-director-review task:

```bash
uv run cb experiment run \
  --dataset data/prior_auth_um/tasks/pa_t008_t008_o002_p01_mdreview_payer \
  --agent codex --model openai/gpt-5.5
```

Trial output lands under `logs/experiments/.../trial_*/`. Read `result.json` for the verifier reward and `verifier/scorecard.json` for per-check verdicts.

Full flag-by-flag CLI reference: [`docs/cli.md`](docs/cli.md).

If you see a scorecard, you're ready to [submit your agent](#submit-your-agent) or [reproduce the paper](#reproduce-paper-tables).

## Submit your agent

Submitting to the [leaderboard](https://github.com/actava-ai/leaderboard) is a 5-command flow: 4 against chi-bench (validate, run, status, prepare) and the final step against the leaderboard repo (commit + open PR).

**1. Configure.** Copy `configs/submission_example.yaml` to `configs/submissions/<your-id>.yaml` and edit `id`, `team`, `contact`, `agent`, `model`; optionally `notes` and `run.*`.

**2. Run trials and prepare a packet.**

```bash
# Schema + preflight: dataset pin, Modal token / Docker image, agent name.
uv run cb submission validate -f configs/submissions/<your-id>.yaml

# Run all 3 domains. Default: one trial per task (pass@1).
uv run cb submission run      -f configs/submissions/<your-id>.yaml

# Check progress; safe to run while `submission run` is in flight.
uv run cb submission status   -f configs/submissions/<your-id>.yaml

# Curate the leaderboard-ready packet (a directory you `cp` into the leaderboard repo).
uv run cb submission prepare  -f configs/submissions/<your-id>.yaml
```

The final command writes to `logs/submissions/<id>/packet/YYYY-MM-DD-<id>/`, containing:

```
submission.json                # manifest: agent, model, results, provenance
results.csv                    # leaderboard rows (one per domain + overall)
sub.yaml                       # frozen copy of your config
provenance.json                # git SHA, image digest, timestamps
README.md                      # auto-generated headline summary
trials/<domain>/<trial_id>/
    result.json                # Harbor reward + agent metadata
    verifier/scorecard.json    # per-check verdicts
    verifier/reward.json       # verifier's reward breakdown
    agent/trajectory.jsonl.zst # full agent trace (zstd-compressed; inspect with `zstdcat | jq .`)
```

Workspace artifacts and Harbor scratch files are deliberately excluded so the packet stays small (typically <100 MB total).

**3. Submit the packet.** Follow the instructions at **<https://github.com/actava-ai/leaderboard>** — either the one-command helper (`python scripts/submit.py <packet-path>`) or the manual `cp` + `git` + `gh pr create` flow. Either way, the packet is identical; the leaderboard repo owns the submission workflow.

Packet contract (for benchmark authors building their own producers): [`docs/submission-packet.md`](docs/submission-packet.md).

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

System diagram and module boundaries: [`docs/architecture.md`](docs/architecture.md). Verifier details: [`docs/judge.md`](docs/judge.md). Full CLI reference: [`docs/cli.md`](docs/cli.md). Environment chapter from the paper: [`chi-bench-arxiv-submission/sections/approach.tex`](chi-bench-arxiv-submission/sections/approach.tex).

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
