# Full75 final reconciliation plan (2026-10-28)

Status: READ ONLY / RECONCILIATION INCOMPLETE. Full75 remains refrozen. No ledger write, rejudge, agent run, paid call, freeze lift, or cap change is authorized by this document.

## Evidence supplied

- OpenAI Platform Usage screenshot, 2026-10-28: "Total Spend" USD 2.40, daily chart Oct 28, **Default project** selected. Other projects/organizations and exact date range are not fully visible.
- Anthropic Claude Console Cost screenshot, 2026-10-28 18:48 UTC: "Costo total" USD 2.51, range "Ultimos 7 dias", workspace/API key/model filters "Todos", individual organization.
- Combined displayed cost: USD 4.91. This is not guaranteed to represent identical periods, projects, accounts, or all billable calls.

## Local Full75 configuration

- Agent model: openai/gpt-5.6-luna (Provider/Payer), openai/gpt-5.4-mini (Care, not run).
- Judge model: claude-opus-4-7.
- Simulator models: claude-sonnet-5.
- All traffic routes through the CHI budget proxy (`OPENAI_BASE_URL=http://host.docker.internal:18045/openai/v1`, `ANTHROPIC_BASE_URL=http://host.docker.internal:18045/anthropic`).
- The local configuration does not record an OpenAI project ID or Anthropic organization ID. The OpenAI screenshot is limited to "Default project"; the Anthropic screenshot is an individual organization over 7 days.

## Ledger at stop

- cap: USD 45.00
- gross_spent_usd: 71.760634
- adjustments_usd: -27.575931
- net_spent_usd: 44.184703
- safe_margin_usd: 0.815297
- adjustments:
  - reconcile:20261028-real-usage: -38.395131 (rollout usage x litellm prices, first batch only)
  - provisional:judge-unmetered:pa_t008: +5.4096
  - provisional:judge-unmetered:pa_t011: +5.4096

## What the external evidence can cover

- Potentially some OpenAI-routed agent calls if the API key belongs to the Default project shown and the date range is Oct 28 UTC.
- Potentially some Anthropic-routed judge/simulator calls if the API key belongs to the individual organization shown and the calls occurred within the last 7 days.
- The USD 4.91 total is far below proxy net USD 44.184703, so it cannot validate the ledger by itself.

## What remains unverified

- OpenAI project/account identity and whether Default project is the project used by Full75.
- Anthropic organization/workspace identity and whether the individual org is the one used by Full75.
- Exact UTC date-hour alignment and console refresh latency.
- Other projects, workspaces, API keys, or users in the same accounts.
- Prepaid credits, discounts, taxes, and cached token pricing.
- Costs for judge and simulator calls, including the two provisional ceilings.
- Payer t015 judge call returned HTTP 402 and has no billable verdict.
- Care domain has not run.

## Proposed compensating entries (not applied)

No entry is authorized now. The following are the only allowable forms after verification:

1. `reconcile:20261028-provider-console-verified`
   - usd = verified_full75_console_total - already_reconciled_portion
   - Must not double-count the existing -38.395131 adjustment.
   - Must be supported by UTC date-hour, model, project/workspace exports.
   - Must keep net <= 45.00.

2. `reconcile:20261028-judge-provisional-correction` (only if measured judge costs exist)
   - usd = measured_judge_cost - provisional_ceiling
   - Currently 0 USD recoverable because no measured original judge costs exist.
   - Rejudge t013 measured cost (1.725289 USD) is not transferable to pa_t008 or pa_t011.

3. `reservation:20261028-payer-t015-rejudge` (only if approved)
   - usd = approved judge spend estimate
   - Must be added only with explicit operator approval and confirmed headroom.

## Safe margin

- Safe margin today: USD 0.815297.
- The USD 39.274703 difference between proxy net and displayed console totals is not approved recovery.
- The USD 10.8192 provisional ceilings are not released.

## Required gates before any continuation

1. Exact UTC start/stop and account/project identity for every Full75 request.
2. Cost/usage exports by date-hour, model, project/workspace, and source.
3. Reconciliation against proxy ledger entries, cached tokens, prior corrections, and unmetered judge/simulator traffic.
4. Single audited compensating entry, preserving gross ledger and previous adjustments.
5. Offline tests, rollback plan, approval for ledger write, no active calls.
6. For Payer t015: confirmed budget headroom and approved judge spend before no-replay rejudge.

## Blockers

- External console evidence is incomplete in period, project, account, and cost attribution.
- No measured judge costs for provisional ceilings.
- Full75 remains refrozen.
- No safe margin beyond USD 0.815297.
EOF