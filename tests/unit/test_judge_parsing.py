"""Smoke test for :meth:`WorkspaceJudge._parse_verdicts`.

The workspace judge is the most-touched runtime component for scoring
trials: every rubric verdict flows through this JSON parsing path. This
test pins the happy-path contract:

1. A ``verdicts.json`` with two ``rubric_verdicts`` entries — one passing,
   one failing — round-trips into a :class:`JudgeOutput`.
2. The passing rubric exposes ``passed = True``.
3. The failing rubric exposes ``passed = False``.
4. No ``judge_unavailable_reason`` is set when every requested rubric is
   present in the parsed output.

The real method is keyword-only and takes a full :class:`JudgeInput`
rather than the parameter list sketched in the implementation plan; this
test adapts to the actual signature.
"""

from __future__ import annotations

import json
from pathlib import Path

from chi_bench.verifier.judge.types import JudgeInput
from chi_bench.verifier.judge.workspace_judge import WorkspaceJudge


def _make_judge_input(case_id: str = "test-case") -> JudgeInput:
    return JudgeInput(
        case_identifier=case_id,
        rubrics=(
            {"rubric_id": "r_clinical_decision", "description": "..."},
            {"rubric_id": "r_documentation", "description": "..."},
        ),
        canonical_case_record={},
        policy_paths=(),
        agent_outputs={},
        audit_logs=(),
        domain="pa_um",
        contract="contract_v5",
    )


def test_parse_verdicts_minimal(tmp_path: Path) -> None:
    workspace_dir = tmp_path
    verdicts_payload = {
        "rubric_verdicts": {
            "r_clinical_decision": {
                "pass": True,
                "explanation": "MD review approved",
                "evidence_refs": ["audit:42"],
            },
            "r_documentation": {
                "pass": False,
                "explanation": "missing chart note",
                "evidence_refs": [],
            },
        },
        "session_metadata": {"model": "claude-opus-4-7", "n_turns": 12},
    }
    (workspace_dir / "verdicts.json").write_text(json.dumps(verdicts_payload))

    # Skip __init__ — it constructs a real ClaudeAgentRunner which needs
    # the Claude CLI installed. _parse_verdicts only uses `self` as a
    # method binding, not for any instance state.
    judge = WorkspaceJudge.__new__(WorkspaceJudge)

    output = judge._parse_verdicts(
        judge_input=_make_judge_input(),
        workspace_dir=workspace_dir,
        duration_s=1.23,
        unavailable_reason=None,
    )

    assert "r_clinical_decision" in output.verdicts
    assert "r_documentation" in output.verdicts
    assert output.verdicts["r_clinical_decision"].passed is True
    assert output.verdicts["r_documentation"].passed is False
    assert output.judge_unavailable_reason is None
    assert output.degraded_rubric_ids == ()
