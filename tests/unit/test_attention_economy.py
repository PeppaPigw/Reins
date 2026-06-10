"""Tests for attention economy engine."""

from __future__ import annotations

import pytest

from reins.attention_economy import (
    AttentionBudget,
    AttentionEconomyEngine,
    AttentionPriority,
    ContentType,
    EvictionPolicy,
)


@pytest.fixture
def engine() -> AttentionEconomyEngine:
    return AttentionEconomyEngine(total_tokens=1000, eviction_policy=EvictionPolicy.HYBRID)


def test_allocate_slot(engine):
    slot = engine.allocate("important context", ContentType.CONTEXT, token_cost=100)
    assert slot is not None
    assert slot.token_cost == 100


def test_allocate_auto_token_cost(engine):
    slot = engine.allocate("hello world foo bar", ContentType.CONTEXT)
    assert slot.token_cost == 8


def test_allocate_with_priority(engine):
    slot = engine.allocate("critical", ContentType.INSTRUCTION,
                           priority=AttentionPriority.CRITICAL, token_cost=50)
    assert slot.priority == AttentionPriority.CRITICAL


def test_allocate_exceeds_budget():
    e = AttentionEconomyEngine(total_tokens=100)
    slot = e.allocate("x" * 1000, ContentType.CONTEXT, token_cost=200)
    assert slot is None


def test_allocate_triggers_eviction():
    e = AttentionEconomyEngine(total_tokens=200, reserve_ratio=0.0)
    e.allocate("old", ContentType.CONTEXT, priority=AttentionPriority.LOW, token_cost=150)
    slot = e.allocate("new", ContentType.INSTRUCTION,
                      priority=AttentionPriority.HIGH, token_cost=150)
    assert slot is not None


def test_access_increments_count(engine):
    slot = engine.allocate("data", ContentType.CONTEXT, token_cost=50)
    updated = engine.access(slot.slot_id)
    assert updated.access_count == 1
    updated2 = engine.access(slot.slot_id)
    assert updated2.access_count == 2


def test_access_nonexistent(engine):
    assert engine.access("fake") is None


def test_update_relevance(engine):
    slot = engine.allocate("data", ContentType.CONTEXT, token_cost=50, relevance_score=0.3)
    updated = engine.update_relevance(slot.slot_id, 0.9)
    assert updated.relevance_score == 0.9


def test_update_relevance_nonexistent(engine):
    assert engine.update_relevance("fake", 0.5) is None


def test_manual_eviction(engine):
    slot = engine.allocate("temp", ContentType.EXAMPLE, token_cost=50)
    event = engine.evict(slot.slot_id, reason="no longer needed")
    assert event is not None
    assert event.tokens_freed == 50
    assert engine.get_slot(slot.slot_id) is None


def test_evict_nonexistent(engine):
    assert engine.evict("fake") is None


def test_get_budget(engine):
    engine.allocate("data", ContentType.CONTEXT, token_cost=200)
    budget = engine.get_budget()
    assert budget.total_tokens == 1000
    assert budget.used_tokens == 200
    assert budget.reserved_tokens == 100
    assert budget.available_tokens == 700


def test_get_slots_by_type(engine):
    engine.allocate("inst", ContentType.INSTRUCTION, token_cost=50)
    engine.allocate("ctx", ContentType.CONTEXT, token_cost=50)
    engine.allocate("ctx2", ContentType.CONTEXT, token_cost=50)
    contexts = engine.get_slots_by_type(ContentType.CONTEXT)
    assert len(contexts) == 2


def test_get_slots_by_priority(engine):
    engine.allocate("hi", ContentType.CONTEXT, priority=AttentionPriority.HIGH, token_cost=50)
    engine.allocate("lo", ContentType.CONTEXT, priority=AttentionPriority.LOW, token_cost=50)
    high = engine.get_slots_by_priority(AttentionPriority.HIGH)
    assert len(high) == 1


def test_get_top_slots(engine):
    engine.allocate("low_rel", ContentType.CONTEXT, token_cost=50,
                    relevance_score=0.1, priority=AttentionPriority.LOW)
    engine.allocate("high_rel", ContentType.CONTEXT, token_cost=50,
                    relevance_score=0.9, priority=AttentionPriority.HIGH)
    top = engine.get_top_slots(n=1)
    assert top[0].relevance_score == 0.9


def test_compact(engine):
    for i in range(8):
        engine.allocate(f"item {i}", ContentType.CONTEXT, token_cost=100,
                        priority=AttentionPriority.LOW)
    events = engine.compact(target_utilization=0.5)
    assert len(events) > 0
    budget = engine.get_budget()
    assert budget.used_tokens <= 500


def test_lru_eviction():
    e = AttentionEconomyEngine(total_tokens=200, eviction_policy=EvictionPolicy.LRU,
                               reserve_ratio=0.0)
    s1 = e.allocate("old", ContentType.CONTEXT, token_cost=100)
    s2 = e.allocate("new", ContentType.CONTEXT, token_cost=100)
    e.access(s2.slot_id)
    new_slot = e.allocate("newest", ContentType.INSTRUCTION,
                          priority=AttentionPriority.HIGH, token_cost=100)
    assert new_slot is not None
    assert e.get_slot(s1.slot_id) is None


def test_stats(engine):
    engine.allocate("a", ContentType.INSTRUCTION, token_cost=100,
                    priority=AttentionPriority.HIGH, relevance_score=0.8)
    engine.allocate("b", ContentType.CONTEXT, token_cost=50,
                    priority=AttentionPriority.NORMAL, relevance_score=0.6)
    stats = engine.get_stats()
    assert stats.total_slots == 2
    assert stats.total_tokens_used == 150
    assert stats.avg_relevance == pytest.approx(0.7, abs=0.01)


def test_stats_empty():
    e = AttentionEconomyEngine()
    stats = e.get_stats()
    assert stats.total_slots == 0
    assert stats.budget_utilization == 0.0
