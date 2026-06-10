from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from reins.dreaming import (
    ActionRecord,
    DreamConsolidator,
    FailureRecord,
    HarnessOptimizer,
    Optimization,
    OptimizationStatus,
    OptimizationType,
    PatternExtractor,
    PatternKind,
    SessionSummary,
    SuccessRecord,
)


def _successful_session(session_id: str = "session-success") -> SessionSummary:
    started = datetime(2026, 5, 15, 9, 0, tzinfo=UTC)
    return SessionSummary(
        session_id=session_id,
        objective="Implement backend feature",
        started_at=started,
        ended_at=started + timedelta(minutes=8),
        status="completed",
        actions=(
            ActionRecord(action="search", tool="rg", success=True, timestamp=started),
            ActionRecord(action="edit", tool="apply_patch", success=True, timestamp=started),
            ActionRecord(action="test", tool="pytest", success=True, timestamp=started),
        ),
        successes=(
            SuccessRecord(
                session_id=session_id,
                outcome="tests_passed",
                action_sequence=("search", "edit", "test"),
                tools=("rg", "apply_patch", "pytest"),
                context={"domain": "backend", "task_type": "feature", "risk_tier": "T1"},
                duration_seconds=480,
                timestamp=started + timedelta(minutes=8),
            ),
        ),
        context={"domain": "backend", "task_type": "feature", "risk_tier": "T1"},
    )


def _failed_session(session_id: str = "session-failed") -> SessionSummary:
    started = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)
    return SessionSummary(
        session_id=session_id,
        objective="Run integration tests",
        started_at=started,
        ended_at=started + timedelta(minutes=12),
        status="failed",
        actions=(
            ActionRecord(action="run-tests", tool="pytest", success=False, timestamp=started),
            ActionRecord(action="retry", tool="pytest", success=False, timestamp=started),
        ),
        failures=(
            FailureRecord(
                session_id=session_id,
                failure_type="environment_failure",
                message="database service unavailable",
                action_sequence=("run-tests", "retry"),
                tool="pytest",
                context={"domain": "backend", "risk_tier": "T2"},
                severity=0.8,
                timestamp=started + timedelta(minutes=12),
            ),
        ),
        context={"domain": "backend", "risk_tier": "T2"},
    )


async def test_pattern_extraction_from_mock_session() -> None:
    extractor = PatternExtractor()

    patterns = await extractor.extract(_successful_session())

    kinds = {pattern.kind for pattern in patterns}
    assert PatternKind.SUCCESS_SEQUENCE in kinds
    assert PatternKind.TOOL_USAGE in kinds
    assert PatternKind.CONTEXT in kinds
    assert any(pattern.sequence == ("search", "edit", "test") for pattern in patterns)
    assert any(pattern.tools and pattern.tools[0] == "pytest" for pattern in patterns)


async def test_failure_clustering_groups_similar_failures() -> None:
    consolidator = DreamConsolidator()
    first = _failed_session("failed-1").failures[0]
    second = FailureRecord(
        session_id="failed-2",
        failure_type="environment_failure",
        message="database service unavailable during setup",
        action_sequence=("run-tests", "retry"),
        tool="pytest",
        context={"domain": "backend", "risk_tier": "T2"},
        severity=0.9,
    )

    clusters = await consolidator.cluster_failures([first, second])

    assert len(clusters) == 1
    assert clusters[0].count == 2
    assert clusters[0].failure_type == "environment_failure"
    assert clusters[0].common_tools == ("pytest",)
    assert clusters[0].common_context["domain"] == "backend"


async def test_strategy_identification_finds_repeated_success_sequence() -> None:
    consolidator = DreamConsolidator()
    successes = [
        _successful_session("success-1").successes[0],
        _successful_session("success-2").successes[0],
    ]

    strategies = await consolidator.identify_strategies(successes)

    assert len(strategies) == 1
    assert strategies[0].action_sequence == ("search", "edit", "test")
    assert strategies[0].tools == ("rg", "apply_patch", "pytest")
    assert strategies[0].support == 2
    assert strategies[0].confidence > 0.6


async def test_optimization_generation_and_application(tmp_path: Path) -> None:
    consolidator = DreamConsolidator()
    report = await consolidator.consolidate(
        [_successful_session("success-1"), _successful_session("success-2")]
    )
    optimizer = HarnessOptimizer(tmp_path)

    optimizations = await optimizer.optimize(report)
    tool_opt = next(opt for opt in optimizations if opt.optimization_type is OptimizationType.TOOL)
    result = await optimizer.apply_optimization(tool_opt)

    assert result.applied is True
    assert result.status is OptimizationStatus.APPLIED
    assert optimizer.get_config()["tools"][tool_opt.target]["preference"] > 0.5
    assert (tmp_path / "optimizer_journal.jsonl").exists()
    reopened = HarnessOptimizer(tmp_path)
    assert reopened.get_config()["tools"][tool_opt.target]["preference"] > 0.5


async def test_consolidator_persists_dream_reports(tmp_path: Path) -> None:
    consolidator = DreamConsolidator(store_path=tmp_path)

    report = await consolidator.consolidate([_successful_session()])
    reports = await consolidator.load_reports()

    assert (tmp_path / "dream_journal.jsonl").exists()
    assert len(reports) == 1
    assert reports[0].report_id == report.report_id
    assert reports[0].session_ids == ("session-success",)


async def test_rollback_on_regression_restores_previous_value(tmp_path: Path) -> None:
    optimizer = HarnessOptimizer(tmp_path)
    opt = Optimization(
        optimization_type=OptimizationType.TIMEOUT,
        target="default_session_timeout_seconds",
        change={
            "recommended_seconds": 120,
            "baseline_success_rate": 0.9,
            "current_success_rate": 0.7,
        },
        rationale="Tune timeout from observed sessions",
        confidence=0.8,
        expected_impact=0.1,
    )

    await optimizer.apply_optimization(opt)
    metrics = await optimizer.measure_impact(opt.optimization_id)
    if metrics.regression_detected:
        await optimizer.rollback_optimization(opt.optimization_id)

    assert metrics.regression_detected is True
    assert "default_session_timeout_seconds" not in optimizer.get_config()["timeouts"]
    stored = optimizer.get_optimization(opt.optimization_id)
    assert stored is not None
    assert stored.status is OptimizationStatus.ROLLED_BACK


async def test_memory_pruning_removes_stale_and_contradicted_memories() -> None:
    consolidator = DreamConsolidator(stale_memory_days=30)
    old_created_at = datetime.now(UTC) - timedelta(days=60)
    memories = [
        {
            "memory_id": "keep",
            "content": "use rg before broad file scans",
            "confidence": 0.8,
            "created_at": datetime.now(UTC).isoformat(),
        },
        {
            "memory_id": "stale",
            "content": "old preference",
            "confidence": 0.8,
            "created_at": old_created_at.isoformat(),
        },
        {
            "memory_id": "wrong",
            "content": "always skip tests for backend work",
            "confidence": 0.7,
            "created_at": datetime.now(UTC).isoformat(),
        },
    ]
    contradictions = [{"content": "always skip tests for backend work"}]

    result = await consolidator.prune_memories(memories, contradictions)

    assert result.pruned_ids == ("stale", "wrong")
    assert result.retained_ids == ("keep",)
    assert result.reasons["stale"] == "stale"
    assert result.reasons["wrong"] == "contradicted"
