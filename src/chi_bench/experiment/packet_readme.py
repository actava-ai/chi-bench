"""Render the per-submission README.md committed alongside a packet."""

from __future__ import annotations

from typing import Any

_TEMPLATE = """\
# {team} · {agent} · {model}

Submitted: {date} · {bench_name} {bench_version} · pass@1: **{overall_pct}%**

| Domain | pass@1 | n_trials |
|---|---|---|
{rows}

Inspect a trajectory:

    zstdcat trials/{first_domain}/<trial_id>/agent/trajectory.jsonl.zst | jq .

See `submission.json` for the full manifest, `provenance.json` for reproducibility info.
"""


def render_packet_readme(manifest: dict[str, Any]) -> str:
    sub = manifest["submission"]
    ds = manifest["dataset"]
    res = manifest["results"]

    submitted_at: str = sub["submitted_at"]
    date = submitted_at.split("T", 1)[0]

    overall_pct = f"{res['overall']['pass_at_1'] * 100:.1f}"

    domains: list[str] = list(ds.get("domains") or [])
    per_dom = res.get("per_domain") or {}
    rows: list[str] = []
    for dom in domains:
        if dom not in per_dom:
            continue
        d = per_dom[dom]
        pct = f"{d['pass_at_1'] * 100:.1f}"
        rows.append(f"| {dom} | {pct}% | {d['n_trials']} |")
    rows_text = "\n".join(rows)

    first_domain = domains[0] if domains else "pa_provider"

    return _TEMPLATE.format(
        team=sub["team"],
        agent=sub["agent"],
        model=sub["model"],
        date=date,
        bench_name=ds["name"],
        bench_version=ds["version"],
        overall_pct=overall_pct,
        rows=rows_text,
        first_domain=first_domain,
    )
