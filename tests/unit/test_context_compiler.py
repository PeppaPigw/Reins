from __future__ import annotations

from pathlib import Path

from reins.context.cache import ContextCache
from reins.context.compiler import (
    CompiledContext,
    ContextCompiler,
    ContextSection,
    ContextSource,
)
from reins.context.optimizer import ContextOptimizer
from reins.kernel.event.journal import EventJournal
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection


async def _build_task_context(
    tmp_path: Path,
    run_id: str = "context-run",
) -> tuple[EventJournal, TaskContextProjection, str]:
    journal = EventJournal(tmp_path / "journal")
    projection = TaskContextProjection()
    manager = TaskManager(journal, projection, run_id=run_id)
    task_id = await manager.create_task(
        title="Compile context",
        task_type="backend",
        prd_content="Ship a safe multi-source context compiler.",
        acceptance_criteria=["Task context is included", "Journal events are visible"],
        created_by="tester",
        assignee="peppa",
    )
    await manager.start_task(task_id, assignee="peppa")
    return journal, projection, task_id


async def test_compile_sources_combines_spec_task_and_journal(tmp_path: Path) -> None:
    journal, projection, task_id = await _build_task_context(tmp_path)
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    (spec_dir / "backend.md").write_text(
        "# Backend\nPrefer projections over mutable state.\n",
        encoding="utf-8",
    )

    compiler = ContextCompiler(
        token_budget=400,
        journal=journal,
        task_projection=projection,
    )

    compiled = await compiler.compile(
        sources=[
            ContextSource(type="spec", path=str(spec_dir), identifier="workspace-spec"),
            ContextSource(type="task", task_id=task_id),
            ContextSource(
                type="journal",
                run_id="context-run",
                event_types=["task.*"],
            ),
        ],
        optimize=True,
        max_tokens=400,
        priority=["task", "spec", "journal"],
    )

    assert isinstance(compiled, CompiledContext)
    assert compiled.total_tokens <= 400
    assert {section.source_type for section in compiled.sections} >= {
        "spec",
        "task",
        "journal",
    }
    rendered = compiled.to_text()
    assert "Compile context" in rendered
    assert "Prefer projections over mutable state" in rendered
    assert "task.created" in rendered or "task.started" in rendered


async def test_compile_sources_uses_cache_when_enabled(tmp_path: Path) -> None:
    spec_file = tmp_path / "spec.md"
    spec_file.write_text("cached context\n", encoding="utf-8")

    cache = ContextCache(ttl_seconds=60)
    compiler = ContextCompiler(cache=cache)
    source = ContextSource(type="spec", path=str(spec_file), identifier="cache-spec")

    first = await compiler.compile(sources=[source], optimize=True, use_cache=True)
    second = await compiler.compile(sources=[source], optimize=True, use_cache=True)

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert len(cache) == 1


async def test_compile_sources_respects_cache_expiry(tmp_path: Path) -> None:
    spec_file = tmp_path / "spec.md"
    spec_file.write_text("expires immediately\n", encoding="utf-8")

    cache = ContextCache(ttl_seconds=0)
    compiler = ContextCompiler(cache=cache)
    source = ContextSource(type="spec", path=str(spec_file), identifier="expire-spec")

    await compiler.compile(sources=[source], optimize=True, use_cache=True)
    second = await compiler.compile(sources=[source], optimize=True, use_cache=True)

    assert second.cache_hit is False


def test_optimizer_deduplicates_and_prioritizes() -> None:
    optimizer = ContextOptimizer()
    sections = [
        ContextSection(
            source_type="journal",
            identifier="event-1",
            content="duplicate",
            token_count=10,
            priority=10.0,
        ),
        ContextSection(
            source_type="task",
            identifier="task-1",
            content="keep me first",
            token_count=10,
            priority=100.0,
        ),
        ContextSection(
            source_type="journal",
            identifier="event-2",
            content="duplicate",
            token_count=10,
            priority=5.0,
        ),
    ]

    result = optimizer.optimize(sections, max_tokens=20, priority=["task", "journal"])

    assert [section.identifier for section in result.sections] == ["task-1", "event-1"]
    assert result.total_tokens <= 20
    assert "event-2" in result.deduplicated
