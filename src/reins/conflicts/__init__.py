"""Semantic conflict detection for multi-agent collaboration."""

from reins.conflicts.detector import ConflictDetector
from reins.conflicts.types import (
    Change,
    ChangeKind,
    Conflict,
    ConflictReport,
    ConflictSeverity,
    ConflictType,
    Resolution,
    ResolutionStrategy,
)

__all__ = [
    "Change",
    "ChangeKind",
    "Conflict",
    "ConflictDetector",
    "ConflictReport",
    "ConflictSeverity",
    "ConflictType",
    "Resolution",
    "ResolutionStrategy",
]
