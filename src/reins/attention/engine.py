from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from reins.attention.types import (
    AttentionBudget,
    AttentionItem,
    AttentionPriority,
    AttentionShift,
    AttentionStats,
    FocusState,
    FocusWindow,
    StreamKind,
)

_PRIORITY_WEIGHTS = {
    AttentionPriority.CRITICAL: 5.0,
    AttentionPriority.HIGH: 3.0,
    AttentionPriority.NORMAL: 1.5,
    AttentionPriority.LOW: 0.8,
    AttentionPriority.BACKGROUND: 0.3,
}


class AttentionManager:
    """Cognitive focus control with attention budgets, priority streams, and focus drift detection.

    Manages what an agent pays attention to, enforces capacity limits,
    and detects when focus becomes overloaded or diffuse.
    """

    def __init__(self, default_capacity: float = 100.0) -> None:
        self._default_capacity = default_capacity
        self._windows: dict[str, _MutableWindow] = {}
        self._shifts: list[AttentionShift] = []

    def push_item(self, agent_id: str, item: AttentionItem) -> FocusState:
        window = self._get_or_create_window(agent_id)
        cost = item.weight * _PRIORITY_WEIGHTS.get(item.priority, 1.0)
        window.items.append(item)
        window.used += cost

        new_state = self._compute_state(window)
        if new_state != window.state:
            self._record_shift(agent_id, window.state, new_state, f"item added: {item.stream.value}")
            window.state = new_state
        return window.state

    def pop_item(self, agent_id: str, item_id: str) -> bool:
        window = self._windows.get(agent_id)
        if not window:
            return False
        for i, item in enumerate(window.items):
            if item.item_id == item_id:
                cost = item.weight * _PRIORITY_WEIGHTS.get(item.priority, 1.0)
                window.items.pop(i)
                window.used = max(0.0, window.used - cost)
                new_state = self._compute_state(window)
                if new_state != window.state:
                    self._record_shift(agent_id, window.state, new_state, "item removed")
                    window.state = new_state
                return True
        return False

    def get_focus_window(self, agent_id: str) -> FocusWindow:
        window = self._windows.get(agent_id)
        if not window:
            return FocusWindow(agent_id=agent_id, capacity=self._default_capacity,
                               state=FocusState.IDLE)
        utilization = window.used / window.capacity if window.capacity > 0 else 0.0
        return FocusWindow(
            agent_id=agent_id,
            items=tuple(window.items),
            state=window.state,
            capacity=window.capacity,
            utilization=utilization,
        )

    def get_budget(self, agent_id: str) -> AttentionBudget:
        window = self._windows.get(agent_id)
        if not window:
            return AttentionBudget(total_capacity=self._default_capacity,
                                   available=self._default_capacity)

        by_stream: dict[str, float] = defaultdict(float)
        for item in window.items:
            cost = item.weight * _PRIORITY_WEIGHTS.get(item.priority, 1.0)
            by_stream[item.stream.value] += cost

        available = max(0.0, window.capacity - window.used)
        return AttentionBudget(
            total_capacity=window.capacity,
            used=window.used,
            available=available,
            by_stream=dict(by_stream),
        )

    def get_top_items(self, agent_id: str, n: int = 5) -> list[AttentionItem]:
        window = self._windows.get(agent_id)
        if not window:
            return []
        sorted_items = sorted(
            window.items,
            key=lambda i: _PRIORITY_WEIGHTS.get(i.priority, 1.0) * i.weight,
            reverse=True,
        )
        return sorted_items[:n]

    def decay_items(self, agent_id: str) -> int:
        window = self._windows.get(agent_id)
        if not window:
            return 0
        removed = 0
        remaining = []
        for item in window.items:
            new_weight = item.weight * (1.0 - item.decay_rate)
            if new_weight < 0.1:
                cost = item.weight * _PRIORITY_WEIGHTS.get(item.priority, 1.0)
                window.used = max(0.0, window.used - cost)
                removed += 1
            else:
                old_cost = item.weight * _PRIORITY_WEIGHTS.get(item.priority, 1.0)
                new_cost = new_weight * _PRIORITY_WEIGHTS.get(item.priority, 1.0)
                window.used = max(0.0, window.used - old_cost + new_cost)
                remaining.append(AttentionItem(
                    item_id=item.item_id,
                    stream=item.stream,
                    priority=item.priority,
                    content=item.content,
                    weight=new_weight,
                    decay_rate=item.decay_rate,
                    metadata=item.metadata,
                    created_at=item.created_at,
                ))
            removed  # noqa: B018
        window.items = remaining

        new_state = self._compute_state(window)
        if new_state != window.state:
            self._record_shift(agent_id, window.state, new_state, "decay cycle")
            window.state = new_state
        return removed

    def clear_stream(self, agent_id: str, stream: StreamKind) -> int:
        window = self._windows.get(agent_id)
        if not window:
            return 0
        cleared = 0
        remaining = []
        for item in window.items:
            if item.stream == stream:
                cost = item.weight * _PRIORITY_WEIGHTS.get(item.priority, 1.0)
                window.used = max(0.0, window.used - cost)
                cleared += 1
            else:
                remaining.append(item)
        window.items = remaining

        new_state = self._compute_state(window)
        if new_state != window.state:
            self._record_shift(agent_id, window.state, new_state, f"cleared stream: {stream.value}")
            window.state = new_state
        return cleared

    def get_shifts(self, agent_id: str | None = None) -> list[AttentionShift]:
        if agent_id:
            return [s for s in self._shifts if s.agent_id == agent_id]
        return list(self._shifts)

    def get_stats(self) -> AttentionStats:
        total_items = sum(len(w.items) for w in self._windows.values())
        utilizations = [
            w.used / w.capacity for w in self._windows.values() if w.capacity > 0
        ]
        avg_util = sum(utilizations) / len(utilizations) if utilizations else 0.0
        overloaded = sum(1 for w in self._windows.values() if w.state == FocusState.OVERLOADED)

        by_priority: dict[str, int] = defaultdict(int)
        by_stream: dict[str, int] = defaultdict(int)
        for w in self._windows.values():
            for item in w.items:
                by_priority[item.priority.value] += 1
                by_stream[item.stream.value] += 1

        return AttentionStats(
            agents_tracked=len(self._windows),
            total_items=total_items,
            total_shifts=len(self._shifts),
            avg_utilization=avg_util,
            overloaded_agents=overloaded,
            by_priority=dict(by_priority),
            by_stream=dict(by_stream),
        )

    def _compute_state(self, window: _MutableWindow) -> FocusState:
        if not window.items:
            return FocusState.IDLE
        utilization = window.used / window.capacity if window.capacity > 0 else 0.0
        if utilization > 1.0:
            return FocusState.OVERLOADED
        if utilization > 0.8:
            return FocusState.DIFFUSE

        streams = {item.stream for item in window.items}
        if len(streams) <= 2 and utilization > 0.3:
            return FocusState.SHARP
        return FocusState.NORMAL

    def _record_shift(self, agent_id: str, from_state: FocusState,
                      to_state: FocusState, reason: str) -> None:
        self._shifts.append(AttentionShift(
            agent_id=agent_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
        ))

    def _get_or_create_window(self, agent_id: str) -> _MutableWindow:
        if agent_id not in self._windows:
            self._windows[agent_id] = _MutableWindow(
                agent_id=agent_id, capacity=self._default_capacity
            )
        return self._windows[agent_id]


class _MutableWindow:
    __slots__ = ("agent_id", "items", "state", "capacity", "used")

    def __init__(self, agent_id: str, capacity: float) -> None:
        self.agent_id = agent_id
        self.items: list[AttentionItem] = []
        self.state = FocusState.IDLE
        self.capacity = capacity
        self.used = 0.0
