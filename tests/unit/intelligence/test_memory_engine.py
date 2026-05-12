from __future__ import annotations

from pathlib import Path

import pytest

from reins.intelligence.memory.engine import MemoryEngine
from reins.intelligence.types import MemoryQuery, MemoryType


@pytest.fixture
def memory_engine(tmp_path: Path) -> MemoryEngine:
    return MemoryEngine(tmp_path / "memory")


async def test_record_and_query(memory_engine: MemoryEngine) -> None:
    mid = await memory_engine.record(
        memory_type="pattern",
        content="Use dependency injection for adapters",
        context={"domain": "architecture"},
        confidence=0.8,
    )
    assert mid
    assert memory_engine.record_count == 1

    results = await memory_engine.query(
        MemoryQuery(query_text="dependency injection", limit=5)
    )
    assert len(results) == 1
    assert results[0].record.memory_id == mid
    assert results[0].record.content == "Use dependency injection for adapters"
    assert results[0].relevance > 0.0


async def test_query_filters_by_type(memory_engine: MemoryEngine) -> None:
    await memory_engine.record("pattern", "pattern content", confidence=0.8)
    await memory_engine.record("failure", "failure content", confidence=0.8)

    patterns = await memory_engine.query(
        MemoryQuery(query_text="content", memory_type=MemoryType.pattern)
    )
    assert len(patterns) == 1
    assert patterns[0].record.memory_type == MemoryType.pattern


async def test_query_filters_by_min_confidence(memory_engine: MemoryEngine) -> None:
    await memory_engine.record("pattern", "low confidence item", confidence=0.2)
    await memory_engine.record("pattern", "high confidence item", confidence=0.9)

    results = await memory_engine.query(
        MemoryQuery(query_text="confidence", min_confidence=0.5)
    )
    assert len(results) == 1
    assert results[0].record.confidence == 0.9


async def test_supersede_removes_memory(memory_engine: MemoryEngine) -> None:
    mid = await memory_engine.record("decision", "old decision", confidence=0.7)
    assert memory_engine.record_count == 1

    await memory_engine.supersede(mid, reason="replaced by new decision")
    assert memory_engine.record_count == 0

    results = await memory_engine.query(MemoryQuery(query_text="old decision"))
    assert len(results) == 0


async def test_persistence_across_reload(tmp_path: Path) -> None:
    store = tmp_path / "memory"

    engine1 = MemoryEngine(store)
    await engine1.record("pattern", "persistent memory", confidence=0.9)
    assert engine1.record_count == 1

    engine2 = MemoryEngine(store)
    assert engine2.record_count == 1
    results = await engine2.query(MemoryQuery(query_text="persistent"))
    assert len(results) == 1


async def test_access_count_increases_on_query(memory_engine: MemoryEngine) -> None:
    await memory_engine.record("pattern", "frequently accessed", confidence=0.8)

    for _ in range(3):
        await memory_engine.query(MemoryQuery(query_text="frequently"))

    assert memory_engine._access_counts[list(memory_engine._records.keys())[0]] == 3


async def test_adjust_confidence(memory_engine: MemoryEngine) -> None:
    mid = await memory_engine.record("pattern", "adjustable", confidence=0.5)
    await memory_engine.adjust_confidence(mid, 0.9)

    results = await memory_engine.query(MemoryQuery(query_text="adjustable"))
    assert results[0].record.confidence == 0.9

