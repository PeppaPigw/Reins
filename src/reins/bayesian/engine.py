from __future__ import annotations

import math
import random
from collections import defaultdict

from reins.bayesian.types import (
    AcquisitionFunction,
    BayesianStats,
    OptimizationResult,
    OptimizationStatus,
    Parameter,
    ParameterKind,
    SearchSpace,
    Trial,
)


class _GaussianProcess:
    """Lightweight GP surrogate using RBF kernel for Bayesian optimization."""

    def __init__(self, length_scale: float = 1.0, noise: float = 1e-6) -> None:
        self._length_scale = length_scale
        self._noise = noise
        self._X: list[list[float]] = []
        self._y: list[float] = []

    def fit(self, X: list[list[float]], y: list[float]) -> None:
        self._X = X
        self._y = y

    def predict(self, x: list[float]) -> tuple[float, float]:
        if not self._X:
            return 0.0, 1.0

        weights = []
        for xi in self._X:
            dist_sq = sum((a - b) ** 2 for a, b in zip(x, xi))
            w = math.exp(-dist_sq / (2 * self._length_scale ** 2))
            weights.append(w)

        total_w = sum(weights) + 1e-10
        mean = sum(w * y for w, y in zip(weights, self._y)) / total_w

        variance = 1.0 - (sum(w ** 2 for w in weights) / (total_w ** 2))
        variance = max(variance, 1e-6)

        return mean, math.sqrt(variance)


class BayesianOptimizer:
    """Bayesian optimization for auto-tuning agent parameters.

    Uses Gaussian process surrogate models with acquisition functions
    to efficiently explore parameter spaces and find optimal configurations.
    """

    def __init__(self, acquisition: AcquisitionFunction = AcquisitionFunction.EXPECTED_IMPROVEMENT,
                 exploration_weight: float = 2.0,
                 random_seed: int | None = None) -> None:
        self._acquisition = acquisition
        self._exploration_weight = exploration_weight
        self._spaces: dict[str, SearchSpace] = {}
        self._trials: dict[str, list[Trial]] = defaultdict(list)
        self._gps: dict[str, _GaussianProcess] = {}
        self._rng = random.Random(random_seed)

    def define_space(self, name: str, parameters: list[Parameter]) -> SearchSpace:
        space = SearchSpace(name=name, parameters=tuple(parameters))
        self._spaces[space.space_id] = space
        self._gps[space.space_id] = _GaussianProcess()
        return space

    def get_space(self, space_id: str) -> SearchSpace | None:
        return self._spaces.get(space_id)

    def suggest(self, space_id: str, n_candidates: int = 100) -> dict[str, float]:
        space = self._spaces.get(space_id)
        if not space:
            return {}

        trials = self._trials.get(space_id, [])
        if len(trials) < 3:
            return self._random_sample(space)

        gp = self._gps[space_id]
        X = [self._params_to_vector(space, t.params) for t in trials]
        y = [t.objective for t in trials]
        gp.fit(X, y)

        best_objective = max(y)
        best_candidate = None
        best_acquisition_value = float("-inf")

        for _ in range(n_candidates):
            candidate = self._random_sample(space)
            x = self._params_to_vector(space, candidate)
            acq_value = self._compute_acquisition(gp, x, best_objective)
            if acq_value > best_acquisition_value:
                best_acquisition_value = acq_value
                best_candidate = candidate

        return best_candidate or self._random_sample(space)

    def report(self, space_id: str, params: dict[str, float], objective: float,
               metadata: dict | None = None) -> Trial:
        iteration = len(self._trials.get(space_id, []))
        trial = Trial(
            params=params,
            objective=objective,
            iteration=iteration,
            metadata=metadata or {},
        )
        self._trials[space_id].append(trial)
        return trial

    def get_best(self, space_id: str) -> Trial | None:
        trials = self._trials.get(space_id, [])
        if not trials:
            return None
        return max(trials, key=lambda t: t.objective)

    def get_trials(self, space_id: str) -> list[Trial]:
        return self._trials.get(space_id, [])

    def get_result(self, space_id: str) -> OptimizationResult:
        space = self._spaces.get(space_id)
        if not space:
            return OptimizationResult(space_id=space_id)

        trials = self._trials.get(space_id, [])
        if not trials:
            return OptimizationResult(space_id=space_id, status=OptimizationStatus.EXPLORING)

        best = max(trials, key=lambda t: t.objective)
        status = self._determine_status(trials)
        convergence = self._compute_convergence(trials)

        return OptimizationResult(
            space_id=space_id,
            best_params=best.params,
            best_objective=best.objective,
            total_trials=len(trials),
            status=status,
            convergence_rate=convergence,
        )

    def get_stats(self) -> BayesianStats:
        total_trials = sum(len(t) for t in self._trials.values())
        all_trials = [t for trials in self._trials.values() for t in trials]
        best_obj = max((t.objective for t in all_trials), default=0.0)

        improvements = []
        for space_trials in self._trials.values():
            if len(space_trials) >= 2:
                for i in range(1, len(space_trials)):
                    improvements.append(
                        space_trials[i].objective - space_trials[i - 1].objective
                    )
        avg_improvement = sum(improvements) / len(improvements) if improvements else 0.0

        by_status: dict[str, int] = defaultdict(int)
        for space_id in self._spaces:
            result = self.get_result(space_id)
            by_status[result.status.value] += 1

        return BayesianStats(
            total_spaces=len(self._spaces),
            total_trials=total_trials,
            avg_improvement=avg_improvement,
            best_objective=best_obj,
            by_status=dict(by_status),
        )

    def _random_sample(self, space: SearchSpace) -> dict[str, float]:
        params: dict[str, float] = {}
        for p in space.parameters:
            if p.kind == ParameterKind.INTEGER:
                params[p.name] = float(self._rng.randint(int(p.lower), int(p.upper)))
            elif p.kind == ParameterKind.LOG_SCALE:
                log_val = self._rng.uniform(math.log(max(p.lower, 1e-10)), math.log(p.upper))
                params[p.name] = math.exp(log_val)
            else:
                params[p.name] = self._rng.uniform(p.lower, p.upper)
        return params

    def _params_to_vector(self, space: SearchSpace, params: dict[str, float]) -> list[float]:
        vector = []
        for p in space.parameters:
            val = params.get(p.name, (p.lower + p.upper) / 2)
            normalized = (val - p.lower) / (p.upper - p.lower) if p.upper > p.lower else 0.5
            vector.append(normalized)
        return vector

    def _compute_acquisition(self, gp: _GaussianProcess, x: list[float],
                             best_so_far: float) -> float:
        mean, std = gp.predict(x)

        if self._acquisition == AcquisitionFunction.EXPECTED_IMPROVEMENT:
            if std < 1e-8:
                return 0.0
            z = (mean - best_so_far) / std
            ei = (mean - best_so_far) * self._normal_cdf(z) + std * self._normal_pdf(z)
            return ei

        elif self._acquisition == AcquisitionFunction.UPPER_CONFIDENCE_BOUND:
            return mean + self._exploration_weight * std

        elif self._acquisition == AcquisitionFunction.PROBABILITY_OF_IMPROVEMENT:
            if std < 1e-8:
                return 1.0 if mean > best_so_far else 0.0
            z = (mean - best_so_far) / std
            return self._normal_cdf(z)

        else:
            return mean + self._rng.gauss(0, std)

    def _determine_status(self, trials: list[Trial]) -> OptimizationStatus:
        if len(trials) < 5:
            return OptimizationStatus.EXPLORING

        recent = trials[-5:]
        objectives = [t.objective for t in recent]
        spread = max(objectives) - min(objectives)
        if spread < 0.01 * abs(max(objectives)) if max(objectives) != 0 else spread < 0.001:
            return OptimizationStatus.CONVERGED

        best_idx = max(range(len(trials)), key=lambda i: trials[i].objective)
        if best_idx < len(trials) - 5:
            return OptimizationStatus.EXPLOITING

        return OptimizationStatus.EXPLORING

    def _compute_convergence(self, trials: list[Trial]) -> float:
        if len(trials) < 2:
            return 0.0
        first_half = trials[:len(trials) // 2]
        second_half = trials[len(trials) // 2:]
        best_first = max(t.objective for t in first_half)
        best_second = max(t.objective for t in second_half)
        if best_first == 0:
            return 0.0
        return (best_second - best_first) / abs(best_first) if best_first != 0 else 0.0

    @staticmethod
    def _normal_pdf(x: float) -> float:
        return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)

    @staticmethod
    def _normal_cdf(x: float) -> float:
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))
