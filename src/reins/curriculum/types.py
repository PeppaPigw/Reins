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


class DifficultyLevel(str, Enum):
    TRIVIAL = "trivial"
    EASY = "easy"
    MODERATE = "moderate"
    HARD = "hard"
    EXPERT = "expert"
    IMPOSSIBLE = "impossible"


class LessonStatus(str, Enum):
    LOCKED = "locked"
    AVAILABLE = "available"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AdaptationStrategy(str, Enum):
    LINEAR = "linear"
    ADAPTIVE = "adaptive"
    MASTERY_BASED = "mastery_based"
    SPACED_REPETITION = "spaced_repetition"


class Lesson(BaseModel):
    model_config = ConfigDict(frozen=True)

    lesson_id: str = Field(default_factory=_new_ulid)
    name: str
    difficulty: DifficultyLevel = DifficultyLevel.MODERATE
    prerequisites: tuple[str, ...] = ()
    skills_taught: tuple[str, ...] = ()
    pass_threshold: float = 0.7
    max_attempts: int = 3
    metadata: dict[str, Any] = Field(default_factory=dict)


class LessonAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempt_id: str = Field(default_factory=_new_ulid)
    lesson_id: str
    agent_id: str
    score: float = 0.0
    passed: bool = False
    attempt_number: int = 1
    duration_ms: float = 0.0
    feedback: str = ""
    attempted_at: datetime = Field(default_factory=_utc_now)


class Curriculum(BaseModel):
    model_config = ConfigDict(frozen=True)

    curriculum_id: str = Field(default_factory=_new_ulid)
    name: str
    description: str = ""
    lessons: tuple[str, ...] = ()
    strategy: AdaptationStrategy = AdaptationStrategy.ADAPTIVE
    created_at: datetime = Field(default_factory=_utc_now)


class AgentProgress(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    curriculum_id: str
    current_lesson_idx: int = 0
    lessons_passed: int = 0
    lessons_failed: int = 0
    total_attempts: int = 0
    avg_score: float = 0.0
    mastery_level: float = 0.0


class CurriculumStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_curricula: int = 0
    total_lessons: int = 0
    total_attempts: int = 0
    agents_enrolled: int = 0
    avg_pass_rate: float = 0.0
    by_difficulty: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
