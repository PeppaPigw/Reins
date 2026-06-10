"""Tests for resilience engine with circuit breakers and fault tolerance."""

from __future__ import annotations

import pytest

from reins.resilience import (
    BulkheadPartition,
    CircuitBreaker,
    CircuitState,
    DegradationLevel,
    FaultEvent,
    FaultKind,
    RecoveryAction,
    ResilienceEngine,
    ResiliencePolicy,
    ResilienceStats,
)


@pytest.fixture
def engine() -> ResilienceEngine:
    return ResilienceEngine()


def test_create_breaker(engine):
    breaker = engine.create_breaker("api-service", failure_threshold=3)
    assert breaker.name == "api-service"
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_threshold == 3


def test_get_breaker(engine):
    breaker = engine.create_breaker("svc")
    assert engine.get_breaker(breaker.breaker_id) is not None
    assert engine.get_breaker("nonexistent") is None


def test_record_success_closed(engine):
    breaker = engine.create_breaker("svc")
    updated = engine.record_success(breaker.breaker_id)
    assert updated.success_count == 1
    assert updated.state == CircuitState.CLOSED


def test_record_failure_below_threshold(engine):
    breaker = engine.create_breaker("svc", failure_threshold=3)
    engine.record_failure(breaker.breaker_id)
    updated = engine.record_failure(breaker.breaker_id)
    assert updated.failure_count == 2
    assert updated.state == CircuitState.CLOSED


def test_record_failure_opens_circuit(engine):
    breaker = engine.create_breaker("svc", failure_threshold=3)
    for _ in range(3):
        breaker = engine.record_failure(breaker.breaker_id)
    assert breaker.state == CircuitState.OPEN


def test_is_call_permitted_closed(engine):
    breaker = engine.create_breaker("svc")
    assert engine.is_call_permitted(breaker.breaker_id) is True


def test_is_call_permitted_open(engine):
    breaker = engine.create_breaker("svc", failure_threshold=1)
    engine.record_failure(breaker.breaker_id)
    assert engine.is_call_permitted(breaker.breaker_id) is False


def test_is_call_permitted_unknown(engine):
    assert engine.is_call_permitted("nonexistent") is True


def test_attempt_reset(engine):
    breaker = engine.create_breaker("svc", failure_threshold=1)
    engine.record_failure(breaker.breaker_id)
    reset = engine.attempt_reset(breaker.breaker_id)
    assert reset.state == CircuitState.HALF_OPEN


def test_half_open_success_closes(engine):
    breaker = engine.create_breaker("svc", failure_threshold=1, recovery_timeout_ms=100)
    breaker = engine.create_breaker("svc2", failure_threshold=1)
    engine.record_failure(breaker.breaker_id)
    engine.attempt_reset(breaker.breaker_id)
    for _ in range(3):
        engine.record_success(breaker.breaker_id)
    updated = engine.get_breaker(breaker.breaker_id)
    assert updated.state == CircuitState.CLOSED


def test_half_open_failure_reopens(engine):
    breaker = engine.create_breaker("svc", failure_threshold=1)
    engine.record_failure(breaker.breaker_id)
    engine.attempt_reset(breaker.breaker_id)
    updated = engine.record_failure(breaker.breaker_id)
    assert updated.state == CircuitState.OPEN


def test_create_partition(engine):
    partition = engine.create_partition("db-pool", max_concurrent=5)
    assert partition.name == "db-pool"
    assert partition.max_concurrent == 5


def test_acquire_slot(engine):
    partition = engine.create_partition("pool", max_concurrent=2)
    assert engine.acquire_slot(partition.partition_id) is True
    assert engine.acquire_slot(partition.partition_id) is True
    assert engine.acquire_slot(partition.partition_id) is False


def test_acquire_slot_tracks_rejected(engine):
    partition = engine.create_partition("pool", max_concurrent=1)
    engine.acquire_slot(partition.partition_id)
    engine.acquire_slot(partition.partition_id)
    updated = engine.get_partition(partition.partition_id)
    assert updated.rejected == 1


def test_release_slot(engine):
    partition = engine.create_partition("pool", max_concurrent=1)
    engine.acquire_slot(partition.partition_id)
    assert engine.release_slot(partition.partition_id) is True
    assert engine.acquire_slot(partition.partition_id) is True


def test_release_slot_empty(engine):
    partition = engine.create_partition("pool")
    assert engine.release_slot(partition.partition_id) is False


def test_record_fault(engine):
    fault = engine.record_fault("api", FaultKind.TIMEOUT, message="timed out")
    assert fault.service == "api"
    assert fault.kind == FaultKind.TIMEOUT
    assert not fault.resolved


def test_record_fault_selects_action(engine):
    fault = engine.record_fault("api", FaultKind.RATE_LIMIT)
    assert fault.recovery_action == RecoveryAction.SHED_LOAD


def test_record_fault_critical_escalates(engine):
    fault = engine.record_fault("api", FaultKind.TIMEOUT, severity=DegradationLevel.CRITICAL)
    assert fault.recovery_action == RecoveryAction.ESCALATE


def test_resolve_fault(engine):
    fault = engine.record_fault("api", FaultKind.TIMEOUT)
    resolved = engine.resolve_fault(fault.event_id)
    assert resolved.resolved is True


def test_resolve_fault_not_found(engine):
    assert engine.resolve_fault("nonexistent") is None


def test_get_faults_by_service(engine):
    engine.record_fault("api", FaultKind.TIMEOUT)
    engine.record_fault("db", FaultKind.CONNECTION_ERROR)
    faults = engine.get_faults(service="api")
    assert len(faults) == 1


def test_get_faults_unresolved_only(engine):
    f1 = engine.record_fault("api", FaultKind.TIMEOUT)
    engine.record_fault("api", FaultKind.TIMEOUT)
    engine.resolve_fault(f1.event_id)
    faults = engine.get_faults(unresolved_only=True)
    assert len(faults) == 1


def test_set_policy(engine):
    policy = engine.set_policy("api", max_retries=5, timeout_ms=10000)
    assert policy.service == "api"
    assert policy.max_retries == 5


def test_get_policy(engine):
    engine.set_policy("api")
    assert engine.get_policy("api") is not None
    assert engine.get_policy("nonexistent") is None


def test_degradation_level_none(engine):
    assert engine.get_degradation_level() == DegradationLevel.NONE


def test_degradation_level_minor(engine):
    engine.record_fault("api", FaultKind.TIMEOUT)
    assert engine.get_degradation_level() == DegradationLevel.MINOR


def test_degradation_level_critical(engine):
    engine.record_fault("api", FaultKind.TIMEOUT, severity=DegradationLevel.CRITICAL)
    assert engine.get_degradation_level() == DegradationLevel.CRITICAL


def test_degradation_level_open_breakers(engine):
    b = engine.create_breaker("svc", failure_threshold=1)
    engine.record_failure(b.breaker_id)
    engine.record_fault("svc", FaultKind.TIMEOUT)
    level = engine.get_degradation_level()
    assert level in (DegradationLevel.MODERATE, DegradationLevel.SEVERE)


def test_stats_empty(engine):
    stats = engine.get_stats()
    assert stats.total_breakers == 0
    assert stats.total_faults == 0


def test_stats_populated(engine):
    engine.create_breaker("svc1", failure_threshold=1)
    b2 = engine.create_breaker("svc2", failure_threshold=1)
    engine.record_failure(b2.breaker_id)
    engine.create_partition("pool")
    engine.record_fault("api", FaultKind.TIMEOUT)
    engine.record_fault("api", FaultKind.RATE_LIMIT)
    stats = engine.get_stats()
    assert stats.total_breakers == 2
    assert stats.open_breakers == 1
    assert stats.total_partitions == 1
    assert stats.total_faults == 2
    assert "timeout" in stats.by_fault_kind
    assert "rate_limit" in stats.by_fault_kind
