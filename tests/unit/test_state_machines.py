"""Smoke tests for the Prior Authorization and Care Management state machines.

Both state machines are exposed as a module-level transition table plus an
``assert_*_transition_allowed`` helper that raises a domain-specific
``Invalid*TransitionError`` for illegal transitions. These tests pin the
core invariants for each:

PA (``chi_bench.core.state_machine``):

1. ``DRAFT`` is the natural starting point (it has outgoing transitions
   but no other status leads into it).
2. ``DRAFT -> REQUIREMENT_CHECKED`` is a legal transition.
3. ``DRAFT -> APPROVED`` is illegal and raises.

CM (``chi_bench.core.cm_state_machine``):

1. ``NEW`` is the natural starting point and ``CLOSED`` / ``DISENROLLED``
   are terminal (no outgoing edges).
2. ``NEW -> INTAKE_COMPLETE`` is a legal transition.
3. ``NEW -> CARE_PLAN_FINALIZED`` is illegal (skip-ahead) and raises.
"""

from __future__ import annotations

import pytest

from chi_bench.core.cm_enums import CMCaseStatus
from chi_bench.core.cm_state_machine import (
    ALLOWED_CM_CASE_TRANSITIONS,
    InvalidCMTransitionError,
    assert_cm_transition_allowed,
)
from chi_bench.core.enums import CaseStatus
from chi_bench.core.errors import InvalidCaseTransitionError
from chi_bench.core.state_machine import (
    ALLOWED_CASE_TRANSITIONS,
    assert_transition_allowed,
)


def test_draft_is_the_initial_status() -> None:
    """DRAFT has outgoing transitions and is never the target of one."""
    assert CaseStatus.DRAFT in ALLOWED_CASE_TRANSITIONS
    assert ALLOWED_CASE_TRANSITIONS[CaseStatus.DRAFT], (
        "DRAFT should have at least one outgoing transition"
    )
    for source, targets in ALLOWED_CASE_TRANSITIONS.items():
        assert CaseStatus.DRAFT not in targets, (
            f"No status should be allowed to transition back to DRAFT, "
            f"but {source} -> DRAFT is in the table"
        )


def test_draft_to_requirement_checked_is_legal() -> None:
    """A representative legal transition should not raise."""
    assert CaseStatus.REQUIREMENT_CHECKED in ALLOWED_CASE_TRANSITIONS[CaseStatus.DRAFT]
    # Should not raise.
    assert_transition_allowed(CaseStatus.DRAFT, CaseStatus.REQUIREMENT_CHECKED)


def test_draft_to_approved_is_illegal() -> None:
    """A skip-ahead transition should be rejected."""
    assert CaseStatus.APPROVED not in ALLOWED_CASE_TRANSITIONS[CaseStatus.DRAFT]
    with pytest.raises(InvalidCaseTransitionError):
        assert_transition_allowed(CaseStatus.DRAFT, CaseStatus.APPROVED)


# --- Care Management state machine -----------------------------------------


def test_cm_new_is_initial_and_closed_is_terminal() -> None:
    """NEW has outgoing edges and is never a target; CLOSED/DISENROLLED are terminal."""
    assert CMCaseStatus.NEW in ALLOWED_CM_CASE_TRANSITIONS
    assert ALLOWED_CM_CASE_TRANSITIONS[CMCaseStatus.NEW], (
        "NEW should have at least one outgoing transition"
    )
    for source, targets in ALLOWED_CM_CASE_TRANSITIONS.items():
        assert CMCaseStatus.NEW not in targets, (
            f"No status should transition back to NEW, but {source} -> NEW is in the table"
        )
    # Both CLOSED and DISENROLLED are terminal: no outgoing transitions.
    assert ALLOWED_CM_CASE_TRANSITIONS[CMCaseStatus.CLOSED] == set()
    assert ALLOWED_CM_CASE_TRANSITIONS[CMCaseStatus.DISENROLLED] == set()


def test_cm_new_to_intake_complete_is_legal() -> None:
    """A representative legal CM transition should not raise."""
    assert CMCaseStatus.INTAKE_COMPLETE in ALLOWED_CM_CASE_TRANSITIONS[CMCaseStatus.NEW]
    # Should not raise.
    assert_cm_transition_allowed(CMCaseStatus.NEW, CMCaseStatus.INTAKE_COMPLETE)


def test_cm_new_to_care_plan_finalized_is_illegal() -> None:
    """A skip-ahead CM transition should be rejected."""
    assert CMCaseStatus.CARE_PLAN_FINALIZED not in ALLOWED_CM_CASE_TRANSITIONS[CMCaseStatus.NEW]
    with pytest.raises(InvalidCMTransitionError):
        assert_cm_transition_allowed(CMCaseStatus.NEW, CMCaseStatus.CARE_PLAN_FINALIZED)
