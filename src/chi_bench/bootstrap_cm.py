"""Resource-type mappings used by the care-management bootstrap path.

``ServiceContext._bootstrap_cm_session`` (and the unified ``bootstrap._seed_cm_fixtures``
helper) iterate these dicts to copy CM world resources into the provider /
payer stores. The standalone bootstrap functions that lived alongside these
constants in the legacy ``healthverse.bootstrap_cm`` module have been folded
into ``chi_bench.bootstrap`` and ``chi_bench.core.context``; only the type
mappings remain shared.
"""

from __future__ import annotations


CM_PROVIDER_RESOURCE_TYPES: dict[str, str] = {
    "patients": "id",
    "coverages": "id",
    "encounters": "id",
    "conditions": "id",
    "observations": "id",
    "medication_requests": "id",
    "procedures": "id",
    "allergies": "id",
    "documents": "id",
    "cm_referrals": "referral_id",
    "cm_outreach_records": "outreach_id",
    "cm_cases": "case_id",
    "cm_chart_reviews": "review_id",
    "cm_assessments": "assessment_id",
}

CM_HIDDEN_RESOURCE_TYPES: dict[str, str] = {
    "cm_hidden_expectations": "expectations_id",
}
