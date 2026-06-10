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


class LogicKind(str, Enum):
    DEDUCTIVE = "deductive"
    INDUCTIVE = "inductive"
    ABDUCTIVE = "abductive"
    ANALOGICAL = "analogical"
    DEFEASIBLE = "defeasible"


class PropositionStatus(str, Enum):
    ASSUMED = "assumed"
    DERIVED = "derived"
    CONTRADICTED = "contradicted"
    RETRACTED = "retracted"


class ArgumentStrength(str, Enum):
    CONCLUSIVE = "conclusive"
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    FALLACIOUS = "fallacious"


class Proposition(BaseModel):
    model_config = ConfigDict(frozen=True)

    prop_id: str = Field(default_factory=_new_ulid)
    statement: str
    status: PropositionStatus = PropositionStatus.ASSUMED
    confidence: float = 1.0
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class InferenceRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str = Field(default_factory=_new_ulid)
    name: str
    premises: tuple[str, ...] = ()
    conclusion: str = ""
    kind: LogicKind = LogicKind.DEDUCTIVE
    strength: float = 1.0


class InferenceStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    step_id: str = Field(default_factory=_new_ulid)
    rule_id: str
    premises_used: tuple[str, ...] = ()
    conclusion_id: str = ""
    confidence: float = 1.0
    timestamp: datetime = Field(default_factory=_utc_now)


class Argument(BaseModel):
    model_config = ConfigDict(frozen=True)

    argument_id: str = Field(default_factory=_new_ulid)
    claim: str
    premises: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    strength: ArgumentStrength = ArgumentStrength.MODERATE
    confidence: float = 0.5


class Contradiction(BaseModel):
    model_config = ConfigDict(frozen=True)

    contradiction_id: str = Field(default_factory=_new_ulid)
    prop_a: str
    prop_b: str
    description: str = ""
    resolved: bool = False


class ReasoningStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_propositions: int = 0
    total_rules: int = 0
    total_inferences: int = 0
    total_arguments: int = 0
    contradictions_found: int = 0
    contradictions_resolved: int = 0
    avg_confidence: float = 0.0
    by_logic_kind: dict[str, int] = Field(default_factory=dict)
