from __future__ import annotations

import math
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from reins.memory.types import (
    ConsolidationResult,
    ConsolidationStrategy,
    ForgetCurve,
    MemoryEntry,
    MemoryKind,
    MemoryQuery,
    MemoryStats,
)


class MemoryConsolidator:
    """Long-term agent memory with forgetting curves, importance scoring, and consolidation.

    Models human-like memory with episodic/semantic/procedural/working types,
    Ebbinghaus forgetting curves, and periodic consolidation cycles.
    """

    def __init__(
        self,
        forget_curve: ForgetCurve = ForgetCurve.EBBINGHAUS,
        consolidation_strategy: ConsolidationStrategy = ConsolidationStrategy.HYBRID,
        forget_threshold: float = 0.1,
    ) -> None:
        self._forget_curve = forget_curve
        self._strategy = consolidation_strategy
        self._forget_threshold = forget_threshold
        self._entries: dict[str, MemoryEntry] = {}
        self._forgotten: dict[str, MemoryEntry] = {}
        self._consolidation_count = 0

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    @property
    def forgotten_count(self) -> int:
        return len(self._forgotten)

    def store(self, entry: MemoryEntry) -> MemoryEntry:
        self._entries[entry.entry_id] = entry
        return entry

    def recall(self, entry_id: str) -> MemoryEntry | None:
        entry = self._entries.get(entry_id)
        if not entry:
            return None
        updated = MemoryEntry(
            entry_id=entry.entry_id,
            agent_id=entry.agent_id,
            kind=entry.kind,
            content=entry.content,
            importance=entry.importance,
            access_count=entry.access_count + 1,
            reinforcement_count=entry.reinforcement_count,
            tags=entry.tags,
            associations=entry.associations,
            metadata=entry.metadata,
            created_at=entry.created_at,
            last_accessed=datetime.now(UTC),
            last_reinforced=entry.last_reinforced,
        )
        self._entries[entry_id] = updated
        return updated

    def reinforce(self, entry_id: str, boost: float = 0.1) -> MemoryEntry | None:
        entry = self._entries.get(entry_id)
        if not entry:
            return None
        updated = MemoryEntry(
            entry_id=entry.entry_id,
            agent_id=entry.agent_id,
            kind=entry.kind,
            content=entry.content,
            importance=min(1.0, entry.importance + boost),
            access_count=entry.access_count + 1,
            reinforcement_count=entry.reinforcement_count + 1,
            tags=entry.tags,
            associations=entry.associations,
            metadata=entry.metadata,
            created_at=entry.created_at,
            last_accessed=datetime.now(UTC),
            last_reinforced=datetime.now(UTC),
        )
        self._entries[entry_id] = updated
        return updated

    def forget(self, entry_id: str) -> bool:
        entry = self._entries.pop(entry_id, None)
        if entry:
            self._forgotten[entry_id] = entry
            return True
        return False

    def query(self, q: MemoryQuery) -> list[MemoryEntry]:
        pool = list(self._entries.values())
        if q.include_forgotten:
            pool.extend(self._forgotten.values())

        if q.agent_id:
            pool = [e for e in pool if e.agent_id == q.agent_id]
        if q.kind:
            pool = [e for e in pool if e.kind == q.kind]
        if q.tags:
            tag_set = set(q.tags)
            pool = [e for e in pool if set(e.tags) & tag_set]
        if q.min_importance > 0:
            pool = [e for e in pool if e.importance >= q.min_importance]

        pool.sort(key=lambda e: self._retention_strength(e), reverse=True)
        return pool[: q.max_results]

    def find_associated(self, entry_id: str) -> list[MemoryEntry]:
        entry = self._entries.get(entry_id)
        if not entry:
            return []
        return [self._entries[aid] for aid in entry.associations if aid in self._entries]

    def consolidate(self) -> ConsolidationResult:
        start = time.perf_counter()
        reviewed = 0
        consolidated = 0
        forgotten = 0
        strengthened = 0

        for entry_id in list(self._entries.keys()):
            entry = self._entries.get(entry_id)
            if not entry:
                continue
            reviewed += 1

            strength = self._retention_strength(entry)

            if strength < self._forget_threshold:
                self._forgotten[entry_id] = self._entries.pop(entry_id)
                forgotten += 1
            elif entry.kind == MemoryKind.WORKING and strength < 0.3:
                self._forgotten[entry_id] = self._entries.pop(entry_id)
                forgotten += 1
            elif strength > 0.8 and entry.access_count > 3:
                if entry.kind == MemoryKind.EPISODIC:
                    upgraded = MemoryEntry(
                        entry_id=entry.entry_id,
                        agent_id=entry.agent_id,
                        kind=MemoryKind.SEMANTIC,
                        content=entry.content,
                        importance=min(1.0, entry.importance + 0.05),
                        access_count=entry.access_count,
                        reinforcement_count=entry.reinforcement_count,
                        tags=entry.tags,
                        associations=entry.associations,
                        metadata=entry.metadata,
                        created_at=entry.created_at,
                        last_accessed=entry.last_accessed,
                        last_reinforced=entry.last_reinforced,
                    )
                    self._entries[entry_id] = upgraded
                    consolidated += 1
                else:
                    strengthened += 1

        self._consolidation_count += 1
        duration = (time.perf_counter() - start) * 1000

        return ConsolidationResult(
            entries_reviewed=reviewed,
            entries_consolidated=consolidated,
            entries_forgotten=forgotten,
            entries_strengthened=strengthened,
            duration_ms=duration,
        )

    def retention_strength(self, entry_id: str) -> float:
        entry = self._entries.get(entry_id)
        if not entry:
            return 0.0
        return self._retention_strength(entry)

    def get_stats(self) -> MemoryStats:
        if not self._entries:
            return MemoryStats(
                forgotten_count=len(self._forgotten),
                consolidation_cycles=self._consolidation_count,
            )

        by_kind: dict[str, int] = defaultdict(int)
        for e in self._entries.values():
            by_kind[e.kind.value] += 1

        importances = [e.importance for e in self._entries.values()]
        accesses = [e.access_count for e in self._entries.values()]

        return MemoryStats(
            total_entries=len(self._entries),
            by_kind=dict(by_kind),
            avg_importance=sum(importances) / len(importances),
            avg_access_count=sum(accesses) / len(accesses),
            forgotten_count=len(self._forgotten),
            consolidation_cycles=self._consolidation_count,
        )

    def _retention_strength(self, entry: MemoryEntry) -> float:
        age_hours = (datetime.now(UTC) - entry.last_accessed).total_seconds() / 3600.0
        base = entry.importance

        if self._forget_curve == ForgetCurve.NONE:
            return base

        reinforcement_factor = 1.0 + (entry.reinforcement_count * 0.2)

        if self._forget_curve == ForgetCurve.EBBINGHAUS:
            stability = reinforcement_factor * (1.0 + entry.access_count * 0.1)
            retention = base * math.exp(-age_hours / (24.0 * stability))
        elif self._forget_curve == ForgetCurve.POWER_LAW:
            retention = base / (1.0 + age_hours / (24.0 * reinforcement_factor)) ** 0.5
        elif self._forget_curve == ForgetCurve.EXPONENTIAL:
            half_life = 48.0 * reinforcement_factor
            retention = base * (0.5 ** (age_hours / half_life))
        else:
            retention = base

        if self._strategy == ConsolidationStrategy.FREQUENCY:
            retention *= min(2.0, 1.0 + entry.access_count * 0.1)
        elif self._strategy == ConsolidationStrategy.IMPORTANCE:
            retention *= (0.5 + entry.importance * 0.5)
        elif self._strategy == ConsolidationStrategy.HYBRID:
            freq_bonus = min(1.5, 1.0 + entry.access_count * 0.05)
            imp_bonus = 0.5 + entry.importance * 0.5
            retention *= (freq_bonus * imp_bonus)

        return min(1.0, max(0.0, retention))
