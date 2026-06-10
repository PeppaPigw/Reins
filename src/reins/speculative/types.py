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


class SpeculativeStrategy(str, Enum):
    BEST_OF_N = "best_of_n"
    RACE = "race"
    CONSENSUS = "consensus"
    CASCADING = "cascading"


class CandidateStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SelectionCriteria(str, Enum):
    HIGHEST_SCORE = "highest_score"
    LOWEST_COST = "lowest_cost"
    FASTEST = "fastest"
    MAJORITY_VOTE = "majority_vote"
    WEIGHTED_ENSEMBLE = "weighted_ensemble"


class Candidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str = Field(default_factory=_new_ulid)
    approach_name: str
    agent_id: str = ""
    model_id: str = ""
    prompt_variant: str = ""
    status: CandidateStatus = CandidateStatus.PENDING
    output: Any = None
    error: str | None = None
    quality_score: float = 0.0
    cost: float = 0.0
    latency_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class SpeculativeTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str = Field(default_factory=_new_ulid)
    description: str
    strategy: SpeculativeStrategy = SpeculativeStrategy.BEST_OF_N
    selection: SelectionCriteria = SelectionCriteria.HIGHEST_SCORE
    candidates: tuple[Candidate, ...] = ()
    max_candidates: int = 3
    timeout_ms: float = 30000.0
    min_quality_threshold: float = 0.0
    created_at: datetime = Field(default_factory=_utc_now)


class SpeculativeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str = Field(default_factory=_new_ulid)
    task_id: str
    selected_candidate: Candidate | None = None
    all_candidates: tuple[Candidate, ...] = ()
    selection_reason: str = ""
    total_cost: float = 0.0
    total_latency_ms: float = 0.0
    strategy_used: SpeculativeStrategy = SpeculativeStrategy.BEST_OF_N
    decided_at: datetime = Field(default_factory=_utc_now)
