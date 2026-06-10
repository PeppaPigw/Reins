from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from reins.adaptive_context.types import (
    ContextPriority,
    ContextShard,
    ContextStats,
    ContextWindow,
    DecayStrategy,
    EvictionEvent,
    EvictionReason,
    TokenBudget,
)


_PRIORITY_WEIGHTS = {
    ContextPriority.CRITICAL: 1.0,
    ContextPriority.HIGH: 0.8,
    ContextPriority.MEDIUM: 0.5,
    ContextPriority.LOW: 0.3,
    ContextPriority.BACKGROUND: 0.1,
}

_DECAY_HALF_LIFE_MINUTES = 30.0


class AdaptiveContextManager:
    """Intelligently manages context window contents with relevance scoring and token budgets.

    Dynamically scores and selects the most relevant context shards for each
    agent turn, enforcing token budgets and applying relevance decay over time.
    """

    def __init__(self, budget: TokenBudget | None = None) -> None:
        self._budget = budget or TokenBudget()
        self._shards: dict[str, ContextShard] = {}
        self._evictions: list[EvictionEvent] = []
        self._access_log: dict[str, int] = defaultdict(int)

    @property
    def shard_count(self) -> int:
        return len(self._shards)

    @property
    def total_tokens(self) -> int:
        return sum(s.token_count for s in self._shards.values())

    @property
    def available_tokens(self) -> int:
        max_ctx = int(self._budget.total_tokens * self._budget.max_context_pct)
        usable = max_ctx - self._budget.reserved_system - self._budget.reserved_output
        return max(0, usable - self.total_tokens)

    def add_shard(self, shard: ContextShard) -> ContextShard:
        self._shards[shard.shard_id] = shard
        self._enforce_budget()
        return shard

    def remove_shard(self, shard_id: str) -> bool:
        if shard_id in self._shards:
            shard = self._shards.pop(shard_id)
            self._evictions.append(EvictionEvent(
                shard_id=shard_id,
                reason=EvictionReason.MANUAL,
                relevance_at_eviction=self._compute_relevance(shard),
                tokens_freed=shard.token_count,
            ))
            return True
        return False

    def get_shard(self, shard_id: str) -> ContextShard | None:
        shard = self._shards.get(shard_id)
        if shard:
            self._access_log[shard_id] += 1
            updated = ContextShard(
                shard_id=shard.shard_id,
                content=shard.content,
                source=shard.source,
                priority=shard.priority,
                token_count=shard.token_count,
                relevance_score=shard.relevance_score,
                decay_strategy=shard.decay_strategy,
                tags=shard.tags,
                created_at=shard.created_at,
                last_accessed=datetime.now(UTC),
                access_count=shard.access_count + 1,
                metadata=shard.metadata,
            )
            self._shards[shard_id] = updated
            return updated
        return None

    def assemble_window(self, task_tags: tuple[str, ...] = (), max_tokens: int | None = None) -> ContextWindow:
        budget_limit = max_tokens or self._compute_max_context_tokens()
        scored = self._score_all_shards(task_tags)
        scored.sort(key=lambda x: x[1], reverse=True)

        selected: list[ContextShard] = []
        tokens_used = 0

        for shard, score in scored:
            if tokens_used + shard.token_count > budget_limit:
                continue
            if shard.token_count < self._budget.min_shard_tokens:
                continue
            selected.append(shard)
            tokens_used += shard.token_count

        return ContextWindow(
            shards=tuple(selected),
            total_tokens_used=tokens_used,
            budget=self._budget,
        )

    def decay_all(self) -> int:
        evicted = 0
        to_evict = []

        for shard_id, shard in self._shards.items():
            relevance = self._compute_relevance(shard)
            if relevance < 0.05:
                to_evict.append((shard_id, shard, relevance))

        for shard_id, shard, relevance in to_evict:
            del self._shards[shard_id]
            self._evictions.append(EvictionEvent(
                shard_id=shard_id,
                reason=EvictionReason.RELEVANCE_DECAY,
                relevance_at_eviction=relevance,
                tokens_freed=shard.token_count,
            ))
            evicted += 1

        return evicted

    def find_by_tags(self, tags: tuple[str, ...]) -> list[ContextShard]:
        tag_set = set(tags)
        return [s for s in self._shards.values() if set(s.tags) & tag_set]

    def find_by_source(self, source: str) -> list[ContextShard]:
        return [s for s in self._shards.values() if s.source == source]

    def get_stats(self) -> ContextStats:
        if not self._shards:
            return ContextStats()

        total_tokens = self.total_tokens
        max_tokens = self._compute_max_context_tokens()
        relevances = [self._compute_relevance(s) for s in self._shards.values()]

        total_accesses = sum(self._access_log.values())
        hits = sum(1 for v in self._access_log.values() if v > 1)

        return ContextStats(
            total_shards=len(self._shards),
            total_tokens=total_tokens,
            budget_utilization=total_tokens / max_tokens if max_tokens else 0.0,
            avg_relevance=sum(relevances) / len(relevances) if relevances else 0.0,
            evictions_total=len(self._evictions),
            cache_hit_rate=hits / len(self._access_log) if self._access_log else 0.0,
        )

    def _compute_max_context_tokens(self) -> int:
        max_ctx = int(self._budget.total_tokens * self._budget.max_context_pct)
        return max_ctx - self._budget.reserved_system - self._budget.reserved_output

    def _score_all_shards(self, task_tags: tuple[str, ...]) -> list[tuple[ContextShard, float]]:
        scored = []
        for shard in self._shards.values():
            relevance = self._compute_relevance(shard)
            priority_weight = _PRIORITY_WEIGHTS.get(shard.priority, 0.5)
            tag_bonus = self._compute_tag_bonus(shard, task_tags)
            score = relevance * 0.4 + priority_weight * 0.4 + tag_bonus * 0.2
            scored.append((shard, score))
        return scored

    def _compute_relevance(self, shard: ContextShard) -> float:
        base = shard.relevance_score
        age_minutes = (datetime.now(UTC) - shard.last_accessed).total_seconds() / 60.0

        if shard.decay_strategy == DecayStrategy.NONE:
            return base
        elif shard.decay_strategy == DecayStrategy.LINEAR:
            decay = max(0.0, 1.0 - age_minutes / (60.0 * 24))
            return base * decay
        elif shard.decay_strategy == DecayStrategy.EXPONENTIAL:
            decay = math.exp(-age_minutes / _DECAY_HALF_LIFE_MINUTES * math.log(2))
            return base * decay
        elif shard.decay_strategy == DecayStrategy.STEP:
            if age_minutes < 30:
                return base
            elif age_minutes < 120:
                return base * 0.5
            else:
                return base * 0.1
        return base

    def _compute_tag_bonus(self, shard: ContextShard, task_tags: tuple[str, ...]) -> float:
        if not task_tags or not shard.tags:
            return 0.0
        overlap = len(set(shard.tags) & set(task_tags))
        return min(1.0, overlap * 0.3)

    def _enforce_budget(self) -> None:
        max_tokens = self._compute_max_context_tokens()
        while self.total_tokens > max_tokens and self._shards:
            worst = min(self._shards.values(), key=lambda s: self._compute_relevance(s))
            del self._shards[worst.shard_id]
            self._evictions.append(EvictionEvent(
                shard_id=worst.shard_id,
                reason=EvictionReason.TOKEN_BUDGET,
                relevance_at_eviction=self._compute_relevance(worst),
                tokens_freed=worst.token_count,
            ))
