"""Tests for predictive failure analysis engine."""

from __future__ import annotations

import pytest

from reins.prediction import (
    FailureCategory,
    FailurePattern,
    FailurePrediction,
    FailureSignal,
    MitigationAction,
    PredictionConfidence,
    PredictiveFailureAnalyzer,
    PredictionStats,
    RiskLevel,
    SignalKind,
)


@pytest.fixture
def analyzer() -> PredictiveFailureAnalyzer:
    pfa = PredictiveFailureAnalyzer()
    pfa.register_pattern(FailurePattern(
        pattern_id="timeout-pattern",
        name="Timeout Cascade",
        category=FailureCategory.TIMEOUT,
        signals=(SignalKind.LATENCY_SPIKE, SignalKind.THRESHOLD_BREACH),
        min_signals_required=2,
        lookback_window_ms=60000.0,
        historical_occurrences=5,
        avg_time_to_failure_ms=10000.0,
    ))
    pfa.register_pattern(FailurePattern(
        pattern_id="resource-pattern",
        name="Resource Exhaustion",
        category=FailureCategory.RESOURCE_EXHAUSTION,
        signals=(SignalKind.RESOURCE_PRESSURE,),
        min_signals_required=1,
        lookback_window_ms=30000.0,
        historical_occurrences=3,
        avg_time_to_failure_ms=5000.0,
    ))
    return pfa


def _signal(kind=SignalKind.LATENCY_SPIKE, value=100.0, threshold=50.0, source="test"):
    return FailureSignal(kind=kind, source=source, value=value, threshold=threshold)


def test_ingest_signal_no_match(analyzer):
    signal = _signal(kind=SignalKind.ERROR_RATE_INCREASE)
    predictions = analyzer.ingest_signal(signal)
    assert len(predictions) == 0


def test_ingest_signal_single_match_insufficient(analyzer):
    signal = _signal(kind=SignalKind.LATENCY_SPIKE)
    predictions = analyzer.ingest_signal(signal)
    assert len(predictions) == 0


def test_ingest_signals_triggers_prediction(analyzer):
    analyzer.ingest_signal(_signal(kind=SignalKind.LATENCY_SPIKE))
    predictions = analyzer.ingest_signal(_signal(kind=SignalKind.THRESHOLD_BREACH))
    assert len(predictions) == 1
    assert predictions[0].category == FailureCategory.TIMEOUT


def test_single_signal_pattern_triggers(analyzer):
    predictions = analyzer.ingest_signal(_signal(kind=SignalKind.RESOURCE_PRESSURE))
    assert len(predictions) == 1
    assert predictions[0].category == FailureCategory.RESOURCE_EXHAUSTION


def test_prediction_has_probability(analyzer):
    analyzer.ingest_signal(_signal(kind=SignalKind.LATENCY_SPIKE))
    predictions = analyzer.ingest_signal(_signal(kind=SignalKind.THRESHOLD_BREACH))
    assert predictions[0].probability > 0


def test_prediction_has_risk_level(analyzer):
    predictions = analyzer.ingest_signal(_signal(kind=SignalKind.RESOURCE_PRESSURE))
    assert predictions[0].risk_level in list(RiskLevel)


def test_prediction_has_confidence(analyzer):
    predictions = analyzer.ingest_signal(_signal(kind=SignalKind.RESOURCE_PRESSURE))
    assert predictions[0].confidence in list(PredictionConfidence)


def test_prediction_has_recommended_actions(analyzer):
    predictions = analyzer.ingest_signal(_signal(kind=SignalKind.RESOURCE_PRESSURE))
    assert len(predictions[0].recommended_actions) > 0


def test_prediction_has_contributing_signals(analyzer):
    analyzer.ingest_signal(_signal(kind=SignalKind.LATENCY_SPIKE))
    predictions = analyzer.ingest_signal(_signal(kind=SignalKind.THRESHOLD_BREACH))
    assert len(predictions[0].contributing_signals) >= 2


def test_get_active_predictions(analyzer):
    analyzer.ingest_signal(_signal(kind=SignalKind.RESOURCE_PRESSURE))
    active = analyzer.get_active_predictions()
    assert len(active) == 1


def test_get_active_predictions_min_probability(analyzer):
    analyzer.ingest_signal(_signal(kind=SignalKind.RESOURCE_PRESSURE))
    active = analyzer.get_active_predictions(min_probability=0.99)
    assert len(active) == 0


def test_add_mitigation(analyzer):
    predictions = analyzer.ingest_signal(_signal(kind=SignalKind.RESOURCE_PRESSURE))
    action = analyzer.add_mitigation(predictions[0].prediction_id, "Scale up resources")
    assert action.description == "Scale up resources"
    assert not action.executed


def test_execute_mitigation(analyzer):
    predictions = analyzer.ingest_signal(_signal(kind=SignalKind.RESOURCE_PRESSURE))
    action = analyzer.add_mitigation(predictions[0].prediction_id, "Scale up")
    executed = analyzer.execute_mitigation(action.action_id, success=True)
    assert executed is not None
    assert executed.executed
    assert executed.success
    assert executed.executed_at is not None


def test_execute_mitigation_nonexistent(analyzer):
    assert analyzer.execute_mitigation("nonexistent") is None


def test_record_actual_failure(analyzer):
    analyzer.ingest_signal(_signal(kind=SignalKind.RESOURCE_PRESSURE))
    analyzer.record_actual_failure(FailureCategory.RESOURCE_EXHAUSTION)
    stats = analyzer.get_stats()
    assert stats.true_positives >= 1


def test_stats_empty():
    pfa = PredictiveFailureAnalyzer()
    stats = pfa.get_stats()
    assert stats.total_predictions == 0


def test_stats_with_predictions(analyzer):
    analyzer.ingest_signal(_signal(kind=SignalKind.RESOURCE_PRESSURE))
    analyzer.ingest_signal(_signal(kind=SignalKind.LATENCY_SPIKE))
    analyzer.ingest_signal(_signal(kind=SignalKind.THRESHOLD_BREACH))

    stats = analyzer.get_stats()
    assert stats.total_predictions >= 1
    assert stats.by_category


def test_stats_precision_and_recall(analyzer):
    analyzer.ingest_signal(_signal(kind=SignalKind.RESOURCE_PRESSURE))
    analyzer.record_actual_failure(FailureCategory.RESOURCE_EXHAUSTION)

    stats = analyzer.get_stats()
    assert stats.precision > 0
    assert stats.recall > 0


def test_missed_failure_counted(analyzer):
    analyzer.record_actual_failure(FailureCategory.LOGIC_ERROR)
    stats = analyzer.get_stats()
    assert stats.missed_failures == 1


def test_threshold_breach_increases_probability(analyzer):
    analyzer.ingest_signal(_signal(kind=SignalKind.LATENCY_SPIKE, value=10.0, threshold=50.0))
    predictions_low = analyzer.ingest_signal(_signal(kind=SignalKind.THRESHOLD_BREACH, value=10.0, threshold=50.0))

    analyzer2 = PredictiveFailureAnalyzer()
    analyzer2.register_pattern(FailurePattern(
        pattern_id="timeout-pattern",
        name="Timeout Cascade",
        category=FailureCategory.TIMEOUT,
        signals=(SignalKind.LATENCY_SPIKE, SignalKind.THRESHOLD_BREACH),
        min_signals_required=2,
        lookback_window_ms=60000.0,
        historical_occurrences=5,
        avg_time_to_failure_ms=10000.0,
    ))
    analyzer2.ingest_signal(_signal(kind=SignalKind.LATENCY_SPIKE, value=100.0, threshold=50.0))
    predictions_high = analyzer2.ingest_signal(_signal(kind=SignalKind.THRESHOLD_BREACH, value=100.0, threshold=50.0))

    assert predictions_high[0].probability >= predictions_low[0].probability


def test_high_historical_occurrences_increase_probability():
    pfa = PredictiveFailureAnalyzer()
    pfa.register_pattern(FailurePattern(
        pattern_id="p1",
        name="Frequent",
        category=FailureCategory.TIMEOUT,
        signals=(SignalKind.LATENCY_SPIKE,),
        min_signals_required=1,
        historical_occurrences=20,
        avg_time_to_failure_ms=5000.0,
    ))
    predictions = pfa.ingest_signal(_signal(kind=SignalKind.LATENCY_SPIKE))
    assert predictions[0].probability > 0.5


def test_cascading_failure_high_risk():
    pfa = PredictiveFailureAnalyzer()
    pfa.register_pattern(FailurePattern(
        pattern_id="cascade",
        name="Cascade",
        category=FailureCategory.CASCADING,
        signals=(SignalKind.ERROR_RATE_INCREASE,),
        min_signals_required=1,
        historical_occurrences=10,
        avg_time_to_failure_ms=3000.0,
    ))
    predictions = pfa.ingest_signal(_signal(kind=SignalKind.ERROR_RATE_INCREASE))
    assert predictions[0].risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)


def test_estimated_time_to_failure(analyzer):
    predictions = analyzer.ingest_signal(_signal(kind=SignalKind.RESOURCE_PRESSURE))
    assert predictions[0].estimated_time_to_failure_ms == 5000.0


def test_avg_lead_time_in_stats(analyzer):
    analyzer.ingest_signal(_signal(kind=SignalKind.RESOURCE_PRESSURE))
    stats = analyzer.get_stats()
    assert stats.avg_lead_time_ms > 0
