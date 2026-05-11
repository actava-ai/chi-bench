"""Deterministic normalization rules for synthesized bundle fields.

Salvaged from the dropped synth pipeline. Only the two normalizers consumed
by ``_provider_new_referral_targets`` are retained -- ``normalize_place_of_service``
and ``normalize_service_type``. Both are pure (no IO, no LLM); each takes a
raw value and returns the canonical form. Unknown values pass through unchanged.
"""

from __future__ import annotations

# -- Place of Service ----------------------------------------------------

# Maps observed raw variants to canonical PlaceOfService values.
# Lookup is case-insensitive (lowercased key -> canonical value).
_POS_CANONICAL: dict[str, str] = {}
_POS_RAW_MAP = {
    "outpatient_hospital": [
        "22",
        "hospital_outpatient",
        "outpatient hospital",
        "Outpatient Hospital",
        "Hospital Outpatient Department",
        "outpatient_hospital",
        "22 - Outpatient Hospital (HOPD)",
        "sleep_lab",
        "outpatient_infusion_center",
        "Freestanding imaging center",
        "Freestanding Imaging Center",
        "independent_laboratory",
        "Independent Laboratory",
        "Reference Laboratory",
        "reference laboratory",
        "outpatient",
        "Outpatient Imaging Center",
        "outpatient_imaging_center",
    ],
    "ambulatory_surgical_center": [
        "24",
        "ASC",
        "Ambulatory Surgical Center",
        "ambulatory_surgery_center",
        "ambulatory_surgical_center",
    ],
    "inpatient_hospital": ["21", "Inpatient Hospital", "inpatient_hospital"],
    "office": ["11", "Office", "Office (11)", "11 - Office", "office"],
    "home": [
        "12",
        "Home",
        "home",
        "home_self_administered",
        "pharmacy",
        "retail_pharmacy",
        "specialty_pharmacy",
        "outpatient_pharmacy",
        "01",
    ],
    "emergency_room": ["emergency_room", "Emergency Room", "23"],
    "skilled_nursing_facility": ["skilled_nursing_facility", "Skilled Nursing Facility", "31"],
    "telehealth": ["telehealth", "Telehealth", "02"],
    "urgent_care": ["urgent_care", "Urgent Care", "20"],
    "rehabilitation_facility": ["rehabilitation_facility", "Rehabilitation Facility"],
    "hospice": ["hospice", "Hospice"],
}
for _canonical, _variants in _POS_RAW_MAP.items():
    for _v in _variants:
        _POS_CANONICAL[_v.lower()] = _canonical


def normalize_place_of_service(value: str | None) -> str | None:
    if value is None:
        return None
    if not value:
        return value
    return _POS_CANONICAL.get(value.lower(), value)


# -- Service Type --------------------------------------------------------

_SERVICE_TYPE_CANONICAL: dict[str, str] = {}
_SERVICE_TYPE_RAW_MAP = {
    "surgical": [
        "surgical",
        "surgical_procedure",
        "outpatient_surgery",
        "outpatient_surgical",
        "elective_outpatient_procedure",
        "surgical_implant",
        "surgical_implantable_device",
        "surgical_inpatient",
        "inpatient_procedure",
        "outpatient_procedure",
    ],
    "radiology": [
        "diagnostic_imaging",
        "advanced_imaging",
        "Diagnostic Imaging",
        "Outpatient Diagnostic Imaging",
        "Outpatient diagnostic imaging",
        "Advanced Imaging - Virtual Endoscopy",
        "outpatient_diagnostic",
        "diagnostic",
        "radiology",
        "outpatient_imaging",
        "outpatient_mri",
    ],
    "dme": [
        "DME",
        "DME - Prosthetic",
        "DME - Prosthetic Device",
        "dme",
        "durable_medical_equipment",
        "prosthetic",
    ],
    "medical": [
        "medical",
        "medical_benefit_drug",
        "sp",
        "specialty_infusion",
        "provider_administered_drug_infusion",
        "outpatient_infusion",
        "Genetic Testing",
        "diagnostic_genetic_testing",
        "Diagnostic Laboratory",
        "Inpatient vEEG Monitoring",
        "Inpatient",
        "Outpatient",
        "specialty_drug",
        "specialty_pharmacy",
        "pharmacy",
        "specialty_pharmacy_rx",
        "Specialty Pharmacy - CGRP Antagonist",
    ],
    "cardiology": ["Ambulatory ECG Monitoring", "cardiology"],
    "rehab_therapy": ["Outpatient Physical Therapy", "rehab_therapy"],
    "behavioral_health": ["behavioral_health"],
    "home_health": ["home_health"],
    "skilled_nursing": ["skilled_nursing"],
    "transplant": ["transplant"],
    "oncology": ["oncology"],
    "pain_management": ["pain_management"],
}
for _canonical, _variants in _SERVICE_TYPE_RAW_MAP.items():
    for _v in _variants:
        _SERVICE_TYPE_CANONICAL[_v.lower()] = _canonical


def normalize_service_type(value: str | None) -> str | None:
    if value is None:
        return None
    if not value:
        return value
    return _SERVICE_TYPE_CANONICAL.get(value.lower(), value)
