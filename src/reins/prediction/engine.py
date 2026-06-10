from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from reins.prediction.types import (
    FailureCategory,
    FailurePattern,
    FailurePrediction,
    FailureSignal,
    MitigationAction,
    PredictionConfidence,
    PredictionStats,
    RiskLevel,
    SignalKind,
)


class PredictiveFailureAnalyzer:
    """Detects failure patterns and predicts upcoming failures before they happen.

    Monitors signals (latency spikes, error rates, resource pressure), matches
    them against known failure patterns, and produces predictions with confidence
    levels and recommended mitigations.
    """

    def __init__(self) -> None:
        self._patterns: dict[str, FailurePattern] = {}
        self._signals: list[FailureSignal] = []
        self._predictions: list[FailurePrediction] = []
        self._mitigations: list[MitigationAction] = []
        self._actual_failures: list[tuple[FailureCategory, datetime]] = []

    def register_pattern(self, pattern: FailurePattern) -> None:
        self._patterns[pattern.pattern_id] = pattern

    def ingest_signal(self, signal: FailureSignal) -> list[FailurePrediction]:
        self._signals.append(signal)
        return self._evaluate_patterns(signal)

    def record_actual_failure(self, category: FailureCategory) -> None:
        self._actual_failures.append((category, datetime.now(UTC)))

    def get_active_predictions(self, min_probability: float = 0.0) -> list[FailurePrediction]:
        now = datetime.now(UTC)
        active = []
        for pred in self._predictions:
            age_ms = (now - pred.predicted_at).total_seconds() * 1000
            if age_ms < pred.estimated_time_to_failure_ms * 2:
                if pred.probability >= min_probability:
                    active.append(pred)
        return active

    def add_mitigation(self, prediction_id: str, description: str,
                       automated: bool = False) -> MitigationAction:
        action = MitigationAction(
            prediction_id=prediction_id,
            description=description,
            automated=automated,
        )
        self._mitigations.append(action)
        return action

    def execute_mitigation(self, action_id: str, success: bool = True) -> MitigationAction | None:
        for i, action in enumerate(self._mitigations):
            if action.action_id == action_id:
                updated = MitigationAction(
                    action_id=action.action_id,
                    prediction_id=action.prediction_id,
                    description=action.description,
                    automated=action.automated,
                    executed=True,
                    success=success,
                    executed_at=datetime.now(UTC),
                )
                self._mitigations[i] = updated
                return updated
        return None

    def get_stats(self) -> PredictionStats:
        if not self._predictions:
            return PredictionStats(missed_failures=self._count_missed_failures())

        total = len(self._predictions)
        tp = self._count_true_positives()
        fp = total - tp
        missed = self._count_missed_failures()

        precision = tp / total if total else 0.0
        recall = tp / (tp + missed) if (tp + missed) else 0.0

        lead_times = [p.estimated_time_to_failure_ms for p in self._predictions]
        avg_lead = sum(lead_times) / len(lead_times) if lead_times else 0.0

        by_category: dict[str, int] = defaultdict(int)
        for p in self._predictions:
            by_category[p.category.value] += 1

        return PredictionStats(
            total_predictions=total,
            true_positives=tp,
            false_positives=fp,
            missed_failures=missed,
            precision=precision,
            recall=recall,
            avg_lead_time_ms=avg_lead,
            by_category=dict(by_category),
        )

    def _evaluate_patterns(self, trigger_signal: FailureSignal) -> list[FailurePrediction]:
        new_predictions: list[FailurePrediction] = []
        now = datetime.now(UTC)

        for pattern in self._patterns.values():
            if trigger_signal.kind not in pattern.signals:
                continue

            window_start = now - timedelta(milliseconds=pattern.lookback_window_ms)
            recent_signals = [
                s for s in self._signals
                if s.observed_at >= window_start and s.kind in pattern.signals
            ]

            matched_kinds = {s.kind for s in recent_signals}
            if len(matched_kinds) >= pattern.min_signals_required:
                probability = self._compute_probability(recent_signals, pattern)
                risk = self._assess_risk(probability, pattern.category)
                confidence = self._assess_confidence(len(recent_signals), pattern)

                prediction = FailurePrediction(
                    pattern_id=pattern.pattern_id,
                    category=pattern.category,
                    risk_level=risk,
                    confidence=confidence,
                    probability=probability,
                    estimated_time_to_failure_ms=pattern.avg_time_to_failure_ms,
                    contributing_signals=tuple(recent_signals[-5:]),
                    recommended_actions=self._suggest_actions(pattern.category),
                )
                new_predictions.append(prediction)
                self._predictions.append(prediction)

        return new_predictions

    def _compute_probability(self, signals: list[FailureSignal], pattern: FailurePattern) -> float:
        if not signals:
            return 0.0

        signal_density = len(signals) / max(1, pattern.min_signals_required)
        threshold_breaches = sum(
            1 for s in signals if s.threshold > 0 and s.value > s.threshold
        )
        breach_ratio = threshold_breaches / len(signals) if signals else 0.0

        historical_factor = min(1.0, pattern.historical_occurrences / 10.0)

        probability = (
            signal_density * 0.3 +
            breach_ratio * 0.4 +
            historical_factor * 0.3
        )
        return min(1.0, probability)

    def _assess_risk(self, probability: float, category: FailureCategory) -> RiskLevel:
        severity_weight = {
            FailureCategory.CASCADING: 1.5,
            FailureCategory.RESOURCE_EXHAUSTION: 1.3,
            FailureCategory.POLICY_VIOLATION: 1.2,
            FailureCategory.CONTEXT_OVERFLOW: 1.1,
            FailureCategory.DEPENDENCY_FAILURE: 1.0,
            FailureCategory.TIMEOUT: 0.8,
            FailureCategory.RATE_LIMIT: 0.7,
            FailureCategory.LOGIC_ERROR: 0.9,
        }
        weighted = probability * severity_weight.get(category, 1.0)

        if weighted >= 0.8:
            return RiskLevel.CRITICAL
        elif weighted >= 0.6:
            return RiskLevel.HIGH
        elif weighted >= 0.3:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _assess_confidence(self, signal_count: int, pattern: FailurePattern) -> PredictionConfidence:
        ratio = signal_count / max(1, pattern.min_signals_required)
        historical = pattern.historical_occurrences

        if ratio >= 3 and historical >= 5:
            return PredictionConfidence.NEAR_CERTAIN
        elif ratio >= 2 and historical >= 3:
            return PredictionConfidence.LIKELY
        elif ratio >= 1 and historical >= 1:
            return PredictionConfidence.PROBABLE
        return PredictionConfidence.SPECULATIVE

    def _suggest_actions(self, category: FailureCategory) -> tuple[str, ...]:
        actions = {
            FailureCategory.TIMEOUT: (
                "Increase timeout thresholds",
                "Add circuit breaker",
                "Check downstream service health",
            ),
            FailureCategory.RESOURCE_EXHAUSTION: (
                "Scale resources",
                "Reduce batch size",
                "Enable garbage collection",
            ),
            FailureCategory.LOGIC_ERROR: (
                "Review recent code changes",
                "Enable verbose logging",
                "Run regression tests",
            ),
            FailureCategory.DEPENDENCY_FAILURE: (
                "Check dependency health",
                "Activate fallback path",
                "Retry with backoff",
            ),
            FailureCategory.RATE_LIMIT: (
                "Reduce request rate",
                "Enable request queuing",
                "Switch to batch API",
            ),
            FailureCategory.CONTEXT_OVERFLOW: (
                "Compress context",
                "Evict low-priority shards",
                "Split into sub-tasks",
            ),
            FailureCategory.POLICY_VIOLATION: (
                "Review policy rules",
                "Request elevated permissions",
                "Route to human approval",
            ),
            FailureCategory.CASCADING: (
                "Isolate affected components",
                "Enable bulkhead pattern",
                "Halt non-critical operations",
            ),
        }
        return actions.get(category, ("Investigate manually",))

    def _count_true_positives(self) -> int:
        tp = 0
        for pred in self._predictions:
            for category, ts in self._actual_failures:
                if category == pred.category:
                    time_diff = (ts - pred.predicted_at).total_seconds() * 1000
                    if 0 <= time_diff <= pred.estimated_time_to_failure_ms * 2:
                        tp += 1
                        break
        return tp

    def _count_missed_failures(self) -> int:
        missed = 0
        for category, ts in self._actual_failures:
            predicted = False
            for pred in self._predictions:
                if pred.category == category:
                    time_diff = (ts - pred.predicted_at).total_seconds() * 1000
                    if 0 <= time_diff <= pred.estimated_time_to_failure_ms * 2:
                        predicted = True
                        break
            if not predicted:
                missed += 1
        return missed
