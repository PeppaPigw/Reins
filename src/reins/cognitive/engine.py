from __future__ import annotations

import time
from collections import defaultdict

from reins.cognitive.types import (
    CognitiveLoad,
    CognitiveProfile,
    CognitiveState,
    CognitiveStats,
    ExecutiveFunction,
    MemoryItem,
    MemoryKind,
    WorkingMemorySlot,
)


class CognitiveArchitecture:
    """Cognitive science-inspired agent architecture with working memory and executive function.

    Models bounded rationality: agents have limited working memory (7+/-2 slots),
    experience cognitive load and fatigue, and must manage attention through
    executive functions. This enables realistic agent behavior modeling.
    """

    def __init__(self, working_memory_capacity: int = 7) -> None:
        self._capacity = working_memory_capacity
        self._memory_store: dict[str, MemoryItem] = {}
        self._working_memory: dict[str, list[WorkingMemorySlot]] = defaultdict(list)
        self._loads: dict[str, dict[str, float]] = defaultdict(lambda: {
            "intrinsic": 0.0, "extraneous": 0.0, "germane": 0.0,
        })
        self._fatigue: dict[str, float] = defaultdict(float)
        self._focus_start: dict[str, float] = {}
        self._task_counts: dict[str, int] = defaultdict(int)

    def store_memory(self, kind: MemoryKind, content: str,
                     salience: float = 0.5, decay_rate: float = 0.1,
                     associations: list[str] | None = None) -> MemoryItem:
        item = MemoryItem(
            kind=kind, content=content, salience=salience,
            decay_rate=decay_rate, associations=tuple(associations or []),
        )
        self._memory_store[item.item_id] = item
        return item

    def get_memory(self, item_id: str) -> MemoryItem | None:
        return self._memory_store.get(item_id)

    def load_to_working_memory(self, agent_id: str, item_id: str) -> WorkingMemorySlot | None:
        if item_id not in self._memory_store:
            return None

        slots = self._working_memory[agent_id]
        if len(slots) >= self._capacity:
            slots.sort(key=lambda s: s.activation)
            slots.pop(0)

        slot = WorkingMemorySlot(item_id=item_id)
        slots.append(slot)
        return slot

    def get_working_memory(self, agent_id: str) -> list[WorkingMemorySlot]:
        return self._working_memory.get(agent_id, [])

    def rehearse(self, agent_id: str, item_id: str) -> WorkingMemorySlot | None:
        slots = self._working_memory.get(agent_id, [])
        for i, slot in enumerate(slots):
            if slot.item_id == item_id:
                updated = WorkingMemorySlot(
                    slot_id=slot.slot_id,
                    item_id=slot.item_id,
                    activation=min(slot.activation + 0.2, 1.0),
                    rehearsals=slot.rehearsals + 1,
                    loaded_at=slot.loaded_at,
                )
                slots[i] = updated
                return updated
        return None

    def clear_working_memory(self, agent_id: str) -> None:
        self._working_memory[agent_id] = []

    def add_load(self, agent_id: str, load_type: CognitiveLoad, amount: float) -> None:
        self._loads[agent_id][load_type.value] += amount
        self._fatigue[agent_id] += amount * 0.05

    def reduce_load(self, agent_id: str, load_type: CognitiveLoad, amount: float) -> None:
        current = self._loads[agent_id][load_type.value]
        self._loads[agent_id][load_type.value] = max(0.0, current - amount)

    def start_focus(self, agent_id: str) -> None:
        self._focus_start[agent_id] = time.monotonic()

    def end_focus(self, agent_id: str) -> float:
        start = self._focus_start.pop(agent_id, None)
        if start is None:
            return 0.0
        duration = (time.monotonic() - start) * 1000
        self._fatigue[agent_id] += duration * 0.0001
        return duration

    def complete_task(self, agent_id: str) -> None:
        self._task_counts[agent_id] += 1
        self._fatigue[agent_id] = max(0.0, self._fatigue[agent_id] - 0.1)

    def rest(self, agent_id: str, amount: float = 0.5) -> None:
        self._fatigue[agent_id] = max(0.0, self._fatigue[agent_id] - amount)

    def get_profile(self, agent_id: str) -> CognitiveProfile:
        slots = self._working_memory.get(agent_id, [])
        wm_load = len(slots) / self._capacity

        loads = self._loads[agent_id]
        intrinsic = loads["intrinsic"]
        extraneous = loads["extraneous"]
        germane = loads["germane"]
        total_load = intrinsic + extraneous + germane

        fatigue = self._fatigue.get(agent_id, 0.0)
        state = self._determine_state(wm_load, total_load, fatigue)

        focus_duration = 0.0
        if agent_id in self._focus_start:
            focus_duration = (time.monotonic() - self._focus_start[agent_id]) * 1000

        return CognitiveProfile(
            agent_id=agent_id,
            state=state,
            working_memory_load=wm_load,
            working_memory_capacity=self._capacity,
            total_load=total_load,
            intrinsic_load=intrinsic,
            extraneous_load=extraneous,
            germane_load=germane,
            fatigue_level=fatigue,
            focus_duration_ms=focus_duration,
        )

    def get_state(self, agent_id: str) -> CognitiveState:
        profile = self.get_profile(agent_id)
        return profile.state

    def should_offload(self, agent_id: str) -> bool:
        profile = self.get_profile(agent_id)
        return profile.working_memory_load > 0.8 or profile.total_load > 2.0

    def get_stats(self) -> CognitiveStats:
        agents = set(list(self._working_memory.keys()) + list(self._loads.keys()))

        by_state: dict[str, int] = defaultdict(int)
        wm_loads = []
        fatigues = []
        for agent_id in agents:
            profile = self.get_profile(agent_id)
            by_state[profile.state.value] += 1
            wm_loads.append(profile.working_memory_load)
            fatigues.append(profile.fatigue_level)

        by_kind: dict[str, int] = defaultdict(int)
        for item in self._memory_store.values():
            by_kind[item.kind.value] += 1

        return CognitiveStats(
            total_agents=len(agents),
            total_memory_items=len(self._memory_store),
            avg_working_memory_load=sum(wm_loads) / len(wm_loads) if wm_loads else 0.0,
            avg_fatigue=sum(fatigues) / len(fatigues) if fatigues else 0.0,
            by_state=dict(by_state),
            by_memory_kind=dict(by_kind),
        )

    def _determine_state(self, wm_load: float, total_load: float,
                         fatigue: float) -> CognitiveState:
        if fatigue > 1.5:
            return CognitiveState.FATIGUED
        if total_load > 3.0 or wm_load > 0.95:
            return CognitiveState.OVERLOADED
        if 0.5 <= wm_load <= 0.8 and total_load < 2.0 and fatigue < 0.5:
            return CognitiveState.FLOW
        if wm_load > 0.2 or total_load > 0.5:
            return CognitiveState.FOCUSED
        if fatigue > 0.8:
            return CognitiveState.RECOVERING
        return CognitiveState.IDLE
