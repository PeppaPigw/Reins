from __future__ import annotations

from pathlib import Path

import pytest

from reins.intelligence.memory.engine import MemoryEngine
from reins.intelligence.memory.retrospective_adapter import RetrospectiveMemoryAdapter
from reins.intelligence.types import MemoryQuery
from reins.workflow.break_loop import LoopPattern
from reins.workflow.retrospective import Learning, RetrospectiveStore


@pytest.fixture
def adapter(tmp_path: Path) -> RetrospectiveMemoryAdapter:
    memory = MemoryEngine(tmp_path / "memory")
    retro = RetrospectiveStore(tmp_path / "retro")
    retro.save_learning(Learning(
        learning_id="learn-1",
        source_retrospective_id="retro-1",
        category="pattern",
        summary="Use retry with backoff for flaky network calls",
        detail="Network calls to external APIs should use exponential backoff",
        applicability={"task_type": "backend"},
        confidence=0.8,
    ))
    retro.save_learning(Learning(
        learning_id="learn-2",
        source_retrospective_id="retro-2",
        category="anti_pattern",
        summary="Avoid global mutable state in async code",
        detail="Global mutable state causes race conditions in async handlers",
        applicability={"task_type": "backend"},
        confidence=0.9,
    ))
    return RetrospectiveMemoryAdapter(memory, retro)


async def test_adapter_queries_both_sources(adapter: RetrospectiveMemoryAdapter) -> None:
    await adapter.record("pattern", "direct memory about retry logic", {})

    results = await adapter.query(MemoryQuery(query_text="retry", limit=10))
    assert len(results) >= 2
    sources = {r.record.source for r in results}
    assert "retrospective" in sources
    assert "" in sources or "intelligence" in sources


async def test_adapter_filters_by_type(adapter: RetrospectiveMemoryAdapter) -> None:
    from reins.intelligence.types import MemoryType

    results = await adapter.query(
        MemoryQuery(query_text="state async", memory_type=MemoryType.failure)
    )
    assert len(results) >= 1
    assert all(r.record.memory_type == MemoryType.failure for r in results)


async def test_adapter_respects_limit(adapter: RetrospectiveMemoryAdapter) -> None:
    results = await adapter.query(MemoryQuery(query_text="code", limit=1))
    assert len(results) <= 1


async def test_adapter_record_delegates_to_memory(adapter: RetrospectiveMemoryAdapter) -> None:
    mid = await adapter.record("decision", "chose event sourcing", {"domain": "arch"})
    assert mid

    results = await adapter.query(MemoryQuery(query_text="event sourcing"))
    assert any(r.record.memory_id == mid for r in results)
