"""Tests for anomaly detection in agent telemetry."""

from __future__ import annotations

import pytest

from reins.observability.anomaly_detector import AnomalyDetector, _kl_divergence
from reins.observability.anomaly_types import (
    AnomalyKind,
    DetectorConfig,
    Severity,
)


@pytest.fixture
def detector() -> AnomalyDetector:
    return AnomalyDetector(DetectorConfig(min_samples=10, window_size=50))


def test_no_anomaly_below_min_samples(detector):
    for i in range(5):
        result = detector.ingest("latency_ms", 100.0)
    assert result is None


def test_no_anomaly_within_normal_range(detector):
    for _ in range(20):
        result = detector.ingest("latency_ms", 100.0)
    assert result is None


def test_latency_spike_detected(detector):
    for _ in range(20):
        detector.ingest("latency_ms", 100.0)
    anomaly = detector.ingest("latency_ms", 10000.0)
    assert anomaly is not None
    assert anomaly.kind == AnomalyKind.LATENCY_SPIKE
    assert anomaly.severity in (Severity.WARNING, Severity.CRITICAL)
    assert anomaly.observed_value == 10000.0


def test_cost_anomaly_classified(detector):
    for _ in range(20):
        detector.ingest("cost_per_request", 0.01)
    anomaly = detector.ingest("cost_per_request", 5.0)
    assert anomaly is not None
    assert anomaly.kind == AnomalyKind.COST_ANOMALY


def test_token_explosion_classified(detector):
    for _ in range(20):
        detector.ingest("token_count", 500.0)
    anomaly = detector.ingest("token_count", 50000.0)
    assert anomaly is not None
    assert anomaly.kind == AnomalyKind.TOKEN_EXPLOSION


def test_error_rate_spike(detector):
    anomaly = detector.check_error_rate(100, 50, agent_id="agent-1")
    assert anomaly is not None
    assert anomaly.kind == AnomalyKind.ERROR_RATE_SPIKE
    assert anomaly.severity == Severity.CRITICAL
    assert anomaly.agent_id == "agent-1"


def test_error_rate_below_threshold(detector):
    anomaly = detector.check_error_rate(100, 5)
    assert anomaly is None


def test_error_rate_zero_total(detector):
    anomaly = detector.check_error_rate(0, 0)
    assert anomaly is None


def test_throughput_drop(detector):
    anomaly = detector.check_throughput(current_rps=2.0, baseline_rps=10.0, agent_id="agent-2")
    assert anomaly is not None
    assert anomaly.kind == AnomalyKind.THROUGHPUT_DROP
    assert anomaly.agent_id == "agent-2"


def test_throughput_normal(detector):
    anomaly = detector.check_throughput(current_rps=8.0, baseline_rps=10.0)
    assert anomaly is None


def test_throughput_zero_baseline(detector):
    anomaly = detector.check_throughput(current_rps=5.0, baseline_rps=0.0)
    assert anomaly is None


def test_behavioral_drift_detected(detector):
    baseline = {"code_gen": 0.4, "review": 0.3, "planning": 0.3}
    current = {"code_gen": 0.9, "review": 0.05, "planning": 0.05}
    anomaly = detector.check_behavioral_drift(current, baseline, agent_id="agent-3")
    assert anomaly is not None
    assert anomaly.kind == AnomalyKind.BEHAVIORAL_DRIFT
    assert anomaly.context["current"] == current


def test_behavioral_drift_within_threshold(detector):
    baseline = {"code_gen": 0.4, "review": 0.3, "planning": 0.3}
    current = {"code_gen": 0.42, "review": 0.29, "planning": 0.29}
    anomaly = detector.check_behavioral_drift(current, baseline)
    assert anomaly is None


def test_baseline_computed(detector):
    for i in range(20):
        detector.ingest("ops", float(i))
    baseline = detector.get_baseline("ops")
    assert baseline is not None
    assert baseline.sample_count == 20
    assert baseline.mean == pytest.approx(9.5)
    assert baseline.min_val == 0.0
    assert baseline.max_val == 19.0


def test_report_aggregates_anomalies(detector):
    for _ in range(20):
        detector.ingest("latency_ms", 100.0)
    detector.ingest("latency_ms", 10000.0)
    detector.check_error_rate(10, 8)

    report = detector.get_report()
    assert len(report.anomalies) == 2
    assert report.has_critical


def test_report_empty_when_no_anomalies(detector):
    report = detector.get_report()
    assert len(report.anomalies) == 0
    assert not report.has_critical


def test_ingest_batch(detector):
    normal = [100.0] * 20
    spikes = [100.0] * 5 + [10000.0]
    anomalies = detector.ingest_batch("latency_ms", normal + spikes)
    assert len(anomalies) >= 1


def test_reset_clears_state(detector):
    for _ in range(20):
        detector.ingest("x", 1.0)
    detector.reset()
    assert detector.get_baseline("x") is None
    assert len(detector.get_report().anomalies) == 0


def test_kl_divergence_identical():
    p = {"a": 0.5, "b": 0.5}
    assert _kl_divergence(p, p) == pytest.approx(0.0, abs=1e-9)


def test_kl_divergence_different():
    p = {"a": 0.9, "b": 0.1}
    q = {"a": 0.1, "b": 0.9}
    assert _kl_divergence(p, q) > 0.5


def test_window_size_trims_old_data():
    det = AnomalyDetector(DetectorConfig(min_samples=5, window_size=10))
    for _ in range(100):
        det.ingest("m", 1.0)
    baseline = det.get_baseline("m")
    assert baseline.sample_count == 10


def test_severity_critical_for_extreme_deviation(detector):
    for _ in range(20):
        detector.ingest("latency_ms", 100.0)
    anomaly = detector.ingest("latency_ms", 100000.0)
    assert anomaly is not None
    assert anomaly.severity == Severity.CRITICAL
