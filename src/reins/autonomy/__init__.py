"""Autonomy: self-governance with escalation, bounded decision-making, and trust calibration."""

from reins.autonomy.engine import AutonomyEngine
from reins.autonomy.types import (
    AutonomyBoundary,
    AutonomyDecision,
    AutonomyLevel,
    AutonomyProfile,
    AutonomyStats,
    DecisionOutcome,
    EscalationReason,
    EscalationRequest,
)

__all__ = [
    "AutonomyBoundary",
    "AutonomyDecision",
    "AutonomyEngine",
    "AutonomyLevel",
    "AutonomyProfile",
    "AutonomyStats",
    "DecisionOutcome",
    "EscalationReason",
    "EscalationRequest",
]
