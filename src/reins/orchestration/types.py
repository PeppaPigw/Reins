"""Shared orchestration result and status types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from reins.orchestration.pipeline import Pipeline


class StageStatus(str, Enum):
    """Lifecycle states for individual pipeline stages."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class PipelineStatus(str, Enum):
    """Lifecycle states for an entire pipeline execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class StageResult:
    """Outcome of executing a single stage."""

    stage_name: str
    status: StageStatus
    output: str
    artifacts: list[Path]
    duration_seconds: float
    error: str | None = None
    attempts: int = 1


@dataclass
class PipelineResult:
    """Aggregated outcome for a full pipeline run."""

    pipeline_name: str
    status: PipelineStatus
    stage_results: list[StageResult]
    total_duration_seconds: float
    success: bool
    pipeline_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


PipelineConfig = Pipeline
