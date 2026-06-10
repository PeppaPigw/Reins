"""Tests for curriculum learning with adaptive task sequencing."""

from __future__ import annotations

import pytest

from reins.curriculum import (
    AdaptationStrategy,
    AgentProgress,
    Curriculum,
    CurriculumEngine,
    CurriculumStats,
    DifficultyLevel,
    Lesson,
    LessonAttempt,
    LessonStatus,
)


@pytest.fixture
def engine() -> CurriculumEngine:
    return CurriculumEngine()


@pytest.fixture
def basic_lessons(engine) -> list[Lesson]:
    l1 = engine.register_lesson(Lesson(name="intro", difficulty=DifficultyLevel.EASY))
    l2 = engine.register_lesson(Lesson(
        name="intermediate", difficulty=DifficultyLevel.MODERATE,
        prerequisites=(l1.lesson_id,),
    ))
    l3 = engine.register_lesson(Lesson(
        name="advanced", difficulty=DifficultyLevel.HARD,
        prerequisites=(l2.lesson_id,),
    ))
    return [l1, l2, l3]


def test_register_lesson(engine):
    lesson = engine.register_lesson(Lesson(name="test", difficulty=DifficultyLevel.EASY))
    assert engine.get_lesson(lesson.lesson_id) is not None


def test_get_lesson_not_found(engine):
    assert engine.get_lesson("nonexistent") is None


def test_create_curriculum(engine, basic_lessons):
    ids = [l.lesson_id for l in basic_lessons]
    curriculum = engine.create_curriculum("basics", ids)
    assert curriculum.name == "basics"
    assert len(curriculum.lessons) == 3


def test_get_curriculum(engine, basic_lessons):
    ids = [l.lesson_id for l in basic_lessons]
    curriculum = engine.create_curriculum("basics", ids)
    assert engine.get_curriculum(curriculum.curriculum_id) is not None


def test_get_curriculum_not_found(engine):
    assert engine.get_curriculum("nonexistent") is None


def test_enroll(engine, basic_lessons):
    ids = [l.lesson_id for l in basic_lessons]
    curriculum = engine.create_curriculum("basics", ids)
    assert engine.enroll("agent-1", curriculum.curriculum_id)


def test_enroll_nonexistent_curriculum(engine):
    assert not engine.enroll("agent-1", "nonexistent")


def test_get_next_lesson(engine, basic_lessons):
    ids = [l.lesson_id for l in basic_lessons]
    curriculum = engine.create_curriculum("basics", ids)
    engine.enroll("agent-1", curriculum.curriculum_id)
    next_lesson = engine.get_next_lesson("agent-1", curriculum.curriculum_id)
    assert next_lesson is not None
    assert next_lesson.lesson_id == basic_lessons[0].lesson_id


def test_get_next_lesson_advances_on_pass(engine, basic_lessons):
    ids = [l.lesson_id for l in basic_lessons]
    curriculum = engine.create_curriculum("basics", ids)
    engine.enroll("agent-1", curriculum.curriculum_id)
    engine.submit_attempt("agent-1", basic_lessons[0].lesson_id, score=0.9)
    next_lesson = engine.get_next_lesson("agent-1", curriculum.curriculum_id)
    assert next_lesson.lesson_id == basic_lessons[1].lesson_id


def test_get_next_lesson_completed_curriculum(engine, basic_lessons):
    ids = [l.lesson_id for l in basic_lessons]
    curriculum = engine.create_curriculum("basics", ids)
    engine.enroll("agent-1", curriculum.curriculum_id)
    for lesson in basic_lessons:
        engine.submit_attempt("agent-1", lesson.lesson_id, score=0.9)
    assert engine.get_next_lesson("agent-1", curriculum.curriculum_id) is None


def test_submit_attempt_pass(engine, basic_lessons):
    attempt = engine.submit_attempt("agent-1", basic_lessons[0].lesson_id, score=0.9)
    assert attempt.passed is True
    assert attempt.score == 0.9


def test_submit_attempt_fail(engine, basic_lessons):
    attempt = engine.submit_attempt("agent-1", basic_lessons[0].lesson_id, score=0.3)
    assert attempt.passed is False


def test_submit_attempt_tracks_number(engine, basic_lessons):
    engine.submit_attempt("agent-1", basic_lessons[0].lesson_id, score=0.3)
    attempt2 = engine.submit_attempt("agent-1", basic_lessons[0].lesson_id, score=0.5)
    assert attempt2.attempt_number == 2


def test_lesson_status_locked(engine, basic_lessons):
    status = engine.get_lesson_status("agent-1", basic_lessons[1].lesson_id)
    assert status == LessonStatus.LOCKED


def test_lesson_status_available(engine, basic_lessons):
    status = engine.get_lesson_status("agent-1", basic_lessons[0].lesson_id)
    assert status == LessonStatus.AVAILABLE


def test_lesson_status_passed(engine, basic_lessons):
    engine.submit_attempt("agent-1", basic_lessons[0].lesson_id, score=0.9)
    status = engine.get_lesson_status("agent-1", basic_lessons[0].lesson_id)
    assert status == LessonStatus.PASSED


def test_lesson_status_in_progress(engine, basic_lessons):
    engine.submit_attempt("agent-1", basic_lessons[0].lesson_id, score=0.3)
    status = engine.get_lesson_status("agent-1", basic_lessons[0].lesson_id)
    assert status == LessonStatus.IN_PROGRESS


def test_lesson_status_failed_max_attempts(engine):
    lesson = engine.register_lesson(Lesson(name="hard", max_attempts=2))
    engine.submit_attempt("agent-1", lesson.lesson_id, score=0.3)
    engine.submit_attempt("agent-1", lesson.lesson_id, score=0.4)
    status = engine.get_lesson_status("agent-1", lesson.lesson_id)
    assert status == LessonStatus.FAILED


def test_prerequisites_unlock(engine, basic_lessons):
    engine.submit_attempt("agent-1", basic_lessons[0].lesson_id, score=0.9)
    status = engine.get_lesson_status("agent-1", basic_lessons[1].lesson_id)
    assert status == LessonStatus.AVAILABLE


def test_get_progress(engine, basic_lessons):
    ids = [l.lesson_id for l in basic_lessons]
    curriculum = engine.create_curriculum("basics", ids)
    engine.enroll("agent-1", curriculum.curriculum_id)
    engine.submit_attempt("agent-1", basic_lessons[0].lesson_id, score=0.9)
    progress = engine.get_progress("agent-1", curriculum.curriculum_id)
    assert progress.lessons_passed == 1
    assert progress.mastery_level == pytest.approx(1.0 / 3.0, abs=0.01)


def test_get_progress_empty(engine):
    progress = engine.get_progress("agent-1", "nonexistent")
    assert progress.lessons_passed == 0


def test_recommended_difficulty_beginner(engine):
    diff = engine.get_recommended_difficulty("new-agent")
    assert diff == DifficultyLevel.EASY


def test_recommended_difficulty_advances(engine):
    easy = engine.register_lesson(Lesson(name="e", difficulty=DifficultyLevel.EASY))
    for _ in range(10):
        engine.submit_attempt("agent-1", easy.lesson_id, score=0.95)
    diff = engine.get_recommended_difficulty("agent-1")
    assert diff in (DifficultyLevel.EASY, DifficultyLevel.MODERATE)


def test_recommended_difficulty_decreases_on_failure(engine):
    mod = engine.register_lesson(Lesson(name="m", difficulty=DifficultyLevel.MODERATE))
    for _ in range(10):
        engine.submit_attempt("agent-1", mod.lesson_id, score=0.2)
    diff = engine.get_recommended_difficulty("agent-1")
    assert diff in (DifficultyLevel.TRIVIAL, DifficultyLevel.EASY)


def test_get_attempts(engine, basic_lessons):
    engine.submit_attempt("agent-1", basic_lessons[0].lesson_id, score=0.5)
    engine.submit_attempt("agent-1", basic_lessons[0].lesson_id, score=0.8)
    attempts = engine.get_attempts("agent-1", lesson_id=basic_lessons[0].lesson_id)
    assert len(attempts) == 2


def test_get_attempts_all(engine, basic_lessons):
    engine.submit_attempt("agent-1", basic_lessons[0].lesson_id, score=0.9)
    engine.submit_attempt("agent-1", basic_lessons[1].lesson_id, score=0.5)
    attempts = engine.get_attempts("agent-1")
    assert len(attempts) == 2


def test_stats_empty():
    eng = CurriculumEngine()
    stats = eng.get_stats()
    assert stats.total_curricula == 0
    assert stats.total_lessons == 0


def test_stats_with_data(engine, basic_lessons):
    ids = [l.lesson_id for l in basic_lessons]
    curriculum = engine.create_curriculum("basics", ids)
    engine.enroll("agent-1", curriculum.curriculum_id)
    engine.submit_attempt("agent-1", basic_lessons[0].lesson_id, score=0.9)
    stats = engine.get_stats()
    assert stats.total_curricula == 1
    assert stats.total_lessons == 3
    assert stats.total_attempts == 1
    assert stats.agents_enrolled == 1
    assert stats.avg_pass_rate > 0


def test_custom_pass_threshold(engine):
    lesson = engine.register_lesson(Lesson(name="strict", pass_threshold=0.95))
    attempt = engine.submit_attempt("agent-1", lesson.lesson_id, score=0.9)
    assert attempt.passed is False
    attempt2 = engine.submit_attempt("agent-1", lesson.lesson_id, score=0.96)
    assert attempt2.passed is True


def test_multiple_agents_independent(engine, basic_lessons):
    ids = [l.lesson_id for l in basic_lessons]
    curriculum = engine.create_curriculum("basics", ids)
    engine.enroll("a", curriculum.curriculum_id)
    engine.enroll("b", curriculum.curriculum_id)
    engine.submit_attempt("a", basic_lessons[0].lesson_id, score=0.9)
    progress_a = engine.get_progress("a", curriculum.curriculum_id)
    progress_b = engine.get_progress("b", curriculum.curriculum_id)
    assert progress_a.lessons_passed == 1
    assert progress_b.lessons_passed == 0
