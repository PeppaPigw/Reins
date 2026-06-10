from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any, Callable

from reins.simulation.types import (
    OutcomeKind,
    Scenario,
    ScenarioKind,
    SimulationBatch,
    SimulationResult,
    SimulationRun,
    SimulationStats,
    SimulationStatus,
    StrategyProfile,
)


class SimulationEngine:
    """Monte Carlo simulation for testing agent strategies before deployment.

    Runs scenarios against strategies with configurable iterations,
    computes statistical results, and compares strategy performance.
    """

    def __init__(self, default_iterations: int = 100) -> None:
        self._default_iterations = default_iterations
        self._scenarios: dict[str, Scenario] = {}
        self._strategies: dict[str, StrategyProfile] = {}
        self._batches: dict[str, SimulationBatch] = {}
        self._evaluators: dict[str, Callable[[Scenario, StrategyProfile, int], SimulationRun]] = {}

    def register_scenario(self, scenario: Scenario) -> Scenario:
        self._scenarios[scenario.scenario_id] = scenario
        return scenario

    def get_scenario(self, scenario_id: str) -> Scenario | None:
        return self._scenarios.get(scenario_id)

    def register_strategy(self, strategy: StrategyProfile) -> StrategyProfile:
        self._strategies[strategy.strategy_id] = strategy
        return strategy

    def get_strategy(self, strategy_id: str) -> StrategyProfile | None:
        return self._strategies.get(strategy_id)

    def register_evaluator(
        self, strategy_id: str,
        evaluator: Callable[[Scenario, StrategyProfile, int], SimulationRun],
    ) -> None:
        self._evaluators[strategy_id] = evaluator

    def run_batch(self, scenario_id: str, strategy_id: str,
                  iterations: int | None = None) -> SimulationBatch | None:
        scenario = self._scenarios.get(scenario_id)
        strategy = self._strategies.get(strategy_id)
        if not scenario or not strategy:
            return None

        iters = iterations or self._default_iterations
        evaluator = self._evaluators.get(strategy_id)

        runs: list[SimulationRun] = []
        for i in range(iters):
            if evaluator:
                run = evaluator(scenario, strategy, i)
            else:
                run = self._default_evaluate(scenario, strategy, i)
            runs.append(run)

        batch = SimulationBatch(
            strategy_id=strategy_id,
            scenario_id=scenario_id,
            iterations=iters,
            status=SimulationStatus.COMPLETED,
            runs=tuple(runs),
        )
        self._batches[batch.batch_id] = batch
        return batch

    def get_result(self, batch_id: str) -> SimulationResult | None:
        batch = self._batches.get(batch_id)
        if not batch:
            return None
        return self._compute_result(batch)

    def compare_strategies(self, scenario_id: str,
                           strategy_ids: list[str] | None = None,
                           iterations: int | None = None) -> list[SimulationResult]:
        ids = strategy_ids or list(self._strategies.keys())
        results = []
        for sid in ids:
            batch = self.run_batch(scenario_id, sid, iterations)
            if batch:
                result = self._compute_result(batch)
                results.append(result)
        results.sort(key=lambda r: r.success_rate, reverse=True)
        return results

    def get_batches(self, scenario_id: str | None = None,
                    strategy_id: str | None = None) -> list[SimulationBatch]:
        batches = list(self._batches.values())
        if scenario_id:
            batches = [b for b in batches if b.scenario_id == scenario_id]
        if strategy_id:
            batches = [b for b in batches if b.strategy_id == strategy_id]
        return batches

    def get_stats(self) -> SimulationStats:
        total_runs = sum(len(b.runs) for b in self._batches.values())

        by_kind: dict[str, int] = defaultdict(int)
        for s in self._scenarios.values():
            by_kind[s.kind.value] += 1

        success_rates = []
        for batch in self._batches.values():
            result = self._compute_result(batch)
            success_rates.append(result.success_rate)
        avg_success = sum(success_rates) / len(success_rates) if success_rates else 0.0

        return SimulationStats(
            total_scenarios=len(self._scenarios),
            total_strategies=len(self._strategies),
            total_batches=len(self._batches),
            total_runs=total_runs,
            avg_success_rate=avg_success,
            by_scenario_kind=dict(by_kind),
        )

    def _compute_result(self, batch: SimulationBatch) -> SimulationResult:
        runs = batch.runs
        total = len(runs)
        if total == 0:
            return SimulationResult(
                batch_id=batch.batch_id,
                strategy_id=batch.strategy_id,
                scenario_id=batch.scenario_id,
            )

        successes = sum(1 for r in runs if r.outcome == OutcomeKind.SUCCESS)
        failures = total - successes
        success_rate = successes / total

        scores = [r.score for r in runs]
        avg_score = sum(scores) / total
        variance = sum((s - avg_score) ** 2 for s in scores) / total if total > 1 else 0.0
        std_dev = math.sqrt(variance)

        latencies = sorted(r.latency_ms for r in runs)
        avg_latency = sum(latencies) / total
        p95_idx = min(int(total * 0.95), total - 1)
        p95_latency = latencies[p95_idx]

        by_outcome: dict[str, int] = defaultdict(int)
        for r in runs:
            by_outcome[r.outcome.value] += 1

        return SimulationResult(
            batch_id=batch.batch_id,
            strategy_id=batch.strategy_id,
            scenario_id=batch.scenario_id,
            total_runs=total,
            success_count=successes,
            failure_count=failures,
            success_rate=success_rate,
            avg_score=avg_score,
            std_dev_score=std_dev,
            avg_latency_ms=avg_latency,
            p95_latency_ms=p95_latency,
            by_outcome=dict(by_outcome),
        )

    def _default_evaluate(self, scenario: Scenario, strategy: StrategyProfile,
                          iteration: int) -> SimulationRun:
        base_success = 0.7
        if scenario.kind == ScenarioKind.STRESS:
            base_success = 0.5
        elif scenario.kind == ScenarioKind.ADVERSARIAL:
            base_success = 0.3
        elif scenario.kind == ScenarioKind.CHAOS:
            base_success = 0.4
        elif scenario.kind == ScenarioKind.EDGE_CASE:
            base_success = 0.6

        success = random.random() < base_success
        outcome = OutcomeKind.SUCCESS if success else OutcomeKind.FAILURE
        score = random.gauss(0.7 if success else 0.3, 0.1)
        latency = random.gauss(100.0, 30.0)

        return SimulationRun(
            scenario_id=scenario.scenario_id,
            strategy_id=strategy.strategy_id,
            iteration=iteration,
            outcome=outcome,
            score=max(0.0, min(1.0, score)),
            latency_ms=max(1.0, latency),
        )
