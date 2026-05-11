"""Conversation simulation engine for multi-turn patient interactions."""

from chi_bench.conversation.message import (
    STOP_SIGNAL,
    ConversationMessage,
    validate_message_history,
)
from chi_bench.conversation.patient_simulator import PatientSimulator, SimulatorResponse
from chi_bench.conversation.persona import PatientPersonaConfig, Verbosity, build_system_prompt
from chi_bench.conversation.session import ConversationSession

__all__ = [
    "ConversationMessage",
    "ConversationSession",
    "PatientPersonaConfig",
    "PatientSimulator",
    "SimulatorResponse",
    "STOP_SIGNAL",
    "Verbosity",
    "build_system_prompt",
    "validate_message_history",
]
