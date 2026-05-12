from __future__ import annotations

from pathlib import Path

import pytest

from reins.evaluation.classifier import FailureClassifier
from reins.intelligence.recovery.planner import PatternRegistry, RecoveryPlanner
from reins.intelligence.types import HealingPattern


@pytest.fixture
def pattern_registry(tmp_path: Path) -> PatternRegistry:
    return PatternRegistry(tmp_path / "patterns")


@pytest.fixture
def recovery_planner(pattern_registry: PatternRegistry) -> RecoveryPlanner:
    return RecoveryPlanner(
        classifier=FailureClassifier(),
        pattern_registry=pattern_registry,
        max_retries=3,
        escalation_threshold=3,
    )


async def test_plan_recovery_without_patterns(recovery_planner: RecoveryPlanner) -> None:
    proposal = await recovery_planner.plan_recovery(
        failure={"error": "timeout", "retryable": False},
        context={"task_id": "task-1", "domain": "testing"},
    )
    assert proposal.failure_class == "environment_failure"
    assert proposal.action == "check_and_fix_environment"
    assert proposal.prior_attempts == 1


async def test_plan_recovery_with_matching_pattern(
    pattern_registry: PatternRegistry, recovery_planner: RecoveryPlanner
) -> None:
    pattern_registry.register_pattern(HealingPattern(
        pattern_id="env-fix-1",
        failure_signature="environment_failure",
        recovery_action="reinstall_dependencies",
        success_rate=0.85,
        applicable_domains=("testing",),
    ))

    proposal = await recovery_planner.plan_recovery(
        failure={"error": "timeout"},
        context={"task_id": "task-2", "domain": "testing"},
    )
    assert proposal.pattern_id == "env-fix-1"
    assert proposal.action == "reinstall_dependencies"
    assert not proposal.requires_approval


async def test_escalation_after_threshold(recovery_planner: RecoveryPlanner) -> None:
    for _ in range(3):
        await recovery_planner.plan_recovery(
            failure={"error": "logic error"},
            context={"task_id": "task-3"},
        )

    decision = recovery_planner.should_escalate({"task_id": "task-3"})
    assert decision.should_escalate
    assert decision.reason is not None


async def test_reset_attempts(recovery_planner: RecoveryPlanner) -> None:
    for _ in range(3):
        await recovery_planner.plan_recovery(
            failure={"error": "logic error"},
            context={"task_id": "task-4"},
        )

    recovery_planner.reset_attempts("task-4")
    decision = recovery_planner.should_escalate({"task_id": "task-4"})
    assert not decision.should_escalate


def test_pattern_outcome_updates_success_rate(pattern_registry: PatternRegistry) -> None:
    pattern_registry.register_pattern(HealingPattern(
        pattern_id="test-pattern",
        failure_signature="logic_failure",
        recovery_action="retry",
        success_rate=0.5,
    ))

    pattern_registry.record_outcome("test-pattern", True)
    pattern_registry.record_outcome("test-pattern", True)
    pattern_registry.record_outcome("test-pattern", False)

    reloaded = PatternRegistry(pattern_registry._store_path)
    patterns = reloaded.match("logic_failure", {})
    assert len(patterns) == 1
    assert abs(patterns[0].success_rate - 2 / 3) < 0.01


async def test_fallback_classes_computed(recovery_planner: RecoveryPlanner) -> None:
    proposal = await recovery_planner.plan_recovery(
        failure={"error": "logic error"},
        context={"task_id": "task-5"},
    )
    assert proposal.failure_class == "logic_failure"
    assert "context_failure" in proposal.fallback_classes
