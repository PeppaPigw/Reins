from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from reins.governance.types import (
    AgentBudget,
    BudgetAlert,
    BudgetAlertKind,
    BudgetPeriod,
    CircuitBreakerState,
    CircuitBreakerStatus,
    CostForecast,
    SpendRecord,
    ThrottleAction,
    ThrottlePolicy,
)


_PERIOD_HOURS = {
    BudgetPeriod.HOURLY: 1,
    BudgetPeriod.DAILY: 24,
    BudgetPeriod.WEEKLY: 168,
    BudgetPeriod.MONTHLY: 720,
}


class CostGovernanceEngine:
    """Enforces budget limits, circuit breakers, and spend forecasting for agents.

    Provides per-agent budget allocation with automatic throttling when
    approaching limits, circuit breakers for runaway spend, and linear
    forecasting to predict budget exhaustion.
    """

    def __init__(
        self,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_cooldown: int = 60,
    ) -> None:
        self._budgets: dict[str, AgentBudget] = {}
        self._records: list[SpendRecord] = []
        self._circuit_breakers: dict[str, CircuitBreakerState] = {}
        self._alerts: list[BudgetAlert] = []
        self._cb_threshold = circuit_breaker_threshold
        self._cb_cooldown = circuit_breaker_cooldown

    def set_budget(self, agent_id: str, limit: float, period: BudgetPeriod = BudgetPeriod.DAILY, warning_threshold: float = 0.8, critical_threshold: float = 0.95) -> AgentBudget:
        budget = AgentBudget(
            agent_id=agent_id,
            period=period,
            limit=limit,
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
        )
        self._budgets[agent_id] = budget
        return budget

    def get_budget(self, agent_id: str) -> AgentBudget | None:
        return self._budgets.get(agent_id)

    def record_spend(self, agent_id: str, amount: float, model_id: str = "", input_tokens: int = 0, output_tokens: int = 0, operation: str = "") -> SpendRecord:
        record = SpendRecord(
            agent_id=agent_id,
            amount=amount,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            operation=operation,
        )
        self._records.append(record)
        self._check_alerts(agent_id)
        return record

    def get_spend(self, agent_id: str, period: BudgetPeriod | None = None) -> float:
        budget = self._budgets.get(agent_id)
        hours = _PERIOD_HOURS.get(period or (budget.period if budget else BudgetPeriod.DAILY), 24)
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        return sum(r.amount for r in self._records if r.agent_id == agent_id and r.timestamp >= cutoff)

    def get_utilization(self, agent_id: str) -> float:
        budget = self._budgets.get(agent_id)
        if not budget or budget.limit <= 0:
            return 0.0
        spend = self.get_spend(agent_id)
        return spend / budget.limit

    def evaluate_request(self, agent_id: str, estimated_cost: float) -> ThrottlePolicy:
        cb = self._circuit_breakers.get(agent_id)
        if cb and cb.status == CircuitBreakerStatus.OPEN:
            if self._should_half_open(cb):
                self._circuit_breakers[agent_id] = CircuitBreakerState(
                    agent_id=agent_id,
                    status=CircuitBreakerStatus.HALF_OPEN,
                    failure_count=cb.failure_count,
                    last_failure_at=cb.last_failure_at,
                    opened_at=cb.opened_at,
                    half_open_at=datetime.now(UTC),
                    cooldown_seconds=cb.cooldown_seconds,
                )
            else:
                return ThrottlePolicy(
                    agent_id=agent_id,
                    action=ThrottleAction.DENY,
                    reason="Circuit breaker open",
                    retry_after_seconds=self._cb_cooldown,
                )

        budget = self._budgets.get(agent_id)
        if not budget:
            return ThrottlePolicy(agent_id=agent_id, action=ThrottleAction.ALLOW, reason="No budget configured")

        current_spend = self.get_spend(agent_id)
        projected = current_spend + estimated_cost

        if projected > budget.limit:
            return ThrottlePolicy(
                agent_id=agent_id,
                action=ThrottleAction.DENY,
                reason=f"Would exceed budget: {projected:.4f} > {budget.limit:.4f}",
            )

        utilization = projected / budget.limit
        if utilization > budget.critical_threshold:
            return ThrottlePolicy(
                agent_id=agent_id,
                action=ThrottleAction.THROTTLE,
                reason=f"Near budget limit: {utilization:.0%} utilization",
                retry_after_seconds=30,
            )

        return ThrottlePolicy(agent_id=agent_id, action=ThrottleAction.ALLOW, reason="Within budget")

    def trip_circuit_breaker(self, agent_id: str) -> CircuitBreakerState:
        current = self._circuit_breakers.get(agent_id)
        failure_count = (current.failure_count + 1) if current else 1

        if failure_count >= self._cb_threshold:
            state = CircuitBreakerState(
                agent_id=agent_id,
                status=CircuitBreakerStatus.OPEN,
                failure_count=failure_count,
                last_failure_at=datetime.now(UTC),
                opened_at=datetime.now(UTC),
                cooldown_seconds=self._cb_cooldown,
            )
        else:
            state = CircuitBreakerState(
                agent_id=agent_id,
                status=CircuitBreakerStatus.CLOSED,
                failure_count=failure_count,
                last_failure_at=datetime.now(UTC),
                cooldown_seconds=self._cb_cooldown,
            )

        self._circuit_breakers[agent_id] = state
        return state

    def reset_circuit_breaker(self, agent_id: str) -> CircuitBreakerState:
        state = CircuitBreakerState(
            agent_id=agent_id,
            status=CircuitBreakerStatus.CLOSED,
            failure_count=0,
            cooldown_seconds=self._cb_cooldown,
        )
        self._circuit_breakers[agent_id] = state
        return state

    def get_circuit_breaker(self, agent_id: str) -> CircuitBreakerState | None:
        return self._circuit_breakers.get(agent_id)

    def forecast(self, agent_id: str) -> CostForecast:
        budget = self._budgets.get(agent_id)
        period = budget.period if budget else BudgetPeriod.DAILY
        hours = _PERIOD_HOURS[period]
        cutoff = datetime.now(UTC) - timedelta(hours=hours)

        recent = [r for r in self._records if r.agent_id == agent_id and r.timestamp >= cutoff]
        current_spend = sum(r.amount for r in recent)

        if not recent:
            return CostForecast(
                agent_id=agent_id,
                period=period,
                projected_spend=0.0,
                current_spend=0.0,
                burn_rate_per_hour=0.0,
                confidence=0.0,
            )

        earliest = min(r.timestamp for r in recent)
        elapsed_hours = max((datetime.now(UTC) - earliest).total_seconds() / 3600, 0.01)
        burn_rate = current_spend / elapsed_hours
        projected = burn_rate * hours

        hours_until_exhaustion = None
        if budget and burn_rate > 0:
            remaining = budget.limit - current_spend
            hours_until_exhaustion = max(0.0, remaining / burn_rate)

        confidence = min(1.0, len(recent) / 20.0)

        return CostForecast(
            agent_id=agent_id,
            period=period,
            projected_spend=projected,
            current_spend=current_spend,
            burn_rate_per_hour=burn_rate,
            hours_until_exhaustion=hours_until_exhaustion,
            confidence=confidence,
        )

    def get_alerts(self, agent_id: str | None = None) -> list[BudgetAlert]:
        if agent_id:
            return [a for a in self._alerts if a.agent_id == agent_id]
        return list(self._alerts)

    def get_summary(self) -> dict[str, Any]:
        by_agent: dict[str, float] = defaultdict(float)
        for r in self._records:
            by_agent[r.agent_id] += r.amount

        return {
            "total_spend": sum(r.amount for r in self._records),
            "total_records": len(self._records),
            "by_agent": dict(by_agent),
            "active_budgets": len(self._budgets),
            "open_circuit_breakers": sum(
                1 for cb in self._circuit_breakers.values()
                if cb.status == CircuitBreakerStatus.OPEN
            ),
            "total_alerts": len(self._alerts),
        }

    def _check_alerts(self, agent_id: str) -> None:
        budget = self._budgets.get(agent_id)
        if not budget:
            return

        spend = self.get_spend(agent_id)
        utilization = spend / budget.limit if budget.limit > 0 else 0.0

        if utilization >= 1.0:
            self._alerts.append(BudgetAlert(
                agent_id=agent_id,
                kind=BudgetAlertKind.BUDGET_EXHAUSTED,
                current_spend=spend,
                budget_limit=budget.limit,
                utilization_pct=utilization,
                message=f"Budget exhausted for {agent_id}: {spend:.4f}/{budget.limit:.4f}",
            ))
        elif utilization >= budget.critical_threshold:
            self._alerts.append(BudgetAlert(
                agent_id=agent_id,
                kind=BudgetAlertKind.THRESHOLD_CRITICAL,
                current_spend=spend,
                budget_limit=budget.limit,
                utilization_pct=utilization,
                message=f"Critical threshold reached for {agent_id}: {utilization:.0%}",
            ))
        elif utilization >= budget.warning_threshold:
            self._alerts.append(BudgetAlert(
                agent_id=agent_id,
                kind=BudgetAlertKind.THRESHOLD_WARNING,
                current_spend=spend,
                budget_limit=budget.limit,
                utilization_pct=utilization,
                message=f"Warning threshold reached for {agent_id}: {utilization:.0%}",
            ))

    def _should_half_open(self, cb: CircuitBreakerState) -> bool:
        if not cb.opened_at:
            return False
        elapsed = (datetime.now(UTC) - cb.opened_at).total_seconds()
        return elapsed >= cb.cooldown_seconds
