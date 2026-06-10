"""Counterfactual Reasoning: what-if analysis for agent decisions."""

from reins.counterfactual.engine import CounterfactualEngine
from reins.counterfactual.types import (
    CausalClaim,
    CausalStrength,
    CounterfactualResult,
    CounterfactualStats,
    Decision,
    Intervention,
    InterventionType,
    OutcomeComparison,
    WorldKind,
    WorldState,
)

__all__ = [
    "CausalClaim",
    "CausalStrength",
    "CounterfactualEngine",
    "CounterfactualResult",
    "CounterfactualStats",
    "Decision",
    "Intervention",
    "InterventionType",
    "OutcomeComparison",
    "WorldKind",
    "WorldState",
]
