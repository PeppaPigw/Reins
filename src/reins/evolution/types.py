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


class MasteryLevel(str, Enum):
    NOVICE = "novice"
    APPRENTICE = "apprentice"
    COMPETENT = "competent"
    PROFICIENT = "proficient"
    EXPERT = "expert"
    MASTER = "master"


class SkillCategory(str, Enum):
    REASONING = "reasoning"
    CODING = "coding"
    PLANNING = "planning"
    COMMUNICATION = "communication"
    TOOL_USE = "tool_use"
    DEBUGGING = "debugging"
    ARCHITECTURE = "architecture"
    SAFETY = "safety"


class ProgressionEvent(str, Enum):
    PRACTICE = "practice"
    SUCCESS = "success"
    FAILURE = "failure"
    FEEDBACK = "feedback"
    MILESTONE = "milestone"
    DECAY = "decay"


class Skill(BaseModel):
    model_config = ConfigDict(frozen=True)

    skill_id: str = Field(default_factory=_new_ulid)
    name: str
    category: SkillCategory
    description: str = ""
    prerequisites: tuple[str, ...] = ()
    xp_to_master: float = 1000.0


class SkillState(BaseModel):
    model_config = ConfigDict(frozen=True)

    skill_id: str
    agent_id: str
    level: MasteryLevel = MasteryLevel.NOVICE
    xp: float = 0.0
    practice_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_practiced_at: datetime | None = None


class ProgressionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    skill_id: str
    event: ProgressionEvent
    xp_delta: float = 0.0
    from_level: MasteryLevel | None = None
    to_level: MasteryLevel | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=_utc_now)


class EvolutionStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    agents_tracked: int = 0
    total_skills: int = 0
    total_progressions: int = 0
    avg_mastery_level: float = 0.0
    by_category: dict[str, int] = Field(default_factory=dict)
    by_level: dict[str, int] = Field(default_factory=dict)
