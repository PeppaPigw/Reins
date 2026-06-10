from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from reins.outcomes import (
    GuardType,
    OutcomeResult,
    OutcomeSpec,
    OutcomeTracker,
    OutcomeVerifier,
    PredicateResult,
    PredicateType,
    QualityGateEngine,
    QualityLevel,
    RegressionGuard,
    VerificationPredicate,
)


def _predicate(
    predicate_id: str,
    predicate_type: PredicateType,
    target: str,
    expected: object = True,
    *,
    weight: float = 1.0,
    required: bool = False,
) -> VerificationPredicate:
    return VerificationPredicate(
        predicate_id=predicate_id,
        description=f"verify {predicate_id}",
        predicate_type=predicate_type,
        target=target,
        expected=expected,
        weight=weight,
        required=required,
    )


def _outcome_result(
    outcome_id: str,
    *,
    score: float,
    progress: float,
    evaluated_at: datetime,
    task_id: str = "task-1",
    passed_predicates: tuple[str, ...] = (),
) -> OutcomeResult:
    predicate_results = tuple(
        PredicateResult(
            predicate_id=predicate_id,
            passed=True,
            score=1.0,
            weight=1.0,
            required=False,
            evaluated_at=evaluated_at,
        )
        for predicate_id in passed_predicates
    )
    return OutcomeResult(
        outcome_id=outcome_id,
        overall_score=score,
        passed=score >= 1.0,
        predicate_results=predicate_results,
        regression_results=(),
        partial_progress=progress,
        evidence={"task_id": task_id},
        evaluated_at=evaluated_at,
    )


async def test_predicate_evaluation_file_pattern_metric_and_invariant(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text(
        "from __future__ import annotations\n\nVALUE = 42\n",
        encoding="utf-8",
    )
    verifier = OutcomeVerifier()
    context = {"cwd": tmp_path, "metrics": {"coverage": 0.91}}

    file_result = await verifier.verify_predicate(
        _predicate("file", PredicateType.FILE_EXISTS, "module.py", {"contains": "VALUE"}),
        context,
    )
    pattern_result = await verifier.verify_predicate(
        _predicate("pattern", PredicateType.PATTERN_MATCHES, "module.py", r"VALUE\s*=\s*42"),
        context,
    )
    metric_result = await verifier.verify_predicate(
        _predicate("metric", PredicateType.METRIC_THRESHOLD, "coverage", {"min": 0.9}),
        context,
    )
    invariant_result = await verifier.verify_predicate(
        _predicate(
            "invariant",
            PredicateType.INVARIANT_HOLDS,
            "module.py",
            {"forbid_patterns": ("import requests",), "require_patterns": ("VALUE",)},
        ),
        context,
    )

    assert file_result.passed is True
    assert pattern_result.passed is True
    assert metric_result.passed is True
    assert invariant_result.passed is True
    assert invariant_result.evidence["files_checked"] == 1


async def test_test_passes_predicate_runs_targeted_pytest(tmp_path: Path) -> None:
    test_file = tmp_path / "test_sample.py"
    test_file.write_text(
        "def test_sample():\n"
        "    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )

    result = await OutcomeVerifier(timeout_seconds=10).verify_predicate(
        _predicate("tests", PredicateType.TEST_PASSES, "test_sample.py"),
        {"cwd": tmp_path},
    )

    assert result.passed is True
    assert result.score == 1.0
    assert result.evidence["returncode"] == 0


async def test_custom_function_predicate_accepts_async_score() -> None:
    async def evaluate(target: str, expected: object, context: dict[str, object]) -> dict[str, object]:
        return {"passed": target == "custom-check", "score": 0.8, "evidence": {"expected": expected}}

    result = await OutcomeVerifier().verify_predicate(
        _predicate("custom", PredicateType.CUSTOM_FUNCTION, "custom-check", {"min": 0.8}),
        {"custom_functions": {"custom-check": evaluate}},
    )

    assert result.passed is True
    assert result.score == 0.8
    assert result.evidence["function"] == "custom-check"


async def test_partial_progress_scoring_and_required_failure(tmp_path: Path) -> None:
    (tmp_path / "done.txt").write_text("done", encoding="utf-8")
    spec = OutcomeSpec(
        outcome_id="outcome-1",
        task_id="task-1",
        predicates=(
            _predicate("done", PredicateType.FILE_EXISTS, "done.txt", True, weight=0.75),
            _predicate(
                "missing",
                PredicateType.FILE_EXISTS,
                "missing.txt",
                True,
                weight=0.25,
                required=True,
            ),
        ),
        acceptance_threshold=0.7,
        regression_guards=(),
        partial_credit=True,
        deadline=None,
    )

    result = await OutcomeVerifier().verify(spec, {"cwd": tmp_path})

    assert result.partial_progress == 0.75
    assert result.overall_score == 0.75
    assert result.passed is False
    assert result.evidence["required_failed"] is True


async def test_deadline_miss_prevents_pass_even_when_score_satisfies_threshold(
    tmp_path: Path,
) -> None:
    (tmp_path / "done.txt").write_text("done", encoding="utf-8")
    spec = OutcomeSpec(
        outcome_id="deadline",
        task_id="task-1",
        predicates=(_predicate("done", PredicateType.FILE_EXISTS, "done.txt"),),
        acceptance_threshold=1.0,
        regression_guards=(),
        partial_credit=True,
        deadline=datetime(2020, 1, 1, tzinfo=UTC),
    )

    result = await OutcomeVerifier().verify(spec, {"cwd": tmp_path})

    assert result.overall_score == 1.0
    assert result.passed is False
    assert result.evidence["deadline_missed"] is True
    assert result.evidence["task_id"] == "task-1"


async def test_regression_guard_caps_outcome_score(tmp_path: Path) -> None:
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("new content", encoding="utf-8")
    spec = OutcomeSpec(
        outcome_id="outcome-regression",
        task_id="task-1",
        predicates=(
            _predicate("done", PredicateType.FILE_EXISTS, "tracked.txt", True, required=True),
        ),
        acceptance_threshold=1.0,
        regression_guards=(
            RegressionGuard(
                guard_id="tracked-unchanged",
                description="tracked file remains unchanged",
                guard_type=GuardType.FILE_UNCHANGED,
                baseline={"path": "tracked.txt", "sha256": "not-the-current-hash"},
                tolerance=0.0,
            ),
        ),
        partial_credit=True,
        deadline=None,
    )

    result = await OutcomeVerifier().verify(spec, {"cwd": tmp_path})

    assert result.partial_progress == 1.0
    assert result.overall_score == 0.0
    assert result.passed is False
    assert result.regression_results[0].passed is False


async def test_quality_gate_composition_blocks_pipeline(tmp_path: Path) -> None:
    (tmp_path / "exists.txt").write_text("ok", encoding="utf-8")
    passing = OutcomeSpec(
        outcome_id="passing",
        task_id="task-1",
        predicates=(_predicate("exists", PredicateType.FILE_EXISTS, "exists.txt"),),
        acceptance_threshold=1.0,
        regression_guards=(),
        partial_credit=True,
        deadline=None,
    )
    failing = OutcomeSpec(
        outcome_id="failing",
        task_id="task-1",
        predicates=(_predicate("missing", PredicateType.FILE_EXISTS, "missing.txt"),),
        acceptance_threshold=1.0,
        regression_guards=(),
        partial_credit=True,
        deadline=None,
    )
    engine = QualityGateEngine(context={"cwd": tmp_path})
    pre_commit = engine.define_gate(
        "pre-commit",
        [passing],
        1.0,
        True,
        quality_level=QualityLevel.PRE_COMMIT,
    )
    release = engine.define_gate(
        "release",
        [failing],
        1.0,
        True,
        quality_level=QualityLevel.RELEASE,
    )

    gate_result = await engine.evaluate_gate(pre_commit)
    pipeline_result = await engine.evaluate_pipeline_gates([pre_commit, release])

    assert gate_result.passed is True
    assert pipeline_result.passed is False
    assert pipeline_result.blocked_by == "release"
    assert len(pipeline_result.gate_results) == 2


async def test_progress_tracking_regression_velocity_and_eta(tmp_path: Path) -> None:
    tracker = OutcomeTracker(tmp_path / "outcomes.jsonl", regression_threshold=0.1)
    start = datetime(2026, 5, 15, 8, 0, tzinfo=UTC)
    first = _outcome_result(
        "outcome-1",
        score=0.6,
        progress=0.5,
        evaluated_at=start,
        passed_predicates=("p1",),
    )
    second = _outcome_result(
        "outcome-1",
        score=0.8,
        progress=0.75,
        evaluated_at=start + timedelta(hours=2),
        passed_predicates=("p1", "p2"),
    )
    regressed = _outcome_result(
        "outcome-1",
        score=0.6,
        progress=0.75,
        evaluated_at=start + timedelta(hours=3),
        passed_predicates=("p1", "p2"),
    )

    await tracker.record_evaluation(first)
    await tracker.record_evaluation(second)
    velocity = await tracker.compute_velocity("task-1")
    eta = await tracker.predict_completion("outcome-1")
    await tracker.record_evaluation(regressed)
    alert = await tracker.detect_regression("outcome-1")
    history = await tracker.get_progress_history("outcome-1")

    assert len(history) == 3
    assert velocity == 0.5
    assert eta == start + timedelta(hours=4)
    assert alert is not None
    assert alert.delta == pytest.approx(-0.2)


def test_outcome_spec_validation() -> None:
    with pytest.raises(ValidationError):
        OutcomeSpec(
            outcome_id="invalid",
            task_id="task-1",
            predicates=(
                _predicate("duplicate", PredicateType.FILE_EXISTS, "a", weight=0.5),
                _predicate("duplicate", PredicateType.FILE_EXISTS, "b", weight=0.5),
            ),
            acceptance_threshold=1.1,
            regression_guards=(),
            partial_credit=True,
            deadline=None,
        )

    with pytest.raises(ValidationError):
        OutcomeSpec(
            outcome_id="zero-weight",
            task_id="task-1",
            predicates=(
                _predicate("a", PredicateType.FILE_EXISTS, "a", weight=0.0),
            ),
            acceptance_threshold=1.0,
            regression_guards=(),
            partial_credit=True,
            deadline=None,
        )
