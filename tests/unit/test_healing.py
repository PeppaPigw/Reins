"""Tests for self-healing engine with automatic failure recovery."""

from __future__ import annotations

import pytest

from reins.healing import (
    ComponentHealth,
    Failure,
    FailureKind,
    HealingStats,
    HealthStatus,
    RecoveryAttempt,
    RecoveryOutcome,
    RecoveryPolicy,
    RecoveryStrategy,
    SelfHealingEngine,
)


@pytest.fixture
def engine() -> SelfHealingEngine:
    return SelfHealingEngine(circuit_break_threshold=5)


def _failure(component_id="comp-1", kind=FailureKind.TRANSIENT, message="test failure"):
    return Failure(component_id=component_id, kind=kind, message=message)


def test_report_failure_returns_strategy(engine):
    strategy = engine.report_failure(_failure())
    assert strategy in RecoveryStrategy


def test_transient_failure_suggests_retry(engine):
    strategy = engine.report_failure(_failure(kind=FailureKind.TRANSIENT))
    assert strategy in (RecoveryStrategy.RETRY, RecoveryStrategy.RETRY_WITH_BACKOFF)


def test_persistent_failure_suggests_rollback(engine):
    strategy = engine.report_failure(_failure(kind=FailureKind.PERSISTENT))
    assert strategy in (RecoveryStrategy.ROLLBACK, RecoveryStrategy.FAILOVER)


def test_cascading_failure_suggests_circuit_break(engine):
    strategy = engine.report_failure(_failure(kind=FailureKind.CASCADING))
    assert strategy in (RecoveryStrategy.CIRCUIT_BREAK, RecoveryStrategy.QUARANTINE)


def test_unknown_failure_escalates(engine):
    strategy = engine.report_failure(_failure(kind=FailureKind.UNKNOWN))
    assert strategy == RecoveryStrategy.ESCALATE


def test_circuit_break_on_threshold(engine):
    for _ in range(5):
        strategy = engine.report_failure(_failure())
    assert strategy == RecoveryStrategy.CIRCUIT_BREAK


def test_health_degrades_on_failure(engine):
    engine.report_failure(_failure())
    health = engine.get_health("comp-1")
    assert health.status == HealthStatus.DEGRADED
    assert health.consecutive_failures == 1


def test_health_critical_on_circuit_break(engine):
    for _ in range(5):
        engine.report_failure(_failure())
    health = engine.get_health("comp-1")
    assert health.status == HealthStatus.CRITICAL
    assert health.circuit_open is True


def test_record_successful_recovery(engine):
    f = _failure()
    engine.report_failure(f)
    attempt = engine.record_recovery(
        f.failure_id, "comp-1", RecoveryStrategy.RETRY, RecoveryOutcome.SUCCESS, duration_ms=50.0
    )
    assert attempt.outcome == RecoveryOutcome.SUCCESS
    health = engine.get_health("comp-1")
    assert health.consecutive_failures == 0
    assert health.circuit_open is False


def test_record_failed_recovery(engine):
    f = _failure()
    engine.report_failure(f)
    engine.record_recovery(
        f.failure_id, "comp-1", RecoveryStrategy.RETRY, RecoveryOutcome.FAILED
    )
    health = engine.get_health("comp-1")
    assert health.consecutive_failures == 1


def test_reset_circuit(engine):
    for _ in range(5):
        engine.report_failure(_failure())
    assert engine.get_health("comp-1").circuit_open is True
    assert engine.reset_circuit("comp-1")
    health = engine.get_health("comp-1")
    assert health.circuit_open is False
    assert health.status == HealthStatus.DEGRADED


def test_reset_circuit_not_open(engine):
    engine.report_failure(_failure())
    assert not engine.reset_circuit("comp-1")


def test_reset_circuit_nonexistent(engine):
    assert not engine.reset_circuit("nonexistent")


def test_get_health_unknown_component(engine):
    health = engine.get_health("unknown")
    assert health.status == HealthStatus.HEALTHY
    assert health.consecutive_failures == 0


def test_recovery_history_all(engine):
    f = _failure()
    engine.report_failure(f)
    engine.record_recovery(f.failure_id, "comp-1", RecoveryStrategy.RETRY, RecoveryOutcome.SUCCESS)
    history = engine.get_recovery_history()
    assert len(history) == 1


def test_recovery_history_by_component(engine):
    f1 = _failure(component_id="a")
    f2 = _failure(component_id="b")
    engine.report_failure(f1)
    engine.report_failure(f2)
    engine.record_recovery(f1.failure_id, "a", RecoveryStrategy.RETRY, RecoveryOutcome.SUCCESS)
    engine.record_recovery(f2.failure_id, "b", RecoveryStrategy.RETRY, RecoveryOutcome.FAILED)

    history_a = engine.get_recovery_history(component_id="a")
    assert len(history_a) == 1
    assert history_a[0].component_id == "a"


def test_recovery_history_by_strategy(engine):
    f = _failure()
    engine.report_failure(f)
    engine.record_recovery(f.failure_id, "comp-1", RecoveryStrategy.RETRY, RecoveryOutcome.SUCCESS)
    engine.record_recovery(
        f.failure_id, "comp-1", RecoveryStrategy.ROLLBACK, RecoveryOutcome.FAILED
    )

    retry_history = engine.get_recovery_history(strategy=RecoveryStrategy.RETRY)
    assert len(retry_history) == 1


def test_strategy_learning_rewards_success(engine):
    for _ in range(5):
        f = _failure()
        engine.report_failure(f)
        engine.record_recovery(
            f.failure_id, "comp-1", RecoveryStrategy.RETRY, RecoveryOutcome.SUCCESS
        )
    strategy = engine.report_failure(_failure())
    assert strategy == RecoveryStrategy.RETRY


def test_strategy_learning_penalizes_failure(engine):
    for _ in range(5):
        f = _failure()
        engine.report_failure(f)
        engine.record_recovery(
            f.failure_id, "comp-1", RecoveryStrategy.RETRY, RecoveryOutcome.FAILED
        )
    for _ in range(3):
        f = _failure()
        engine.report_failure(f)
        engine.record_recovery(
            f.failure_id, "comp-1", RecoveryStrategy.RETRY_WITH_BACKOFF, RecoveryOutcome.SUCCESS
        )
    strategy = engine.report_failure(_failure())
    assert strategy == RecoveryStrategy.RETRY_WITH_BACKOFF


def test_register_custom_policy(engine):
    policy = RecoveryPolicy(
        failure_kind=FailureKind.TRANSIENT,
        strategies=(RecoveryStrategy.FAILOVER,),
        max_retries=1,
    )
    engine.register_policy(policy)
    strategy = engine.report_failure(_failure(kind=FailureKind.TRANSIENT))
    assert strategy == RecoveryStrategy.FAILOVER


def test_stats_empty():
    engine = SelfHealingEngine()
    stats = engine.get_stats()
    assert stats.total_failures == 0
    assert stats.total_recoveries == 0
    assert stats.components_monitored == 0


def test_stats_with_data(engine):
    f = _failure()
    engine.report_failure(f)
    engine.record_recovery(f.failure_id, "comp-1", RecoveryStrategy.RETRY, RecoveryOutcome.SUCCESS)

    stats = engine.get_stats()
    assert stats.total_failures == 1
    assert stats.total_recoveries == 1
    assert stats.successful_recoveries == 1
    assert stats.recovery_rate == 1.0
    assert stats.components_monitored == 1
    assert stats.components_healthy == 1


def test_stats_recovery_rate(engine):
    for i in range(4):
        f = _failure()
        engine.report_failure(f)
        outcome = RecoveryOutcome.SUCCESS if i < 3 else RecoveryOutcome.FAILED
        engine.record_recovery(f.failure_id, "comp-1", RecoveryStrategy.RETRY, outcome)

    stats = engine.get_stats()
    assert stats.recovery_rate == pytest.approx(0.75)
    assert stats.successful_recoveries == 3
    assert stats.failed_recoveries == 1


def test_multiple_components_independent(engine):
    engine.report_failure(_failure(component_id="a"))
    engine.report_failure(_failure(component_id="b"))
    engine.report_failure(_failure(component_id="b"))

    health_a = engine.get_health("a")
    health_b = engine.get_health("b")
    assert health_a.consecutive_failures == 1
    assert health_b.consecutive_failures == 2


def test_health_recovers_after_success(engine):
    for _ in range(3):
        f = _failure()
        engine.report_failure(f)
    assert engine.get_health("comp-1").status == HealthStatus.UNHEALTHY

    engine.record_recovery("x", "comp-1", RecoveryStrategy.RETRY, RecoveryOutcome.SUCCESS)
    assert engine.get_health("comp-1").status == HealthStatus.HEALTHY


def test_dependency_failure_strategy(engine):
    strategy = engine.report_failure(_failure(kind=FailureKind.DEPENDENCY))
    assert strategy in (RecoveryStrategy.FAILOVER, RecoveryStrategy.RETRY_WITH_BACKOFF)


def test_corruption_failure_strategy(engine):
    strategy = engine.report_failure(_failure(kind=FailureKind.CORRUPTION))
    assert strategy in (RecoveryStrategy.ROLLBACK, RecoveryStrategy.ESCALATE)
