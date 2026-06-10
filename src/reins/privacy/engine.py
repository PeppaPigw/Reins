from __future__ import annotations

import math
import random
from collections import defaultdict

from reins.privacy.types import (
    BudgetStatus,
    DataRecord,
    PrivacyBudget,
    PrivacyLevel,
    PrivacyMechanism,
    PrivacyQuery,
    PrivacyStats,
)


class DifferentialPrivacyEngine:
    """Formal epsilon-delta differential privacy for agent memory sharing.

    Provides mathematically rigorous privacy guarantees when agents query
    shared data. Uses composition theorems to track cumulative privacy loss
    and prevents budget exhaustion.
    """

    def __init__(self, default_epsilon: float = 1.0, default_delta: float = 1e-5,
                 random_seed: int | None = None) -> None:
        self._default_epsilon = default_epsilon
        self._default_delta = default_delta
        self._budgets: dict[str, PrivacyBudget] = {}
        self._records: dict[str, DataRecord] = {}
        self._queries: list[PrivacyQuery] = []
        self._rng = random.Random(random_seed)

    def register_data(self, key: str, value: float, sensitivity: float = 1.0,
                      level: PrivacyLevel = PrivacyLevel.MODERATE_SENSITIVITY) -> DataRecord:
        record = DataRecord(key=key, value=value, sensitivity=sensitivity, level=level)
        self._records[key] = record
        return record

    def get_record(self, key: str) -> DataRecord | None:
        return self._records.get(key)

    def allocate_budget(self, agent_id: str, epsilon: float | None = None,
                        delta: float | None = None) -> PrivacyBudget:
        budget = PrivacyBudget(
            agent_id=agent_id,
            epsilon_total=epsilon or self._default_epsilon,
            delta_total=delta or self._default_delta,
        )
        self._budgets[agent_id] = budget
        return budget

    def get_budget(self, agent_id: str) -> PrivacyBudget | None:
        return self._budgets.get(agent_id)

    def get_budget_status(self, agent_id: str) -> BudgetStatus:
        budget = self._budgets.get(agent_id)
        if not budget:
            return BudgetStatus.AVAILABLE
        ratio = budget.epsilon_spent / budget.epsilon_total if budget.epsilon_total > 0 else 0
        if ratio >= 1.0:
            return BudgetStatus.EXHAUSTED
        if ratio > 0.8:
            return BudgetStatus.LOW
        return BudgetStatus.AVAILABLE

    def query(self, agent_id: str, data_key: str,
              mechanism: PrivacyMechanism = PrivacyMechanism.LAPLACE,
              epsilon: float | None = None) -> PrivacyQuery | None:
        record = self._records.get(data_key)
        if not record:
            return None

        budget = self._budgets.get(agent_id)
        if not budget:
            budget = self.allocate_budget(agent_id)

        eps = epsilon or self._compute_epsilon(record)
        delta = self._compute_delta(mechanism, eps)

        if budget.epsilon_spent + eps > budget.epsilon_total:
            return None

        noise = self._generate_noise(mechanism, record.sensitivity, eps)
        noisy_value = record.value + noise

        query = PrivacyQuery(
            agent_id=agent_id,
            data_key=data_key,
            mechanism=mechanism,
            epsilon_cost=eps,
            delta_cost=delta,
            sensitivity=record.sensitivity,
            true_value=record.value,
            noisy_value=noisy_value,
            noise_added=noise,
        )
        self._queries.append(query)

        updated_budget = PrivacyBudget(
            budget_id=budget.budget_id,
            agent_id=agent_id,
            epsilon_total=budget.epsilon_total,
            epsilon_spent=budget.epsilon_spent + eps,
            delta_total=budget.delta_total,
            delta_spent=budget.delta_spent + delta,
            queries_made=budget.queries_made + 1,
        )
        self._budgets[agent_id] = updated_budget

        return query

    def get_queries(self, agent_id: str | None = None) -> list[PrivacyQuery]:
        queries = self._queries
        if agent_id:
            queries = [q for q in queries if q.agent_id == agent_id]
        return queries

    def compute_privacy_loss(self, agent_id: str) -> float:
        budget = self._budgets.get(agent_id)
        if not budget:
            return 0.0
        return budget.epsilon_spent

    def remaining_budget(self, agent_id: str) -> float:
        budget = self._budgets.get(agent_id)
        if not budget:
            return self._default_epsilon
        return max(0.0, budget.epsilon_total - budget.epsilon_spent)

    def get_stats(self) -> PrivacyStats:
        by_mechanism: dict[str, int] = defaultdict(int)
        for q in self._queries:
            by_mechanism[q.mechanism.value] += 1

        by_level: dict[str, int] = defaultdict(int)
        for r in self._records.values():
            by_level[r.level.value] += 1

        epsilons = [b.epsilon_spent for b in self._budgets.values()]
        avg_eps = sum(epsilons) / len(epsilons) if epsilons else 0.0
        exhausted = sum(1 for b in self._budgets.values()
                        if b.epsilon_spent >= b.epsilon_total)

        return PrivacyStats(
            total_agents=len(self._budgets),
            total_queries=len(self._queries),
            total_records=len(self._records),
            avg_epsilon_spent=avg_eps,
            budgets_exhausted=exhausted,
            by_mechanism=dict(by_mechanism),
            by_level=dict(by_level),
        )

    def _compute_epsilon(self, record: DataRecord) -> float:
        level_costs = {
            PrivacyLevel.PUBLIC: 0.01,
            PrivacyLevel.LOW_SENSITIVITY: 0.1,
            PrivacyLevel.MODERATE_SENSITIVITY: 0.3,
            PrivacyLevel.HIGH_SENSITIVITY: 0.5,
            PrivacyLevel.CRITICAL: 0.8,
        }
        return level_costs.get(record.level, 0.3)

    def _compute_delta(self, mechanism: PrivacyMechanism, epsilon: float) -> float:
        if mechanism == PrivacyMechanism.GAUSSIAN:
            return self._default_delta
        return 0.0

    def _generate_noise(self, mechanism: PrivacyMechanism,
                        sensitivity: float, epsilon: float) -> float:
        if mechanism == PrivacyMechanism.LAPLACE:
            scale = sensitivity / epsilon if epsilon > 0 else 1e6
            u = self._rng.uniform(-0.5, 0.5)
            return -scale * math.copysign(1, u) * math.log(1 - 2 * abs(u))

        elif mechanism == PrivacyMechanism.GAUSSIAN:
            sigma = sensitivity * math.sqrt(2 * math.log(1.25 / self._default_delta)) / epsilon
            return self._rng.gauss(0, sigma)

        elif mechanism == PrivacyMechanism.RANDOMIZED_RESPONSE:
            p = math.exp(epsilon) / (math.exp(epsilon) + 1)
            if self._rng.random() < p:
                return 0.0
            return self._rng.choice([-sensitivity, sensitivity])

        else:
            scale = sensitivity / epsilon if epsilon > 0 else 1e6
            return self._rng.uniform(-scale, scale)
