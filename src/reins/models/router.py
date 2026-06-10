from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from reins.models.types import (
    CostPolicy,
    ModelCapability,
    ModelConfig,
    ModelProvider,
    ModelRegistry,
    RoutingDecision,
    RoutingStrategy,
    TaskComplexity,
    UsageRecord,
)


class ModelRouter:
    """Routes tasks to optimal models based on capability, cost, and performance.

    Supports multiple routing strategies:
    - CHEAPEST: minimize cost while meeting capability requirements
    - FASTEST: minimize latency
    - BEST_QUALITY: maximize quality score
    - BALANCED: weighted combination of cost, latency, and quality
    - CAPABILITY_MATCH: best fit for required capabilities
    - FALLBACK_CHAIN: ordered list with automatic failover
    """

    def __init__(self, registry: ModelRegistry | None = None) -> None:
        self._models: list[ModelConfig] = list(registry.models) if registry else []
        self._cost_policy: CostPolicy = registry.cost_policy if registry else CostPolicy()
        self._default_strategy: RoutingStrategy = (
            registry.default_strategy if registry else RoutingStrategy.BALANCED
        )
        self._usage: list[UsageRecord] = []
        self._failure_counts: dict[str, int] = defaultdict(int)

    def register_model(self, model: ModelConfig) -> None:
        self._models = [m for m in self._models if m.model_id != model.model_id]
        self._models.append(model)

    def unregister_model(self, model_id: str) -> None:
        self._models = [m for m in self._models if m.model_id != model_id]

    def route(
        self,
        required_capabilities: list[ModelCapability] | None = None,
        complexity: TaskComplexity = TaskComplexity.MEDIUM,
        strategy: RoutingStrategy | None = None,
        max_cost: float | None = None,
        max_latency_ms: float | None = None,
        exclude_models: list[str] | None = None,
        prefer_provider: ModelProvider | None = None,
    ) -> RoutingDecision:
        strategy = strategy or self._default_strategy
        candidates = self._filter_candidates(
            required_capabilities or [],
            max_cost,
            max_latency_ms,
            exclude_models or [],
        )

        if not candidates:
            candidates = [m for m in self._models if m.is_available]
            if not candidates:
                raise ValueError("No available models to route to")

        if prefer_provider:
            preferred = [m for m in candidates if m.provider == prefer_provider]
            if preferred:
                candidates = preferred

        scored = self._score_candidates(candidates, strategy, complexity)
        scored.sort(key=lambda x: x[1], reverse=True)

        selected = scored[0][0]
        fallbacks = tuple(m for m, _ in scored[1:4])

        estimated_cost = self._estimate_cost(selected, complexity)
        reason = self._build_reason(selected, strategy, complexity)

        return RoutingDecision(
            selected_model=selected,
            strategy_used=strategy,
            reason=reason,
            estimated_cost=estimated_cost,
            estimated_latency_ms=selected.avg_latency_ms,
            fallback_models=fallbacks,
        )

    def record_usage(self, record: UsageRecord) -> None:
        self._usage.append(record)
        if not record.success:
            self._failure_counts[record.model_id] += 1

    def get_cost_summary(self, window_hours: int = 24) -> dict[str, Any]:
        cutoff = datetime.now(UTC) - timedelta(hours=window_hours)
        recent = [u for u in self._usage if u.timestamp >= cutoff]

        total_cost = sum(u.cost for u in recent)
        by_model: dict[str, float] = defaultdict(float)
        by_provider: dict[str, float] = defaultdict(float)

        for u in recent:
            by_model[u.model_id] += u.cost
            by_provider[u.provider.value] += u.cost

        return {
            "total_cost": total_cost,
            "request_count": len(recent),
            "by_model": dict(by_model),
            "by_provider": dict(by_provider),
            "avg_cost_per_request": total_cost / len(recent) if recent else 0.0,
            "budget_remaining_hourly": self._cost_policy.max_cost_per_hour - (
                total_cost / max(window_hours, 1)
            ),
        }

    def is_within_budget(self, estimated_cost: float) -> bool:
        hour_cutoff = datetime.now(UTC) - timedelta(hours=1)
        day_cutoff = datetime.now(UTC) - timedelta(hours=24)

        hour_spend = sum(u.cost for u in self._usage if u.timestamp >= hour_cutoff)
        day_spend = sum(u.cost for u in self._usage if u.timestamp >= day_cutoff)

        if estimated_cost > self._cost_policy.max_cost_per_request:
            return False
        if hour_spend + estimated_cost > self._cost_policy.max_cost_per_hour:
            return False
        if day_spend + estimated_cost > self._cost_policy.max_cost_per_day:
            return False
        return True

    def get_model_health(self, model_id: str) -> dict[str, Any]:
        recent = [
            u for u in self._usage
            if u.model_id == model_id
            and u.timestamp >= datetime.now(UTC) - timedelta(hours=1)
        ]
        if not recent:
            return {"status": "unknown", "requests": 0}

        successes = sum(1 for u in recent if u.success)
        avg_latency = sum(u.latency_ms for u in recent) / len(recent)

        return {
            "status": "healthy" if successes / len(recent) > 0.9 else "degraded",
            "requests": len(recent),
            "success_rate": successes / len(recent),
            "avg_latency_ms": avg_latency,
            "total_failures": self._failure_counts.get(model_id, 0),
        }

    def _filter_candidates(
        self,
        required_capabilities: list[ModelCapability],
        max_cost: float | None,
        max_latency_ms: float | None,
        exclude_models: list[str],
    ) -> list[ModelConfig]:
        candidates = []
        for model in self._models:
            if not model.is_available:
                continue
            if model.model_id in exclude_models:
                continue
            if required_capabilities:
                model_caps = set(model.capabilities)
                if not all(cap in model_caps for cap in required_capabilities):
                    continue
            if max_latency_ms and model.avg_latency_ms > max_latency_ms:
                continue
            candidates.append(model)
        return candidates

    def _score_candidates(
        self,
        candidates: list[ModelConfig],
        strategy: RoutingStrategy,
        complexity: TaskComplexity,
    ) -> list[tuple[ModelConfig, float]]:
        scored = []
        for model in candidates:
            score = self._compute_score(model, strategy, complexity)
            failure_penalty = self._failure_counts.get(model.model_id, 0) * 0.05
            score = max(0.0, score - failure_penalty)
            scored.append((model, score))
        return scored

    def _compute_score(
        self, model: ModelConfig, strategy: RoutingStrategy, complexity: TaskComplexity
    ) -> float:
        cost_score = 1.0 - min(1.0, model.cost_per_input_token * 1000)
        latency_score = 1.0 - min(1.0, model.avg_latency_ms / 10000)
        quality_score = model.quality_score

        if strategy == RoutingStrategy.CHEAPEST:
            return cost_score * 0.8 + quality_score * 0.15 + latency_score * 0.05
        elif strategy == RoutingStrategy.FASTEST:
            return latency_score * 0.8 + quality_score * 0.15 + cost_score * 0.05
        elif strategy == RoutingStrategy.BEST_QUALITY:
            return quality_score * 0.8 + latency_score * 0.1 + cost_score * 0.1
        elif strategy == RoutingStrategy.CAPABILITY_MATCH:
            cap_bonus = len(model.capabilities) * 0.05
            return quality_score * 0.5 + cap_bonus + latency_score * 0.2 + cost_score * 0.1
        else:
            complexity_weights = {
                TaskComplexity.TRIVIAL: (0.5, 0.3, 0.2),
                TaskComplexity.LOW: (0.4, 0.3, 0.3),
                TaskComplexity.MEDIUM: (0.33, 0.33, 0.34),
                TaskComplexity.HIGH: (0.2, 0.2, 0.6),
                TaskComplexity.CRITICAL: (0.1, 0.1, 0.8),
            }
            cw, lw, qw = complexity_weights.get(complexity, (0.33, 0.33, 0.34))
            return cost_score * cw + latency_score * lw + quality_score * qw

    def _estimate_cost(self, model: ModelConfig, complexity: TaskComplexity) -> float:
        token_estimates = {
            TaskComplexity.TRIVIAL: (500, 200),
            TaskComplexity.LOW: (2000, 500),
            TaskComplexity.MEDIUM: (5000, 1500),
            TaskComplexity.HIGH: (15000, 4000),
            TaskComplexity.CRITICAL: (50000, 8000),
        }
        input_tokens, output_tokens = token_estimates.get(complexity, (5000, 1500))
        return (
            input_tokens * model.cost_per_input_token
            + output_tokens * model.cost_per_output_token
        )

    def _build_reason(
        self, model: ModelConfig, strategy: RoutingStrategy, complexity: TaskComplexity
    ) -> str:
        return (
            f"Selected {model.display_name} ({model.provider.value}) "
            f"using {strategy.value} strategy for {complexity.value} complexity task"
        )
