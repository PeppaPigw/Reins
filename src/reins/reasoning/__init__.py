"""Reasoning: formal logical inference with argument construction and consistency checking."""

from reins.reasoning.engine import ReasoningEngine
from reins.reasoning.types import (
    Argument,
    ArgumentStrength,
    Contradiction,
    InferenceRule,
    InferenceStep,
    LogicKind,
    Proposition,
    PropositionStatus,
    ReasoningStats,
)

__all__ = [
    "Argument",
    "ArgumentStrength",
    "Contradiction",
    "InferenceRule",
    "InferenceStep",
    "LogicKind",
    "Proposition",
    "PropositionStatus",
    "ReasoningEngine",
    "ReasoningStats",
]
