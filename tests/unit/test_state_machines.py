"""Smoke tests for the Prior Authorization case state machine.

The state machine is exposed as a module-level transition table
(``ALLOWED_CASE_TRANSITIONS``) plus an ``assert_transition_allowed``
helper that raises :class:`InvalidCaseTransitionError` for illegal
transitions. These tests pin the core invariants:

1. ``DRAFT`` is the natural starting point (it has outgoing transitions
   but no other status leads into it).
2. ``DRAFT -> REQUIREMENT_CHECKED`` is a legal transition.
3. ``DRAFT -> APPROVED`` is illegal and raises.
"""

from __future__ import annotations

import pytest

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
