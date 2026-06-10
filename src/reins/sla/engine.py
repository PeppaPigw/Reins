from __future__ import annotations

import time
from collections import defaultdict

from reins.sla.types import (
    DegradationAction,
    ErrorBudget,
    Measurement,
    SlaBreach,
    SlaMetric,
    SlaObjective,
    SlaStats,
    SlaStatus,
)


class SlaEngine:
    """Runtime SLA enforcement with error budgets and automatic degradation.

    Tracks service level objectives, detects breaches, manages error budgets,
    and triggers graceful degradation when objectives are at risk.
    """

    def __init__(self, budget_window_seconds: int = 3600) -> None:
        self._budget_window = budget_window_seconds
        self._objectives: dict[str, SlaObjective] = {}
        self._measurements: dict[str, list[Measurement]] = defaultdict(list)
        self._breaches: list[SlaBreach] = []
        self._degradation_map: dict[SlaMetric, DegradationAction] = {
            SlaMetric.LATENCY_P99: DegradationAction.SHED_LOAD,
            SlaMetric.ERROR_RATE: DegradationAction.CIRCUIT_BREAK,
            SlaMetric.THROUGHPUT: DegradationAction.REDUCE_QUALITY,
            SlaMetric.AVAILABILITY: DegradationAction.FALLBACK,
        }

    def define_objective(self, metric: SlaMetric, target: float,
                         warning_threshold: float | None = None,
                         window_seconds: int = 300,
                         description: str = "") -> SlaObjective:
        if warning_threshold is None:
            if metric in (SlaMetric.ERROR_RATE,):
                warning_threshold = target * 0.8
            else:
                warning_threshold = target * 1.2

        obj = SlaObjective(
            metric=metric, target=target,
            warning_threshold=warning_threshold,
            window_seconds=window_seconds,
            description=description,
        )
        self._objectives[obj.objective_id] = obj
        return obj

    def record_measurement(self, objective_id: str, value: float) -> Measurement | None:
        obj = self._objectives.get(objective_id)
        if not obj:
            return None

        m = Measurement(objective_id=objective_id, value=value)
        self._measurements[objective_id].append(m)

        if self._is_breach(obj, value):
            severity = self._compute_severity(obj, value)
            action = self._degradation_map.get(obj.metric, DegradationAction.NONE)
            breach = SlaBreach(
                objective_id=objective_id,
                metric=obj.metric,
                target=obj.target,
                actual=value,
                severity=severity,
                action_taken=action,
            )
            self._breaches.append(breach)

        return m

    def get_status(self, objective_id: str) -> SlaStatus:
        obj = self._objectives.get(objective_id)
        if not obj:
            return SlaStatus.UNKNOWN

        measurements = self._measurements.get(objective_id, [])
        if not measurements:
            return SlaStatus.UNKNOWN

        recent = measurements[-10:]
        avg = sum(m.value for m in recent) / len(recent)

        if self._is_breach(obj, avg):
            return SlaStatus.BREACHED
        elif self._is_warning(obj, avg):
            return SlaStatus.WARNING
        return SlaStatus.HEALTHY

    def get_error_budget(self, objective_id: str) -> ErrorBudget | None:
        obj = self._objectives.get(objective_id)
        if not obj:
            return None

        measurements = self._measurements.get(objective_id, [])
        if not measurements:
            return ErrorBudget(
                objective_id=objective_id,
                total_budget=1.0,
                consumed=0.0,
                remaining=1.0,
                burn_rate=0.0,
            )

        total = len(measurements)
        violations = sum(1 for m in measurements if self._is_breach(obj, m.value))
        consumed = violations / total if total > 0 else 0.0
        remaining = max(0.0, 1.0 - consumed)

        recent = measurements[-20:]
        recent_violations = sum(1 for m in recent if self._is_breach(obj, m.value))
        burn_rate = recent_violations / len(recent) if recent else 0.0

        return ErrorBudget(
            objective_id=objective_id,
            total_budget=1.0,
            consumed=consumed,
            remaining=remaining,
            burn_rate=burn_rate,
        )

    def get_breaches(self, objective_id: str | None = None) -> list[SlaBreach]:
        if objective_id:
            return [b for b in self._breaches if b.objective_id == objective_id]
        return list(self._breaches)

    def get_degradation_action(self, objective_id: str) -> DegradationAction:
        obj = self._objectives.get(objective_id)
        if not obj:
            return DegradationAction.NONE

        status = self.get_status(objective_id)
        if status == SlaStatus.BREACHED:
            return self._degradation_map.get(obj.metric, DegradationAction.NONE)
        return DegradationAction.NONE

    def set_degradation_policy(self, metric: SlaMetric, action: DegradationAction) -> None:
        self._degradation_map[metric] = action

    def get_stats(self) -> SlaStats:
        healthy = 0
        warning = 0
        breached = 0
        by_metric: dict[str, str] = {}

        for oid, obj in self._objectives.items():
            status = self.get_status(oid)
            if status == SlaStatus.HEALTHY:
                healthy += 1
            elif status == SlaStatus.WARNING:
                warning += 1
            elif status == SlaStatus.BREACHED:
                breached += 1
            by_metric[obj.metric.value] = status.value

        budgets = [self.get_error_budget(oid) for oid in self._objectives]
        avg_remaining = (
            sum(b.remaining for b in budgets if b) / len(budgets)
            if budgets else 1.0
        )

        total_measurements = sum(len(ms) for ms in self._measurements.values())

        return SlaStats(
            total_objectives=len(self._objectives),
            healthy=healthy,
            warning=warning,
            breached=breached,
            total_measurements=total_measurements,
            total_breaches=len(self._breaches),
            avg_budget_remaining=avg_remaining,
            by_metric=by_metric,
        )

    def _is_breach(self, obj: SlaObjective, value: float) -> bool:
        if obj.metric in (SlaMetric.ERROR_RATE,):
            return value > obj.target
        elif obj.metric in (SlaMetric.THROUGHPUT, SlaMetric.AVAILABILITY, SlaMetric.QUALITY_SCORE):
            return value < obj.target
        else:
            return value > obj.target

    def _is_warning(self, obj: SlaObjective, value: float) -> bool:
        if obj.metric in (SlaMetric.ERROR_RATE,):
            return value > obj.warning_threshold
        elif obj.metric in (SlaMetric.THROUGHPUT, SlaMetric.AVAILABILITY, SlaMetric.QUALITY_SCORE):
            return value < obj.warning_threshold
        else:
            return value > obj.warning_threshold

    def _compute_severity(self, obj: SlaObjective, value: float) -> float:
        if obj.target == 0:
            return 1.0
        deviation = abs(value - obj.target) / abs(obj.target)
        return min(1.0, deviation)
