from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from reins.evolution.types import (
    EvolutionStats,
    MasteryLevel,
    ProgressionEvent,
    ProgressionRecord,
    Skill,
    SkillCategory,
    SkillState,
)

_LEVEL_THRESHOLDS = {
    MasteryLevel.NOVICE: 0.0,
    MasteryLevel.APPRENTICE: 0.1,
    MasteryLevel.COMPETENT: 0.3,
    MasteryLevel.PROFICIENT: 0.55,
    MasteryLevel.EXPERT: 0.8,
    MasteryLevel.MASTER: 1.0,
}

_LEVEL_ORDER = [
    MasteryLevel.NOVICE,
    MasteryLevel.APPRENTICE,
    MasteryLevel.COMPETENT,
    MasteryLevel.PROFICIENT,
    MasteryLevel.EXPERT,
    MasteryLevel.MASTER,
]

_XP_GAINS = {
    ProgressionEvent.PRACTICE: 5.0,
    ProgressionEvent.SUCCESS: 15.0,
    ProgressionEvent.FAILURE: 3.0,
    ProgressionEvent.FEEDBACK: 10.0,
    ProgressionEvent.MILESTONE: 50.0,
    ProgressionEvent.DECAY: -10.0,
}


class CapabilityEvolution:
    """Skill progression tracking with mastery levels, skill trees, and capability unlocking.

    Tracks agent skill development over time, manages prerequisites,
    and computes mastery levels based on accumulated experience.
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._states: dict[str, dict[str, _MutableState]] = defaultdict(dict)
        self._records: list[ProgressionRecord] = []

    def register_skill(self, skill: Skill) -> Skill:
        self._skills[skill.skill_id] = skill
        return skill

    def get_skill(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def record_progression(self, agent_id: str, skill_id: str,
                           event: ProgressionEvent,
                           metadata: dict | None = None) -> ProgressionRecord:
        state = self._get_or_create_state(agent_id, skill_id)
        xp_delta = _XP_GAINS.get(event, 0.0)

        old_level = state.level
        state.xp = max(0.0, state.xp + xp_delta)
        state.practice_count += 1
        state.last_practiced_at = datetime.now(UTC)

        if event == ProgressionEvent.SUCCESS:
            state.success_count += 1
        elif event == ProgressionEvent.FAILURE:
            state.failure_count += 1

        new_level = self._compute_level(state, skill_id)
        state.level = new_level

        record = ProgressionRecord(
            agent_id=agent_id,
            skill_id=skill_id,
            event=event,
            xp_delta=xp_delta,
            from_level=old_level if old_level != new_level else None,
            to_level=new_level if old_level != new_level else None,
            metadata=metadata or {},
        )
        self._records.append(record)
        return record

    def get_state(self, agent_id: str, skill_id: str) -> SkillState:
        state = self._states.get(agent_id, {}).get(skill_id)
        if not state:
            return SkillState(skill_id=skill_id, agent_id=agent_id)
        return SkillState(
            skill_id=skill_id,
            agent_id=agent_id,
            level=state.level,
            xp=state.xp,
            practice_count=state.practice_count,
            success_count=state.success_count,
            failure_count=state.failure_count,
            last_practiced_at=state.last_practiced_at,
        )

    def get_agent_skills(self, agent_id: str) -> list[SkillState]:
        states = self._states.get(agent_id, {})
        return [
            SkillState(
                skill_id=sid,
                agent_id=agent_id,
                level=s.level,
                xp=s.xp,
                practice_count=s.practice_count,
                success_count=s.success_count,
                failure_count=s.failure_count,
                last_practiced_at=s.last_practiced_at,
            )
            for sid, s in states.items()
        ]

    def check_prerequisites(self, agent_id: str, skill_id: str) -> bool:
        skill = self._skills.get(skill_id)
        if not skill or not skill.prerequisites:
            return True
        for prereq_id in skill.prerequisites:
            state = self._states.get(agent_id, {}).get(prereq_id)
            if not state or _LEVEL_ORDER.index(state.level) < _LEVEL_ORDER.index(MasteryLevel.COMPETENT):
                return False
        return True

    def get_unlocked_skills(self, agent_id: str) -> list[Skill]:
        unlocked = []
        for skill in self._skills.values():
            if self.check_prerequisites(agent_id, skill.skill_id):
                unlocked.append(skill)
        return unlocked

    def get_progression_history(self, agent_id: str | None = None,
                                skill_id: str | None = None) -> list[ProgressionRecord]:
        records = self._records
        if agent_id:
            records = [r for r in records if r.agent_id == agent_id]
        if skill_id:
            records = [r for r in records if r.skill_id == skill_id]
        return records

    def get_stats(self) -> EvolutionStats:
        all_states = [
            s for agent_states in self._states.values()
            for s in agent_states.values()
        ]

        by_category: dict[str, int] = defaultdict(int)
        for skill in self._skills.values():
            by_category[skill.category.value] += 1

        by_level: dict[str, int] = defaultdict(int)
        for state in all_states:
            by_level[state.level.value] += 1

        level_values = [_LEVEL_ORDER.index(s.level) for s in all_states]
        avg_mastery = sum(level_values) / len(level_values) if level_values else 0.0

        return EvolutionStats(
            agents_tracked=len(self._states),
            total_skills=len(self._skills),
            total_progressions=len(self._records),
            avg_mastery_level=avg_mastery,
            by_category=dict(by_category),
            by_level=dict(by_level),
        )

    def _compute_level(self, state: _MutableState, skill_id: str) -> MasteryLevel:
        skill = self._skills.get(skill_id)
        xp_to_master = skill.xp_to_master if skill else 1000.0
        progress = min(1.0, state.xp / xp_to_master)

        for level in reversed(_LEVEL_ORDER):
            if progress >= _LEVEL_THRESHOLDS[level]:
                return level
        return MasteryLevel.NOVICE

    def _get_or_create_state(self, agent_id: str, skill_id: str) -> _MutableState:
        if skill_id not in self._states[agent_id]:
            self._states[agent_id][skill_id] = _MutableState(skill_id=skill_id)
        return self._states[agent_id][skill_id]


class _MutableState:
    __slots__ = (
        "skill_id", "level", "xp", "practice_count",
        "success_count", "failure_count", "last_practiced_at",
    )

    def __init__(self, skill_id: str) -> None:
        self.skill_id = skill_id
        self.level = MasteryLevel.NOVICE
        self.xp = 0.0
        self.practice_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.last_practiced_at: datetime | None = None
