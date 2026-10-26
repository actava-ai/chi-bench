"""Workflow request fidelity does not invent an unavailable fixed-slot contract."""

import json

import pytest

from chi_bench.verifier.stages.provider_submission import ProviderSubmissionVerifier


@pytest.mark.parametrize(
    "protocol,explicit,expected",
    [
        ("workflow_v2", False, "not_applicable"),
        ("workflow_v2", True, False),
    ],
)
def test_authored_documents_do_not_need_an_unauthored_destination_slot(
    protocol, explicit, expected
):
    state = {
        "e2e_protocol": protocol,
        "target_case_id": "C",
        "target_case": {"id": "C"},
        "submission_packets": [{"id": "PK", "case_id": "C", "payload": {}}],
        "workspace_artifacts": [
            {
                "case_id": "C",
                "artifact_type": "submission_manifest",
                "linked_resource_id": "PK",
                "content": json.dumps(
                    {
                        "documents": [
                            {
                                "id": "AUTHORED",
                                "source_slot_keys": ["CHART"],
                                "derivation_relation": "Summary of chart evidence",
                            }
                        ]
                    }
                ),
            }
        ],
    }
    expectations = {
        "task_kind": "provider_to_payer_e2e",
        "target_case_id": "C",
        "verifier_contract": "contract_v3",
        "expected_provider_submission": {},
    }
    if explicit:
        expectations["expected_provider_submission"]["require_source_attachment_provenance"] = True
    result = ProviderSubmissionVerifier(state, expectations, []).verify()
    assert result.checks["provider.provenance_complete"] == expected
    assert result.checks["provider.packet_exists"] is True
    if expected == "not_applicable":
        assert result.details["not_applicable_reasons"]["provider.provenance_complete"]
