# χ-Bench Healthcare AI Agents Challenge

**Build an autonomous agent for prior authorization, utilization management, and care management in χ-World.**

Aligned with the [published Kaggle Overview](https://www.kaggle.com/competitions/chi-bench/overview) and [Rules](https://www.kaggle.com/competitions/chi-bench/rules) on October 6, 2026. The live Rules tab, including Kaggle's Foundational Competition Rules, remains authoritative; the [local rules reference](competition-rules-draft.md) records the competition-specific requirements.

## Description

Can an AI agent complete a complex healthcare-administration workflow—not merely answer a question, but gather evidence, apply policy, use operational tools, communicate with simulated people, and drive a case to the correct outcome?

χ-Bench evaluates long-horizon agents inside χ-World, a high-fidelity simulator of U.S. healthcare operations. Agents work across healthcare applications exposed through MCP and REST tools while grounding their decisions in the 1,279-document Managed-Care Operations Handbook.

The benchmark contains only simulated patients and synthetic operational data. It contains no real patient data or protected health information and must not be used to make decisions about real patients.

| | Competition at a glance |
|---|---|
| Public development set | 75 tasks, 25 per track |
| Private evaluation set | Approximately 75 unreleased clinician-validated tasks |
| Primary metric | Strict binary pass@1 |
| Reliability metric | pass³ across three independent attempts |
| Prize pool | USD 3,000 plus a Reliability Award |
| Conference | IEEE Big Data 2026, Phoenix, December 14–17, 2026 |

### How the competition works

1. Join the Kaggle competition and accept the Rules.
2. Request and receive access to the gated Managed-Care Operations Handbook **before running χ-Bench**.
3. Develop and evaluate your agent on the 75 public tasks.
4. Submit the public task results through Kaggle and prepare the required runnable final package.
5. The organizers run every complete, prize-eligible final entry on the unreleased private tasks.
6. Organizer-run private scores determine the final rankings and prizes.

The Kaggle public leaderboard is a provisional development leaderboard because its task rewards are generated in participant-controlled environments. Every team that submits a complete runnable system, evidence packet, source code, and qualifying report by the deadline receives a private score.

## Start here

### Essential links

- [Official χ-Bench repository](https://github.com/actava-ai/chi-bench)
- [Public χ-Bench task dataset](https://huggingface.co/datasets/actava/chi-bench)
- [Request access to the Managed-Care Operations Handbook](https://huggingface.co/datasets/actava/managed-care-operations-handbook)
- [Quickstart](https://www.actava.ai/benchmarks/docs/quickstart)
- [Running experiments and submissions](https://www.actava.ai/benchmarks/docs/run)
- [Browse all 75 public tasks](https://www.actava.ai/benchmarks/tasks)
- [Live χ-Bench leaderboard](https://www.actava.ai/benchmarks/leaderboards)
- [Evidence and submission-packet repository](https://github.com/actava-ai/leaderboard)
- [χ-Bench paper](https://arxiv.org/abs/2605.16679)
- [IEEE Big Data Cup 2026](https://bigdataieee.org/BigData2026/cup/)
- [Kaggle competition](https://www.kaggle.com/competitions/chi-bench)

### Prerequisites

- Python 3.12 or newer
- Docker
- [`uv`](https://docs.astral.sh/uv/)
- An approved Hugging Face token for the handbook
- `ANTHROPIC_API_KEY` for the official workspace judge
- The provider key required by your chosen agent model

Any model, agent harness, prompting strategy, hardware, cloud provider, or local environment may be used, subject to the Rules and applicable licenses. You are not limited to the harnesses included in the repository.

### Minimal local setup

Clone and install χ-Bench:

```bash
git clone https://github.com/actava-ai/chi-bench
cd chi-bench
uv sync --extra dev
```

Download the pinned public task release:

```bash
uv run huggingface-cli login

REV=chi-bench-v1.0.0
uv run huggingface-cli download actava/chi-bench \
  --repo-type dataset \
  --revision "$REV" \
  --local-dir data/
echo "$REV" > data/.chi-bench-version
```

Before continuing, request and obtain approval for the [Managed-Care Operations Handbook](https://huggingface.co/datasets/actava/managed-care-operations-handbook). Once approved, download it:

```bash
uv run huggingface-cli download actava/managed-care-operations-handbook \
  --repo-type dataset \
  --local-dir data/skills/
```

Configure credentials locally. Never upload `.env`, API keys, or Hugging Face tokens to Kaggle or a source repository:

```bash
cp .env.example .env
```

Build and verify the local benchmark:

```bash
uv run cb docker build
uv run cb data verify
```

Run a smoke-test task by following the [Quickstart](https://www.actava.ai/benchmarks/docs/quickstart). For Harbor and Modal alternatives, see the [run guide](https://www.actava.ai/benchmarks/docs/run).

### Run a complete public submission

Start from the [submission configuration template](https://github.com/actava-ai/chi-bench/blob/main/configs/submission_example.yaml):

```bash
mkdir -p configs/submissions
cp configs/submission_example.yaml configs/submissions/my-team.yaml

uv run cb submission validate -f configs/submissions/my-team.yaml
uv run cb submission run      -f configs/submissions/my-team.yaml
uv run cb submission status   -f configs/submissions/my-team.yaml
uv run cb submission prepare  -f configs/submissions/my-team.yaml
```

Edit `my-team.yaml` before running it. Set your team, contact, agent, model, environment, and dataset version. The prepared evidence packet contains the manifest, per-domain results, verifier evidence, provenance, and compressed trajectories required for validation.

## Evaluation

### Task reward

Each task receives one strict binary reward:

- `1` only when every required non-N/A verifier check passes.
- `0` when any required check fails.

Fractional check completion is diagnostic only and does not affect competition ranking.

The verifier combines deterministic workflow-contract checks with rubric-based review of policy and clinical reasoning. For official private evaluation, the judge is pinned to `claude-opus-4-7`, with three independent votes per rubric.

The current simulator configuration is:

| Component | Pinned model and configuration |
|---|---|
| Care Management patient simulator | `claude-sonnet-5`, adaptive thinking disabled, maximum 1,024 output tokens |
| Peer-to-peer physician counterpart | `claude-sonnet-5` |
| Workspace judge | `claude-opus-4-7`, three independent votes per rubric |

If a provider introduces an immutable replacement snapshot identifier before launch, the organizers will announce and freeze that identifier before official evaluation. The frozen simulator and judge configuration will not change between teams.

### Public score

Run each of the 75 public tasks once. The public development score is:

\[
\mathrm{Public\ pass@1}
=\frac{\text{public tasks with reward 1}}{75}.
\]

The Kaggle submission file contains exactly one binary reward for each required public task:

```csv
task_id,reward
cm_afib_moderate_anxious_001,1
pa_t008_t008_o002_p01_mdreview_payer,0
```

The competition Data tab will provide `sample_submission.csv` containing the complete required task list. Do not submit a reward of `1` unless the corresponding official verifier output is `1`.

### Private score and final ranking

Every complete, runnable, prize-eligible final entry is evaluated for three independent attempts on the unreleased private set.

Attempt 1 determines private pass@1:

\[
\mathrm{Pass@1}
=\frac{1}{N}\sum_{i=1}^{N}r_{i,1}.
\]

All three attempts determine pass³:

\[
\mathrm{Pass^3}
=\frac{1}{N}\sum_{i=1}^{N}
\mathbf{1}(r_{i,1}=r_{i,2}=r_{i,3}=1).
\]

Final entries are ranked by:

1. Higher private pass@1.
2. Higher private pass³.
3. Lower mean agent inference cost.
4. Fewer mean agent tool calls.

The Rules tab adds earlier valid final Kaggle submission as the remaining tie-breaker. When either tied system lacks comparable cost records, the rules skip cost and use tool-call count next.

Organizer-run private results supersede the provisional Kaggle public score. The final private ranking will be announced on Kaggle and published through the official χ-Bench leaderboard.

## Submission requirements

### Public Kaggle submission

Submit `submission.csv` through Kaggle. It must contain:

- exactly one row for every required public task;
- an unchanged official `task_id` in every row;
- a `reward` value of either `0` or `1`; and
- no missing, additional, or duplicate task identifiers.

### Prize-eligible final package

To receive a private score and remain eligible for prizes, submit the following by the final deadline using the private delivery instructions in the Rules tab:

- The final Kaggle `submission.csv`.
- The official audit packet produced by `cb submission prepare`.
- The agent and orchestration source code.
- Prompts, system instructions, tool definitions, and configuration.
- Dependency manifests and lock files.
- Exact model and API endpoint identifiers.
- A runnable container image, image digest, or complete reproduction instructions.
- Cost and token-usage records where available.
- A qualifying report using the IEEE conference template, no more than five pages excluding references.

Source-code disclosure applies to participant-created agent and orchestration components. It does not require disclosure of proprietary third-party model weights or source code the team does not own. Do not include credentials in any submitted artifact.

Teams may contain up to five people. Each person who accesses the handbook must have their own approved access.

## Timeline

All deadlines are 11:59 PM UTC unless otherwise announced.

| Event | Date |
|---|---|
| Cup data-release program began | June 1, 2026 |
| Kaggle competition opens | August 15, 2026 |
| Entry deadline | November 7, 2026 |
| Team-merger deadline | November 7, 2026 |
| Final Kaggle submission deadline | November 15, 2026 |
| Final results announced | November 23, 2026 |
| Finalist materials due | December 7, 2026 |
| IEEE Big Data 2026 | December 14–17, 2026 |
| Conference location | Phoenix, Arizona, USA |

These are the dates published on Kaggle. Its submission text also requires a complete package by the final deadline, although the timeline puts finalist materials after the results announcement. The header names 2027 while the rules and overview describe 2026. See the [rules source notes](competition-rules-draft.md#source-notes) and contact the organizers for clarification.

## Rules, data use, and safety

- Read and accept the Kaggle Rules before participating.
- Obtain handbook approval before running the benchmark.
- The [public χ-Bench dataset](https://huggingface.co/datasets/actava/chi-bench) is released under its stated Apache-2.0 license.
- The [Managed-Care Operations Handbook](https://huggingface.co/datasets/actava/managed-care-operations-handbook) is separately gated for non-commercial research and may not be redistributed.
- Do not upload the handbook, protected excerpts, credentials, or private evaluation materials to Kaggle or public repositories.
- Evaluated tasks must be completed autonomously. Human task-level intervention and manual modification of verifier results are prohibited.
- Agents may not access hidden expectations, private solutions, or verifier-only files.
- χ-Bench is a research benchmark, not a medical device or source of medical advice.

The complete Competition Rules are available in the [Kaggle Rules tab](https://www.kaggle.com/competitions/chi-bench/rules). Questions should be posted in the Kaggle Discussion forum or sent to [research@actava.ai](mailto:research@actava.ai).

## Resources

- [χ-Bench documentation](https://www.actava.ai/benchmarks/docs)
- [Quickstart](https://www.actava.ai/benchmarks/docs/quickstart)
- [Run and submit](https://www.actava.ai/benchmarks/docs/run)
- [Task explorer](https://www.actava.ai/benchmarks/tasks)
- [Live leaderboard](https://www.actava.ai/benchmarks/leaderboards)
- [Official GitHub repository](https://github.com/actava-ai/chi-bench)
- [Public task dataset](https://huggingface.co/datasets/actava/chi-bench)
- [Managed-Care Operations Handbook access](https://huggingface.co/datasets/actava/managed-care-operations-handbook)
- [Evidence leaderboard repository](https://github.com/actava-ai/leaderboard)
- [Research paper](https://arxiv.org/abs/2605.16679)
- [IEEE Big Data Cup 2026](https://bigdataieee.org/BigData2026/cup/)

## Citation

If you use χ-Bench in a publication, cite:

```bibtex
@misc{chen2026chibenchaiagentsautomate,
  title        = {CHI-Bench: Can AI Agents Automate End-to-End,
                  Long-Horizon, Policy-Rich Healthcare Workflows?},
  author       = {Haolin Chen and Deon Metelski and Leon Qi and Tao Xia
                  and Joonyul Lee and Steve Brown and Kevin Riley and
                  Frank Wang and others},
  year         = {2026},
  eprint       = {2605.16679},
  archivePrefix = {arXiv},
  primaryClass = {cs.CL},
  url          = {https://arxiv.org/abs/2605.16679}
}
```
