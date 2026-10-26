"""Dual-role workflow mode must not generate a hidden single-role counterpart."""

from types import SimpleNamespace

import pytest

from chi_bench.services.p2p import P2PService


@pytest.mark.parametrize(
    "task_kind,protocol,suppressed",
    [
        ("provider_to_payer_e2e", "workflow_v2", True),
        ("payer_p2p", "workflow_v2", False),
    ],
)
def test_only_workflow_v2_e2e_uses_two_role_coordination(task_kind, protocol, suppressed):
    contract = {
        "benchmark_side": "payer",
        "event_contract": {"opening_statement": "Authored single-role counterpart opening."},
    }
    ctx = SimpleNamespace(
        task_kind=task_kind,
        e2e_protocol=protocol,
        _expectations=SimpleNamespace(target_case_id="C", expected_p2p_workflow=contract),
    )
    service = P2PService(ctx)
    actual = service._workflow_contract(SimpleNamespace(case_id="C"))
    assert actual == ({} if suppressed else contract)
    assert ctx._expectations.expected_p2p_workflow == contract


def test_legacy_e2e_cannot_activate_a_single_role_counterpart():
    ctx = SimpleNamespace(task_kind="provider_to_payer_e2e", e2e_protocol="dual_viewpoint_v1")
    with pytest.raises(ValueError, match="workflow_v2"):
        P2PService(ctx)._workflow_contract(SimpleNamespace(case_id="C"))
