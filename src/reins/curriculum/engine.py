from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

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

_DIFFICULTY_ORDER = [
    DifficultyLevel.TRIVIAL,
    DifficultyLevel.EASY,
    DifficultyLevel.MODERATE,
    DifficultyLevel.HARD,
    DifficultyLevel.EXPERT,
    DifficultyLevel.IMPOSSIBLE,
]


class CurriculumEngine:
    """Adaptive task sequencing that progressively increases difficulty based on agent mastery.

    Manages curricula with ordered lessons, tracks agent progress,
    adapts difficulty based on performance, and enforces prerequisites.
    """

    def __init__(self) -> None:
        self._lessons: dict[str, Lesson] = {}
        self._curricula: dict[str, Curriculum] = {}
        self._attempts: dict[str, list[LessonAttempt]] = defaultdict(list)
        self._enrollments: dict[str, dict[str, int]] = defaultdict(dict)

    def register_lesson(self, lesson: Lesson) -> Lesson:
        self._lessons[lesson.lesson_id] = lesson
        return lesson

    def get_lesson(self, lesson_id: str) -> Lesson | None:
        return self._lessons.get(lesson_id)

    def create_curriculum(self, name: str, lesson_ids: list[str],
                          strategy: AdaptationStrategy = AdaptationStrategy.ADAPTIVE,
                          description: str = "") -> Curriculum:
        curriculum = Curriculum(
            name=name,
            description=description,
            lessons=tuple(lesson_ids),
            strategy=strategy,
        )
        self._curricula[curriculum.curriculum_id] = curriculum
        return curriculum

    def get_curriculum(self, curriculum_id: str) -> Curriculum | None:
        return self._curricula.get(curriculum_id)

    def enroll(self, agent_id: str, curriculum_id: str) -> bool:
        if curriculum_id not in self._curricula:
            return False
        self._enrollments[agent_id][curriculum_id] = 0
        return True

    def get_next_lesson(self, agent_id: str, curriculum_id: str) -> Lesson | None:
        curriculum = self._curricula.get(curriculum_id)
        if not curriculum:
            return None
        idx = self._enrollments.get(agent_id, {}).get(curriculum_id, 0)
        if idx >= len(curriculum.lessons):
            return None
        lesson_id = curriculum.lessons[idx]
        return self._lessons.get(lesson_id)

    def submit_attempt(self, agent_id: str, lesson_id: str, score: float,
                       duration_ms: float = 0.0, feedback: str = "") -> LessonAttempt:
        lesson = self._lessons.get(lesson_id)
        passed = score >= (lesson.pass_threshold if lesson else 0.7)

        existing = [a for a in self._attempts.get(agent_id, []) if a.lesson_id == lesson_id]
        attempt_number = len(existing) + 1

        attempt = LessonAttempt(
            lesson_id=lesson_id,
            agent_id=agent_id,
            score=score,
            passed=passed,
            attempt_number=attempt_number,
            duration_ms=duration_ms,
            feedback=feedback,
        )
        self._attempts[agent_id].append(attempt)

        if passed:
            for cid, idx in self._enrollments.get(agent_id, {}).items():
                curriculum = self._curricula.get(cid)
                if curriculum and idx < len(curriculum.lessons) and curriculum.lessons[idx] == lesson_id:
                    self._enrollments[agent_id][cid] = idx + 1

        return attempt

    def get_lesson_status(self, agent_id: str, lesson_id: str) -> LessonStatus:
        lesson = self._lessons.get(lesson_id)
        if not lesson:
            return LessonStatus.LOCKED

        attempts = [a for a in self._attempts.get(agent_id, []) if a.lesson_id == lesson_id]
        if not attempts:
            if self._prerequisites_met(agent_id, lesson):
                return LessonStatus.AVAILABLE
            return LessonStatus.LOCKED

        if any(a.passed for a in attempts):
            return LessonStatus.PASSED

        if len(attempts) >= lesson.max_attempts:
            return LessonStatus.FAILED

        return LessonStatus.IN_PROGRESS

    def get_progress(self, agent_id: str, curriculum_id: str) -> AgentProgress:
        curriculum = self._curricula.get(curriculum_id)
        if not curriculum:
            return AgentProgress(agent_id=agent_id, curriculum_id=curriculum_id)

        idx = self._enrollments.get(agent_id, {}).get(curriculum_id, 0)
        all_attempts = self._attempts.get(agent_id, [])
        curriculum_attempts = [
            a for a in all_attempts if a.lesson_id in curriculum.lessons
        ]

        passed = sum(1 for lid in curriculum.lessons[:idx] if any(
            a.passed for a in all_attempts if a.lesson_id == lid
        ))
        failed = sum(1 for lid in curriculum.lessons if
                     self.get_lesson_status(agent_id, lid) == LessonStatus.FAILED)

        scores = [a.score for a in curriculum_attempts]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        mastery = passed / len(curriculum.lessons) if curriculum.lessons else 0.0

        return AgentProgress(
            agent_id=agent_id,
            curriculum_id=curriculum_id,
            current_lesson_idx=idx,
            lessons_passed=passed,
            lessons_failed=failed,
            total_attempts=len(curriculum_attempts),
            avg_score=avg_score,
            mastery_level=mastery,
        )

    def get_recommended_difficulty(self, agent_id: str) -> DifficultyLevel:
        all_attempts = self._attempts.get(agent_id, [])
        if not all_attempts:
            return DifficultyLevel.EASY

        recent = all_attempts[-10:]
        avg_score = sum(a.score for a in recent) / len(recent)
        pass_rate = sum(1 for a in recent if a.passed) / len(recent)

        if pass_rate >= 0.9 and avg_score >= 0.85:
            current_max = self._get_max_difficulty_passed(agent_id)
            idx = _DIFFICULTY_ORDER.index(current_max)
            return _DIFFICULTY_ORDER[min(idx + 1, len(_DIFFICULTY_ORDER) - 1)]
        elif pass_rate < 0.4:
            current_max = self._get_max_difficulty_passed(agent_id)
            idx = _DIFFICULTY_ORDER.index(current_max)
            return _DIFFICULTY_ORDER[max(idx - 1, 0)]
        else:
            return self._get_max_difficulty_passed(agent_id)

    def get_attempts(self, agent_id: str, lesson_id: str | None = None) -> list[LessonAttempt]:
        attempts = self._attempts.get(agent_id, [])
        if lesson_id:
            attempts = [a for a in attempts if a.lesson_id == lesson_id]
        return attempts

    def get_stats(self) -> CurriculumStats:
        total_attempts = sum(len(a) for a in self._attempts.values())
        agents = set()
        for agent_id, enrolls in self._enrollments.items():
            if enrolls:
                agents.add(agent_id)

        all_attempts_flat = [a for alist in self._attempts.values() for a in alist]
        pass_rate = (
            sum(1 for a in all_attempts_flat if a.passed) / len(all_attempts_flat)
            if all_attempts_flat else 0.0
        )

        by_difficulty: dict[str, int] = defaultdict(int)
        for lesson in self._lessons.values():
            by_difficulty[lesson.difficulty.value] += 1

        by_status: dict[str, int] = defaultdict(int)
        for agent_id in self._attempts:
            for lesson_id in self._lessons:
                status = self.get_lesson_status(agent_id, lesson_id)
                by_status[status.value] += 1

        return CurriculumStats(
            total_curricula=len(self._curricula),
            total_lessons=len(self._lessons),
            total_attempts=total_attempts,
            agents_enrolled=len(agents),
            avg_pass_rate=pass_rate,
            by_difficulty=dict(by_difficulty),
            by_status=dict(by_status),
        )

    def _prerequisites_met(self, agent_id: str, lesson: Lesson) -> bool:
        if not lesson.prerequisites:
            return True
        for prereq_id in lesson.prerequisites:
            attempts = [a for a in self._attempts.get(agent_id, []) if a.lesson_id == prereq_id]
            if not any(a.passed for a in attempts):
                return False
        return True

    def _get_max_difficulty_passed(self, agent_id: str) -> DifficultyLevel:
        passed_lessons = set()
        for a in self._attempts.get(agent_id, []):
            if a.passed:
                passed_lessons.add(a.lesson_id)

        max_diff = DifficultyLevel.TRIVIAL
        for lid in passed_lessons:
            lesson = self._lessons.get(lid)
            if lesson:
                idx = _DIFFICULTY_ORDER.index(lesson.difficulty)
                if idx > _DIFFICULTY_ORDER.index(max_diff):
                    max_diff = lesson.difficulty
        return max_diff
