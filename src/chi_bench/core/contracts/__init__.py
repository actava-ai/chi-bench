"""Runtime contracts salvaged from the dropped synth pipeline.

Pydantic models that describe runtime JSON shapes consumed by the
verifier / services layer. Originally lived under ``chi_bench.synth``
but the synth pipeline is out of scope for the OSS release; these
specific classes were preserved because runtime code still depends
on them.
"""

from chi_bench.core.contracts.cm_export_contract import (
    CMExportContract,
    derive_target_case_id,
)
from chi_bench.core.contracts.cm_persona_contract import (
    AntiTrigger,
    PatientPersonaContract,
    TriggerMetadata,
)
from chi_bench.core.contracts.stage_artifact import StageArtifact

__all__ = [
    "AntiTrigger",
    "CMExportContract",
    "PatientPersonaContract",
    "StageArtifact",
    "TriggerMetadata",
    "derive_target_case_id",
]
