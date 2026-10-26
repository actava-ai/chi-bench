"""Consultation provenance shared by workflow validation and final scoring."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chi_bench.core.enums import PeerToPeerOutcome


class ExternalP2PEvidence(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    occurred_at: datetime
    payer_contact_id: str = Field(min_length=1)
    provider_contact_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    outcome: PeerToPeerOutcome


class RelayEvidenceTurn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    actor: Literal["provider", "payer"]
    message: str = Field(min_length=1)
    final_position: PeerToPeerOutcome | None
    ready_to_finalize: bool = Field(strict=True)
    source_path: str | None = None


class RelayP2PEvidence(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    request_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    turns: list[RelayEvidenceTurn]
    provider_final_position: PeerToPeerOutcome | None
    payer_final_position: PeerToPeerOutcome | None
    payer_ready_to_finalize: bool = Field(strict=True)
    failure_reason: str | None = None

    @model_validator(mode="after")
    def validate_position_summaries(self) -> Self:
        """Bind scoring summaries to the complete host-collected role turns.

        These fields are required even when their value is null/false. Older
        actor/message-only receipts cannot prove the positions used in scoring.
        """
        for role in ("provider", "payer"):
            position = next(
                (
                    turn.final_position
                    for turn in reversed(self.turns)
                    if turn.actor == role and turn.final_position is not None
                ),
                None,
            )
            if getattr(self, f"{role}_final_position") != position:
                raise ValueError(f"{role} position summary does not match collected turns")
        payer_turns = [turn for turn in self.turns if turn.actor == "payer"]
        if any(turn.ready_to_finalize and turn.final_position is None for turn in payer_turns):
            raise ValueError("Payer readiness requires a collected final position")
        if self.payer_ready_to_finalize != any(turn.ready_to_finalize for turn in payer_turns):
            raise ValueError("Payer readiness summary does not match collected turns")
        return self


def utc_time(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def consultation_evidence(
    request: dict[str, Any],
    *,
    sessions: list[dict[str, Any]],
    external: list[dict[str, Any]],
    relays: list[dict[str, Any]],
    allow_pending_payer_turn: bool = False,
) -> tuple[str, str] | None:
    """Require evidence bound to both this request and this case.

    E2E recording occurs inside a payer turn, before the host appends that
    turn. Only the live service uses allow_pending_payer_turn; final scoring
    always requires both roles in the trusted host-collected transcript.
    """
    request_id, case_id = request.get("id"), request.get("case_id")
    if not request_id or not case_id:
        return None
    for record in sessions:
        if record.get("request_id") != request_id or record.get("case_id") != case_id:
            continue
        turns = record.get("transcript") or []
        side = record.get("benchmark_side")
        if side not in {"provider", "payer"}:
            continue
        actors = {
            turn.get("speaker")
            for turn in turns
            if isinstance(turn, dict) and str(turn.get("message") or "").strip()
        }
        used = record.get("agent_turns_used", 0)
        if (
            isinstance(used, int)
            and used > 0
            and {side, "counterpart"} <= actors
            and record.get("id")
        ):
            return "simulated_session", record["id"]
    for record in external:
        if record.get("request_id") != request_id or record.get("case_id") != case_id:
            continue
        try:
            evidence = ExternalP2PEvidence.model_validate(record)
        except ValueError:
            continue
        reviewer = request.get("payer_contact_id")
        if reviewer not in {None, "SYSTEM"} and reviewer != evidence.payer_contact_id:
            continue
        if request.get("outcome") and request["outcome"] != evidence.outcome.value:
            continue
        return "external", evidence.id
    for record in relays:
        if record.get("request_id") != request_id or record.get("case_id") != case_id:
            continue
        try:
            evidence = RelayP2PEvidence.model_validate(record)
        except ValueError:
            continue
        actors = {turn.actor for turn in evidence.turns}
        required = {"provider"} if allow_pending_payer_turn else {"provider", "payer"}
        if required <= actors:
            return "e2e_relay", request_id
    return None
