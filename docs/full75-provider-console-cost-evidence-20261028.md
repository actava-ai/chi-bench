# Full75 — external provider cost evidence (2026-10-28)

Status: RECONCILIATION INCOMPLETE; READ ONLY. Do not lift REFROZEN.

## Evidence supplied by owner

- OpenAI Platform Usage screenshot, 2026-10-28: "Total Spend" USD 2.40, daily chart Oct 28; **Default project** selected, not necessarily all projects/organizations. Date range/other filters not fully visible.
- Anthropic Claude Console Cost screenshot, 2026-10-28 18:48 UTC refresh: "Costo total" USD 2.51, range "Últimos 7 días", workspace/API key/model/agent filters "Todos"; organization shown is the user's individual org.
- Combined displayed costs: USD 4.91. These are not guaranteed to represent identical time periods, projects or all billable calls, so DO NOT equate to Full75 final costs or use them as direct ledger adjustments.
- Existing benchmark proxy at stop: net USD 44.184703, gross USD 71.760634, net adjustments -27.575931, cap USD 45, safe margin USD 0.815297.
- Approximate difference between proxy net and displayed console totals: USD 39.274703 (NOT APPROVED RECOVERY).
- Prior adjustment includes two unmetered judge ceilings USD 10.8192. Judge task-level usage not stored, and rejudge t013's measured cost cannot be substituted for unrelated calls.

## Next safe reconciliation

1. Establish exact Full75 start/stop UTC and API organization/project identity per request from sanitized local routing configs. Do not publish API keys or patient data.
2. Export **cost/usage** by UTC date-hour, model, project/workspace, and source (API vs console) from OpenAI/Anthropic, accounting for possible latency and other users/projects.
3. Reconcile those reports against each proxy-ledger entry, cached input/output, prior corrections, and unmetered judge/simulator traffic. Separate funds added by prepaid recharge from usage expense; distinguish discounts and prior credits.
4. Propose a single audited compensating entry ONLY for positively reconciled, bounded costs, preserving gross ledger and previous adjustments. Require offline tests, no active calls, rollback, approval for ledger write. Do not double-count existing -27.575931 adjustment.
5. For Payer t015: 402 budget_exhausted caused empty judge verdicts; no schema fix needed. A no-replay rejudge is possible only after confirmed budget headroom and explicit approved judge spend.
6. Maintain frozen=true, cap USD45, no rejudge, restart, agent replay, or submission until the above gates are met.

This document is not evidence of actual full-account/full-period cost and does not authorize spending.
