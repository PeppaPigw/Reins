"""Tests for capability evolution with skill progression tracking."""

from __future__ import annotations

import pytest

from reins.evolution import (
    CapabilityEvolution,
    EvolutionStats,
    MasteryLevel,
    ProgressionEvent,
    ProgressionRecord,
    Skill,
    SkillCategory,
    SkillState,
)


@pytest.fixture
def engine() -> CapabilityEvolution:
    return CapabilityEvolution()


@pytest.fixture
def coding_skill() -> Skill:
    return Skill(name="Python", category=SkillCategory.CODING, xp_to_master=100.0)


@pytest.fixture
def advanced_skill(coding_skill) -> Skill:
    return Skill(
        name="Architecture",
        category=SkillCategory.ARCHITECTURE,
        prerequisites=(coding_skill.skill_id,),
        xp_to_master=200.0,
    )


def test_register_skill(engine, coding_skill):
    registered = engine.register_skill(coding_skill)
    assert engine.get_skill(registered.skill_id) is not None


def test_get_skill_not_found(engine):
    assert engine.get_skill("nonexistent") is None


def test_record_progression_practice(engine, coding_skill):
    engine.register_skill(coding_skill)
    record = engine.record_progression("agent-1", coding_skill.skill_id, ProgressionEvent.PRACTICE)
    assert record.event == ProgressionEvent.PRACTICE
    assert record.xp_delta == 5.0


def test_record_progression_success(engine, coding_skill):
    engine.register_skill(coding_skill)
    record = engine.record_progression("agent-1", coding_skill.skill_id, ProgressionEvent.SUCCESS)
    assert record.xp_delta == 15.0


def test_record_progression_milestone(engine, coding_skill):
    engine.register_skill(coding_skill)
    record = engine.record_progression("agent-1", coding_skill.skill_id, ProgressionEvent.MILESTONE)
    assert record.xp_delta == 50.0


def test_xp_accumulates(engine, coding_skill):
    engine.register_skill(coding_skill)
    engine.record_progression("agent-1", coding_skill.skill_id, ProgressionEvent.SUCCESS)
    engine.record_progression("agent-1", coding_skill.skill_id, ProgressionEvent.SUCCESS)
    state = engine.get_state("agent-1", coding_skill.skill_id)
    assert state.xp == 30.0


def test_level_up_on_xp(engine, coding_skill):
    engine.register_skill(coding_skill)
    for _ in range(3):
        engine.record_progression("agent-1", coding_skill.skill_id, ProgressionEvent.SUCCESS)
    state = engine.get_state("agent-1", coding_skill.skill_id)
    assert state.level != MasteryLevel.NOVICE


def test_level_progression_to_master(engine, coding_skill):
    engine.register_skill(coding_skill)
    for _ in range(7):
        engine.record_progression("agent-1", coding_skill.skill_id, ProgressionEvent.MILESTONE)
    state = engine.get_state("agent-1", coding_skill.skill_id)
    assert state.level == MasteryLevel.MASTER


def test_level_up_recorded_in_progression(engine, coding_skill):
    engine.register_skill(coding_skill)
    engine.record_progression("agent-1", coding_skill.skill_id, ProgressionEvent.MILESTONE)
    records = engine.get_progression_history(agent_id="agent-1")
    level_ups = [r for r in records if r.to_level is not None]
    assert len(level_ups) >= 1


def test_decay_reduces_xp(engine, coding_skill):
    engine.register_skill(coding_skill)
    engine.record_progression("agent-1", coding_skill.skill_id, ProgressionEvent.SUCCESS)
    engine.record_progression("agent-1", coding_skill.skill_id, ProgressionEvent.DECAY)
    state = engine.get_state("agent-1", coding_skill.skill_id)
    assert state.xp == 5.0


def test_xp_floor_at_zero(engine, coding_skill):
    engine.register_skill(coding_skill)
    engine.record_progression("agent-1", coding_skill.skill_id, ProgressionEvent.DECAY)
    state = engine.get_state("agent-1", coding_skill.skill_id)
    assert state.xp == 0.0


def test_get_state_unknown(engine):
    state = engine.get_state("agent-1", "unknown-skill")
    assert state.level == MasteryLevel.NOVICE
    assert state.xp == 0.0


def test_get_agent_skills(engine, coding_skill):
    engine.register_skill(coding_skill)
    engine.record_progression("agent-1", coding_skill.skill_id, ProgressionEvent.PRACTICE)
    skills = engine.get_agent_skills("agent-1")
    assert len(skills) == 1
    assert skills[0].skill_id == coding_skill.skill_id


def test_get_agent_skills_empty(engine):
    assert engine.get_agent_skills("unknown") == []


def test_check_prerequisites_no_prereqs(engine, coding_skill):
    engine.register_skill(coding_skill)
    assert engine.check_prerequisites("agent-1", coding_skill.skill_id)


def test_check_prerequisites_unmet(engine, coding_skill, advanced_skill):
    engine.register_skill(coding_skill)
    engine.register_skill(advanced_skill)
    assert not engine.check_prerequisites("agent-1", advanced_skill.skill_id)


def test_check_prerequisites_met(engine, coding_skill, advanced_skill):
    engine.register_skill(coding_skill)
    engine.register_skill(advanced_skill)
    for _ in range(5):
        engine.record_progression("agent-1", coding_skill.skill_id, ProgressionEvent.MILESTONE)
    assert engine.check_prerequisites("agent-1", advanced_skill.skill_id)


def test_get_unlocked_skills(engine, coding_skill, advanced_skill):
    engine.register_skill(coding_skill)
    engine.register_skill(advanced_skill)
    unlocked = engine.get_unlocked_skills("agent-1")
    assert coding_skill in unlocked
    assert advanced_skill not in unlocked


def test_get_unlocked_skills_after_progression(engine, coding_skill, advanced_skill):
    engine.register_skill(coding_skill)
    engine.register_skill(advanced_skill)
    for _ in range(5):
        engine.record_progression("agent-1", coding_skill.skill_id, ProgressionEvent.MILESTONE)
    unlocked = engine.get_unlocked_skills("agent-1")
    assert advanced_skill in unlocked


def test_progression_history_by_agent(engine, coding_skill):
    engine.register_skill(coding_skill)
    engine.record_progression("a", coding_skill.skill_id, ProgressionEvent.PRACTICE)
    engine.record_progression("b", coding_skill.skill_id, ProgressionEvent.PRACTICE)
    history = engine.get_progression_history(agent_id="a")
    assert len(history) == 1


def test_progression_history_by_skill(engine, coding_skill):
    other = Skill(name="Debug", category=SkillCategory.DEBUGGING)
    engine.register_skill(coding_skill)
    engine.register_skill(other)
    engine.record_progression("a", coding_skill.skill_id, ProgressionEvent.PRACTICE)
    engine.record_progression("a", other.skill_id, ProgressionEvent.PRACTICE)
    history = engine.get_progression_history(skill_id=coding_skill.skill_id)
    assert len(history) == 1


def test_success_and_failure_counts(engine, coding_skill):
    engine.register_skill(coding_skill)
    engine.record_progression("a", coding_skill.skill_id, ProgressionEvent.SUCCESS)
    engine.record_progression("a", coding_skill.skill_id, ProgressionEvent.SUCCESS)
    engine.record_progression("a", coding_skill.skill_id, ProgressionEvent.FAILURE)
    state = engine.get_state("a", coding_skill.skill_id)
    assert state.success_count == 2
    assert state.failure_count == 1


def test_practice_count(engine, coding_skill):
    engine.register_skill(coding_skill)
    for _ in range(5):
        engine.record_progression("a", coding_skill.skill_id, ProgressionEvent.PRACTICE)
    state = engine.get_state("a", coding_skill.skill_id)
    assert state.practice_count == 5


def test_stats_empty():
    e = CapabilityEvolution()
    stats = e.get_stats()
    assert stats.agents_tracked == 0
    assert stats.total_skills == 0


def test_stats_with_data(engine, coding_skill):
    engine.register_skill(coding_skill)
    engine.record_progression("a", coding_skill.skill_id, ProgressionEvent.SUCCESS)
    stats = engine.get_stats()
    assert stats.agents_tracked == 1
    assert stats.total_skills == 1
    assert stats.total_progressions == 1
    assert SkillCategory.CODING.value in stats.by_category


def test_multiple_agents_independent(engine, coding_skill):
    engine.register_skill(coding_skill)
    engine.record_progression("a", coding_skill.skill_id, ProgressionEvent.MILESTONE)
    engine.record_progression("b", coding_skill.skill_id, ProgressionEvent.PRACTICE)
    state_a = engine.get_state("a", coding_skill.skill_id)
    state_b = engine.get_state("b", coding_skill.skill_id)
    assert state_a.xp > state_b.xp


def test_metadata_preserved(engine, coding_skill):
    engine.register_skill(coding_skill)
    record = engine.record_progression(
        "a", coding_skill.skill_id, ProgressionEvent.SUCCESS,
        metadata={"task": "code-review"}
    )
    assert record.metadata == {"task": "code-review"}
