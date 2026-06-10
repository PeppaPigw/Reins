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


class HypothesisStatus(str, Enum):
    PROPOSED = "proposed"
    TESTING = "testing"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"


class EvidenceKind(str, Enum):
    CONFIRMING = "confirming"
    DISCONFIRMING = "disconfirming"
    NEUTRAL = "neutral"
    ANOMALOUS = "anomalous"


class TestOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    ERROR = "error"


class Hypothesis(BaseModel):
    model_config = ConfigDict(frozen=True)

    hypothesis_id: str = Field(default_factory=_new_ulid)
    statement: str
    prior_probability: float = 0.5
    posterior_probability: float = 0.5
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    domain: str = ""
    created_at: datetime = Field(default_factory=_utc_now)


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(default_factory=_new_ulid)
    hypothesis_id: str
    kind: EvidenceKind
    description: str
    likelihood_ratio: float = 1.0
    strength: float = 0.5
    metadata: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime = Field(default_factory=_utc_now)


class Experiment(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_id: str = Field(default_factory=_new_ulid)
    hypothesis_id: str
    description: str
    outcome: TestOutcome = TestOutcome.PASS
    observations: tuple[str, ...] = ()
    conducted_at: datetime = Field(default_factory=_utc_now)


class HypothesisStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_hypotheses: int = 0
    supported: int = 0
    refuted: int = 0
    testing: int = 0
    total_evidence: int = 0
    total_experiments: int = 0
    avg_posterior: float = 0.5
    by_status: dict[str, int] = Field(default_factory=dict)
