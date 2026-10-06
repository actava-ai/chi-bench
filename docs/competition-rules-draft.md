# χ-Bench Healthcare AI Agents Challenge

## IEEE Big Data Cup 2026 — Competition Rules

This local reference was aligned with the [published Kaggle Rules](https://www.kaggle.com/competitions/chi-bench/rules) and [Overview](https://www.kaggle.com/competitions/chi-bench/overview) on October 6, 2026. Kaggle hosts public submissions; organizer-run private evaluation determines final standings and prizes. The live Rules tab, including Kaggle's Foundational Competition Rules, remains authoritative.

### 1. Competition

The χ-Bench Healthcare AI Agents Challenge is part of the IEEE Big Data Cup 2026 and is sponsored and organized by actAVA.ai.

The Competition evaluates autonomous AI agents on long-horizon U.S. healthcare-administration workflows. It is hosted through [Kaggle](https://www.kaggle.com/competitions/chi-bench).

Participation is also subject to the [Kaggle Terms of Service](https://www.kaggle.com/terms) and the Foundational Competition Rules on the [Rules tab](https://www.kaggle.com/competitions/chi-bench/rules). Kaggle states that its foundational rules take precedence over conflicting competition-specific provisions.

### 2. Challenge scope

The Competition covers three χ-Bench tracks:

1. Provider Prior Authorization: verify coverage, assemble clinical evidence, submit an authorization request, and handle requests for information, peer-to-peer review, and appeals.
2. Payer Utilization Management: intake requests, apply plan medical policy, conduct nurse and physician review, and issue coverage determinations.
3. Care Management: review patient charts, conduct outreach and assessments, and create NANDA-I/NOC/NIC-aligned care plans.

The public development benchmark contains 75 tasks: 25 tasks in each track. The private final benchmark is expected to contain approximately 75 additional clinician-validated tasks that are not released during the Competition.

The combined three-track result on the private set determines the overall winners. Per-track results will also be reported.

### 3. Important dates

All deadlines are at 11:59 PM UTC unless otherwise announced.

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

The organizers may adjust dates when necessary. Material changes will be announced on Kaggle.

### 4. Eligibility and teams

The Competition is open to individuals and teams worldwide, subject to applicable laws, sanctions, export controls, employer policies, and Kaggle eligibility requirements.

- Each participant may use only one Kaggle account.
- A participant may belong to only one team.
- The maximum team size is five people.
- Team mergers must be completed before the team-merger deadline.
- Each team member must accept these Rules.
- Organizers, competition administrators, and anyone with advance access to private tasks, expectations, verifier assets, or solutions may participate for demonstration purposes but are not eligible for rankings or prizes.
- Participants under the age of majority in their jurisdiction must obtain any required parental or guardian consent.

Private sharing of competition code or private competition data between separate teams is prohibited. Public sharing available equally to all participants is permitted, subject to the handbook restrictions in Section 5.

### 5. Data and Managed-Care Operations Handbook

The χ-Bench code and public task fixtures are available through the official repository and dataset release under their stated licenses.

The Managed-Care Operations Handbook is a separate, gated artifact. Access is manually reviewed and governed by the actAVA clinical-collaborator license. It is restricted to non-commercial research use and may not be redistributed. The complete access conditions are published on the [official handbook page](https://huggingface.co/datasets/actava/managed-care-operations-handbook).

The following requirements are mandatory:

- Participants must request and receive handbook access before running χ-Bench.
- Every team member who accesses the handbook must be separately authorized.
- Teams may not share the handbook with other people or teams.
- The handbook, substantial excerpts, or derived confidential content must not be uploaded to Kaggle, GitHub, public model repositories, public notebooks, or other public services without prior written permission from actAVA.
- Hugging Face tokens, model API keys, and other credentials must never be included in submissions, notebooks, logs, or source repositories.
- Public reports should refer to handbook section identifiers or summarize methods without reproducing protected material.
- Private test tasks and their associated data must remain confidential.

χ-Bench uses simulated patients and contains no real patient data or protected health information. Participants must not introduce real patient information into their systems or submissions.

### 6. Permitted systems

Participants may use any lawful model, agent harness, orchestration framework, prompting method, hardware, cloud provider, local environment, or external API.

There is no required execution environment and no restriction to the agent harnesses shipped with χ-Bench. Proprietary models and custom agents are permitted.

External models, tools, and datasets must:

- be lawfully accessible to the team;
- comply with their applicable licenses and terms;
- be disclosed in the qualifying report; and
- not contain leaked private χ-Bench tasks, expectations, or solutions.

Participants are responsible for ensuring that any third-party API or service they use is compatible with the handbook’s access and confidentiality terms.

### 7. Automation and human involvement

Human work is permitted when developing, configuring, testing, and debugging an agent.

Once an evaluated trial begins:

- The task must be completed by the submitted automated system.
- Humans may not select actions, supply task-specific answers, repair artifacts, or intervene based on intermediate task state.
- Teams may not manually change verifier outputs, rewards, scorecards, trajectories, or result files.
- The same frozen system configuration must be used for all private-final tasks.

Systems may evolve during the public development period. The version selected for final judging must be frozen at the final submission deadline.

### 8. Prohibited conduct

The following may result in submission invalidation or team disqualification:

- Accessing private tasks, hidden expectations, verifier solutions, or organizer-only materials.
- Making hidden verifier files available to the agent during execution.
- Hard-coding private task answers or task-specific final outputs.
- Submitting a reward that was not produced by the official verifier.
- Submitting an all-passing result file when the corresponding trials did not pass.
- Fabricating, deleting, or materially altering execution evidence.
- Using multiple Kaggle accounts or proxy accounts.
- Sharing private competition code or private data between teams.
- Attempting to interfere with Kaggle, χ-Bench infrastructure, other participants, or the evaluation process.
- Introducing real patient data or other unlawfully obtained information.
- Failing to disclose material external models, tools, or data.

General workflow logic, reusable healthcare knowledge, and improvements derived from public development tasks are permitted. The prohibition concerns answer leakage, falsification, and task-specific circumvention.

### 9. Public Kaggle evaluation

The public competition uses the 75 core tasks from the announced χ-Bench dataset version, initially `chi-bench-v1.0.0`.

Each task must be run once for the submitted result. Its value is taken directly from `verifier/reward.json`:

- `1` means the trial passed every required non-N/A check.
- `0` means one or more required checks failed.

Fractional diagnostic scores are not accepted as competition rewards.

The Kaggle submission file must contain exactly one row for every required task:

```csv
task_id,reward
cm_afib_moderate_anxious_001,1
pa_t008_t008_o002_p01_mdreview_payer,0
```

Requirements:

- `task_id` must match the official task identifier.
- `reward` must be either `0` or `1`.
- Every required task must appear exactly once.
- No additional rows or duplicate task identifiers are permitted.

Kaggle Accuracy will be configured against a target value of `1` for every row. With binary rewards, this equals:

\[
\mathrm{Public\ Pass@1}
=\frac{\text{number of tasks with reward 1}}{75}.
\]

Because participants run the benchmark themselves, the Kaggle score is a provisional, evidence-backed claim. It does not by itself establish prize eligibility.

Teams may make up to five Kaggle submissions per day and must select one final submission before the deadline.

### 10. Official verifier

The official verifier combines:

1. deterministic contract checks covering terminal state, routing, structured payloads, and required artifacts; and
2. rubric-based judging of policy grounding and clinical or operational reasoning.

Unless announced otherwise before the final-system freeze:

- the LLM judge will be pinned to `claude-opus-4-7`;
- the patient simulator will be pinned to `claude-sonnet-5`;
- each rubric will receive three independent judge votes;
- the majority result determines the rubric verdict; and
- a task receives reward `1` only when all required non-N/A checks pass.

The primary score is strict binary pass@1. Fractional reward may be retained for diagnostics but will not affect ranking.

An agent timeout, API failure, malformed output, or participant-infrastructure failure normally produces a failed trial. A trial may be rerun only when the organizers determine that an organizer-controlled infrastructure failure prevented valid execution. Reruns will not be granted because an agent made an incorrect decision.

### 11. Finalist audit and private evaluation

Every team that submits a complete runnable system, evidence packet, source code, qualifying report, and valid Kaggle entry by the deadline receives a private score. Organizer-run private results determine official standings.

For eligibility, each team must privately provide:

- the official χ-Bench audit packet produced through `cb submission prepare`;
- source code for the agent and orchestration logic;
- prompts, system instructions, tools, and configuration;
- dependency manifests and lock files;
- the exact model and API endpoint identifiers;
- a container image, image digest, or complete reproduction instructions;
- cost and token-usage records where available;
- a qualifying technical report using the IEEE conference template, no more than five pages excluding references; and
- reasonable assistance enabling organizer re-verification.

“Source code” refers to the participant-created agent and orchestration components. It does not require disclosure of proprietary third-party model weights or source code that the participant does not own.

The organizer's [submission clarification](https://www.kaggle.com/competitions/chi-bench/discussion/745236)
specifies delivery to `research@actava.ai`, with `[Kaggle]` in the email subject
and team information included. The complete package is due November 15;
December 7 is for prize winners' conference materials. Forum participation is
not required. Credentials must not be placed in Kaggle submissions or repositories.

The organizer's [API-cost clarification](https://www.kaggle.com/competitions/chi-bench/discussion/741283)
states that participants fund development, with no sponsored token credits, and
that organizers pay all API costs during private evaluation.

Failure to provide complete materials, or inability to execute the submitted system within the verification period, may result in removal from consideration.

The organizers will evaluate all eligible systems on the private held-out task set. Private evaluation results supersede the provisional Kaggle public leaderboard and determine official standings and prizes.

Submission to the separate [χ-Bench evidence leaderboard](https://github.com/actava-ai/leaderboard) is encouraged but is not a substitute for the required Kaggle entry.

### 12. Final scoring and tie-breaking

For each eligible team, the organizers will conduct three independent attempts per private task using the frozen submitted system.

The primary score uses only the first attempt:

\[
\mathrm{Pass@1}
=\frac{1}{N}\sum_{i=1}^{N}r_{i,1},
\]

where \(r_{i,1}\in\{0,1\}\) and \(N\) is the number of private tasks.

Ties in overall pass@1 will be resolved in this order:

1. Higher pass³:

\[
\mathrm{Pass^3}
=\frac{1}{N}\sum_{i=1}^{N}
\mathbf{1}(r_{i,1}=r_{i,2}=r_{i,3}=1).
\]

2. Lower mean agent inference cost, calculated from recorded usage and the organizer’s frozen price table.
3. Fewer mean agent tool calls per task.
4. Earlier valid final Kaggle submission.

If inference costs are unavailable or not meaningfully comparable for either tied system, the cost tie-breaker will be skipped and tool-call count will be used next.

Unrounded scores will be used for ranking.

### 13. Prizes

The stated prize pool is USD 3,000:

- Gold — first overall: USD 1,500
- Silver — second overall: USD 1,000
- Bronze — third overall: USD 500
- Reliability Award — highest private pass³ score

The Reliability Award is a separate recognition and may be awarded to an overall medalist. No additional cash amount beyond the stated USD 3,000 pool is attached to it unless separately announced.

Prize eligibility requires successful private verification, submission of source code and the qualifying report, and compliance with these Rules.

Teams are responsible for taxes, reporting obligations, and any documentation required to receive a prize. Unless the team unanimously supplies different written instructions, a monetary team prize will be divided equally among eligible team members.

### 14. Reports, presentation, and publication

Finalists may be invited to:

- present their systems at IEEE Big Data 2026 in Phoenix;
- contribute to a post-competition community results report; and
- extend their work into a conference or proceedings submission.

At least one team representative should be available to present in person or through an organizer-approved remote format. Travel, accommodation, and conference registration are not guaranteed unless separately announced.

Participants retain ownership of their original code and methods. By entering, participants grant the organizers permission to evaluate their submission and publish the team name, system description, scores, rankings, and qualifying report. Private source code will not be publicly released without the owner’s permission, except where a separately accepted award or publication agreement requires it.

Authorship on any community report will follow normal scholarly contribution and approval requirements and is not automatically granted by placement alone.

### 15. Organizer authority

The organizers may:

- inspect or re-judge submitted evidence;
- require clarification or additional reproduction materials;
- invalidate suspicious or unsupported submissions;
- correct scoring or infrastructure errors;
- disqualify participants who violate these Rules;
- withhold an award if no eligible submission satisfies the verification requirements; and
- amend these Rules when necessary for fairness, security, legal compliance, or platform requirements.

Material changes will be announced publicly. Whenever practical, changes affecting evaluation will be made before the final-system freeze and applied consistently to all teams.

Organizer decisions concerning eligibility, verification, scoring, and rule enforcement are final, subject to Kaggle requirements and applicable law.

### 16. Medical disclaimer and contact

χ-Bench is a research benchmark using simulated healthcare workflows. It is not a medical device, does not provide medical advice, and must not be used to make decisions about real patients.

Questions should be posted in the Kaggle discussion forum or sent to [research@actava.ai](mailto:research@actava.ai).

---

## Source notes

The [Kaggle Rules](https://www.kaggle.com/competitions/chi-bench/rules) supply the competition policy; the [Overview](https://www.kaggle.com/competitions/chi-bench/overview) also specifies the simulator configuration. See the [local overview](kaggle-challenge-overview.md) for setup and submission commands.

The Kaggle header says “IEEE Big Data Cup 2027,” while its rules, overview, and
dates describe 2026. The submission discussion clarifies the November 15
final-package deadline and December 7 conference-material deadline. Its
follow-up about whether email delivery also requires a Kaggle CSV or Writeup
remains unanswered; Section 9 above retains the published CSV requirements.
