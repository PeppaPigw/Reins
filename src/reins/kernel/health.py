"""Kernel Health Monitor: continuous runtime health assessment."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from reins.event_bus import EventBus


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"


@dataclass
class HealthCheck:
    name: str
    status: HealthStatus
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class KernelHealthMonitor:
    """Monitors kernel runtime health and emits status events."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._checks: dict[str, HealthCheck] = {}
        self._thresholds = {"quarantine_ratio": 0.5, "denial_rate": 0.8}

    def report(self, name: str, status: HealthStatus, message: str = "",
               metadata: dict[str, Any] | None = None) -> None:
        check = HealthCheck(name=name, status=status, message=message,
                            metadata=metadata or {})
        self._checks[name] = check
        if status != HealthStatus.HEALTHY:
            self._bus.publish_sync(f"health.{status.value}", "health-monitor",
                                   {"check": name, "status": status.value, "message": message})

    def assess(self, total_agents: int, quarantined_count: int,
               total_evaluations: int, denied_count: int) -> HealthStatus:
        if total_agents == 0:
            self.report("agents", HealthStatus.DEGRADED, "no agents registered")
            return HealthStatus.DEGRADED

        q_ratio = quarantined_count / total_agents if total_agents else 0
        if q_ratio >= self._thresholds["quarantine_ratio"]:
            self.report("quarantine", HealthStatus.CRITICAL,
                        f"{quarantined_count}/{total_agents} agents quarantined")
            return HealthStatus.CRITICAL

        d_rate = denied_count / total_evaluations if total_evaluations else 0
        if d_rate >= self._thresholds["denial_rate"]:
            self.report("denial_rate", HealthStatus.DEGRADED,
                        f"denial rate {d_rate:.0%}")
            return HealthStatus.DEGRADED

        self.report("overall", HealthStatus.HEALTHY)
        return HealthStatus.HEALTHY

    @property
    def status(self) -> HealthStatus:
        if not self._checks:
            return HealthStatus.HEALTHY
        statuses = [c.status for c in self._checks.values()]
        if HealthStatus.CRITICAL in statuses:
            return HealthStatus.CRITICAL
        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY

    @property
    def checks(self) -> dict[str, HealthCheck]:
        return dict(self._checks)
