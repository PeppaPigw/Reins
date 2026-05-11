"""Tests for retrospective persistence and knowledge base."""

from __future__ import annotations

import pytest

from reins.workflow.break_loop import LoopPattern, Retrospective
from reins.workflow.retrospective import Learning, RetrospectiveStore


def _make_pattern() -> LoopPattern:
    return LoopPattern(
        pattern_type="repeated_failure",
        event_types=("command.failed",),
        count=3,
        window_seconds=60.0,
    )


def _make_retrospective(task_id: str = "task-1") -> Retrospective:
    return Retrospective(
        task_id=task_id,
        trigger=_make_pattern(),
        timestamp="2025-01-01T00:00:00+00:00",
        context_summary="Agent stuck on failing test",
        attempted_actions=["run test", "fix code", "run test"],
        failure_reasons=["assertion error in test_foo"],
        learnings=["Need to check return type before asserting"],
        suggested_next="Add type guard before assertion",
    )


def _make_learning(
    learning_id: str = "learn-1",
    category: str = "pattern",
    task_type: str | None = None,
    file_pattern: str | None = None,
    confidence: float = 0.8,
) -> Learning:
    applicability: dict[str, str] = {}
    if task_type:
        applicability["task_type"] = task_type
    if file_pattern:
        applicability["file_pattern"] = file_pattern
    return Learning(
        learning_id=learning_id,
        source_retrospective_id="retro-1",
        category=category,
        summary="Check return types before assertions",
        detail="Functions may return None when expected to return a value",
        applicability=applicability,
        confidence=confidence,
    )


def test_save_retrospective_persists_to_file(tmp_path: object) -> None:
    store = RetrospectiveStore(tmp_path)  # type: ignore[arg-type]
    retro = _make_retrospective()
    retro_id = store.save_retrospective(retro)
    assert retro_id  # non-empty string
    retro_file = tmp_path / "retrospectives.jsonl"  # type: ignore[operator]
    assert retro_file.exists()
    content = retro_file.read_text()
    assert "task-1" in content


def test_load_retrospectives_reads_all(tmp_path: object) -> None:
    store = RetrospectiveStore(tmp_path)  # type: ignore[arg-type]
    store.save_retrospective(_make_retrospective("task-1"))
    store.save_retrospective(_make_retrospective("task-2"))
    loaded = store.load_retrospectives()
    assert len(loaded) == 2
    assert loaded[0].task_id == "task-1"
    assert loaded[1].task_id == "task-2"


def test_save_learning_persists(tmp_path: object) -> None:
    store = RetrospectiveStore(tmp_path)  # type: ignore[arg-type]
    learning = _make_learning()
    store.save_learning(learning)
    learnings_file = tmp_path / "learnings.jsonl"  # type: ignore[operator]
    assert learnings_file.exists()
    content = learnings_file.read_text()
    assert "learn-1" in content


def test_load_learnings_reads_all(tmp_path: object) -> None:
    store = RetrospectiveStore(tmp_path)  # type: ignore[arg-type]
    store.save_learning(_make_learning("learn-1"))
    store.save_learning(_make_learning("learn-2"))
    loaded = store.load_learnings()
    assert len(loaded) == 2
    assert loaded[0].learning_id == "learn-1"
    assert loaded[1].learning_id == "learn-2"


def test_query_learnings_by_task_type(tmp_path: object) -> None:
    store = RetrospectiveStore(tmp_path)  # type: ignore[arg-type]
    store.save_learning(_make_learning("l1", task_type="refactor"))
    store.save_learning(_make_learning("l2", task_type="feature"))
    store.save_learning(_make_learning("l3", task_type="refactor"))
    results = store.query_learnings(task_type="refactor")
    assert len(results) == 2
    assert all(l.applicability.get("task_type") == "refactor" for l in results)


def test_query_learnings_by_file_pattern(tmp_path: object) -> None:
    store = RetrospectiveStore(tmp_path)  # type: ignore[arg-type]
    store.save_learning(_make_learning("l1", file_pattern="*.py"))
    store.save_learning(_make_learning("l2", file_pattern="*.ts"))
    store.save_learning(_make_learning("l3", file_pattern="*.py"))
    results = store.query_learnings(file_pattern="*.py")
    assert len(results) == 2
    assert all(l.applicability.get("file_pattern") == "*.py" for l in results)


def test_get_recent_learnings_returns_latest(tmp_path: object) -> None:
    store = RetrospectiveStore(tmp_path)  # type: ignore[arg-type]
    for i in range(10):
        store.save_learning(_make_learning(f"l{i}"))
    recent = store.get_recent_learnings(count=3)
    assert len(recent) == 3
    assert recent[0].learning_id == "l7"
    assert recent[1].learning_id == "l8"
    assert recent[2].learning_id == "l9"


def test_format_learnings_for_context_produces_string(tmp_path: object) -> None:
    store = RetrospectiveStore(tmp_path)  # type: ignore[arg-type]
    learnings = [
        _make_learning("l1", category="pattern", task_type="refactor"),
        _make_learning("l2", category="anti_pattern"),
    ]
    result = store.format_learnings_for_context(learnings)
    assert "[Pattern]" in result
    assert "[Anti Pattern]" in result
    assert "Check return types" in result


def test_empty_store_returns_empty_lists(tmp_path: object) -> None:
    store = RetrospectiveStore(tmp_path)  # type: ignore[arg-type]
    assert store.load_retrospectives() == []
    assert store.load_learnings() == []
    assert store.query_learnings() == []
    assert store.get_recent_learnings() == []


def test_learning_confidence_field_validated() -> None:
    with pytest.raises(ValueError, match="confidence must be between"):
        _make_learning(confidence=1.5)
    with pytest.raises(ValueError, match="confidence must be between"):
        _make_learning(confidence=-0.1)
