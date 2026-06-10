from __future__ import annotations

import math
from collections import defaultdict

from reins.economics.types import (
    Allocation,
    AllocationStrategy,
    EconomicStats,
    MarketState,
    PricingModel,
    Resource,
    ResourceKind,
    UtilityFunction,
)


class EconomicEngine:
    """Economic modeling for agent resource allocation with utility maximization.

    Treats agent compute as an economic resource: models supply/demand,
    computes optimal allocations using utility functions, and supports
    dynamic pricing based on market conditions.
    """

    def __init__(self) -> None:
        self._resources: dict[str, Resource] = {}
        self._utilities: dict[str, list[UtilityFunction]] = defaultdict(list)
        self._allocations: list[Allocation] = []
        self._consumed: dict[str, float] = defaultdict(float)

    def register_resource(self, kind: ResourceKind, name: str,
                          total_supply: float = 100.0,
                          unit_cost: float = 1.0,
                          pricing: PricingModel = PricingModel.PAY_PER_USE) -> Resource:
        resource = Resource(
            kind=kind, name=name, total_supply=total_supply,
            unit_cost=unit_cost, pricing=pricing,
        )
        self._resources[resource.resource_id] = resource
        return resource

    def get_resource(self, resource_id: str) -> Resource | None:
        return self._resources.get(resource_id)

    def register_utility(self, agent_id: str, resource_id: str,
                         marginal_value: float = 1.0,
                         diminishing_rate: float = 0.1,
                         min_required: float = 0.0,
                         max_useful: float = 100.0) -> UtilityFunction:
        uf = UtilityFunction(
            agent_id=agent_id, resource_id=resource_id,
            marginal_value=marginal_value, diminishing_rate=diminishing_rate,
            min_required=min_required, max_useful=max_useful,
        )
        self._utilities[resource_id].append(uf)
        return uf

    def compute_utility(self, agent_id: str, resource_id: str, amount: float) -> float:
        utilities = self._utilities.get(resource_id, [])
        uf = next((u for u in utilities if u.agent_id == agent_id), None)
        if not uf:
            return amount * 0.5

        if amount < uf.min_required:
            return 0.0
        effective = min(amount, uf.max_useful)
        return uf.marginal_value * effective * math.exp(-uf.diminishing_rate * effective)

    def allocate(self, agent_id: str, resource_id: str, amount: float,
                 strategy: AllocationStrategy = AllocationStrategy.PROPORTIONAL) -> Allocation | None:
        resource = self._resources.get(resource_id)
        if not resource:
            return None

        available = resource.total_supply - self._consumed.get(resource_id, 0.0)
        actual_amount = min(amount, available)
        if actual_amount <= 0:
            return None

        cost = self._compute_cost(resource, actual_amount)
        utility = self.compute_utility(agent_id, resource_id, actual_amount)

        allocation = Allocation(
            agent_id=agent_id, resource_id=resource_id,
            amount=actual_amount, cost=cost, utility_gained=utility,
        )
        self._allocations.append(allocation)
        self._consumed[resource_id] += actual_amount
        return allocation

    def get_market_state(self, resource_id: str) -> MarketState | None:
        resource = self._resources.get(resource_id)
        if not resource:
            return None

        consumed = self._consumed.get(resource_id, 0.0)
        available = resource.total_supply - consumed
        utilization = consumed / resource.total_supply if resource.total_supply > 0 else 0.0

        demand = sum(
            uf.max_useful for uf in self._utilities.get(resource_id, [])
        )

        price = self._dynamic_price(resource, utilization)

        return MarketState(
            resource_id=resource_id,
            current_price=price,
            supply_available=available,
            demand_total=demand,
            utilization=utilization,
        )

    def optimal_allocation(self, resource_id: str,
                           budget: float | None = None) -> dict[str, float]:
        """Compute utility-maximizing allocation across all agents."""
        resource = self._resources.get(resource_id)
        if not resource:
            return {}

        utilities = self._utilities.get(resource_id, [])
        if not utilities:
            return {}

        available = resource.total_supply - self._consumed.get(resource_id, 0.0)
        allocations: dict[str, float] = {}

        sorted_utils = sorted(utilities, key=lambda u: -u.marginal_value)
        remaining = available

        for uf in sorted_utils:
            desired = min(uf.max_useful, remaining)
            if budget is not None:
                max_affordable = budget / resource.unit_cost if resource.unit_cost > 0 else desired
                desired = min(desired, max_affordable)
            allocations[uf.agent_id] = max(desired, 0.0)
            remaining -= desired
            if remaining <= 0:
                break

        return allocations

    def get_allocations(self, agent_id: str | None = None,
                        resource_id: str | None = None) -> list[Allocation]:
        allocs = self._allocations
        if agent_id:
            allocs = [a for a in allocs if a.agent_id == agent_id]
        if resource_id:
            allocs = [a for a in allocs if a.resource_id == resource_id]
        return allocs

    def get_stats(self) -> EconomicStats:
        total_cost = sum(a.cost for a in self._allocations)
        total_utility = sum(a.utility_gained for a in self._allocations)
        efficiency = total_utility / total_cost if total_cost > 0 else 0.0

        by_resource: dict[str, float] = defaultdict(float)
        by_agent: dict[str, float] = defaultdict(float)
        for a in self._allocations:
            by_resource[a.resource_id] += a.cost
            by_agent[a.agent_id] += a.cost

        return EconomicStats(
            total_resources=len(self._resources),
            total_allocations=len(self._allocations),
            total_cost=total_cost,
            total_utility=total_utility,
            efficiency_ratio=efficiency,
            by_resource=dict(by_resource),
            by_agent=dict(by_agent),
        )

    def _compute_cost(self, resource: Resource, amount: float) -> float:
        if resource.pricing == PricingModel.FIXED:
            return resource.unit_cost
        elif resource.pricing == PricingModel.DYNAMIC:
            utilization = self._consumed.get(resource.resource_id, 0.0) / resource.total_supply
            multiplier = 1.0 + utilization * 2.0
            return resource.unit_cost * amount * multiplier
        else:
            return resource.unit_cost * amount

    def _dynamic_price(self, resource: Resource, utilization: float) -> float:
        base = resource.unit_cost
        if resource.pricing == PricingModel.DYNAMIC:
            return base * (1.0 + utilization * 2.0)
        return base
