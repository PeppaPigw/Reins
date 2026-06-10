"""Tests for memory consolidation engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from reins.memory import (
    ConsolidationResult,
    ConsolidationStrategy,
    ForgetCurve,
    MemoryConsolidator,
    MemoryEntry,
    MemoryKind,
    MemoryQuery,
    MemoryStats,
)


@pytest.fixture
def consolidator() -> MemoryConsolidator:
    return MemoryConsolidator(forget_curve=ForgetCurve.NONE)


def _entry(agent_id="agent-1", kind=MemoryKind.EPISODIC, content="test",
           importance=0.5, tags=(), associations=(), entry_id=None):
    kwargs = {
        "agent_id": agent_id,
        "kind": kind,
        "content": content,
        "importance": importance,
        "tags": tags,
        "associations": associations,
    }
    if entry_id:
        kwargs["entry_id"] = entry_id
    return MemoryEntry(**kwargs)


def test_store_and_recall(consolidator):
    entry = consolidator.store(_entry(content="hello"))
    recalled = consolidator.recall(entry.entry_id)
    assert recalled is not None
    assert recalled.content == "hello"
    assert recalled.access_count == 1


def test_recall_nonexistent(consolidator):
    assert consolidator.recall("nonexistent") is None


def test_recall_increments_access(consolidator):
    entry = consolidator.store(_entry())
    consolidator.recall(entry.entry_id)
    consolidator.recall(entry.entry_id)
    recalled = consolidator.recall(entry.entry_id)
    assert recalled.access_count == 3


def test_reinforce_boosts_importance(consolidator):
    entry = consolidator.store(_entry(importance=0.5))
    reinforced = consolidator.reinforce(entry.entry_id, boost=0.2)
    assert reinforced.importance == pytest.approx(0.7)
    assert reinforced.reinforcement_count == 1


def test_reinforce_clamped_at_one(consolidator):
    entry = consolidator.store(_entry(importance=0.9))
    reinforced = consolidator.reinforce(entry.entry_id, boost=0.5)
    assert reinforced.importance == 1.0


def test_reinforce_nonexistent(consolidator):
    assert consolidator.reinforce("nonexistent") is None


def test_forget_entry(consolidator):
    entry = consolidator.store(_entry())
    assert consolidator.forget(entry.entry_id)
    assert consolidator.entry_count == 0
    assert consolidator.forgotten_count == 1


def test_forget_nonexistent(consolidator):
    assert not consolidator.forget("nonexistent")


def test_query_by_agent(consolidator):
    consolidator.store(_entry(agent_id="a"))
    consolidator.store(_entry(agent_id="b"))
    consolidator.store(_entry(agent_id="a"))

    results = consolidator.query(MemoryQuery(agent_id="a"))
    assert len(results) == 2


def test_query_by_kind(consolidator):
    consolidator.store(_entry(kind=MemoryKind.EPISODIC))
    consolidator.store(_entry(kind=MemoryKind.SEMANTIC))
    consolidator.store(_entry(kind=MemoryKind.EPISODIC))

    results = consolidator.query(MemoryQuery(kind=MemoryKind.EPISODIC))
    assert len(results) == 2


def test_query_by_tags(consolidator):
    consolidator.store(_entry(tags=("python", "async")))
    consolidator.store(_entry(tags=("rust",)))
    consolidator.store(_entry(tags=("python",)))

    results = consolidator.query(MemoryQuery(tags=("python",)))
    assert len(results) == 2


def test_query_min_importance(consolidator):
    consolidator.store(_entry(importance=0.2))
    consolidator.store(_entry(importance=0.8))
    consolidator.store(_entry(importance=0.9))

    results = consolidator.query(MemoryQuery(min_importance=0.7))
    assert len(results) == 2


def test_query_max_results(consolidator):
    for i in range(20):
        consolidator.store(_entry(content=f"entry-{i}"))

    results = consolidator.query(MemoryQuery(max_results=5))
    assert len(results) == 5


def test_query_includes_forgotten(consolidator):
    entry = consolidator.store(_entry(content="forgotten"))
    consolidator.forget(entry.entry_id)

    results = consolidator.query(MemoryQuery(include_forgotten=True))
    assert len(results) == 1

    results = consolidator.query(MemoryQuery(include_forgotten=False))
    assert len(results) == 0


def test_find_associated(consolidator):
    e1 = consolidator.store(_entry(entry_id="e1", content="first"))
    e2 = consolidator.store(_entry(entry_id="e2", content="second"))
    e3 = consolidator.store(_entry(entry_id="e3", content="linked", associations=("e1", "e2")))

    associated = consolidator.find_associated("e3")
    assert len(associated) == 2


def test_find_associated_nonexistent(consolidator):
    assert consolidator.find_associated("nonexistent") == []


def test_consolidate_forgets_low_retention(consolidator):
    cons = MemoryConsolidator(
        forget_curve=ForgetCurve.EXPONENTIAL,
        forget_threshold=0.3,
    )
    old_time = datetime.now(UTC) - timedelta(days=30)
    entry = MemoryEntry(
        agent_id="a",
        kind=MemoryKind.WORKING,
        content="old working memory",
        importance=0.3,
        last_accessed=old_time,
        created_at=old_time,
    )
    cons.store(entry)

    result = cons.consolidate()
    assert result.entries_forgotten >= 1
    assert cons.entry_count == 0


def test_consolidate_upgrades_episodic_to_semantic(consolidator):
    entry = MemoryEntry(
        agent_id="a",
        kind=MemoryKind.EPISODIC,
        content="frequently accessed",
        importance=0.9,
        access_count=10,
        reinforcement_count=5,
    )
    consolidator.store(entry)

    result = consolidator.consolidate()
    assert result.entries_consolidated == 1

    updated = consolidator.recall(entry.entry_id)
    assert updated.kind == MemoryKind.SEMANTIC


def test_consolidate_counts_strengthened(consolidator):
    entry = MemoryEntry(
        agent_id="a",
        kind=MemoryKind.SEMANTIC,
        content="strong semantic",
        importance=0.9,
        access_count=10,
        reinforcement_count=5,
    )
    consolidator.store(entry)

    result = consolidator.consolidate()
    assert result.entries_strengthened == 1


def test_retention_strength_with_no_decay():
    cons = MemoryConsolidator(forget_curve=ForgetCurve.NONE)
    entry = cons.store(_entry(importance=0.8))
    strength = cons.retention_strength(entry.entry_id)
    assert strength > 0


def test_retention_strength_nonexistent(consolidator):
    assert consolidator.retention_strength("nope") == 0.0


def test_ebbinghaus_decay():
    cons = MemoryConsolidator(forget_curve=ForgetCurve.EBBINGHAUS)
    old_time = datetime.now(UTC) - timedelta(hours=48)
    entry = MemoryEntry(
        agent_id="a",
        kind=MemoryKind.EPISODIC,
        content="old",
        importance=0.8,
        last_accessed=old_time,
        created_at=old_time,
    )
    cons.store(entry)
    strength = cons.retention_strength(entry.entry_id)
    assert strength < 0.8


def test_power_law_decay():
    cons = MemoryConsolidator(forget_curve=ForgetCurve.POWER_LAW)
    old_time = datetime.now(UTC) - timedelta(hours=48)
    entry = MemoryEntry(
        agent_id="a",
        kind=MemoryKind.EPISODIC,
        content="old",
        importance=0.8,
        last_accessed=old_time,
        created_at=old_time,
    )
    cons.store(entry)
    strength = cons.retention_strength(entry.entry_id)
    assert strength < 0.8


def test_reinforcement_slows_decay():
    cons = MemoryConsolidator(forget_curve=ForgetCurve.EXPONENTIAL)
    old_time = datetime.now(UTC) - timedelta(hours=48)

    weak = MemoryEntry(
        agent_id="a", kind=MemoryKind.EPISODIC, content="weak",
        importance=0.8, last_accessed=old_time, created_at=old_time,
        reinforcement_count=0,
    )
    strong = MemoryEntry(
        agent_id="a", kind=MemoryKind.EPISODIC, content="strong",
        importance=0.8, last_accessed=old_time, created_at=old_time,
        reinforcement_count=5,
    )
    cons.store(weak)
    cons.store(strong)

    weak_strength = cons.retention_strength(weak.entry_id)
    strong_strength = cons.retention_strength(strong.entry_id)
    assert strong_strength > weak_strength


def test_stats_empty():
    cons = MemoryConsolidator()
    stats = cons.get_stats()
    assert stats.total_entries == 0


def test_stats_with_data(consolidator):
    consolidator.store(_entry(kind=MemoryKind.EPISODIC, importance=0.6))
    consolidator.store(_entry(kind=MemoryKind.SEMANTIC, importance=0.8))
    consolidator.store(_entry(kind=MemoryKind.EPISODIC, importance=0.4))

    stats = consolidator.get_stats()
    assert stats.total_entries == 3
    assert stats.by_kind["episodic"] == 2
    assert stats.by_kind["semantic"] == 1
    assert stats.avg_importance == pytest.approx(0.6)


def test_stats_tracks_consolidation_cycles(consolidator):
    consolidator.store(_entry())
    consolidator.consolidate()
    consolidator.consolidate()
    stats = consolidator.get_stats()
    assert stats.consolidation_cycles == 2


def test_entry_count_property(consolidator):
    assert consolidator.entry_count == 0
    consolidator.store(_entry())
    consolidator.store(_entry())
    assert consolidator.entry_count == 2
