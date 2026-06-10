from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from reins.attention_economy.types import (
    AttentionBudget,
    AttentionPriority,
    AttentionSlot,
    AttentionStats,
    ContentType,
    EvictionEvent,
    EvictionPolicy,
)

_PRIORITY_WEIGHTS = {
    AttentionPriority.CRITICAL: 5.0,
    AttentionPriority.HIGH: 4.0,
    AttentionPriority.NORMAL: 3.0,
    AttentionPriority.LOW: 2.0,
    AttentionPriority.BACKGROUND: 1.0,
}


class AttentionEconomyEngine:
    """Manages attention as a scarce economic resource.

    Allocates context window budget across competing information needs,
    evicts low-value content when budget is exhausted, and optimizes
    the information density of the active context.
    """

    def __init__(self, total_tokens: int = 100000,
                 eviction_policy: EvictionPolicy = EvictionPolicy.HYBRID,
                 reserve_ratio: float = 0.1) -> None:
        self._total_tokens = total_tokens
        self._eviction_policy = eviction_policy
        self._reserve_ratio = reserve_ratio
        self._reserved = int(total_tokens * reserve_ratio)
        self._slots: dict[str, AttentionSlot] = {}
        self._evictions: list[EvictionEvent] = []

    def allocate(self, content: str, content_type: ContentType,
                 priority: AttentionPriority = AttentionPriority.NORMAL,
                 token_cost: int = 0,
                 relevance_score: float = 0.5) -> AttentionSlot | None:
        if token_cost == 0:
            token_cost = len(content.split()) * 2

        available = self._total_tokens - self._reserved - self._used_tokens()

        while token_cost > available and self._slots:
            evicted = self._evict_one(priority)
            if not evicted:
                break
            available = self._total_tokens - self._reserved - self._used_tokens()

        if token_cost > available:
            return None

        slot = AttentionSlot(
            content=content, content_type=content_type,
            priority=priority, token_cost=token_cost,
            relevance_score=relevance_score,
        )
        self._slots[slot.slot_id] = slot
        return slot

    def access(self, slot_id: str) -> AttentionSlot | None:
        slot = self._slots.get(slot_id)
        if not slot:
            return None
        updated = AttentionSlot(
            slot_id=slot.slot_id, content=slot.content,
            content_type=slot.content_type, priority=slot.priority,
            token_cost=slot.token_cost, relevance_score=slot.relevance_score,
            access_count=slot.access_count + 1,
            last_accessed_at=datetime.now(UTC),
            created_at=slot.created_at,
        )
        self._slots[slot_id] = updated
        return updated

    def update_relevance(self, slot_id: str, relevance: float) -> AttentionSlot | None:
        slot = self._slots.get(slot_id)
        if not slot:
            return None
        updated = AttentionSlot(
            slot_id=slot.slot_id, content=slot.content,
            content_type=slot.content_type, priority=slot.priority,
            token_cost=slot.token_cost, relevance_score=relevance,
            access_count=slot.access_count,
            last_accessed_at=slot.last_accessed_at,
            created_at=slot.created_at,
        )
        self._slots[slot_id] = updated
        return updated

    def evict(self, slot_id: str, reason: str = "manual") -> EvictionEvent | None:
        slot = self._slots.get(slot_id)
        if not slot:
            return None
        del self._slots[slot_id]
        event = EvictionEvent(
            evicted_slot_id=slot_id,
            reason=reason,
            tokens_freed=slot.token_cost,
        )
        self._evictions.append(event)
        return event

    def get_budget(self) -> AttentionBudget:
        used = self._used_tokens()
        return AttentionBudget(
            total_tokens=self._total_tokens,
            used_tokens=used,
            reserved_tokens=self._reserved,
            available_tokens=self._total_tokens - self._reserved - used,
        )

    def get_slot(self, slot_id: str) -> AttentionSlot | None:
        return self._slots.get(slot_id)

    def get_slots_by_type(self, content_type: ContentType) -> list[AttentionSlot]:
        return [s for s in self._slots.values() if s.content_type == content_type]

    def get_slots_by_priority(self, priority: AttentionPriority) -> list[AttentionSlot]:
        return [s for s in self._slots.values() if s.priority == priority]

    def get_top_slots(self, n: int = 10) -> list[AttentionSlot]:
        return sorted(
            self._slots.values(),
            key=lambda s: self._slot_value(s),
            reverse=True,
        )[:n]

    def compact(self, target_utilization: float = 0.7) -> list[EvictionEvent]:
        target_used = int(self._total_tokens * target_utilization)
        events = []
        while self._used_tokens() > target_used and self._slots:
            event = self._evict_one(AttentionPriority.CRITICAL)
            if event:
                events.append(event)
            else:
                break
        return events

    def get_stats(self) -> AttentionStats:
        by_type: dict[str, int] = defaultdict(int)
        by_priority: dict[str, int] = defaultdict(int)
        relevances = []

        for slot in self._slots.values():
            by_type[slot.content_type.value] += 1
            by_priority[slot.priority.value] += 1
            relevances.append(slot.relevance_score)

        used = self._used_tokens()
        utilization = used / self._total_tokens if self._total_tokens > 0 else 0.0
        avg_rel = sum(relevances) / len(relevances) if relevances else 0.0

        return AttentionStats(
            total_slots=len(self._slots),
            total_tokens_used=used,
            budget_utilization=utilization,
            evictions=len(self._evictions),
            avg_relevance=avg_rel,
            by_type=dict(by_type),
            by_priority=dict(by_priority),
        )

    def _used_tokens(self) -> int:
        return sum(s.token_cost for s in self._slots.values())

    def _slot_value(self, slot: AttentionSlot) -> float:
        priority_w = _PRIORITY_WEIGHTS.get(slot.priority, 3.0)
        recency = slot.access_count * 0.1
        return priority_w * slot.relevance_score + recency

    def _evict_one(self, protect_priority: AttentionPriority) -> EvictionEvent | None:
        candidates = [
            s for s in self._slots.values()
            if _PRIORITY_WEIGHTS.get(s.priority, 3) < _PRIORITY_WEIGHTS.get(protect_priority, 3)
        ]
        if not candidates:
            candidates = list(self._slots.values())

        if not candidates:
            return None

        if self._eviction_policy == EvictionPolicy.LRU:
            victim = min(candidates, key=lambda s: s.last_accessed_at)
        elif self._eviction_policy == EvictionPolicy.LFU:
            victim = min(candidates, key=lambda s: s.access_count)
        elif self._eviction_policy == EvictionPolicy.PRIORITY:
            victim = min(candidates, key=lambda s: _PRIORITY_WEIGHTS.get(s.priority, 3))
        elif self._eviction_policy == EvictionPolicy.RELEVANCE:
            victim = min(candidates, key=lambda s: s.relevance_score)
        else:
            victim = min(candidates, key=lambda s: self._slot_value(s))

        return self.evict(victim.slot_id, reason=f"eviction_policy:{self._eviction_policy.value}")
