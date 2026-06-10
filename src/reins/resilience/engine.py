from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from reins.resilience.types import (
    BulkheadPartition,
    CircuitBreaker,
    CircuitState,
    DegradationLevel,
    FaultEvent,
    FaultKind,
    RecoveryAction,
    ResiliencePolicy,
    ResilienceStats,
)


class ResilienceEngine:
    """Fault tolerance with circuit breakers, bulkheads, and graceful degradation.

    Manages circuit breaker state machines, bulkhead partitions for load isolation,
    fault event tracking, and automatic recovery action selection.
    """

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._partitions: dict[str, BulkheadPartition] = {}
        self._faults: list[FaultEvent] = []
        self._policies: dict[str, ResiliencePolicy] = {}

    def create_breaker(self, name: str, failure_threshold: int = 5,
                       recovery_timeout_ms: int = 30000) -> CircuitBreaker:
        breaker = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout_ms=recovery_timeout_ms,
        )
        self._breakers[breaker.breaker_id] = breaker
        return breaker

    def get_breaker(self, breaker_id: str) -> CircuitBreaker | None:
        return self._breakers.get(breaker_id)

    def record_success(self, breaker_id: str) -> CircuitBreaker | None:
        breaker = self._breakers.get(breaker_id)
        if not breaker:
            return None

        if breaker.state == CircuitState.HALF_OPEN:
            new_success = breaker.success_count + 1
            if new_success >= breaker.half_open_max_calls:
                breaker = breaker.model_copy(update={
                    "state": CircuitState.CLOSED,
                    "failure_count": 0,
                    "success_count": 0,
                })
            else:
                breaker = breaker.model_copy(update={"success_count": new_success})
        elif breaker.state == CircuitState.CLOSED:
            breaker = breaker.model_copy(update={
                "success_count": breaker.success_count + 1,
            })

        self._breakers[breaker_id] = breaker
        return breaker

    def record_failure(self, breaker_id: str) -> CircuitBreaker | None:
        breaker = self._breakers.get(breaker_id)
        if not breaker:
            return None

        now = datetime.now(UTC)
        new_failures = breaker.failure_count + 1

        if breaker.state == CircuitState.HALF_OPEN:
            breaker = breaker.model_copy(update={
                "state": CircuitState.OPEN,
                "failure_count": new_failures,
                "last_failure_at": now,
                "opened_at": now,
            })
        elif breaker.state == CircuitState.CLOSED:
            if new_failures >= breaker.failure_threshold:
                breaker = breaker.model_copy(update={
                    "state": CircuitState.OPEN,
                    "failure_count": new_failures,
                    "last_failure_at": now,
                    "opened_at": now,
                })
            else:
                breaker = breaker.model_copy(update={
                    "failure_count": new_failures,
                    "last_failure_at": now,
                })

        self._breakers[breaker_id] = breaker
        return breaker

    def attempt_reset(self, breaker_id: str) -> CircuitBreaker | None:
        breaker = self._breakers.get(breaker_id)
        if not breaker or breaker.state != CircuitState.OPEN:
            return breaker
        breaker = breaker.model_copy(update={
            "state": CircuitState.HALF_OPEN,
            "success_count": 0,
        })
        self._breakers[breaker_id] = breaker
        return breaker

    def is_call_permitted(self, breaker_id: str) -> bool:
        breaker = self._breakers.get(breaker_id)
        if not breaker:
            return True
        return breaker.state != CircuitState.OPEN

    def create_partition(self, name: str, max_concurrent: int = 10) -> BulkheadPartition:
        partition = BulkheadPartition(name=name, max_concurrent=max_concurrent)
        self._partitions[partition.partition_id] = partition
        return partition

    def get_partition(self, partition_id: str) -> BulkheadPartition | None:
        return self._partitions.get(partition_id)

    def acquire_slot(self, partition_id: str) -> bool:
        partition = self._partitions.get(partition_id)
        if not partition:
            return False
        if partition.current_load >= partition.max_concurrent:
            self._partitions[partition_id] = partition.model_copy(
                update={"rejected": partition.rejected + 1}
            )
            return False
        self._partitions[partition_id] = partition.model_copy(
            update={"current_load": partition.current_load + 1}
        )
        return True

    def release_slot(self, partition_id: str) -> bool:
        partition = self._partitions.get(partition_id)
        if not partition or partition.current_load <= 0:
            return False
        self._partitions[partition_id] = partition.model_copy(
            update={"current_load": partition.current_load - 1}
        )
        return True

    def record_fault(self, service: str, kind: FaultKind,
                     severity: DegradationLevel = DegradationLevel.MINOR,
                     message: str = "") -> FaultEvent:
        action = self._select_recovery_action(kind, severity)
        fault = FaultEvent(
            service=service,
            kind=kind,
            severity=severity,
            message=message,
            recovery_action=action,
        )
        self._faults.append(fault)
        return fault

    def resolve_fault(self, event_id: str) -> FaultEvent | None:
        for i, fault in enumerate(self._faults):
            if fault.event_id == event_id:
                resolved = fault.model_copy(update={"resolved": True})
                self._faults[i] = resolved
                return resolved
        return None

    def get_faults(self, service: str | None = None,
                   unresolved_only: bool = False) -> list[FaultEvent]:
        faults = self._faults
        if service:
            faults = [f for f in faults if f.service == service]
        if unresolved_only:
            faults = [f for f in faults if not f.resolved]
        return faults

    def set_policy(self, service: str, max_retries: int = 3,
                   timeout_ms: int = 5000,
                   fallback_service: str = "") -> ResiliencePolicy:
        policy = ResiliencePolicy(
            service=service,
            max_retries=max_retries,
            timeout_ms=timeout_ms,
            fallback_service=fallback_service,
        )
        self._policies[service] = policy
        return policy

    def get_policy(self, service: str) -> ResiliencePolicy | None:
        return self._policies.get(service)

    def get_degradation_level(self) -> DegradationLevel:
        unresolved = [f for f in self._faults if not f.resolved]
        if not unresolved:
            return DegradationLevel.NONE

        severities = [f.severity for f in unresolved]
        if DegradationLevel.CRITICAL in severities:
            return DegradationLevel.CRITICAL
        if DegradationLevel.SEVERE in severities:
            return DegradationLevel.SEVERE

        open_breakers = sum(
            1 for b in self._breakers.values() if b.state == CircuitState.OPEN
        )
        if open_breakers > len(self._breakers) * 0.5 and self._breakers:
            return DegradationLevel.SEVERE
        if open_breakers > 0:
            return DegradationLevel.MODERATE

        if len(unresolved) > 5:
            return DegradationLevel.MODERATE
        return DegradationLevel.MINOR

    def get_stats(self) -> ResilienceStats:
        open_breakers = sum(
            1 for b in self._breakers.values() if b.state == CircuitState.OPEN
        )
        unresolved = sum(1 for f in self._faults if not f.resolved)

        by_fault_kind: dict[str, int] = defaultdict(int)
        by_recovery: dict[str, int] = defaultdict(int)
        for fault in self._faults:
            by_fault_kind[fault.kind.value] += 1
            by_recovery[fault.recovery_action.value] += 1

        return ResilienceStats(
            total_breakers=len(self._breakers),
            open_breakers=open_breakers,
            total_partitions=len(self._partitions),
            total_faults=len(self._faults),
            unresolved_faults=unresolved,
            degradation_level=self.get_degradation_level(),
            by_fault_kind=dict(by_fault_kind),
            by_recovery_action=dict(by_recovery),
        )

    def _select_recovery_action(self, kind: FaultKind,
                                severity: DegradationLevel) -> RecoveryAction:
        if severity in (DegradationLevel.CRITICAL, DegradationLevel.SEVERE):
            return RecoveryAction.ESCALATE
        if kind == FaultKind.TIMEOUT:
            return RecoveryAction.RETRY
        if kind == FaultKind.RATE_LIMIT:
            return RecoveryAction.SHED_LOAD
        if kind == FaultKind.RESOURCE_EXHAUSTION:
            return RecoveryAction.ISOLATE
        if kind == FaultKind.DEPENDENCY_FAILURE:
            return RecoveryAction.FALLBACK
        if kind == FaultKind.DATA_CORRUPTION:
            return RecoveryAction.ESCALATE
        return RecoveryAction.RETRY
