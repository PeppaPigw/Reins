from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from reins.experiments.types import (
    AllocationStrategy,
    Experiment,
    ExperimentConclusion,
    ExperimentManagerStats,
    ExperimentStatus,
    SignificanceLevel,
    TrialResult,
    Variant,
    VariantOutcome,
    VariantStats,
)


class ExperimentManager:
    """A/B testing for agent strategies with statistical significance and bandit optimization.

    Supports uniform allocation, epsilon-greedy, Thompson sampling, and UCB
    strategies for traffic allocation across experiment variants.
    """

    def __init__(self, epsilon: float = 0.1) -> None:
        self._epsilon = epsilon
        self._experiments: dict[str, Experiment] = {}
        self._trials: dict[str, list[TrialResult]] = defaultdict(list)
        self._conclusions: dict[str, ExperimentConclusion] = {}

    def create_experiment(self, name: str, variants: list[Variant],
                          allocation: AllocationStrategy = AllocationStrategy.UNIFORM,
                          min_trials: int = 30, max_trials: int = 1000,
                          description: str = "") -> Experiment:
        experiment = Experiment(
            name=name,
            description=description,
            variants=tuple(variants),
            status=ExperimentStatus.RUNNING,
            allocation=allocation,
            min_trials_per_variant=min_trials,
            max_total_trials=max_trials,
        )
        self._experiments[experiment.experiment_id] = experiment
        return experiment

    def get_experiment(self, experiment_id: str) -> Experiment | None:
        return self._experiments.get(experiment_id)

    def allocate_variant(self, experiment_id: str) -> Variant | None:
        experiment = self._experiments.get(experiment_id)
        if not experiment or experiment.status != ExperimentStatus.RUNNING:
            return None
        if not experiment.variants:
            return None

        trials = self._trials.get(experiment_id, [])
        if len(trials) >= experiment.max_total_trials:
            return None

        if experiment.allocation == AllocationStrategy.UNIFORM:
            return self._allocate_uniform(experiment, trials)
        elif experiment.allocation == AllocationStrategy.EPSILON_GREEDY:
            return self._allocate_epsilon_greedy(experiment, trials)
        elif experiment.allocation == AllocationStrategy.THOMPSON_SAMPLING:
            return self._allocate_thompson(experiment, trials)
        elif experiment.allocation == AllocationStrategy.UCB:
            return self._allocate_ucb(experiment, trials)
        return experiment.variants[0]

    def record_trial(self, experiment_id: str, variant_id: str,
                     outcome: VariantOutcome, metric_value: float = 0.0,
                     latency_ms: float = 0.0, metadata: dict[str, Any] | None = None) -> TrialResult | None:
        experiment = self._experiments.get(experiment_id)
        if not experiment or experiment.status != ExperimentStatus.RUNNING:
            return None

        trial = TrialResult(
            experiment_id=experiment_id,
            variant_id=variant_id,
            outcome=outcome,
            metric_value=metric_value,
            latency_ms=latency_ms,
            metadata=metadata or {},
        )
        self._trials[experiment_id].append(trial)
        return trial

    def conclude(self, experiment_id: str) -> ExperimentConclusion | None:
        experiment = self._experiments.get(experiment_id)
        if not experiment or experiment.status != ExperimentStatus.RUNNING:
            return None

        trials = self._trials.get(experiment_id, [])
        variant_stats = self._compute_variant_stats(experiment, trials)

        winner, confidence = self._determine_winner(variant_stats)
        significance = self._classify_significance(confidence)

        recommendation = self._build_recommendation(winner, variant_stats, significance)

        conclusion = ExperimentConclusion(
            experiment_id=experiment_id,
            winner_variant_id=winner.variant_id if winner else None,
            winner_name=winner.variant_name if winner else "",
            confidence=confidence,
            significance=significance,
            variant_stats=tuple(variant_stats),
            recommendation=recommendation,
        )
        self._conclusions[experiment_id] = conclusion

        self._experiments[experiment_id] = Experiment(
            experiment_id=experiment.experiment_id,
            name=experiment.name,
            description=experiment.description,
            variants=experiment.variants,
            status=ExperimentStatus.CONCLUDED,
            allocation=experiment.allocation,
            min_trials_per_variant=experiment.min_trials_per_variant,
            max_total_trials=experiment.max_total_trials,
            created_at=experiment.created_at,
            concluded_at=datetime.now(UTC),
        )
        return conclusion

    def pause(self, experiment_id: str) -> bool:
        experiment = self._experiments.get(experiment_id)
        if not experiment or experiment.status != ExperimentStatus.RUNNING:
            return False
        self._experiments[experiment_id] = Experiment(
            experiment_id=experiment.experiment_id,
            name=experiment.name,
            description=experiment.description,
            variants=experiment.variants,
            status=ExperimentStatus.PAUSED,
            allocation=experiment.allocation,
            min_trials_per_variant=experiment.min_trials_per_variant,
            max_total_trials=experiment.max_total_trials,
            created_at=experiment.created_at,
        )
        return True

    def resume(self, experiment_id: str) -> bool:
        experiment = self._experiments.get(experiment_id)
        if not experiment or experiment.status != ExperimentStatus.PAUSED:
            return False
        self._experiments[experiment_id] = Experiment(
            experiment_id=experiment.experiment_id,
            name=experiment.name,
            description=experiment.description,
            variants=experiment.variants,
            status=ExperimentStatus.RUNNING,
            allocation=experiment.allocation,
            min_trials_per_variant=experiment.min_trials_per_variant,
            max_total_trials=experiment.max_total_trials,
            created_at=experiment.created_at,
        )
        return True

    def get_variant_stats(self, experiment_id: str) -> list[VariantStats]:
        experiment = self._experiments.get(experiment_id)
        if not experiment:
            return []
        trials = self._trials.get(experiment_id, [])
        return self._compute_variant_stats(experiment, trials)

    def get_stats(self) -> ExperimentManagerStats:
        if not self._experiments:
            return ExperimentManagerStats()

        running = sum(1 for e in self._experiments.values() if e.status == ExperimentStatus.RUNNING)
        concluded = sum(1 for e in self._experiments.values() if e.status == ExperimentStatus.CONCLUDED)
        total_trials = sum(len(t) for t in self._trials.values())
        avg_trials = total_trials / len(self._experiments) if self._experiments else 0.0

        return ExperimentManagerStats(
            total_experiments=len(self._experiments),
            running=running,
            concluded=concluded,
            total_trials=total_trials,
            avg_trials_per_experiment=avg_trials,
        )

    def _compute_variant_stats(self, experiment: Experiment,
                               trials: list[TrialResult]) -> list[VariantStats]:
        stats = []
        for variant in experiment.variants:
            variant_trials = [t for t in trials if t.variant_id == variant.variant_id]
            count = len(variant_trials)
            successes = sum(1 for t in variant_trials if t.outcome == VariantOutcome.SUCCESS)
            metrics = [t.metric_value for t in variant_trials]
            latencies = [t.latency_ms for t in variant_trials]

            avg_metric = sum(metrics) / count if count else 0.0
            avg_latency = sum(latencies) / count if count else 0.0
            success_rate = successes / count if count else 0.0

            std_dev = 0.0
            if count > 1:
                variance = sum((m - avg_metric) ** 2 for m in metrics) / (count - 1)
                std_dev = math.sqrt(variance)

            stats.append(VariantStats(
                variant_id=variant.variant_id,
                variant_name=variant.name,
                trial_count=count,
                success_count=successes,
                success_rate=success_rate,
                avg_metric=avg_metric,
                avg_latency_ms=avg_latency,
                std_dev=std_dev,
            ))
        return stats

    def _determine_winner(self, stats: list[VariantStats]) -> tuple[VariantStats | None, float]:
        if not stats:
            return None, 0.0

        viable = [s for s in stats if s.trial_count > 0]
        if not viable:
            return None, 0.0

        best = max(viable, key=lambda s: s.success_rate)
        if len(viable) < 2:
            return best, 0.5

        second = max((s for s in viable if s != best), key=lambda s: s.success_rate)

        confidence = self._compute_confidence(best, second)
        return best, confidence

    def _compute_confidence(self, a: VariantStats, b: VariantStats) -> float:
        n_a, n_b = a.trial_count, b.trial_count
        if n_a < 2 or n_b < 2:
            return 0.3

        p_a, p_b = a.success_rate, b.success_rate
        se_a = math.sqrt(p_a * (1 - p_a) / n_a) if p_a > 0 and p_a < 1 else 0.01
        se_b = math.sqrt(p_b * (1 - p_b) / n_b) if p_b > 0 and p_b < 1 else 0.01
        se_diff = math.sqrt(se_a ** 2 + se_b ** 2)

        if se_diff == 0:
            return 0.99 if p_a != p_b else 0.5

        z = abs(p_a - p_b) / se_diff
        confidence = min(0.99, 1.0 - math.exp(-z * 0.7))
        return confidence

    def _classify_significance(self, confidence: float) -> SignificanceLevel:
        if confidence >= 0.95:
            return SignificanceLevel.VERY_HIGH
        elif confidence >= 0.9:
            return SignificanceLevel.HIGH
        elif confidence >= 0.8:
            return SignificanceLevel.MEDIUM
        return SignificanceLevel.LOW

    def _build_recommendation(self, winner: VariantStats | None,
                              stats: list[VariantStats],
                              significance: SignificanceLevel) -> str:
        if not winner:
            return "Insufficient data to determine a winner"
        if significance in (SignificanceLevel.VERY_HIGH, SignificanceLevel.HIGH):
            return f"Deploy '{winner.variant_name}' — statistically significant winner"
        elif significance == SignificanceLevel.MEDIUM:
            return f"'{winner.variant_name}' leads but consider more trials for confidence"
        return f"No clear winner yet — '{winner.variant_name}' has a slight edge"

    def _allocate_uniform(self, experiment: Experiment, trials: list[TrialResult]) -> Variant:
        counts = defaultdict(int)
        for t in trials:
            counts[t.variant_id] += 1
        return min(experiment.variants, key=lambda v: counts[v.variant_id])

    def _allocate_epsilon_greedy(self, experiment: Experiment, trials: list[TrialResult]) -> Variant:
        if random.random() < self._epsilon or not trials:
            return random.choice(experiment.variants)

        success_rates: dict[str, float] = {}
        for variant in experiment.variants:
            vt = [t for t in trials if t.variant_id == variant.variant_id]
            if vt:
                success_rates[variant.variant_id] = sum(
                    1 for t in vt if t.outcome == VariantOutcome.SUCCESS
                ) / len(vt)
            else:
                success_rates[variant.variant_id] = 0.0

        best_id = max(success_rates, key=success_rates.get)
        return next(v for v in experiment.variants if v.variant_id == best_id)

    def _allocate_thompson(self, experiment: Experiment, trials: list[TrialResult]) -> Variant:
        best_sample = -1.0
        best_variant = experiment.variants[0]

        for variant in experiment.variants:
            vt = [t for t in trials if t.variant_id == variant.variant_id]
            successes = sum(1 for t in vt if t.outcome == VariantOutcome.SUCCESS)
            failures = len(vt) - successes
            sample = random.betavariate(successes + 1, failures + 1)
            if sample > best_sample:
                best_sample = sample
                best_variant = variant

        return best_variant

    def _allocate_ucb(self, experiment: Experiment, trials: list[TrialResult]) -> Variant:
        total = len(trials)
        if total == 0:
            return experiment.variants[0]

        best_score = -1.0
        best_variant = experiment.variants[0]

        for variant in experiment.variants:
            vt = [t for t in trials if t.variant_id == variant.variant_id]
            n = len(vt)
            if n == 0:
                return variant

            avg = sum(1 for t in vt if t.outcome == VariantOutcome.SUCCESS) / n
            exploration = math.sqrt(2 * math.log(total) / n)
            score = avg + exploration

            if score > best_score:
                best_score = score
                best_variant = variant

        return best_variant
