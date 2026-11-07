# Full75 score-first resumption plan (2026-10-28)

Status: PREPARATION ONLY. REFROZEN remains active. No paid execution, rejudge, submission, or main merge is authorized by this document.

## Score baseline

- Provider: 12/25.
- Payer: 3/6 attempted; t015 interrupted during judge.
- Care: 0/25.
- Total verified positive: 15/75.
- Target: exceed official baseline 20/75; initial target 21/75.

## Observed failure patterns

Provider:
- 11 tasks lost `new_referral.case_status`.
- 7 tasks lost `site_of_service`.
- 6 tasks lost `provider_pre_submission.final_action`.
- 4 tasks failed all intake checks (`pa_t011`, `pa_t014`, `pa_t022`) due to agent execution failure, not rubric design.
- 2 tasks lost `required_documents_present`.
- 2 tasks lost closed-loop provider determination checks.

Payer:
- `pa_t011` lost all 12 judge rubrics and terminal outcome checks.
- `pa_t014` lost `triage.disposition_matches`.
- `pa_t015` lost all 8 judge rubrics because the judge session returned HTTP 402 and left an empty verdicts file.

Care:
- No attempts yet; 25 tasks pending.

## Profile to retain

- Keep Provider model `openai/gpt-5.6-luna` with high reasoning effort.
- Keep concurrency 1.
- Keep terminal closure guards and site-of-service resolution rules.
- Keep no-replay handling for interrupted/rejudged tasks.
- Keep remote backup after every sealed task.

## Profile changes for Payer and Care

- Payer: require triage disposition to be reconciled before terminal determination; use the existing payer terminal guard for every terminal decision.
- Care: use `openai/gpt-5.4-mini` with high reasoning effort to control cost; preserve all terminal guards.
- Do not change rubrics, expected outcomes, or official verifier behavior.
- Do not replay completed or rejudged tasks.

## Payer t015 recovery without replay

- Agent result is complete.
- Rejudge requires budget headroom and explicit approved judge spend.
- Pending judge rubrics: 8 nurse/MD review rubrics.
- No schema relaxation is permitted.

## Execution strategy

Priority order:
1. Reconcile t015 if approved.
2. Run Payer t016-t036 in official order.
3. Run Care tasks in official order.
4. Stop on any incomplete task, API limit, backup failure, or budget denial.

Budget control:
- Cap remains USD 45.00.
- Safe margin today: 0.815297 USD.
- Required margin before Payer resumption: at least one judge ceiling plus task agent cost.
- No spend from provisional ceilings or console difference.

## Exact resumption commands (do not run until gates pass)

Provider already complete; do not rerun.

Payer, after freeze lift and preflight:
```
/opt/chi-bench/.venv/bin/python /opt/chi-bench/hg-full75/tools/run_single_task_matrix.py \
  --root /opt/chi-bench --domain payer --model openai/gpt-5.6-luna \
  --concurrency 1 --run-contract /opt/chi-bench/hg-full75/contracts/payer.json --resume \
  --output-root /opt/chi-bench/hg-full75/results \
  --backup-root /opt/chi-bench/hg-full75/staging \
  --budget-proxy http://127.0.0.1:18045 \
  --budget-proxy-container-url http://host.docker.internal:18045 \
  --rclone-remote chi-gdrive:HG-Backups/chi-bench/full75-20261028
```

Care, after Payer is reconciled or explicitly paused:
```
/opt/chi-bench/.venv/bin/python /opt/chi-bench/hg-full75/tools/run_single_task_matrix.py \
  --root /opt/chi-bench --domain care --model openai/gpt-5.4-mini \
  --concurrency 1 --run-contract /opt/chi-bench/hg-full75/contracts/care.json --resume \
  --output-root /opt/chi-bench/hg-full75/results \
  --backup-root /opt/chi-bench/hg-full75/staging \
  --budget-proxy http://127.0.0.1:18045 \
  --budget-proxy-container-url http://host.docker.internal:18045 \
  --rclone-remote chi-gdrive:HG-Backups/chi-bench/full75-20261028
```

## Offline validation

- tests/test_budget_proxy_v2.py: 11 passed.
- tests/test_judge_guard_and_routing.py: 13 passed.
- tests/test_payer_t015_judge_schema_regression.py: 7 passed.
- Total: 31 passed.

## Exact condition to continue obtaining points

1. REFROZEN removed by explicit operator action.
2. Paid-run preflight passes with cap USD 45.
3. Billing exports reconciled by UTC date-hour, model, project/workspace, and source.
4. Net spend plus required judge/task ceilings remains <= 45.00 USD.
5. Payer t015 has confirmed budget headroom and approved judge spend.
6. All pending tasks have valid contracts, checkpoints, and backup paths.
7. Offline tests pass immediately before launch.

Until then, keep Full75 refrozen and do not execute paid work.
EOF