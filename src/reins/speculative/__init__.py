"""Speculative Execution: parallel approach evaluation with configurable selection strategies."""

from reins.speculative.engine import SpeculativeExecutor
from reins.speculative.types import (
    Candidate,
    CandidateStatus,
    SelectionCriteria,
    SpeculativeResult,
    SpeculativeStrategy,
    SpeculativeTask,
)

__all__ = [
    "Candidate",
    "CandidateStatus",
    "SelectionCriteria",
    "SpeculativeExecutor",
    "SpeculativeResult",
    "SpeculativeStrategy",
    "SpeculativeTask",
]
