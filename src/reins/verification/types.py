from __future__ import annotations

from enum import Enum
from datetime import UTC, datetime
from typing import Any

import ulid
from pydantic import BaseModel, ConfigDict, Field


def _new_ulid() -> str:
    return str(ulid.new())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InvariantKind(str, Enum):
    STATE_INVARIANT = "state_invariant"
    TRANSITION_INVARIANT = "transition_invariant"
    SAFETY_PROPERTY = "safety_property"
    LIVENESS_PROPERTY = "liveness_property"
    POLICY_COMPLETENESS = "policy_completeness"
    DEADLOCK_FREEDOM = "deadlock_freedom"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    VIOLATED = "violated"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"


class Invariant(BaseModel):
    model_config = ConfigDict(frozen=True)

    invariant_id: str = Field(default_factory=_new_ulid)
    name: str
    kind: InvariantKind
    description: str
    predicate: str
    severity: str = "error"


class StateTransition(BaseModel):
    model_config = ConfigDict(frozen=True)

    from_state: str
    to_state: str
    event_type: str
    guard: str | None = None


class VerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str = Field(default_factory=_new_ulid)
    invariant_id: str
    status: VerificationStatus
    evidence: dict[str, Any] = Field(default_factory=dict)
    counterexample: list[dict[str, Any]] | None = None
    checked_states: int = 0
    checked_transitions: int = 0
    duration_ms: float = 0.0
    verified_at: datetime = Field(default_factory=_utc_now)


class DeadlockReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    has_deadlock: bool
    deadlock_states: tuple[str, ...] = ()
    cycle_path: tuple[str, ...] = ()
    reachable_from: str | None = None


class PolicyCompletenessReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_complete: bool
    total_capabilities: int
    covered_capabilities: int
    uncovered_capabilities: tuple[str, ...] = ()
    conflicting_rules: tuple[tuple[str, str], ...] = ()


class VerificationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_id: str = Field(default_factory=_new_ulid)
    results: tuple[VerificationResult, ...] = ()
    deadlock_report: DeadlockReport | None = None
    policy_report: PolicyCompletenessReport | None = None
    all_verified: bool = False
    total_invariants: int = 0
    violated_count: int = 0
    verified_at: datetime = Field(default_factory=_utc_now)
