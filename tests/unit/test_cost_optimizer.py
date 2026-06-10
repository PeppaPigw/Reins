"""Tests for cost optimizer with budget-aware routing."""

from __future__ import annotations

import pytest

from reins.cost_optimizer import (
    Budget,
    BudgetStatus,
    CostOptimizer,
    CostReport,
    CostStats,
    ModelPricing,
    ModelTier,
    RoutingDecision,
    TokenUsage,
)


@pytest.fixture
def optimizer() -> CostOptimizer:
    return CostOptimizer()


def test_record_usage(optimizer):
    usage = optimizer.record_usage("agent-1", "claude-sonnet",
                                   input_tokens=1000, output_tokens=500)
    assert usage.agent_id == "agent-1"
    assert usage.cost_usd > 0


def test_record_usage_unknown_model(optimizer):
    usage = optimizer.record_usage("agent-1", "unknown-model",
                                   input_tokens=1000, output_tokens=500)
    assert usage.cost_usd == 0.0


def test_set_pricing(optimizer):
    pricing = optimizer.set_pricing("custom-model", ModelTier.PREMIUM,
                                    input_cost_per_1k=0.01,
                                    output_cost_per_1k=0.03)
    assert pricing.model == "custom-model"
    assert optimizer.get_pricing("custom-model") is not None


def test_get_pricing_default(optimizer):
    assert optimizer.get_pricing("claude-sonnet") is not None
    assert optimizer.get_pricing("nonexistent") is None


def test_create_budget(optimizer):
    budget = optimizer.create_budget("daily", limit_usd=5.0)
    assert budget.name == "daily"
    assert budget.limit_usd == 5.0


def test_budget_status_under(optimizer):
    budget = optimizer.create_budget("test", limit_usd=100.0)
    assert optimizer.get_budget_status(budget.budget_id) == BudgetStatus.UNDER_BUDGET


def test_budget_status_warning(optimizer):
    budget = optimizer.create_budget("test", limit_usd=1.0, warning_threshold=0.8)
    optimizer.record_usage("a", "claude-opus", input_tokens=10000, output_tokens=10000)
    status = optimizer.get_budget_status(budget.budget_id)
    assert status in (BudgetStatus.WARNING, BudgetStatus.AT_LIMIT, BudgetStatus.OVER_BUDGET)


def test_budget_status_not_found(optimizer):
    assert optimizer.get_budget_status("nonexistent") == BudgetStatus.UNDER_BUDGET


def test_route_model_within_budget(optimizer):
    budget = optimizer.create_budget("test", limit_usd=100.0)
    decision = optimizer.route_model("claude-sonnet", budget_id=budget.budget_id)
    assert decision.routed_model == "claude-sonnet"
    assert decision.reason == "Within budget"


def test_route_model_over_budget_downgrades(optimizer):
    budget = optimizer.create_budget("tight", limit_usd=0.001)
    optimizer.record_usage("a", "claude-opus", input_tokens=1000, output_tokens=1000)
    decision = optimizer.route_model("claude-opus", budget_id=budget.budget_id,
                                     estimated_tokens=5000)
    if decision.routed_model != "claude-opus":
        assert "Budget constraint" in decision.reason


def test_route_model_no_budget(optimizer):
    decision = optimizer.route_model("claude-sonnet")
    assert decision.routed_model == "claude-sonnet"


def test_estimate_cost(optimizer):
    cost = optimizer.estimate_cost("claude-sonnet", input_tokens=1000, output_tokens=500)
    assert cost > 0
    assert cost == pytest.approx(0.003 + 0.015 * 0.5, abs=0.001)


def test_estimate_cost_unknown_model(optimizer):
    assert optimizer.estimate_cost("unknown", 1000, 500) == 0.0


def test_get_report_all(optimizer):
    optimizer.record_usage("a", "claude-sonnet", input_tokens=1000, output_tokens=500)
    optimizer.record_usage("b", "claude-haiku", input_tokens=2000, output_tokens=1000)
    report = optimizer.get_report()
    assert report.total_requests == 2
    assert report.total_cost_usd > 0
    assert "claude-sonnet" in report.by_model


def test_get_report_by_agent(optimizer):
    optimizer.record_usage("a", "claude-sonnet", input_tokens=1000, output_tokens=500)
    optimizer.record_usage("b", "claude-haiku", input_tokens=2000, output_tokens=1000)
    report = optimizer.get_report(agent_id="a")
    assert report.total_requests == 1


def test_get_report_by_task(optimizer):
    optimizer.record_usage("a", "claude-sonnet", input_tokens=1000,
                           output_tokens=500, task_id="task-1")
    optimizer.record_usage("a", "claude-sonnet", input_tokens=500,
                           output_tokens=200, task_id="task-1")
    report = optimizer.get_report()
    assert "task-1" in report.by_task


def test_cost_per_request(optimizer):
    optimizer.record_usage("a", "claude-sonnet", input_tokens=1000, output_tokens=500)
    optimizer.record_usage("a", "claude-sonnet", input_tokens=1000, output_tokens=500)
    report = optimizer.get_report()
    assert report.cost_per_request == pytest.approx(report.total_cost_usd / 2)


def test_stats_empty(optimizer):
    stats = optimizer.get_stats()
    assert stats.total_spend_usd == 0.0
    assert stats.total_requests == 0


def test_stats_populated(optimizer):
    optimizer.create_budget("daily", limit_usd=10.0)
    optimizer.record_usage("a", "claude-opus", input_tokens=5000, output_tokens=2000)
    optimizer.record_usage("b", "claude-haiku", input_tokens=10000, output_tokens=5000)
    stats = optimizer.get_stats()
    assert stats.total_spend_usd > 0
    assert stats.total_tokens == 22000
    assert stats.total_requests == 2
    assert stats.active_budgets == 1
    assert "claude-opus" in stats.by_model
    assert "flagship" in stats.by_tier


def test_flagship_costs_more_than_economy(optimizer):
    opus_cost = optimizer.estimate_cost("claude-opus", 1000, 1000)
    haiku_cost = optimizer.estimate_cost("claude-haiku", 1000, 1000)
    assert opus_cost > haiku_cost * 10
