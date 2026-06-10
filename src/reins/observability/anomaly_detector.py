from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from reins.observability.anomaly_types import (
    Anomaly,
    AnomalyKind,
    AnomalyReport,
    BaselineStats,
    DetectorConfig,
    MetricPoint,
    Severity,
)


class AnomalyDetector:
    """Detects anomalies in agent telemetry using statistical methods.

    Maintains rolling baselines per metric and flags deviations beyond
    configured thresholds. Supports latency spikes, error rate changes,
    throughput drops, cost anomalies, and behavioral drift.
    """

    def __init__(self, config: DetectorConfig | None = None) -> None:
        self._config = config or DetectorConfig()
        self._metrics: dict[str, list[MetricPoint]] = defaultdict(list)
        self._baselines: dict[str, BaselineStats] = {}
        self._anomalies: list[Anomaly] = []

    @property
    def config(self) -> DetectorConfig:
        return self._config

    def ingest(self, metric_name: str, value: float, labels: dict[str, str] | None = None) -> Anomaly | None:
        point = MetricPoint(value=value, labels=labels or {})
        self._metrics[metric_name].append(point)

        if len(self._metrics[metric_name]) > self._config.window_size * 2:
            self._metrics[metric_name] = self._metrics[metric_name][-self._config.window_size * 2:]

        if len(self._metrics[metric_name]) < self._config.min_samples:
            return None

        self._recompute_baseline_excluding_last(metric_name)
        anomaly = self._check_anomaly(metric_name, point)
        self._recompute_baseline(metric_name)
        return anomaly

    def ingest_batch(self, metric_name: str, values: list[float]) -> list[Anomaly]:
        anomalies = []
        for v in values:
            a = self.ingest(metric_name, v)
            if a:
                anomalies.append(a)
        return anomalies

    def check_error_rate(self, total: int, errors: int, agent_id: str | None = None) -> Anomaly | None:
        if total == 0:
            return None
        rate = errors / total
        if rate > self._config.error_rate_threshold:
            severity = Severity.CRITICAL if rate >= 0.5 else Severity.WARNING
            anomaly = Anomaly(
                kind=AnomalyKind.ERROR_RATE_SPIKE,
                severity=severity,
                metric_name="error_rate",
                observed_value=rate,
                expected_range=(0.0, self._config.error_rate_threshold),
                deviation_sigma=(rate - self._config.error_rate_threshold) / max(0.01, self._config.error_rate_threshold),
                agent_id=agent_id,
                description=f"Error rate {rate:.1%} exceeds threshold {self._config.error_rate_threshold:.1%}",
            )
            self._anomalies.append(anomaly)
            return anomaly
        return None

    def check_throughput(self, current_rps: float, baseline_rps: float, agent_id: str | None = None) -> Anomaly | None:
        if baseline_rps <= 0:
            return None
        ratio = current_rps / baseline_rps
        if ratio < self._config.throughput_drop_pct:
            anomaly = Anomaly(
                kind=AnomalyKind.THROUGHPUT_DROP,
                severity=Severity.WARNING,
                metric_name="throughput_rps",
                observed_value=current_rps,
                expected_range=(baseline_rps * self._config.throughput_drop_pct, baseline_rps * 1.5),
                agent_id=agent_id,
                description=f"Throughput dropped to {ratio:.0%} of baseline ({current_rps:.1f} vs {baseline_rps:.1f} rps)",
            )
            self._anomalies.append(anomaly)
            return anomaly
        return None

    def check_behavioral_drift(
        self,
        current_distribution: dict[str, float],
        baseline_distribution: dict[str, float],
        agent_id: str | None = None,
    ) -> Anomaly | None:
        divergence = _kl_divergence(baseline_distribution, current_distribution)
        if divergence > self._config.drift_threshold:
            anomaly = Anomaly(
                kind=AnomalyKind.BEHAVIORAL_DRIFT,
                severity=Severity.WARNING if divergence < 1.0 else Severity.CRITICAL,
                metric_name="behavioral_distribution",
                observed_value=divergence,
                expected_range=(0.0, self._config.drift_threshold),
                deviation_sigma=divergence / self._config.drift_threshold,
                agent_id=agent_id,
                description=f"Behavioral drift detected (KL divergence: {divergence:.3f})",
                context={"current": current_distribution, "baseline": baseline_distribution},
            )
            self._anomalies.append(anomaly)
            return anomaly
        return None

    def get_baseline(self, metric_name: str) -> BaselineStats | None:
        return self._baselines.get(metric_name)

    def get_report(self, window_hours: int = 1) -> AnomalyReport:
        cutoff = datetime.now(UTC) - timedelta(hours=window_hours)
        recent = [a for a in self._anomalies if a.detected_at >= cutoff]

        total_points = sum(len(pts) for pts in self._metrics.values())

        return AnomalyReport(
            anomalies=tuple(recent),
            baselines=tuple(self._baselines.values()),
            total_points_analyzed=total_points,
            has_critical=any(a.severity == Severity.CRITICAL for a in recent),
        )

    def reset(self) -> None:
        self._metrics.clear()
        self._baselines.clear()
        self._anomalies.clear()

    def _recompute_baseline(self, metric_name: str) -> None:
        points = self._metrics[metric_name]
        self._compute_baseline_from(metric_name, points[-self._config.window_size:])

    def _recompute_baseline_excluding_last(self, metric_name: str) -> None:
        points = self._metrics[metric_name]
        window = points[-(self._config.window_size + 1):-1]
        if len(window) < self._config.min_samples:
            return
        self._compute_baseline_from(metric_name, window)

    def _compute_baseline_from(self, metric_name: str, window: list[MetricPoint]) -> None:
        values = sorted(p.value for p in window)
        n = len(values)

        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n
        std_dev = math.sqrt(variance)

        self._baselines[metric_name] = BaselineStats(
            metric_name=metric_name,
            mean=mean,
            std_dev=std_dev,
            min_val=values[0],
            max_val=values[-1],
            p50=values[n // 2],
            p95=values[int(n * 0.95)],
            p99=values[min(int(n * 0.99), n - 1)],
            sample_count=n,
        )

    def _check_anomaly(self, metric_name: str, point: MetricPoint) -> Anomaly | None:
        baseline = self._baselines.get(metric_name)
        if not baseline:
            return None

        if baseline.std_dev == 0:
            if point.value == baseline.mean:
                return None
            sigma = float("inf")
        else:
            sigma = abs(point.value - baseline.mean) / baseline.std_dev
            if sigma < self._config.sigma_threshold:
                return None

        if point.value > baseline.mean:
            kind = self._classify_high_anomaly(metric_name)
        else:
            kind = AnomalyKind.THROUGHPUT_DROP

        severity = Severity.CRITICAL if sigma > self._config.sigma_threshold * 2 else Severity.WARNING

        anomaly = Anomaly(
            kind=kind,
            severity=severity,
            metric_name=metric_name,
            observed_value=point.value,
            expected_range=(baseline.mean - baseline.std_dev * 2, baseline.mean + baseline.std_dev * 2),
            deviation_sigma=sigma,
            description=f"{metric_name} at {point.value:.2f} is {sigma:.1f}σ from mean {baseline.mean:.2f}",
        )
        self._anomalies.append(anomaly)
        return anomaly

    def _classify_high_anomaly(self, metric_name: str) -> AnomalyKind:
        name_lower = metric_name.lower()
        if "latency" in name_lower or "duration" in name_lower:
            return AnomalyKind.LATENCY_SPIKE
        if "cost" in name_lower or "spend" in name_lower:
            return AnomalyKind.COST_ANOMALY
        if "token" in name_lower:
            return AnomalyKind.TOKEN_EXPLOSION
        if "retry" in name_lower:
            return AnomalyKind.RETRY_STORM
        return AnomalyKind.LATENCY_SPIKE


def _kl_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    all_keys = set(p.keys()) | set(q.keys())
    epsilon = 1e-10
    divergence = 0.0
    for key in all_keys:
        p_val = p.get(key, epsilon)
        q_val = q.get(key, epsilon)
        if p_val > 0:
            divergence += p_val * math.log(p_val / q_val)
    return max(0.0, divergence)
