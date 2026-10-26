"""Small, non-sensitive scoring validity records shared by result consumers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_validity(scorecard: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "scoring_status": scorecard.get("scoring_status", "valid"),
                "invalid_checks": scorecard.get("invalid_checks", []),
            },
            indent=2,
        )
    )


def trial_invalid_reason(result_path: Path) -> str | None:
    """Recognize current validity records and retained legacy judge outages.

    A complete legacy trial without validity metadata stays supported. An
    explicit invalid marker is never overridden by a scalar reward of one.
    """
    return _verifier_invalid_reason(result_path.parent / "verifier")


def _verifier_invalid_reason(verifier: Path) -> str | None:
    scorecard = {}
    for filename in ("validity.json", "scorecard.json", "session_score.json"):
        path = verifier / filename
        if not path.exists():
            continue
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            return f"unreadable {filename}"
        if not isinstance(record, dict):
            return f"malformed {filename}"
        if record.get("scoring_status", "valid") != "valid" or record.get("invalid_checks"):
            return "required verifier checks unavailable"
        if filename == "scorecard.json":
            scorecard = record
    checks = scorecard.get("checks") or {}
    if not isinstance(checks, dict):
        checks = {}
    if "unavailable" in checks.values():
        return "required verifier checks unavailable"
    unavailable_na = any(
        name.startswith(("judge.", "cm_rubric.")) and value == "not_applicable"
        for name, value in checks.items()
    )
    if unavailable_na:
        records = [scorecard]
        context_path = verifier / "verifier_context.json"
        if context_path.exists():
            try:
                records.append(json.loads(context_path.read_text()))
            except (OSError, ValueError):
                return "unreadable legacy judge context"
        for context in records:
            if not isinstance(context, dict):
                return "malformed legacy judge context"
            metadata = context.get("judge_session_metadata") or {}
            if not isinstance(metadata, dict):
                return "malformed legacy judge metadata"
            if (
                context.get("judge_unavailable_reason")
                and metadata.get("skipped") != "no_submit_e2e_path"
            ):
                return "legacy required judge unavailable"
    task_scores = verifier / "task_scores"
    if task_scores.is_dir():
        for task in task_scores.iterdir():
            if task.is_dir():
                reason = _verifier_invalid_reason(task)
                if reason:
                    return f"session task {task.name}: {reason}"
    return None


def require_valid_trial(result_path: Path) -> None:
    reason = trial_invalid_reason(result_path)
    if reason is not None:
        raise ValueError(
            f"invalid trial {result_path.parent.name}: {reason}; rejudge or rerun before aggregation/submission"
        )
