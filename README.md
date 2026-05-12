<p align="center">
  <img src="assets/figures/logo.svg" alt="chi-Bench" width="520"/>
</p>

<h1 align="center">Χ-Bench</h1>

<p align="center">
  <b>C</b>linical <b>H</b>ealthcare <b>I</b>n-Situ Environment and Evaluation <b>Bench</b>mark<br/>
  Long-horizon, policy-rich healthcare workflows for AI agents.
</p>

<p align="center">
  <a href="https://arxiv.org/abs/XXXX.XXXXX">
    <img src="https://img.shields.io/badge/arXiv-XXXX.XXXXX-b31b1b?logo=arxiv&logoColor=white" alt="arXiv"/>
  </a>
  <a href="https://huggingface.co/datasets/actava/chi-bench">
    <img src="assets/figures/huggingface.png" alt="Hugging Face" height="28"/>
  </a>
  <a href="https://actava-ai.github.io/chi-bench/leaderboard">
    <img src="assets/figures/leaderboard.png" alt="Leaderboard" height="28"/>
  </a>
  <a href="https://www.python.org/downloads/">
    <img src="assets/figures/python.png" alt="Python 3.12+" height="28"/>
  </a>
</p>

- Paper: https://arxiv.org/abs/XXXX.XXXXX *(fill in once posted)*
- Dataset: https://huggingface.co/datasets/actava/chi-bench
- Leaderboard: https://actava-ai.github.io/chi-bench/leaderboard
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
uv run chi-bench data verify
# 2. Build the docker image (~5 min, one-time)
uv run chi-bench docker build
# 3. Run one task as a smoke check
cp .env.example .env  # then fill in ANTHROPIC_API_KEY + OPENAI_API_KEY
uv run chi-bench experiment run \
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
uv run python scripts/aggregate.py \
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
uv pip install -U "huggingface_hub[cli]"
uv run chi-bench data download --revision chi-bench-v1.0.0
```

This wraps `huggingface-cli download actava/chi-bench` and writes the revision tag to `data/.chi-bench-version` — submission preflight verifies this against your config's `dataset.version`. Use this command rather than raw `huggingface-cli` so the version pin works.

### 2. Managed-Care Operations Handbook (Google Drive)

Download from: **<GOOGLE_DRIVE_SHARE_URL_PLACEHOLDER>**

```bash
mkdir -p data/skills
tar -xzf managed-care-operations-handbook.tar.gz -C data/skills/
```

### 3. Verify

```bash
uv run chi-bench data verify
```

## Submit your agent

Submitting to the [leaderboard](https://actava-ai.github.io/chi-bench/leaderboard) is a four-command flow over one YAML. Copy `configs/submission_example.yaml`, edit the highlighted fields, then:

```bash
# 1. Schema + preflight check (dataset pin, Modal token / Docker image, agent name)
uv run chi-bench submission validate -f my_submission.yaml

# 2. Run all 3 domains. Default: one trial per task (pass@1).
#    Raw Harbor trial trees stay on disk under logs/submissions/<id>/ for human verification.
uv run chi-bench submission run -f my_submission.yaml

# 3. Check progress (safe to run while step 2 is still going).
uv run chi-bench submission status -f my_submission.yaml

# 4. Build the upload-ready zip (~30–50 MB).
uv run chi-bench submission package -f my_submission.yaml
```

The packet (`logs/submissions/<id>/<id>.zip`) contains everything needed for human verification:

```
submission.json   # manifest: agent, model, provenance (code_sha, dataset_version, ...), results, per_domain
results.csv       # leaderboard row: agent, model, n_trials, n_tasks, pass_at_1, mean_cost_usd, mean_walltime_s
sub.yaml          # frozen copy of your input config
provenance.json   # captured at run start (git SHA, image digest, timestamps, host)
trials/<domain>/<trial_id>/
    result.json                 # Harbor reward + agent metadata
    verifier/scorecard.json     # per-check verdicts
    verifier/reward.json        # verifier's reward breakdown
    agent/trajectory.json       # full agent message trace (for replay/audit)
```

Workspace artifacts, server logs, and Harbor scratch files are deliberately excluded so the zip stays uploadable while remaining sufficient for a human to replay any single trial.

**Partial submissions** (development only): `--domain pa | um | cm` on `submission run` restricts to one domain at a time. Partial submissions are flagged as such on the leaderboard.

**Leaderboard policy**: one run per task — pass@3 / pass^3 / Wilson CIs are not included in the submission manifest. If you want those for your own analysis, set `run.n_attempts: 3` in the YAML; the extra trials are kept on disk and the manifest still publishes pass@1.

## Architecture

A single Python package (`chi_bench`) wraps a FastAPI server + 3 MCP servers (provider :8020, payer :8100, CM :8200) + an LLM-based verifier ("workspace judge"). Each trial runs in a fresh Docker container that bundles the server, the judge, the agent harness, and the per-task fixtures. See `docs/architecture.md`.

## Modal (optional)

Modal parallelizes trials across remote sandboxes — recommended for full submissions and matrix reproduction (local Docker is bounded to one host).

```bash
uv run modal token set --profile chi-bench
# Submitters: just set `run.environment: modal` in sub.yaml.
# Paper-table reproduction: run_table.sh accepts --modal.
./scripts/run_table.sh table1 --modal
```

## Citation

(see `CITATION.cff`)

## License

Code: Apache-2.0 (`LICENSE`).
Data: see the HF dataset card.
