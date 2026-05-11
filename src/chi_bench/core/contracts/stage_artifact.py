"""StageArtifact runtime contract.

Single Pydantic model salvaged from the dropped synth pipeline. Used by
``chi_bench.core.fast_forward`` to model per-stage synthesized artifacts
that are pre-applied before the agent takes control.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from chi_bench.core.contracts._null_safe import _NullSafeModel


class StageArtifact(_NullSafeModel):
    """Synthesized artifacts for a single workflow stage."""

    stage: str  # WorkflowStage value
    model_name: str  # ChiBench model (e.g., "IntakeCase")
    # Raw JSON emitted by synthesis before schema coercion.
    fields: dict[str, Any] = Field(default_factory=dict)
    # Canonicalized subset after validating/coercing against the target model.
    validated_fields: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""  # why these values were chosen
    node_ids: list[str] = Field(default_factory=list)  # tree nodes that contributed
