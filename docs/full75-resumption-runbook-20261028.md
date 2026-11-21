# Full75 resumption runbook (2026-10-28)

Status: PREPARATION ONLY. REFROZEN remains active. No rejudge, paid agent, ledger write, freeze lift, cap change, or submission is authorized by this document.

## 1. Verified current state

- chi-full75.service: inactive, disabled; last exit code 1.
- chi-budget-proxy.service: active; cap USD 45.00.
- Budget proxy: net 44.184703, gross 71.760634, adjustments -27.575931, safe margin 0.815297 USD.
- REFROZEN: present.
- Provider: 24 verified, 1 interrupted (`pa_t012`), 1 rejudged (`pa_t013`), 0 pending.
- Payer: 5 verified, 1 incomplete (`pa_t015`), 19 unlaunched.
- Care: 0 verified, 25 pending.
- Accumulated binary score: 15/75. Rejudge `pa_t013`: binary 0.0, fractional 0.9230769231.

## 2. Missing billing exports

OpenAI:
- Export by UTC date-hour, model, project, and API key for the exact Full75 period.
- Required project identity for the key used by Full75; the supplied screenshot is "Default project" only.
- Confirm whether `gpt-5.6-luna` and `gpt-5.4-mini` calls are in that project or another.
- Separate cached input/output and any discounts/credits.

Anthropic:
- Export by UTC date-hour, model, workspace/API key, and organization for the exact Full75 period.
- The supplied evidence covers "Ultimos 7 dias" for an individual organization and includes possible non-Full75 usage.
- Separate `claude-opus-4-7` judge calls and `claude-sonnet-5` simulator calls.
- Confirm whether the individual organization is the one used by Full75.

Cross-provider:
- Exact Full75 start/stop UTC, account/project identity, prepaid credits vs expense, and cached token pricing.
- Reconcile exports against proxy ledger entries without double-counting the existing -38.395131 adjustment.

## 3. Accounting position

- Gross ledger: 71.760634 USD.
- Net after adjustments: 44.184703 USD.
- Safe margin: 0.815297 USD.
- Provisional judge ceilings: 10.8192 USD, not measured and not spendable.
- Potential margin if ceilings were verified: 11.634497 USD, not approved.
- USD 39.274703 difference between proxy net and displayed console totals is not approved recovery.

Compensating entries remain proposed only:
- `reconcile:20261028-provider-console-verified`
- `reconcile:20261028-judge-provisional-correction` (currently 0 USD recoverable)
- `reservation:20261028-payer-t015-rejudge` (only with approved judge spend)

## 4. Payer t015 recovery without replay

- Agent phase completed; deterministic checks passed 37/45.
- Judge failed with `VerdictsParseError` because the verdicts file stayed empty after HTTP 402 budget_exhausted.
- The eight pending judge rubrics are:
  - nurse_review:mmp109_18_qualifying_indication
  - nurse_review:mmp109_18_prior_cardiac_workup
  - nurse_review:mmp109_18_fda_clearance
  - nurse_review:mmp109_18_device_type_appropriateness
  - nurse_review:recommendation
  - md_review:mmp109_18_device_type_appropriateness_md
  - md_review:final_decision
  - md_review:decision_rationale
- No schema relaxation or verdict invention is permitted.
- Rejudge without replay is feasible only after confirmed budget headroom and explicit approved judge spend.

## 5. Resumption procedure for pending work

Payer:
1. Reconcile t015 through approved no-replay rejudge after judge schema/budget gates.
2. Resume unlaunched Payer tasks t016-t036 in original order, one task at a time.
3. Require `backup_offhost` success before admitting the next task.
4. Stop immediately on incomplete task, API limit, backup failure, or budget denial.

Care:
1. Start only after Payer is reconciled or explicitly paused by operator.
2. Run Care tasks in official order, one task at a time.
3. Use existing checkpoints and never overwrite existing trials.
4. Preserve all completed task receipts and interrupted markers.

Controls:
- Concurrency must remain 1.
- `PAID_RUN_FREEZE.json` must be explicitly unfrozen by operator after preflight.
- `API_LIMIT_STOP.json` must be absent before launch.
- Every task must seal and back up before the next task starts.
- Restore only via `restore_task` into a non-existing destination.

## 6. Offline validation already executed

- tests/test_budget_proxy_v2.py: 11 passed.
- tests/test_judge_guard_and_routing.py: 13 passed.
- tests/test_payer_t015_judge_schema_regression.py: 7 passed.
- Total: 31 passed.
- review_budget_readonly.py matches /budget exactly.
- inventory_payer_judge_usage_readonly.py found no measured judge usage.

## 7. What can be executed now

- Offline tests and read-only budget/judge inventory.
- Schema and reconciliation analysis without network spend.
- Documentation and runbook updates in Draft.

## 8. What is actually available

- Safe spendable margin: 0.815297 USD.
- No approved recovery from 10.8192 USD provisional ceilings.
- No approved recovery from 39.274703 USD console difference.

## 9. Exact condition to resume

Full75 may resume only when all of the following are true:
1. REFROZEN is removed by explicit operator action.
2. Paid-run preflight passes with the existing USD 45 cap.
3. OpenAI/Anthropic billing exports are reconciled by UTC date-hour, model, project/workspace, and source.
4. Net spend plus required judge/task ceilings remains <= 45.00 USD.
5. Payer t015 has confirmed budget headroom and approved judge spend.
6. All pending tasks have valid contracts, checkpoints, and backup paths.
7. Offline tests pass immediately before launch.

Until then, keep Full75 refrozen and do not execute paid work.
EOF