from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from reins.healing.types import (
    ComponentHealth,
    Failure,
    FailureKind,
    HealingStats,
    HealthStatus,
    RecoveryAttempt,
    RecoveryOutcome,
    RecoveryPolicy,
    RecoveryStrategy,
)


class SelfHealingEngine:
    """Automatic failure recovery with strategy selection and learning.

    Monitors component health, selects recovery strategies based on failure
    classification, tracks outcomes, and adapts strategy preferences over time.
    """

    def __init__(self, circuit_break_threshold: int = 5) -> None:
        self._circuit_break_threshold = circuit_break_threshold
        self._health: dict[str, _MutableHealth] = {}
        self._policies: dict[FailureKind, RecoveryPolicy] = {}
        self._attempts: list[RecoveryAttempt] = []
        self._strategy_scores: dict[str, dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        self._register_default_policies()

    def register_policy(self, policy: RecoveryPolicy) -> None:
        self._policies[policy.failure_kind] = policy

    def report_failure(self, failure: Failure) -> RecoveryStrategy:
        health = self._get_or_create_health(failure.component_id)
        health.consecutive_failures += 1
        health.total_failures += 1
        health.last_failure_at = failure.occurred_at

        if health.consecutive_failures >= self._circuit_break_threshold:
            health.circuit_open = True
            health.status = HealthStatus.CRITICAL
            return RecoveryStrategy.CIRCUIT_BREAK

        health.status = self._compute_status(health)
        return self._select_strategy(failure)

    def record_recovery(self, failure_id: str, component_id: str,
                        strategy: RecoveryStrategy, outcome: RecoveryOutcome,
                        duration_ms: float = 0.0, details: str = "") -> RecoveryAttempt:
        attempt = RecoveryAttempt(
            failure_id=failure_id,
            component_id=component_id,
            strategy=strategy,
            outcome=outcome,
            duration_ms=duration_ms,
            details=details,
        )
        self._attempts.append(attempt)

        health = self._get_or_create_health(component_id)
        health.total_recoveries += 1

        if outcome == RecoveryOutcome.SUCCESS:
            health.consecutive_failures = 0
            health.circuit_open = False
            health.last_recovery_at = datetime.now(UTC)
            health.status = self._compute_status(health)
            self._reward_strategy(component_id, strategy)
        elif outcome == RecoveryOutcome.FAILED:
            self._penalize_strategy(component_id, strategy)

        return attempt

    def get_health(self, component_id: str) -> ComponentHealth:
        health = self._health.get(component_id)
        if not health:
            return ComponentHealth(component_id=component_id)
        return ComponentHealth(
            component_id=component_id,
            status=health.status,
            consecutive_failures=health.consecutive_failures,
            total_failures=health.total_failures,
            total_recoveries=health.total_recoveries,
            last_failure_at=health.last_failure_at,
            last_recovery_at=health.last_recovery_at,
            circuit_open=health.circuit_open,
        )

    def reset_circuit(self, component_id: str) -> bool:
        health = self._health.get(component_id)
        if not health or not health.circuit_open:
            return False
        health.circuit_open = False
        health.consecutive_failures = 0
        health.status = HealthStatus.DEGRADED
        return True

    def get_recovery_history(self, component_id: str | None = None,
                            strategy: RecoveryStrategy | None = None) -> list[RecoveryAttempt]:
        attempts = self._attempts
        if component_id:
            attempts = [a for a in attempts if a.component_id == component_id]
        if strategy:
            attempts = [a for a in attempts if a.strategy == strategy]
        return attempts

    def get_stats(self) -> HealingStats:
        total_failures = sum(h.total_failures for h in self._health.values())
        total_recoveries = len(self._attempts)
        successful = sum(1 for a in self._attempts if a.outcome == RecoveryOutcome.SUCCESS)
        failed = sum(1 for a in self._attempts if a.outcome == RecoveryOutcome.FAILED)
        recovery_rate = successful / total_recoveries if total_recoveries else 0.0

        by_strategy: dict[str, int] = defaultdict(int)
        by_kind: dict[str, int] = defaultdict(int)
        for a in self._attempts:
            by_strategy[a.strategy.value] += 1

        for h in self._health.values():
            pass

        healthy = sum(1 for h in self._health.values() if h.status == HealthStatus.HEALTHY)
        degraded = sum(1 for h in self._health.values() if h.status == HealthStatus.DEGRADED)
        critical = sum(1 for h in self._health.values() if h.status == HealthStatus.CRITICAL)

        return HealingStats(
            total_failures=total_failures,
            total_recoveries=total_recoveries,
            successful_recoveries=successful,
            failed_recoveries=failed,
            recovery_rate=recovery_rate,
            components_monitored=len(self._health),
            components_healthy=healthy,
            components_degraded=degraded,
            components_critical=critical,
            by_strategy=dict(by_strategy),
        )

    def _select_strategy(self, failure: Failure) -> RecoveryStrategy:
        policy = self._policies.get(failure.kind)
        if not policy or not policy.strategies:
            return RecoveryStrategy.RETRY

        scores = self._strategy_scores.get(failure.component_id, {})
        best_strategy = policy.strategies[0]
        best_score = -float("inf")

        for strategy in policy.strategies:
            score = scores.get(strategy.value, 0.0)
            if score > best_score:
                best_score = score
                best_strategy = strategy

        return best_strategy

    def _reward_strategy(self, component_id: str, strategy: RecoveryStrategy) -> None:
        self._strategy_scores[component_id][strategy.value] += 1.0

    def _penalize_strategy(self, component_id: str, strategy: RecoveryStrategy) -> None:
        self._strategy_scores[component_id][strategy.value] -= 0.5

    def _compute_status(self, health: _MutableHealth) -> HealthStatus:
        if health.circuit_open:
            return HealthStatus.CRITICAL
        if health.consecutive_failures >= 3:
            return HealthStatus.UNHEALTHY
        if health.consecutive_failures >= 1:
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY

    def _get_or_create_health(self, component_id: str) -> _MutableHealth:
        if component_id not in self._health:
            self._health[component_id] = _MutableHealth(component_id=component_id)
        return self._health[component_id]

    def _register_default_policies(self) -> None:
        self._policies[FailureKind.TRANSIENT] = RecoveryPolicy(
            failure_kind=FailureKind.TRANSIENT,
            strategies=(RecoveryStrategy.RETRY, RecoveryStrategy.RETRY_WITH_BACKOFF),
            max_retries=3,
        )
        self._policies[FailureKind.TIMEOUT] = RecoveryPolicy(
            failure_kind=FailureKind.TIMEOUT,
            strategies=(RecoveryStrategy.RETRY_WITH_BACKOFF, RecoveryStrategy.CIRCUIT_BREAK),
            max_retries=2,
        )
        self._policies[FailureKind.PERSISTENT] = RecoveryPolicy(
            failure_kind=FailureKind.PERSISTENT,
            strategies=(RecoveryStrategy.ROLLBACK, RecoveryStrategy.FAILOVER),
            max_retries=1,
        )
        self._policies[FailureKind.CASCADING] = RecoveryPolicy(
            failure_kind=FailureKind.CASCADING,
            strategies=(RecoveryStrategy.CIRCUIT_BREAK, RecoveryStrategy.QUARANTINE),
            max_retries=1,
        )
        self._policies[FailureKind.RESOURCE_EXHAUSTION] = RecoveryPolicy(
            failure_kind=FailureKind.RESOURCE_EXHAUSTION,
            strategies=(RecoveryStrategy.RESTART, RecoveryStrategy.QUARANTINE),
            max_retries=2,
        )
        self._policies[FailureKind.DEPENDENCY] = RecoveryPolicy(
            failure_kind=FailureKind.DEPENDENCY,
            strategies=(RecoveryStrategy.FAILOVER, RecoveryStrategy.RETRY_WITH_BACKOFF),
            max_retries=3,
        )
        self._policies[FailureKind.CORRUPTION] = RecoveryPolicy(
            failure_kind=FailureKind.CORRUPTION,
            strategies=(RecoveryStrategy.ROLLBACK, RecoveryStrategy.ESCALATE),
            max_retries=1,
        )
        self._policies[FailureKind.UNKNOWN] = RecoveryPolicy(
            failure_kind=FailureKind.UNKNOWN,
            strategies=(RecoveryStrategy.ESCALATE,),
            max_retries=1,
        )


class _MutableHealth:
    __slots__ = (
        "component_id", "status", "consecutive_failures", "total_failures",
        "total_recoveries", "last_failure_at", "last_recovery_at", "circuit_open",
    )

    def __init__(self, component_id: str) -> None:
        self.component_id = component_id
        self.status = HealthStatus.HEALTHY
        self.consecutive_failures = 0
        self.total_failures = 0
        self.total_recoveries = 0
        self.last_failure_at: datetime | None = None
        self.last_recovery_at: datetime | None = None
        self.circuit_open = False
