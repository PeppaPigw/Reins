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


class ScenarioKind(str, Enum):
    NORMAL = "normal"
    STRESS = "stress"
    ADVERSARIAL = "adversarial"
    EDGE_CASE = "edge_case"
    REGRESSION = "regression"
    CHAOS = "chaos"


class SimulationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OutcomeKind(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    CRASH = "crash"
    DEGRADED = "degraded"


class Scenario(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_id: str = Field(default_factory=_new_ulid)
    name: str
    kind: ScenarioKind = ScenarioKind.NORMAL
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    expected_outcome: OutcomeKind = OutcomeKind.SUCCESS
    weight: float = 1.0


class SimulationRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str = Field(default_factory=_new_ulid)
    scenario_id: str
    strategy_id: str
    iteration: int = 0
    outcome: OutcomeKind = OutcomeKind.SUCCESS
    score: float = 0.0
    latency_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    executed_at: datetime = Field(default_factory=_utc_now)


class SimulationBatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    batch_id: str = Field(default_factory=_new_ulid)
    strategy_id: str
    scenario_id: str
    iterations: int = 100
    status: SimulationStatus = SimulationStatus.PENDING
    runs: tuple[SimulationRun, ...] = ()
    created_at: datetime = Field(default_factory=_utc_now)


class StrategyProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_id: str
    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class SimulationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    batch_id: str
    strategy_id: str
    scenario_id: str
    total_runs: int = 0
    success_count: int = 0
    failure_count: int = 0
    success_rate: float = 0.0
    avg_score: float = 0.0
    std_dev_score: float = 0.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    by_outcome: dict[str, int] = Field(default_factory=dict)


class SimulationStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_scenarios: int = 0
    total_strategies: int = 0
    total_batches: int = 0
    total_runs: int = 0
    avg_success_rate: float = 0.0
    by_scenario_kind: dict[str, int] = Field(default_factory=dict)
