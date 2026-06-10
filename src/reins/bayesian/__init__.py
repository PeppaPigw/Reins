"""Bayesian Optimization: auto-tuning agent parameters with Gaussian process surrogates."""

from reins.bayesian.engine import BayesianOptimizer
from reins.bayesian.types import (
    AcquisitionFunction,
    BayesianStats,
    OptimizationResult,
    OptimizationStatus,
    Parameter,
    ParameterKind,
    SearchSpace,
    Trial,
)

__all__ = [
    "AcquisitionFunction",
    "BayesianOptimizer",
    "BayesianStats",
    "OptimizationResult",
    "OptimizationStatus",
    "Parameter",
    "ParameterKind",
    "SearchSpace",
    "Trial",
]
