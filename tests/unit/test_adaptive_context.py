"""Tests for adaptive context management engine."""

from __future__ import annotations

import pytest

from reins.adaptive_context import (
    AdaptiveContextManager,
    ContextPriority,
    ContextShard,
    DecayStrategy,
    EvictionReason,
    TokenBudget,
)


@pytest.fixture
def manager() -> AdaptiveContextManager:
    budget = TokenBudget(total_tokens=10000, reserved_system=1000, reserved_output=1000, max_context_pct=0.8)
    return AdaptiveContextManager(budget=budget)


def _shard(content="test", tokens=100, priority=ContextPriority.MEDIUM, tags=(), decay=DecayStrategy.NONE, source=""):
    return ContextShard(
        content=content,
        token_count=tokens,
        priority=priority,
        tags=tags,
        decay_strategy=decay,
        source=source,
    )


def test_add_shard(manager):
    shard = _shard("hello", 200)
    manager.add_shard(shard)
    assert manager.shard_count == 1
    assert manager.total_tokens == 200


def test_remove_shard(manager):
    shard = _shard("hello", 200)
    manager.add_shard(shard)
    assert manager.remove_shard(shard.shard_id)
    assert manager.shard_count == 0


def test_remove_nonexistent(manager):
    assert not manager.remove_shard("nonexistent")


def test_get_shard_increments_access(manager):
    shard = _shard("hello", 200)
    manager.add_shard(shard)
    retrieved = manager.get_shard(shard.shard_id)
    assert retrieved is not None
    assert retrieved.access_count == 1


def test_get_nonexistent_shard(manager):
    assert manager.get_shard("nonexistent") is None


def test_assemble_window_respects_budget(manager):
    for i in range(100):
        manager.add_shard(_shard(f"shard-{i}", 100))
    window = manager.assemble_window()
    assert window.total_tokens_used <= 6000


def test_assemble_window_prioritizes_high(manager):
    manager.add_shard(_shard("low", 500, ContextPriority.LOW))
    manager.add_shard(_shard("critical", 500, ContextPriority.CRITICAL))
    manager.add_shard(_shard("medium", 500, ContextPriority.MEDIUM))
    window = manager.assemble_window()
    assert window.shards[0].priority == ContextPriority.CRITICAL


def test_assemble_window_tag_bonus(manager):
    manager.add_shard(_shard("python", 200, ContextPriority.LOW, tags=("python", "backend")))
    manager.add_shard(_shard("rust", 200, ContextPriority.LOW, tags=("rust",)))
    window = manager.assemble_window(task_tags=("python",))
    assert window.shards[0].content == "python"


def test_assemble_window_skips_tiny_shards(manager):
    budget = TokenBudget(total_tokens=10000, reserved_system=500, reserved_output=500, max_context_pct=0.8, min_shard_tokens=100)
    mgr = AdaptiveContextManager(budget=budget)
    mgr.add_shard(_shard("tiny", 10))
    mgr.add_shard(_shard("normal", 200))
    window = mgr.assemble_window()
    assert len(window.shards) == 1
    assert window.shards[0].content == "normal"


def test_budget_enforcement_evicts_lowest_relevance(manager):
    for i in range(200):
        manager.add_shard(_shard(f"s-{i}", 100, ContextPriority.MEDIUM))
    assert manager.total_tokens <= 6000


def test_find_by_tags(manager):
    manager.add_shard(_shard("a", 100, tags=("python",)))
    manager.add_shard(_shard("b", 100, tags=("rust",)))
    manager.add_shard(_shard("c", 100, tags=("python", "async")))
    results = manager.find_by_tags(("python",))
    assert len(results) == 2


def test_find_by_source(manager):
    manager.add_shard(_shard("a", 100, source="file:main.py"))
    manager.add_shard(_shard("b", 100, source="file:utils.py"))
    results = manager.find_by_source("file:main.py")
    assert len(results) == 1


def test_available_tokens(manager):
    assert manager.available_tokens == 6000
    manager.add_shard(_shard("x", 1000))
    assert manager.available_tokens == 5000


def test_stats_empty(manager):
    stats = manager.get_stats()
    assert stats.total_shards == 0
    assert stats.total_tokens == 0


def test_stats_with_data(manager):
    manager.add_shard(_shard("a", 500))
    manager.add_shard(_shard("b", 500))
    stats = manager.get_stats()
    assert stats.total_shards == 2
    assert stats.total_tokens == 1000
    assert stats.budget_utilization > 0


def test_decay_none_preserves(manager):
    shard = _shard("persistent", 100, decay=DecayStrategy.NONE)
    manager.add_shard(shard)
    evicted = manager.decay_all()
    assert evicted == 0
    assert manager.shard_count == 1


def test_assemble_window_max_tokens_override(manager):
    for i in range(10):
        manager.add_shard(_shard(f"s-{i}", 200))
    window = manager.assemble_window(max_tokens=500)
    assert window.total_tokens_used <= 500


def test_multiple_evictions_tracked(manager):
    for i in range(200):
        manager.add_shard(_shard(f"s-{i}", 100))
    stats = manager.get_stats()
    assert stats.evictions_total > 0
