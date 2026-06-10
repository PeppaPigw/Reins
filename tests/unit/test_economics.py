"""Tests for economic modeling with utility maximization."""

from __future__ import annotations

import pytest

from reins.economics import (
    Allocation,
    AllocationStrategy,
    EconomicEngine,
    EconomicStats,
    MarketState,
    PricingModel,
    Resource,
    ResourceKind,
    UtilityFunction,
)


@pytest.fixture
def engine() -> EconomicEngine:
    return EconomicEngine()


@pytest.fixture
def market(engine) -> Resource:
    r = engine.register_resource(ResourceKind.COMPUTE, "gpu_hours", total_supply=100.0, unit_cost=2.0)
    engine.register_utility("agent-1", r.resource_id, marginal_value=5.0, max_useful=40.0)
    engine.register_utility("agent-2", r.resource_id, marginal_value=3.0, max_useful=30.0)
    return r


def test_register_resource(engine):
    r = engine.register_resource(ResourceKind.TOKENS, "gpt4_tokens")
    assert engine.get_resource(r.resource_id) is not None


def test_get_resource_not_found(engine):
    assert engine.get_resource("nonexistent") is None


def test_register_utility(engine, market):
    uf = engine.register_utility("agent-3", market.resource_id, marginal_value=2.0)
    assert uf.agent_id == "agent-3"


def test_compute_utility(engine, market):
    u = engine.compute_utility("agent-1", market.resource_id, 10.0)
    assert u > 0


def test_compute_utility_diminishing(engine, market):
    u_small = engine.compute_utility("agent-1", market.resource_id, 5.0)
    u_large = engine.compute_utility("agent-1", market.resource_id, 50.0)
    assert u_small / 5.0 > u_large / 50.0


def test_compute_utility_below_minimum(engine):
    r = engine.register_resource(ResourceKind.MEMORY, "ram")
    engine.register_utility("a", r.resource_id, min_required=10.0)
    u = engine.compute_utility("a", r.resource_id, 5.0)
    assert u == 0.0


def test_allocate(engine, market):
    alloc = engine.allocate("agent-1", market.resource_id, 20.0)
    assert alloc is not None
    assert alloc.amount == 20.0
    assert alloc.cost > 0


def test_allocate_limited_by_supply(engine, market):
    engine.allocate("agent-1", market.resource_id, 80.0)
    alloc = engine.allocate("agent-2", market.resource_id, 30.0)
    assert alloc.amount == 20.0


def test_allocate_no_supply(engine, market):
    engine.allocate("agent-1", market.resource_id, 100.0)
    alloc = engine.allocate("agent-2", market.resource_id, 10.0)
    assert alloc is None


def test_allocate_nonexistent_resource(engine):
    assert engine.allocate("a", "nonexistent", 10.0) is None


def test_market_state(engine, market):
    engine.allocate("agent-1", market.resource_id, 30.0)
    state = engine.get_market_state(market.resource_id)
    assert state.supply_available == 70.0
    assert state.utilization == pytest.approx(0.3)


def test_market_state_not_found(engine):
    assert engine.get_market_state("nonexistent") is None


def test_dynamic_pricing(engine):
    r = engine.register_resource(
        ResourceKind.API_CALLS, "openai", total_supply=1000.0,
        unit_cost=0.01, pricing=PricingModel.DYNAMIC,
    )
    engine.allocate("a", r.resource_id, 500.0)
    state = engine.get_market_state(r.resource_id)
    assert state.current_price > 0.01


def test_optimal_allocation(engine, market):
    optimal = engine.optimal_allocation(market.resource_id)
    assert "agent-1" in optimal
    assert "agent-2" in optimal
    assert optimal["agent-1"] >= optimal["agent-2"]


def test_optimal_allocation_respects_supply(engine, market):
    optimal = engine.optimal_allocation(market.resource_id)
    total = sum(optimal.values())
    assert total <= 100.0


def test_get_allocations_all(engine, market):
    engine.allocate("agent-1", market.resource_id, 10.0)
    engine.allocate("agent-2", market.resource_id, 5.0)
    assert len(engine.get_allocations()) == 2


def test_get_allocations_by_agent(engine, market):
    engine.allocate("agent-1", market.resource_id, 10.0)
    engine.allocate("agent-2", market.resource_id, 5.0)
    assert len(engine.get_allocations(agent_id="agent-1")) == 1


def test_get_allocations_by_resource(engine, market):
    r2 = engine.register_resource(ResourceKind.MEMORY, "ram")
    engine.allocate("agent-1", market.resource_id, 10.0)
    engine.allocate("agent-1", r2.resource_id, 5.0)
    assert len(engine.get_allocations(resource_id=market.resource_id)) == 1


def test_stats_empty():
    eng = EconomicEngine()
    stats = eng.get_stats()
    assert stats.total_resources == 0
    assert stats.total_allocations == 0


def test_stats_with_data(engine, market):
    engine.allocate("agent-1", market.resource_id, 20.0)
    engine.allocate("agent-2", market.resource_id, 10.0)
    stats = engine.get_stats()
    assert stats.total_resources == 1
    assert stats.total_allocations == 2
    assert stats.total_cost > 0
    assert stats.total_utility > 0
    assert stats.efficiency_ratio > 0
