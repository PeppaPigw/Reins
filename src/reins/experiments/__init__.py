"""Experiment Framework: A/B testing for agent strategies with multi-armed bandit optimization."""

from reins.experiments.engine import ExperimentManager
from reins.experiments.types import (
    AllocationStrategy,
    Experiment,
    ExperimentConclusion,
    ExperimentManagerStats,
    ExperimentStatus,
    SignificanceLevel,
    TrialResult,
    Variant,
    VariantOutcome,
    VariantStats,
)

__all__ = [
    "AllocationStrategy",
    "Experiment",
    "ExperimentConclusion",
    "ExperimentManager",
    "ExperimentManagerStats",
    "ExperimentStatus",
    "SignificanceLevel",
    "TrialResult",
    "Variant",
    "VariantOutcome",
    "VariantStats",
]
