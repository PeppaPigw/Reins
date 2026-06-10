"""Tests for semantic drift detection engine."""

from __future__ import annotations

import pytest

from reins.drift import (
    Baseline,
    BehaviorSample,
    BehaviorVersion,
    DriftAlert,
    DriftDirection,
    DriftKind,
    DriftReport,
    DriftSeverity,
    DriftStats,
    SemanticDriftDetector,
)


@pytest.fixture
def detector() -> SemanticDriftDetector:
    return SemanticDriftDetector(sigma_threshold=2.0, min_samples=5)


def _sample(agent_id="agent-1", dimension=DriftKind.QUALITY, value=0.8):
    return BehaviorSample(agent_id=agent_id, dimension=dimension, value=value)


def test_record_sample_no_baseline(detector):
    alert = detector.record_sample(_sample(value=0.8))
    assert alert is None


def test_baseline_established_after_min_samples(detector):
    for i in range(5):
        detector.record_sample(_sample(value=0.8))
    baseline = detector.get_baseline("agent-1", DriftKind.QUALITY)
    assert baseline is not None
    assert baseline.mean == pytest.approx(0.8)


def test_no_alert_within_threshold(detector):
    for i in range(5):
        detector.record_sample(_sample(value=0.8))
    alert = detector.record_sample(_sample(value=0.81))
    assert alert is None


def test_alert_on_significant_drift(detector):
    for i in range(5):
        detector.record_sample(_sample(value=0.8))
    alert = detector.record_sample(_sample(value=0.2))
    assert alert is not None
    assert alert.severity != DriftSeverity.NONE
    assert alert.direction == DriftDirection.DEGRADING


def test_improving_drift_detected(detector):
    for i in range(5):
        detector.record_sample(_sample(value=0.5))
    alert = detector.record_sample(_sample(value=0.95))
    assert alert is not None
    assert alert.direction == DriftDirection.IMPROVING


def test_latency_increase_is_degrading(detector):
    for i in range(5):
        detector.record_sample(_sample(dimension=DriftKind.LATENCY, value=100.0))
    alert = detector.record_sample(_sample(dimension=DriftKind.LATENCY, value=500.0))
    assert alert is not None
    assert alert.direction == DriftDirection.DEGRADING


def test_latency_decrease_is_improving(detector):
    for i in range(5):
        detector.record_sample(_sample(dimension=DriftKind.LATENCY, value=100.0))
    alert = detector.record_sample(_sample(dimension=DriftKind.LATENCY, value=10.0))
    assert alert is not None
    assert alert.direction == DriftDirection.IMPROVING


def test_severity_classification(detector):
    for i in range(5):
        detector.record_sample(_sample(value=0.8))
    alert = detector.record_sample(_sample(value=0.0))
    assert alert is not None
    assert alert.severity in (DriftSeverity.MAJOR, DriftSeverity.CRITICAL)


def test_establish_baseline_explicit(detector):
    for i in range(5):
        detector.record_sample(_sample(value=0.7 + i * 0.01))
    baseline = detector.establish_baseline("agent-1", DriftKind.QUALITY, version="v1")
    assert baseline is not None
    assert baseline.version == "v1"


def test_establish_baseline_insufficient_samples(detector):
    detector.record_sample(_sample(value=0.8))
    baseline = detector.establish_baseline("agent-1", DriftKind.QUALITY)
    assert baseline is None


def test_create_version(detector):
    for i in range(5):
        detector.record_sample(_sample(value=0.8))
    version = detector.create_version("agent-1", "v1.0")
    assert version.version == "v1.0"
    assert version.sample_count == 5
    assert len(version.baselines) == 1


def test_generate_report_stable(detector):
    for i in range(5):
        detector.record_sample(_sample(value=0.8))
    report = detector.generate_report("agent-1")
    assert report.overall_direction == DriftDirection.STABLE
    assert report.dimensions_drifting == 0


def test_generate_report_degrading(detector):
    for i in range(5):
        detector.record_sample(_sample(value=0.8))
    for i in range(3):
        detector.record_sample(_sample(value=0.1))
    report = detector.generate_report("agent-1")
    assert report.overall_direction == DriftDirection.DEGRADING
    assert report.dimensions_drifting >= 1


def test_get_alerts_by_agent(detector):
    for i in range(5):
        detector.record_sample(_sample(agent_id="a", value=0.8))
    detector.record_sample(_sample(agent_id="a", value=0.1))

    alerts = detector.get_alerts(agent_id="a")
    assert len(alerts) >= 1
    alerts_b = detector.get_alerts(agent_id="b")
    assert len(alerts_b) == 0


def test_get_alerts_by_dimension(detector):
    for i in range(5):
        detector.record_sample(_sample(dimension=DriftKind.QUALITY, value=0.8))
    detector.record_sample(_sample(dimension=DriftKind.QUALITY, value=0.1))

    alerts = detector.get_alerts(dimension=DriftKind.QUALITY)
    assert len(alerts) >= 1
    alerts_lat = detector.get_alerts(dimension=DriftKind.LATENCY)
    assert len(alerts_lat) == 0


def test_get_alerts_by_severity(detector):
    for i in range(5):
        detector.record_sample(_sample(value=0.8))
    detector.record_sample(_sample(value=0.0))

    all_alerts = detector.get_alerts()
    assert len(all_alerts) >= 1
    minor_alerts = detector.get_alerts(severity=DriftSeverity.MINOR)
    critical_alerts = detector.get_alerts(severity=DriftSeverity.CRITICAL)
    assert len(minor_alerts) + len(critical_alerts) <= len(all_alerts)


def test_reset_baseline(detector):
    for i in range(5):
        detector.record_sample(_sample(value=0.8))
    assert detector.get_baseline("agent-1", DriftKind.QUALITY) is not None

    assert detector.reset_baseline("agent-1", DriftKind.QUALITY)
    assert detector.get_baseline("agent-1", DriftKind.QUALITY) is None


def test_reset_baseline_nonexistent(detector):
    assert not detector.reset_baseline("agent-1", DriftKind.QUALITY)


def test_zero_variance_baseline(detector):
    for i in range(5):
        detector.record_sample(_sample(value=0.8))
    alert = detector.record_sample(_sample(value=0.9))
    assert alert is not None


def test_multiple_dimensions_independent(detector):
    for i in range(5):
        detector.record_sample(_sample(dimension=DriftKind.QUALITY, value=0.8))
        detector.record_sample(_sample(dimension=DriftKind.SAFETY, value=0.9))

    alert_q = detector.record_sample(_sample(dimension=DriftKind.QUALITY, value=0.1))
    alert_s = detector.record_sample(_sample(dimension=DriftKind.SAFETY, value=0.89))

    assert alert_q is not None
    assert alert_s is None


def test_stats_empty():
    det = SemanticDriftDetector()
    stats = det.get_stats()
    assert stats.total_samples == 0
    assert stats.total_alerts == 0


def test_stats_with_data(detector):
    for i in range(5):
        detector.record_sample(_sample(value=0.8))
    detector.record_sample(_sample(value=0.1))

    stats = detector.get_stats()
    assert stats.total_samples == 6
    assert stats.total_alerts >= 1
    assert stats.agents_monitored == 1
    assert DriftKind.QUALITY.value in stats.by_dimension


def test_deviation_sigma_in_alert(detector):
    for i in range(5):
        detector.record_sample(_sample(value=0.8))
    alert = detector.record_sample(_sample(value=0.1))
    assert alert.deviation_sigma >= 2.0
    assert alert.baseline_mean == pytest.approx(0.8)
    assert alert.current_value == pytest.approx(0.1)
