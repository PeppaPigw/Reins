from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from reins.cost_optimizer.types import (
    Budget,
    BudgetStatus,
    CostReport,
    CostStats,
    ModelPricing,
    ModelTier,
    RoutingDecision,
    TokenUsage,
)


class CostOptimizer:
    """Token economics with budget-aware routing and cost-per-outcome tracking.

    Tracks token spend across models and agents, enforces budgets,
    routes requests to cost-optimal models, and provides spend analytics.
    """

    def __init__(self) -> None:
        self._usage: list[TokenUsage] = []
        self._budgets: dict[str, Budget] = {}
        self._pricing: dict[str, ModelPricing] = {}
        self._register_default_pricing()

    def record_usage(self, agent_id: str, model: str,
                     input_tokens: int = 0, output_tokens: int = 0,
                     task_id: str = "") -> TokenUsage:
        cost = self._compute_cost(model, input_tokens, output_tokens)
        usage = TokenUsage(
            agent_id=agent_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            task_id=task_id,
        )
        self._usage.append(usage)
        self._update_budgets(cost)
        return usage

    def set_pricing(self, model: str, tier: ModelTier,
                    input_cost_per_1k: float,
                    output_cost_per_1k: float,
                    context_window: int = 128000) -> ModelPricing:
        pricing = ModelPricing(
            model=model,
            tier=tier,
            input_cost_per_1k=input_cost_per_1k,
            output_cost_per_1k=output_cost_per_1k,
            context_window=context_window,
        )
        self._pricing[model] = pricing
        return pricing

    def get_pricing(self, model: str) -> ModelPricing | None:
        return self._pricing.get(model)

    def create_budget(self, name: str, limit_usd: float = 10.0,
                      warning_threshold: float = 0.8,
                      period_hours: int = 24) -> Budget:
        budget = Budget(
            name=name,
            limit_usd=limit_usd,
            warning_threshold=warning_threshold,
            period_hours=period_hours,
        )
        self._budgets[budget.budget_id] = budget
        return budget

    def get_budget_status(self, budget_id: str) -> BudgetStatus:
        budget = self._budgets.get(budget_id)
        if not budget:
            return BudgetStatus.UNDER_BUDGET
        ratio = budget.spent_usd / budget.limit_usd if budget.limit_usd > 0 else 0
        if ratio >= 1.0:
            return BudgetStatus.OVER_BUDGET
        if ratio >= 0.95:
            return BudgetStatus.AT_LIMIT
        if ratio >= budget.warning_threshold:
            return BudgetStatus.WARNING
        return BudgetStatus.UNDER_BUDGET

    def route_model(self, requested_model: str, budget_id: str | None = None,
                    estimated_tokens: int = 1000) -> RoutingDecision:
        budget_remaining = float("inf")
        if budget_id:
            budget = self._budgets.get(budget_id)
            if budget:
                budget_remaining = budget.limit_usd - budget.spent_usd

        pricing = self._pricing.get(requested_model)
        estimated_cost = 0.0
        if pricing:
            estimated_cost = (estimated_tokens / 1000) * (
                pricing.input_cost_per_1k + pricing.output_cost_per_1k
            ) / 2

        if estimated_cost > budget_remaining:
            cheaper = self._find_cheaper_model(requested_model, budget_remaining, estimated_tokens)
            if cheaper:
                return RoutingDecision(
                    requested_model=requested_model,
                    routed_model=cheaper,
                    reason="Budget constraint - routed to cheaper model",
                    estimated_cost=estimated_cost,
                    budget_remaining=budget_remaining,
                )

        return RoutingDecision(
            requested_model=requested_model,
            routed_model=requested_model,
            reason="Within budget",
            estimated_cost=estimated_cost,
            budget_remaining=budget_remaining,
        )

    def get_report(self, agent_id: str | None = None) -> CostReport:
        usage = self._usage
        if agent_id:
            usage = [u for u in usage if u.agent_id == agent_id]

        total_cost = sum(u.cost_usd for u in usage)
        total_input = sum(u.input_tokens for u in usage)
        total_output = sum(u.output_tokens for u in usage)

        by_model: dict[str, float] = defaultdict(float)
        by_task: dict[str, float] = defaultdict(float)
        for u in usage:
            by_model[u.model] += u.cost_usd
            if u.task_id:
                by_task[u.task_id] += u.cost_usd

        cost_per_request = total_cost / len(usage) if usage else 0.0

        return CostReport(
            agent_id=agent_id or "",
            total_cost_usd=total_cost,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_requests=len(usage),
            cost_per_request=cost_per_request,
            by_model=dict(by_model),
            by_task=dict(by_task),
        )

    def estimate_cost(self, model: str, input_tokens: int,
                      output_tokens: int) -> float:
        return self._compute_cost(model, input_tokens, output_tokens)

    def get_stats(self) -> CostStats:
        total_spend = sum(u.cost_usd for u in self._usage)
        total_tokens = sum(u.input_tokens + u.output_tokens for u in self._usage)

        by_model: dict[str, float] = defaultdict(float)
        by_tier: dict[str, float] = defaultdict(float)
        for u in self._usage:
            by_model[u.model] += u.cost_usd
            pricing = self._pricing.get(u.model)
            if pricing:
                by_tier[pricing.tier.value] += u.cost_usd

        exceeded = sum(
            1 for b in self._budgets.values()
            if b.spent_usd >= b.limit_usd
        )
        avg_cost = total_spend / len(self._usage) if self._usage else 0.0

        return CostStats(
            total_spend_usd=total_spend,
            total_tokens=total_tokens,
            total_requests=len(self._usage),
            active_budgets=len(self._budgets),
            budgets_exceeded=exceeded,
            avg_cost_per_request=avg_cost,
            by_model=dict(by_model),
            by_tier=dict(by_tier),
        )

    def _compute_cost(self, model: str, input_tokens: int,
                      output_tokens: int) -> float:
        pricing = self._pricing.get(model)
        if not pricing:
            return 0.0
        input_cost = (input_tokens / 1000) * pricing.input_cost_per_1k
        output_cost = (output_tokens / 1000) * pricing.output_cost_per_1k
        return input_cost + output_cost

    def _update_budgets(self, cost: float) -> None:
        for bid, budget in self._budgets.items():
            updated = budget.model_copy(update={"spent_usd": budget.spent_usd + cost})
            self._budgets[bid] = updated

    def _find_cheaper_model(self, current: str, max_cost: float,
                            tokens: int) -> str | None:
        current_pricing = self._pricing.get(current)
        if not current_pricing:
            return None

        candidates = []
        for model, pricing in self._pricing.items():
            if model == current:
                continue
            est_cost = (tokens / 1000) * (
                pricing.input_cost_per_1k + pricing.output_cost_per_1k
            ) / 2
            if est_cost <= max_cost:
                candidates.append((model, est_cost))

        if candidates:
            candidates.sort(key=lambda x: x[1])
            return candidates[0][0]
        return None

    def _register_default_pricing(self) -> None:
        defaults = [
            ("gpt-4o", ModelTier.FLAGSHIP, 0.005, 0.015, 128000),
            ("gpt-4o-mini", ModelTier.ECONOMY, 0.00015, 0.0006, 128000),
            ("claude-opus", ModelTier.FLAGSHIP, 0.015, 0.075, 200000),
            ("claude-sonnet", ModelTier.STANDARD, 0.003, 0.015, 200000),
            ("claude-haiku", ModelTier.ECONOMY, 0.00025, 0.00125, 200000),
        ]
        for model, tier, inp, out, ctx in defaults:
            self._pricing[model] = ModelPricing(
                model=model, tier=tier,
                input_cost_per_1k=inp, output_cost_per_1k=out,
                context_window=ctx,
            )
