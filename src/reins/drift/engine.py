from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from reins.drift.types import (
    Baseline,
    BehaviorSample,
    BehaviorVersion,
    DriftAlert,
    DriftDirection,
    DriftKind,
    DriftReport,
    DriftSeverity,
    DriftStats,
)


class SemanticDriftDetector:
    """Tracks behavioral changes in agent outputs over time.

    Detects quality regressions, style drift, and performance degradation
    by comparing current behavior against established baselines using
    statistical deviation analysis.
    """

    def __init__(self, sigma_threshold: float = 2.0, min_samples: int = 5) -> None:
        self._sigma_threshold = sigma_threshold
        self._min_samples = min_samples
        self._samples: dict[str, dict[DriftKind, list[BehaviorSample]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._baselines: dict[str, dict[DriftKind, Baseline]] = defaultdict(dict)
        self._alerts: list[DriftAlert] = []
        self._versions: list[BehaviorVersion] = []

    def record_sample(self, sample: BehaviorSample) -> DriftAlert | None:
        self._samples[sample.agent_id][sample.dimension].append(sample)
        baseline = self._baselines.get(sample.agent_id, {}).get(sample.dimension)

        if not baseline:
            samples = self._samples[sample.agent_id][sample.dimension]
            if len(samples) >= self._min_samples:
                self._establish_baseline(sample.agent_id, sample.dimension)
            return None

        return self._check_drift(sample, baseline)

    def establish_baseline(self, agent_id: str, dimension: DriftKind,
                           version: str = "") -> Baseline | None:
        return self._establish_baseline(agent_id, dimension, version)

    def get_baseline(self, agent_id: str, dimension: DriftKind) -> Baseline | None:
        return self._baselines.get(agent_id, {}).get(dimension)

    def create_version(self, agent_id: str, version: str) -> BehaviorVersion:
        baselines = tuple(self._baselines.get(agent_id, {}).values())
        total_samples = sum(
            len(samples)
            for samples in self._samples.get(agent_id, {}).values()
        )
        bv = BehaviorVersion(
            agent_id=agent_id,
            version=version,
            baselines=baselines,
            sample_count=total_samples,
        )
        self._versions.append(bv)
        return bv

    def generate_report(self, agent_id: str) -> DriftReport:
        agent_alerts = [a for a in self._alerts if a.agent_id == agent_id]
        recent_alerts = agent_alerts[-20:]

        dimensions_drifting = len({a.dimension for a in recent_alerts})
        degrading = sum(1 for a in recent_alerts if a.direction == DriftDirection.DEGRADING)
        improving = sum(1 for a in recent_alerts if a.direction == DriftDirection.IMPROVING)

        if degrading > improving:
            overall = DriftDirection.DEGRADING
        elif improving > degrading:
            overall = DriftDirection.IMPROVING
        else:
            overall = DriftDirection.STABLE

        return DriftReport(
            agent_id=agent_id,
            alerts=tuple(recent_alerts),
            overall_direction=overall,
            dimensions_drifting=dimensions_drifting,
        )

    def get_alerts(self, agent_id: str | None = None,
                   dimension: DriftKind | None = None,
                   severity: DriftSeverity | None = None) -> list[DriftAlert]:
        alerts = self._alerts
        if agent_id:
            alerts = [a for a in alerts if a.agent_id == agent_id]
        if dimension:
            alerts = [a for a in alerts if a.dimension == dimension]
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        return alerts

    def reset_baseline(self, agent_id: str, dimension: DriftKind) -> bool:
        if agent_id in self._baselines and dimension in self._baselines[agent_id]:
            del self._baselines[agent_id][dimension]
            return True
        return False

    def get_stats(self) -> DriftStats:
        total_samples = sum(
            len(s) for agent in self._samples.values() for s in agent.values()
        )
        by_severity: dict[str, int] = defaultdict(int)
        by_dimension: dict[str, int] = defaultdict(int)
        for alert in self._alerts:
            by_severity[alert.severity.value] += 1
            by_dimension[alert.dimension.value] += 1

        return DriftStats(
            total_samples=total_samples,
            total_alerts=len(self._alerts),
            total_versions=len(self._versions),
            agents_monitored=len(self._samples),
            by_severity=dict(by_severity),
            by_dimension=dict(by_dimension),
        )

    def _establish_baseline(self, agent_id: str, dimension: DriftKind,
                            version: str = "") -> Baseline | None:
        samples = self._samples.get(agent_id, {}).get(dimension, [])
        if len(samples) < self._min_samples:
            return None

        values = [s.value for s in samples]
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std_dev = math.sqrt(variance)

        baseline = Baseline(
            agent_id=agent_id,
            dimension=dimension,
            mean=mean,
            std_dev=std_dev,
            sample_count=len(samples),
            version=version,
        )
        self._baselines[agent_id][dimension] = baseline
        return baseline

    def _check_drift(self, sample: BehaviorSample, baseline: Baseline) -> DriftAlert | None:
        if baseline.std_dev == 0:
            min_std = abs(baseline.mean) * 0.05 if baseline.mean != 0 else 0.05
            deviation = abs(sample.value - baseline.mean) / min_std
        else:
            deviation = abs(sample.value - baseline.mean) / baseline.std_dev

        if deviation < self._sigma_threshold:
            return None

        direction = (
            DriftDirection.IMPROVING if sample.value > baseline.mean
            else DriftDirection.DEGRADING
        )

        if sample.dimension in (DriftKind.LATENCY, DriftKind.COST):
            direction = (
                DriftDirection.DEGRADING if sample.value > baseline.mean
                else DriftDirection.IMPROVING
            )

        severity = self._classify_severity(deviation)

        alert = DriftAlert(
            agent_id=sample.agent_id,
            dimension=sample.dimension,
            severity=severity,
            direction=direction,
            deviation_sigma=deviation,
            baseline_mean=baseline.mean,
            current_value=sample.value,
            message=f"{sample.dimension.value} drifted {deviation:.1f}σ from baseline "
                    f"(baseline={baseline.mean:.3f}, current={sample.value:.3f})",
        )
        self._alerts.append(alert)
        return alert

    def _classify_severity(self, deviation: float) -> DriftSeverity:
        if deviation >= 4.0:
            return DriftSeverity.CRITICAL
        elif deviation >= 3.0:
            return DriftSeverity.MAJOR
        elif deviation >= 2.5:
            return DriftSeverity.MODERATE
        elif deviation >= self._sigma_threshold:
            return DriftSeverity.MINOR
        return DriftSeverity.NONE
