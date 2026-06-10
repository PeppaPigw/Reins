from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

import ulid
from pydantic import BaseModel, ConfigDict, Field


def _new_ulid() -> str:
    return str(ulid.new())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TemporalOperator(str, Enum):
    """Linear Temporal Logic operators."""
    ALWAYS = "always"
    EVENTUALLY = "eventually"
    NEXT = "next"
    UNTIL = "until"
    RELEASE = "release"
    IMPLIES = "implies"
    AND = "and"
    OR = "or"
    NOT = "not"


class PropertyKind(str, Enum):
    SAFETY = "safety"
    LIVENESS = "liveness"
    FAIRNESS = "fairness"
    REACHABILITY = "reachability"
    INVARIANCE = "invariance"
    RESPONSE = "response"


class CheckResult(str, Enum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    VACUOUSLY_TRUE = "vacuously_true"


class AtomicProposition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    predicate: str = ""
    description: str = ""


class TemporalFormula(BaseModel):
    model_config = ConfigDict(frozen=True)

    formula_id: str = Field(default_factory=_new_ulid)
    operator: TemporalOperator
    operands: tuple[str, ...] = ()
    atom: str | None = None
    description: str = ""

    def __str__(self) -> str:
        if self.atom:
            return f"{self.operator.value}({self.atom})"
        return f"{self.operator.value}({', '.join(self.operands)})"


class FormalProperty(BaseModel):
    model_config = ConfigDict(frozen=True)

    property_id: str = Field(default_factory=_new_ulid)
    name: str
    kind: PropertyKind
    formula_id: str
    description: str = ""
    critical: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class StateSpace(BaseModel):
    model_config = ConfigDict(frozen=True)

    space_id: str = Field(default_factory=_new_ulid)
    name: str
    states: tuple[str, ...] = ()
    initial_state: str = ""
    transitions: tuple[tuple[str, str, str], ...] = ()
    propositions: dict[str, tuple[str, ...]] = Field(default_factory=dict)


class Counterexample(BaseModel):
    model_config = ConfigDict(frozen=True)

    trace: tuple[str, ...] = ()
    loop_start: int = -1
    violated_at_step: int = -1
    explanation: str = ""


class ModelCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str = Field(default_factory=_new_ulid)
    property_id: str
    space_id: str
    result: CheckResult = CheckResult.UNKNOWN
    counterexample: Counterexample | None = None
    states_explored: int = 0
    transitions_explored: int = 0
    duration_ms: float = 0.0
    checked_at: datetime = Field(default_factory=_utc_now)


class FormalStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_properties: int = 0
    total_spaces: int = 0
    total_checks: int = 0
    satisfied: int = 0
    violated: int = 0
    by_kind: dict[str, int] = Field(default_factory=dict)
    avg_states_explored: float = 0.0
