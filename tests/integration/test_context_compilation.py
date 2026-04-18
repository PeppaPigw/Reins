from __future__ import annotations

from pathlib import Path

from reins.context.compiler import ContextCompiler, ContextSource
from reins.kernel.event.journal import EventJournal
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection


async def test_context_compilation_prioritizes_task_and_specs_over_journal(
    tmp_path: Path,
) -> None:
    journal = EventJournal(tmp_path / "journal")
    projection = TaskContextProjection()
    manager = TaskManager(journal, projection, run_id="ctx-integration")

    task_id = await manager.create_task(
        title="Guard approval boundaries",
        task_type="backend",
        prd_content="Implement the policy and approval flow with auditability.",
        acceptance_criteria=[
            "Task context survives optimization",
            "Journal slices are included when budget allows",
        ],
        created_by="tester",
        assignee="peppa",
    )
    await manager.start_task(task_id, assignee="peppa")
    await manager.complete_task(task_id, outcome={"summary": "done"})

    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    (spec_dir / "approval.md").write_text(
        "# Approval\nAudit every destructive operation.\n",
        encoding="utf-8",
    )

    compiler = ContextCompiler(
        token_budget=260,
        journal=journal,
        task_projection=projection,
    )

    compiled = await compiler.compile(
        sources=[
            ContextSource(type="task", task_id=task_id, priority=90.0),
            ContextSource(type="spec", path=str(spec_dir), priority=70.0),
            ContextSource(
                type="journal",
                run_id="ctx-integration",
                event_types=["task.*"],
                priority=20.0,
            ),
        ],
        optimize=True,
        max_tokens=260,
        priority=["task", "spec", "journal"],
    )

    assert compiled.total_tokens <= 260
    assert any(section.source_type == "task" for section in compiled.sections)
    assert any(section.source_type == "spec" for section in compiled.sections)
    assert any(section.source_type == "journal" for section in compiled.sections) or any(
        item.startswith("ctx-integration:") for item in compiled.dropped
    )

    task_section = next(
        section for section in compiled.sections if section.source_type == "task"
    )
    assert "Guard approval boundaries" in task_section.content
    assert "Implement the policy and approval flow" in task_section.content
