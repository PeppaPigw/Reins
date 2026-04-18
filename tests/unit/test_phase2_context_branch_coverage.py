from __future__ import annotations
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reins.context.checklist import Checklist, ChecklistItem, ChecklistParser
from reins.context.compiler import (
    ContextCompiler,
    ContextSection,
    ContextShard,
    ContextSource,
    _coerce_datetime,
)
from reins.context.types import SpecLayer, normalize_layer_name
from reins.export import TaskExporter
from reins.kernel.event.journal import EventJournal
from reins.orchestration.hooks import ContextInjectionHook
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection


def test_checklist_branch_edges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec_dir = tmp_path / "spec"
    (spec_dir / "nested").mkdir(parents=True)
    (spec_dir / "nested" / "rules.md").write_text("# Rules\n", encoding="utf-8")

    untargeted = ChecklistItem(checked=False, text="Read overview")
    targeted = ChecklistItem(checked=False, target="nested/rules.md", description="Layer rules")
    checklist = Checklist(spec_dir=spec_dir, items=[untargeted, targeted])

    assert untargeted.resolved_path(spec_dir) is None
    assert targeted.resolved_path(spec_dir) == (spec_dir / "nested" / "rules.md").resolve()
    assert "nested/rules.md" in targeted.to_display(spec_dir)
    assert checklist.get_required_specs() == [spec_dir / "nested" / "rules.md"]
    assert ChecklistParser.find_checklists(tmp_path / "missing") == {}

    index_path = spec_dir / "index.md"
    index_path.write_text("# Backend\n", encoding="utf-8")

    def _raise_oserror(self: Path, *_args, **_kwargs) -> str:
        raise OSError("boom")

    monkeypatch.setattr(Path, "read_text", _raise_oserror)
    assert ChecklistParser.parse(index_path) is None


def test_normalize_layer_name_blank_defaults_to_custom() -> None:
    assert normalize_layer_name("") == SpecLayer.CUSTOM.value


@pytest.mark.asyncio
async def test_compiler_layered_source_edge_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = ContextCompiler(token_budget=20)

    empty = await compiler.compile_layered_sources(sources=[], max_tokens=5)
    assert empty.sections == []
    assert empty.total_tokens == 0

    async def _compile_oversized(**kwargs):
        source = kwargs["sources"][0]
        identifier = str(source.identifier)
        return type(empty)(
            sections=[
                ContextSection(
                    source_type="spec",
                    identifier=identifier,
                    content=identifier,
                    token_count=6,
                    priority=10.0,
                )
            ],
            total_tokens=6,
            max_tokens=kwargs["max_tokens"],
            sources=[identifier],
        )

    monkeypatch.setattr(compiler, "compile_sources", _compile_oversized)
    optimized = await compiler.compile_layered_sources(
        sources=[
            ContextSource(type="literal", identifier="alpha"),
            ContextSource(type="literal", identifier="beta"),
        ],
        max_tokens=5,
    )
    assert optimized.total_tokens <= 5

    async def _compile_should_not_run(**kwargs):
        raise AssertionError("compile_sources should be skipped when allocation is zero")

    monkeypatch.setattr(compiler, "compile_sources", _compile_should_not_run)
    monkeypatch.setattr(compiler, "_allocate_source_budgets", lambda *_args, **_kwargs: {"zero": 0})
    skipped = await compiler.compile_layered_sources(
        sources=[ContextSource(type="literal", identifier="zero")],
        max_tokens=5,
    )
    assert skipped.sections == []


def test_compiler_source_resolution_and_legacy_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = ContextCompiler(token_budget=12)
    assert compiler.resolve_spec_sources(tmp_path / "missing", task_type="backend") == []
    assert compiler._requested_layers("guides") == [SpecLayer.GUIDES]
    assert compiler._requested_layers("custom-layer") == [SpecLayer.BACKEND]
    assert _coerce_datetime("2026-04-19T00:00:00+00:00") is not None

    spec_root = tmp_path / ".reins" / "spec"
    (spec_root / "pkg").mkdir(parents=True)
    (spec_root / "backend").mkdir(parents=True)
    (spec_root / "guides").mkdir(parents=True)

    duplicate_source = compiler._make_spec_source(
        spec_root / "backend",
        identifier="duplicate",
        layer=SpecLayer.BACKEND,
        package="pkg",
        package_specific=True,
    )
    monkeypatch.setattr(
        compiler,
        "_package_sources",
        lambda *_args, **_kwargs: [ContextSource(type="spec", identifier="no-path"), duplicate_source],
    )
    resolved = compiler.resolve_spec_sources(spec_root, task_type="backend", package="pkg")
    assert [source.identifier for source in resolved] == ["duplicate", "guides"]
    monkeypatch.undo()

    empty_package_sources = compiler._package_sources(spec_root / "pkg", "pkg", [SpecLayer.BACKEND])
    assert empty_package_sources == []

    (spec_root / "pkg-guides" / "guides").mkdir(parents=True)
    guides_sources = compiler._package_sources(
        spec_root / "pkg-guides",
        "pkg-guides",
        [SpecLayer.BACKEND],
    )
    assert any(source.identifier == "package:pkg-guides:guides" for source in guides_sources)

    allocations = compiler._allocate_source_budgets(
        [
            ContextSource(type="literal", identifier="a", priority=1.0),
            ContextSource(type="literal", identifier="b", priority=1.0),
        ],
        max_tokens=1,
    )
    assert sum(allocations.values()) == 1
    skewed_allocations = compiler._allocate_source_budgets(
        [
            ContextSource(type="literal", identifier="a", priority=1.0, metadata={"token_weight": 1.0}),
            ContextSource(type="literal", identifier="b", priority=1.0, metadata={"token_weight": 1.0}),
            ContextSource(type="literal", identifier="c", priority=1.0, metadata={"token_weight": 1.0}),
            ContextSource(type="literal", identifier="d", priority=1.0, metadata={"token_weight": 97.0}),
        ],
        max_tokens=5,
    )
    assert sum(skewed_allocations.values()) == 5
    break_allocations = compiler._allocate_source_budgets(
        [
            ContextSource(type="literal", identifier="heavy", priority=1.0, metadata={"token_weight": 80.0}),
            ContextSource(type="literal", identifier="medium", priority=1.0, metadata={"token_weight": 20.0}),
            ContextSource(type="literal", identifier="light-a", priority=1.0, metadata={"token_weight": 1.0}),
            ContextSource(type="literal", identifier="light-b", priority=1.0, metadata={"token_weight": 1.0}),
        ],
        max_tokens=5,
    )
    assert sum(break_allocations.values()) == 5

    with pytest.raises(ValueError):
        compiler.compile()

    folded = compiler.add_folded(
        [{"episode_id": "ep-1", "outcome": "ok", "decisions": "ship it", "invariants": "stay typed"}]
    )
    cold = compiler.add_cold([{"source": "cold", "content": "archived", "priority": 1.0}])
    working = compiler.compile(
        run_id="legacy-run",
        active_shards=[
            ContextShard(
                tier="B",
                source="active",
                content="active context",
                token_estimate=3,
                priority=10.0,
            )
        ],
        folded_shards=folded,
        cold_shards=cold,
    )
    assert working.total_tokens > 0


@pytest.mark.asyncio
async def test_compiler_source_error_and_journal_paths(tmp_path: Path) -> None:
    compiler = ContextCompiler()

    literal_sections = await compiler._resolve_source(ContextSource(type="literal", identifier="literal"))
    assert literal_sections[0].content == ""

    with pytest.raises(ValueError):
        await compiler._resolve_source(ContextSource(type="unsupported", identifier="bad"))
    with pytest.raises(ValueError):
        compiler._load_spec_sections(ContextSource(type="spec", identifier="spec-only"))
    assert compiler._load_spec_sections(
        ContextSource(type="spec", path=str(tmp_path / "missing"), identifier="missing-spec")
    ) == []
    with pytest.raises(ValueError):
        compiler._load_task_sections(ContextSource(type="task"))
    with pytest.raises(ValueError):
        ContextCompiler()._load_task_sections(ContextSource(type="task", task_id="t-1"))
    projection = TaskContextProjection()
    assert ContextCompiler(task_projection=projection)._load_task_sections(
        ContextSource(type="task", task_id="unknown")
    ) == []

    with pytest.raises(ValueError):
        await ContextCompiler()._load_journal_sections(ContextSource(type="journal"))
    assert [event async for event in ContextCompiler()._iter_journal_events()] == []

    journal = EventJournal(tmp_path / "journal.jsonl")
    projection = TaskContextProjection()
    manager = TaskManager(journal, projection, run_id="journal-run")
    task_id = await manager.create_task(
        title="Journal task",
        task_type="backend",
        prd_content="Track journal events.",
        acceptance_criteria=["Events exist"],
        created_by="tester",
        assignee="peppa",
    )
    await manager.start_task(task_id, assignee="peppa")
    journal.path.write_text("\n" + journal.path.read_text(encoding="utf-8"), encoding="utf-8")

    journal_compiler = ContextCompiler(journal=journal, task_projection=projection)
    assert await journal_compiler._load_journal_sections(
        ContextSource(type="journal", event_types=["does.not.match"])
    ) == []
    assert await journal_compiler._load_journal_sections(
        ContextSource(type="journal", event_types=["task.*"], from_time="2100-01-01T00:00:00+00:00")
    ) == []
    assert await journal_compiler._load_journal_sections(
        ContextSource(type="journal", event_types=["task.*"], to_time="2000-01-01T00:00:00+00:00")
    ) == []

    sections = await journal_compiler._load_journal_sections(
        ContextSource(type="journal", event_types=["task.*"])
    )
    assert sections
    formatted = journal_compiler._format_event(
        type(
            "_Event",
            (),
            {
                "payload": {"status": "ok"},
                "ts": datetime.now(UTC),
                "run_id": "journal-run",
                "seq": 1,
                "actor": type("_Actor", (), {"value": "system"})(),
                "type": "task.created",
            },
        )
    )
    assert "Payload:" in formatted


async def _build_hook_fixture(
    tmp_path: Path,
) -> tuple[ContextInjectionHook, Path]:
    repo_root = tmp_path
    reins_dir = repo_root / ".reins"
    (reins_dir / "tasks").mkdir(parents=True, exist_ok=True)
    journal = EventJournal(reins_dir / "journal.jsonl")
    projection = TaskContextProjection()
    manager = TaskManager(journal, projection, run_id="hook-run")
    task_id = await manager.create_task(
        title="Hook task",
        task_type="backend",
        prd_content="Exercise hook helpers.",
        acceptance_criteria=["Hooks work"],
        created_by="tester",
        assignee="peppa",
    )
    exporter = TaskExporter(projection, reins_dir / "tasks")
    task_dir = exporter.export_task(task_id)
    assert task_dir is not None
    exporter.set_current_task(task_id)
    hook = ContextInjectionHook(
        repo_root=repo_root,
        journal=journal,
        context_compiler=ContextCompiler(token_budget=200),
    )
    return hook, task_dir


@pytest.mark.asyncio
async def test_hook_branch_helpers(tmp_path: Path) -> None:
    repo_root = tmp_path
    (repo_root / ".reins").mkdir(parents=True, exist_ok=True)
    hook = ContextInjectionHook(
        repo_root=repo_root,
        journal=EventJournal(repo_root / ".reins" / "journal.jsonl"),
        context_compiler=ContextCompiler(token_budget=200),
    )

    context = await hook.before_subagent_spawn("implement")
    assert context["task_metadata"] is None
    await hook.after_subagent_complete("implement", {"status": "completed"})
    await hook.on_error("implement", RuntimeError("no task"))

    task_dir = repo_root / ".reins" / "tasks" / "bare-task"
    task_dir.mkdir(parents=True, exist_ok=True)
    hook._current_task_file.write_text("", encoding="utf-8")
    assert hook._resolve_current_task_dir() is None
    hook._current_task_file.write_text("bare-task", encoding="utf-8")
    assert hook._resolve_current_task_dir() == task_dir
    absolute_task_dir = repo_root / "absolute-task"
    absolute_task_dir.mkdir()
    hook._current_task_file.write_text(str(absolute_task_dir), encoding="utf-8")
    assert hook._resolve_current_task_dir() == absolute_task_dir
    hook._current_task_file.write_text("missing-task", encoding="utf-8")
    assert hook._resolve_current_task_dir() is None

    assert hook._load_task_metadata(task_dir) is None
    (task_dir / "task.json").write_text("[]", encoding="utf-8")
    assert hook._load_task_metadata(task_dir) is None
    assert await hook._compile_specs([]) == []
    assert hook._build_spec_sources({"task_type": "backend"}) == []


@pytest.mark.asyncio
async def test_hook_status_and_checklist_helper_branches(tmp_path: Path) -> None:
    hook, task_dir = await _build_hook_fixture(tmp_path)
    spec_root = tmp_path / ".reins" / "spec"
    (spec_root / "backend").mkdir(parents=True, exist_ok=True)
    (spec_root / "backend" / "index.md").write_text(
        "# Backend\n\n## Pre-Development Checklist\n\n- [ ] [Guide](guide.md) - Read it\n",
        encoding="utf-8",
    )
    (spec_root / "backend" / "guide.md").write_text("# Guide\n", encoding="utf-8")

    pending = {"id": "task-1", "status": "pending", "metadata": "bad"}
    assert hook._tracked_read_specs(pending) == set()
    assert hook._tracked_read_specs({"metadata": {"checklist": {"read_specs": "bad"}}}) == set()
    assert hook._task_id(None) is None
    assert hook._task_id(pending) == "task-1"
    assert hook._resolve_run_id(None).startswith("context-hook-")

    assert hook._update_task_status_from_result(task_dir, None, {"status": "completed"}) is None
    started = hook._update_task_status_from_result(task_dir, {"status": "pending"}, {"status": "in_progress"})
    assert started is not None and started["status"] == "in_progress" and started["started_at"]

    completed = hook._update_task_status_from_result(task_dir, {"status": "pending"}, {"completed": True})
    assert completed is not None and completed["status"] == "completed" and completed["completed_at"]
    assert hook._update_task_status_from_result(task_dir, {"status": "pending"}, {"status": "invalid"}) == {
        "status": "pending"
    }
    assert hook._status_from_result({"status": "invalid"}) is None
    assert hook._update_checklist_status(
        task_dir=task_dir,
        task_metadata=None,
        spec_sources=[],
        specs=[],
    ) == (None, None)
    untouched = {"metadata": {}}
    assert hook._update_checklist_status(
        task_dir=task_dir,
        task_metadata=untouched,
        spec_sources=[],
        specs=[],
    ) == (None, untouched)
    assert hook._update_checklist_status(
        task_dir=task_dir,
        task_metadata=untouched,
        spec_sources=[ContextSource(type="spec", identifier="missing-path")],
        specs=[],
    ) == (None, untouched)

    relative_reads = hook._relative_reads_for_checklist(
        Checklist(spec_dir=spec_root / "backend", items=[]),
        {"backend/guide.md", "guides/shared.md"},
    )
    assert relative_reads == {"guide.md"}

    serialized = hook._serialize_checklist_item(
        Checklist(spec_dir=spec_root / "backend", items=[]),
        ChecklistItem(checked=False, target="../../outside.md"),
        set(),
    )
    assert serialized["target"] == "outside.md"

    outside_repo = tmp_path.parent / "external.md"
    assert hook._relative_to_repo(outside_repo) == outside_repo.as_posix()

    read_specs = hook._read_specs_from_compiled_context(
        [
            {"metadata": "bad"},
            {"metadata": {"path": 123}},
            {"metadata": {"path": str(tmp_path / ".reins" / "spec" / "backend" / "guide.md")}},
            {"metadata": {"path": str(tmp_path.parent / "external.md")}},
        ]
    )
    assert read_specs == {"backend/guide.md"}
