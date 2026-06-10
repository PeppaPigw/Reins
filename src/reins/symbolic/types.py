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


class TermKind(str, Enum):
    CONSTANT = "constant"
    VARIABLE = "variable"
    FUNCTION = "function"
    PREDICATE = "predicate"


class ProofStatus(str, Enum):
    PROVED = "proved"
    DISPROVED = "disproved"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    CONTRADICTION = "contradiction"


class InferenceRule(str, Enum):
    MODUS_PONENS = "modus_ponens"
    MODUS_TOLLENS = "modus_tollens"
    RESOLUTION = "resolution"
    UNIFICATION = "unification"
    UNIVERSAL_INSTANTIATION = "universal_instantiation"
    EXISTENTIAL_GENERALIZATION = "existential_generalization"


class Term(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: TermKind
    name: str
    args: tuple[str, ...] = ()

    def __str__(self) -> str:
        if self.args:
            return f"{self.name}({', '.join(self.args)})"
        return self.name


class Clause(BaseModel):
    model_config = ConfigDict(frozen=True)

    clause_id: str = Field(default_factory=_new_ulid)
    positive: tuple[str, ...] = ()
    negative: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return not self.positive and not self.negative

    def is_unit(self) -> bool:
        return len(self.positive) + len(self.negative) == 1


class KnowledgeBase(BaseModel):
    model_config = ConfigDict(frozen=True)

    kb_id: str = Field(default_factory=_new_ulid)
    name: str
    facts: tuple[str, ...] = ()
    rules: tuple[tuple[str, str], ...] = ()
    clauses: tuple[str, ...] = ()


class ProofStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    step_id: str = Field(default_factory=_new_ulid)
    rule: InferenceRule
    premises: tuple[str, ...] = ()
    conclusion: str = ""
    substitution: dict[str, str] = Field(default_factory=dict)


class ProofResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str = Field(default_factory=_new_ulid)
    query: str
    status: ProofStatus = ProofStatus.UNKNOWN
    steps: tuple[ProofStep, ...] = ()
    depth: int = 0
    substitutions: dict[str, str] = Field(default_factory=dict)
    proved_at: datetime = Field(default_factory=_utc_now)


class SymbolicStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_facts: int = 0
    total_rules: int = 0
    total_queries: int = 0
    proofs_found: int = 0
    avg_proof_depth: float = 0.0
    by_status: dict[str, int] = Field(default_factory=dict)
