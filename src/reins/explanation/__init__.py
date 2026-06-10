"""Explanation Engine: human-readable decision explanations with causal attribution."""

from reins.explanation.engine import ExplanationEngine
from reins.explanation.types import (
    AudienceLevel,
    Counterfactual,
    DecisionFactor,
    DecisionRecord,
    Explanation,
    ExplanationDepth,
    ExplanationStats,
    FactorKind,
)

__all__ = [
    "AudienceLevel",
    "Counterfactual",
    "DecisionFactor",
    "DecisionRecord",
    "Explanation",
    "ExplanationDepth",
    "ExplanationEngine",
    "ExplanationStats",
    "FactorKind",
]
