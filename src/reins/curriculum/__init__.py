"""Curriculum Learning: adaptive task sequencing with progressive difficulty based on agent mastery."""

from reins.curriculum.engine import CurriculumEngine
from reins.curriculum.types import (
    AdaptationStrategy,
    AgentProgress,
    Curriculum,
    CurriculumStats,
    DifficultyLevel,
    Lesson,
    LessonAttempt,
    LessonStatus,
)

__all__ = [
    "AdaptationStrategy",
    "AgentProgress",
    "Curriculum",
    "CurriculumEngine",
    "CurriculumStats",
    "DifficultyLevel",
    "Lesson",
    "LessonAttempt",
    "LessonStatus",
]
