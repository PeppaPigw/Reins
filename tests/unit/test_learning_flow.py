"""Tests for learning extraction and spec-update flow."""

from __future__ import annotations

from pathlib import Path

from reins.context.learning_injection import LearningInjector
from reins.workflow.break_loop import LoopPattern, Retrospective
from reins.workflow.learning import (
    LearningCategory,
    LearningExtractor,
    LearningFlow,
    SpecUpdateProposal,
)
from reins.workflow.retrospective import Learning, RetrospectiveStore


def _make_pattern(count: int = 3) -> LoopPattern:
    return LoopPattern(
        pattern_type="repeated_failure",
        event_types=("command.failed",),
        count=count,
        window_seconds=60.0,
    )


def _make_retrospective(
    learnings: list[str] | None = None, count: int = 3
) -> Retrospective:
    return Retrospective(
        task_id="task-1",
        trigger=_make_pattern(count),
        timestamp="2025-01-01T00:00:00+00:00",
        context_summary="Agent stuck",
        attempted_actions=["run test", "fix code"],
        failure_reasons=["assertion error"],
        learnings=learnings or ["Need to check return type before asserting"],
    )


def test_extract_from_retrospective_creates_learnings() -> None:
    store = RetrospectiveStore(Path("/tmp/test_extract_retro"))
    extractor = LearningExtractor(store)
    retro = _make_retrospective(["Learning one", "Learning two"])
    learnings = extractor.extract_from_retrospective(retro)
    assert len(learnings) == 2
    assert learnings[0].summary == "Learning one"
    assert learnings[1].summary == "Learning two"


def test_extract_assigns_category_from_content() -> None:
    store = RetrospectiveStore(Path("/tmp/test_extract_cat"))
    extractor = LearningExtractor(store)
    retro = _make_retrospective(["Avoid using mutable defaults"])
    learnings = extractor.extract_from_retrospective(retro)
    assert learnings[0].category == LearningCategory.anti_pattern.value


def test_extract_sets_confidence_from_pattern_count() -> None:
    store = RetrospectiveStore(Path("/tmp/test_extract_conf"))
    extractor = LearningExtractor(store)
    # count=5 should give 0.9 confidence
    retro = _make_retrospective(["Some learning"], count=5)
    learnings = extractor.extract_from_retrospective(retro)
    assert learnings[0].confidence == 0.9
    # count=3 should give 0.7
    retro2 = _make_retrospective(["Another learning"], count=3)
    learnings2 = extractor.extract_from_retrospective(retro2)
    assert learnings2[0].confidence == 0.7
    # count=2 should give 0.5
    retro3 = _make_retrospective(["Low learning"], count=2)
    learnings3 = extractor.extract_from_retrospective(retro3)
    assert learnings3[0].confidence == 0.5


def test_propose_spec_updates_for_high_confidence() -> None:
    store = RetrospectiveStore(Path("/tmp/test_propose_high"))
    extractor = LearningExtractor(store)
    learning = Learning(
        learning_id="l1",
        source_retrospective_id="r1",
        category="anti_pattern",
        summary="Avoid mutable defaults",
        detail="Use field(default_factory=list) instead",
        applicability={"task_type": "refactor"},
        confidence=0.9,
    )
    proposals = extractor.propose_spec_updates([learning])
    assert len(proposals) == 1
    assert proposals[0].learning_id == "l1"
    assert "constraint" in proposals[0].proposed_content.lower()


def test_propose_spec_updates_skips_low_confidence() -> None:
    store = RetrospectiveStore(Path("/tmp/test_propose_low"))
    extractor = LearningExtractor(store)
    learning = Learning(
        learning_id="l1",
        source_retrospective_id="r1",
        category="pattern",
        summary="Maybe useful",
        detail="Not sure yet",
        applicability={"task_type": "feature"},
        confidence=0.4,
    )
    proposals = extractor.propose_spec_updates([learning])
    assert len(proposals) == 0


def test_should_promote_to_spec_true_for_high_confidence() -> None:
    store = RetrospectiveStore(Path("/tmp/test_promote_true"))
    extractor = LearningExtractor(store)
    learning = Learning(
        learning_id="l1",
        source_retrospective_id="r1",
        category="pattern",
        summary="Good pattern",
        detail="Detail",
        applicability={"task_type": "feature"},
        confidence=0.8,
    )
    assert extractor.should_promote_to_spec(learning) is True


def test_should_promote_to_spec_false_for_low_confidence() -> None:
    store = RetrospectiveStore(Path("/tmp/test_promote_false"))
    extractor = LearningExtractor(store)
    learning = Learning(
        learning_id="l1",
        source_retrospective_id="r1",
        category="pattern",
        summary="Uncertain",
        detail="Detail",
        applicability={"task_type": "feature"},
        confidence=0.5,
    )
    assert extractor.should_promote_to_spec(learning) is False


def test_process_retrospective_full_pipeline(tmp_path: object) -> None:
    store = RetrospectiveStore(tmp_path)  # type: ignore[arg-type]
    extractor = LearningExtractor(store)
    flow = LearningFlow(store, extractor)
    retro = _make_retrospective(
        ["Avoid using global state in tests"], count=5
    )
    proposals = flow.process_retrospective(retro)
    # Should have saved retro and learnings
    assert len(store.load_retrospectives()) == 1
    assert len(store.load_learnings()) == 1
    # High confidence (count=5 -> 0.9) with applicability -> proposal
    assert len(proposals) == 1


def test_learning_injector_returns_empty_for_no_learnings(tmp_path: object) -> None:
    store = RetrospectiveStore(tmp_path)  # type: ignore[arg-type]
    injector = LearningInjector(store)
    result = injector.inject_for_task(task_type="feature")
    assert result == ""


def test_learning_injector_returns_formatted_learnings(tmp_path: object) -> None:
    store = RetrospectiveStore(tmp_path)  # type: ignore[arg-type]
    learning = Learning(
        learning_id="l1",
        source_retrospective_id="r1",
        category="pattern",
        summary="Always validate inputs",
        detail="Input validation prevents downstream errors",
        applicability={"task_type": "feature"},
        confidence=0.8,
    )
    store.save_learning(learning)
    injector = LearningInjector(store)
    result = injector.inject_for_task(task_type="feature")
    assert "Always validate inputs" in result
    assert "[Pattern]" in result


def test_learning_injector_xml_has_tags(tmp_path: object) -> None:
    store = RetrospectiveStore(tmp_path)  # type: ignore[arg-type]
    learning = Learning(
        learning_id="l1",
        source_retrospective_id="r1",
        category="constraint",
        summary="Must use parameterized queries",
        detail="Prevents SQL injection",
        applicability={"task_type": "feature"},
        confidence=0.9,
    )
    store.save_learning(learning)
    injector = LearningInjector(store)
    result = injector.inject_as_xml(task_type="feature")
    assert result.startswith("<past-learnings>")
    assert result.endswith("</past-learnings>")
    assert "Must use parameterized queries" in result


def test_learning_flow_get_pending_proposals(tmp_path: object) -> None:
    store = RetrospectiveStore(tmp_path)  # type: ignore[arg-type]
    extractor = LearningExtractor(store)
    flow = LearningFlow(store, extractor)
    # Initially empty
    assert flow.get_pending_proposals() == []
    # Process a retro with high-confidence learning
    retro = _make_retrospective(["Avoid mutable defaults"], count=5)
    flow.process_retrospective(retro)
    pending = flow.get_pending_proposals()
    assert len(pending) == 1
    assert isinstance(pending[0], SpecUpdateProposal)
