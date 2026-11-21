# CHI-Bench Full75 recovery evidence (2026-10-28)

Status: STOPPED / BLOCKED. No service restart, task execution, rejudge, or ledger change was performed for this audit.

## 1. Run state

- `chi-full75.service`: inactive (dead), disabled; last exit code 1 at 2026-10-28 19:00:03 UTC.
- `chi-budget-proxy.service`: active (running), cap USD 45.00.
- Budget proxy endpoint: spent_usd=44.184703, gross_spent_usd=71.760634, adjustments_usd=-27.575931, calls=1033, denied=13, inflight=0.
- No Full75 task is currently running. REFROZEN is present; launcher exits immediately.

## 2. Task accounting

- Provider: 25 attempted / 24 valid judge evaluations / 1 interrupted (pa_t012_t012_o001_p01_new_referral_provider) / 0 pending.
- Payer: 6 attempted / 5 valid / 1 incomplete (pa_t015_t015_o002_p01_intake_payer) / 19 pending.
- Care: 0 attempted / 0 valid / 0 interrupted / 25 pending.
- Reward files with reward=1.0: 15 (Provider 12, Payer 3). Accumulated binary score: 15/75.
- Rejudge pa_t013_t013_o002_p01_new_referral_provider: valid, binary reward 0.0, fractional reward 0.9230769231.

## 3. Payer t015 root cause

- Agent phase completed normally. All deterministic checks passed (37/45).
- Judge phase failed with VerdictsParseError: rubric_verdicts must contain exactly the requested rubric IDs.
- Classification: judge-side schema/parse failure, not agent failure, infrastructure outage, or budget denial.
- Agent result is complete enough for a no-replay rejudge in principle, subject to operator approval and paid-judge authorization.

## 4. Missing backup audit

- Remote backups: 23/25 Provider, 5/6 Payer.
- Provider missing: pa_t012... (interrupted, no sealed receipt by design) and pa_t013... (judge-invalid original; later rejudged, verdict backed up separately).
- Payer missing: pa_t015... (incomplete judge-parse failure, no sealed receipt).
- No sealed task backup is missing. Missing entries are consistent with fail-closed receipt policy.

## 5. Proxy spend reconciliation

- Proxy net spend: USD 44.184703 against USD 45.00 cap; margin USD 0.815297.
- Adjustments: -38.395131 reconciliation (codex rollout usage x litellm prices, first batch) plus two provisional +5.4096 judge-unmetered ceilings.
- Local agent rollout usage estimate: approximately USD 17.86 for 31 agent sessions; this is a lower bound and excludes judge/simulator traffic.
- Provider billing statements are not available in this environment. The proxy net value is an accounting estimate, not proof of billed cost.

## 6. Margin recovery assessment

- The two +5.4096 entries are conservative ceilings, not measured judge costs.
- Rejudge pa_t013 measured judge cost was USD 1.725289, materially below the provisional ceiling, but no measured judge costs exist for the two affected tasks.
- No safe margin recovery is authorized now. Replacing provisional ceilings requires measured evidence and operator approval.
- Global limit remains USD 45.00.

## 7. Recovery plan (no execution)

1. Keep freeze active; do not restart Full75.
2. Reconcile t015 through an approved no-replay rejudge only after judge schema fix and budget check.
3. Reconcile t013 backup/receipt state as rejudged; do not replay agent.
4. Leave t012 retired as interrupted.
5. Before any Payer/Care continuation, verify margin >= required ceiling plus safety buffer; otherwise stop.
6. Restore from existing checkpoints only via restore_task (no overwrite).
7. Run offline tests before any paid authorization:
   - tests/test_budget_proxy_v2.py
   - tests/test_judge_guard_and_routing.py

## 8. Offline validation

- tests/test_budget_proxy_v2.py: 11 passed.
- tests/test_judge_guard_and_routing.py: 13 passed.

## 9. Required operator decisions

- Approve or reject no-replay rejudge for t015.
- Decide whether to fund additional judge calls within the remaining USD 45 cap.
- Confirm whether to attempt auditable adjustment of provisional judge ceilings.
EOF