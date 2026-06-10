"""Self-Healing Engine: automatic failure recovery with strategy selection and learning."""

from reins.healing.engine import SelfHealingEngine
from reins.healing.types import (
    ComponentHealth,
    Failure,
    FailureKind,
    HealingStats,
    HealthStatus,
    RecoveryAttempt,
    RecoveryOutcome,
    RecoveryPolicy,
    RecoveryStrategy,
)

__all__ = [
    "ComponentHealth",
    "Failure",
    "FailureKind",
    "HealingStats",
    "HealthStatus",
    "RecoveryAttempt",
    "RecoveryOutcome",
    "RecoveryPolicy",
    "RecoveryStrategy",
    "SelfHealingEngine",
]
