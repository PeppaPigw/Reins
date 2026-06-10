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


class SignalKind(str, Enum):
    PHEROMONE = "pheromone"
    BROADCAST = "broadcast"
    STIGMERGY = "stigmergy"
    GRADIENT = "gradient"
    ALARM = "alarm"


class SwarmRole(str, Enum):
    SCOUT = "scout"
    WORKER = "worker"
    LEADER = "leader"
    RELAY = "relay"
    IDLE = "idle"


class ConsensusMethod(str, Enum):
    MAJORITY_VOTE = "majority_vote"
    QUORUM_SENSING = "quorum_sensing"
    WEIGHTED_VOTE = "weighted_vote"
    THRESHOLD = "threshold"


class SwarmSignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_id: str = Field(default_factory=_new_ulid)
    kind: SignalKind
    source_agent: str
    target: str = ""
    intensity: float = 1.0
    payload: dict[str, Any] = Field(default_factory=dict)
    decay_rate: float = 0.1
    created_at: datetime = Field(default_factory=_utc_now)


class SwarmAgent(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    role: SwarmRole = SwarmRole.IDLE
    position: tuple[float, ...] = ()
    velocity: tuple[float, ...] = ()
    energy: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class PheromoneTrail(BaseModel):
    model_config = ConfigDict(frozen=True)

    trail_id: str = Field(default_factory=_new_ulid)
    resource: str
    deposited_by: str
    intensity: float = 1.0
    decay_rate: float = 0.05
    created_at: datetime = Field(default_factory=_utc_now)


class SwarmDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(default_factory=_new_ulid)
    proposal: str
    method: ConsensusMethod = ConsensusMethod.MAJORITY_VOTE
    votes_for: int = 0
    votes_against: int = 0
    quorum: int = 1
    resolved: bool = False
    outcome: bool | None = None
    decided_at: datetime | None = None


class SwarmTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str = Field(default_factory=_new_ulid)
    description: str
    required_agents: int = 1
    assigned_agents: tuple[str, ...] = ()
    completed: bool = False
    priority: float = 1.0


class SwarmStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_agents: int = 0
    active_signals: int = 0
    active_trails: int = 0
    decisions_made: int = 0
    tasks_completed: int = 0
    avg_energy: float = 0.0
    by_role: dict[str, int] = Field(default_factory=dict)
