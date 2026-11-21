#!/usr/bin/env python3
"""Read-only Full75 budget review. Never starts a judge or edits a ledger."""
import argparse
import json
from pathlib import Path

def inspect(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    gross = float(d.get("spent", 0))
    adjustments = d.get("adjustments") or []
    signed = sum(float(a.get("usd", 0)) for a in adjustments)
    persisted = float(d.get("adjustments_usd", signed))
    cap = float(d.get("cap", 45))
    reserved = d.get("reserved") or {}
    reserved_usd = sum(float(x) for x in reserved.values()) if isinstance(reserved, dict) else 0.0
    net = gross + signed
    details = [{"reason": str(a.get("reason", ""))[:120], "usd": float(a.get("usd", 0))}
               for a in adjustments]
    provisional = sum(v["usd"] for v in details if any(
        w in v["reason"].lower() for w in ("provisional", "unmetered", "ceiling", "judge")) and v["usd"] > 0)
    # Provisional judge ceilings are already included in net.  They are not
    # evidence of billed cost, so they are reported separately; only the margin
    # after all recorded adjustments is safe to spend.
    remaining_safe = cap - net - reserved_usd
    remaining_before_unmetered = cap - (net - provisional) - reserved_usd
    result = {"cap": cap, "gross": round(gross, 6), "adjustments": details,
              "adjustment_sum": round(signed, 6), "persisted_adjustments_usd": round(persisted, 6),
              "net": round(net, 6), "reserved": round(reserved_usd, 6),
              "remaining_safe_usd": round(remaining_safe, 6),
              "remaining_before_unmetered_usd": round(remaining_before_unmetered, 6),
              "remaining_before_unmetered": round(remaining_before_unmetered, 6),
              "provisional_ceiling_usd": round(provisional, 6),
              "provisional_by_reason": round(provisional, 6),
              "warning": "Only remaining_safe_usd is spendable. Do NOT treat remaining_before_unmetered_usd or provisional ceilings as available budget without measured billing evidence."}
    if abs(persisted - signed) > 0.00001:
        result["inconsistency"] = "reported adjustments sum differs from ledger entries"
    return result

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--ledger", required=True, type=Path)
    args = p.parse_args()
    print(json.dumps(inspect(args.ledger), indent=2))
