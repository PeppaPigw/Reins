"""Tests for multi-model orchestration and routing."""

from __future__ import annotations

import pytest

from reins.models import (
    CostPolicy,
    ModelCapability,
    ModelConfig,
    ModelProvider,
    ModelRegistry,
    ModelRouter,
    RoutingDecision,
    RoutingStrategy,
    TaskComplexity,
    UsageRecord,
)


def _make_model(
    model_id: str = "test-model",
    provider: ModelProvider = ModelProvider.ANTHROPIC,
    capabilities: tuple[ModelCapability, ...] = (),
    cost_input: float = 0.003,
    cost_output: float = 0.015,
    latency: float = 1000.0,
    quality: float = 0.9,
    available: bool = True,
) -> ModelConfig:
    return ModelConfig(
        model_id=model_id,
        provider=provider,
        display_name=model_id,
        capabilities=capabilities,
        cost_per_input_token=cost_input,
        cost_per_output_token=cost_output,
        avg_latency_ms=latency,
        quality_score=quality,
        is_available=available,
    )


@pytest.fixture
def router() -> ModelRouter:
    registry = ModelRegistry(
        models=(
            _make_model("claude-opus", ModelProvider.ANTHROPIC,
                        (ModelCapability.REASONING, ModelCapability.CODE_GENERATION, ModelCapability.TOOL_USE),
                        cost_input=0.015, cost_output=0.075, latency=3000, quality=0.98),
            _make_model("claude-sonnet", ModelProvider.ANTHROPIC,
                        (ModelCapability.CODE_GENERATION, ModelCapability.TOOL_USE, ModelCapability.FAST_RESPONSE),
                        cost_input=0.003, cost_output=0.015, latency=1000, quality=0.92),
            _make_model("gpt-4o", ModelProvider.OPENAI,
                        (ModelCapability.REASONING, ModelCapability.VISION, ModelCapability.TOOL_USE),
                        cost_input=0.005, cost_output=0.015, latency=1500, quality=0.93),
            _make_model("gemini-pro", ModelProvider.GOOGLE,
                        (ModelCapability.LONG_CONTEXT, ModelCapability.FAST_RESPONSE),
                        cost_input=0.001, cost_output=0.002, latency=800, quality=0.85),
            _make_model("local-llama", ModelProvider.LOCAL,
                        (ModelCapability.FAST_RESPONSE,),
                        cost_input=0.0, cost_output=0.0, latency=200, quality=0.7),
        ),
        default_strategy=RoutingStrategy.BALANCED,
    )
    return ModelRouter(registry)


def test_route_returns_decision(router):
    decision = router.route()
    assert isinstance(decision, RoutingDecision)
    assert decision.selected_model is not None
    assert decision.strategy_used == RoutingStrategy.BALANCED


def test_cheapest_strategy_prefers_low_cost(router):
    decision = router.route(strategy=RoutingStrategy.CHEAPEST)
    assert decision.selected_model.model_id == "local-llama"


def test_fastest_strategy_prefers_low_latency(router):
    decision = router.route(strategy=RoutingStrategy.FASTEST)
    assert decision.selected_model.model_id == "local-llama"


def test_best_quality_strategy_prefers_high_quality(router):
    decision = router.route(strategy=RoutingStrategy.BEST_QUALITY)
    assert decision.selected_model.model_id == "claude-opus"


def test_capability_match_filters_models(router):
    decision = router.route(
        required_capabilities=[ModelCapability.REASONING, ModelCapability.TOOL_USE],
        strategy=RoutingStrategy.CAPABILITY_MATCH,
    )
    assert ModelCapability.REASONING in decision.selected_model.capabilities
    assert ModelCapability.TOOL_USE in decision.selected_model.capabilities


def test_exclude_models(router):
    decision = router.route(
        strategy=RoutingStrategy.CHEAPEST,
        exclude_models=["local-llama", "gemini-pro"],
    )
    assert decision.selected_model.model_id not in ("local-llama", "gemini-pro")


def test_prefer_provider(router):
    decision = router.route(
        strategy=RoutingStrategy.BALANCED,
        prefer_provider=ModelProvider.OPENAI,
    )
    assert decision.selected_model.provider == ModelProvider.OPENAI


def test_fallback_models_populated(router):
    decision = router.route()
    assert len(decision.fallback_models) > 0
    assert len(decision.fallback_models) <= 3


def test_complexity_affects_quality_weight(router):
    trivial = router.route(complexity=TaskComplexity.TRIVIAL, strategy=RoutingStrategy.BALANCED)
    critical = router.route(complexity=TaskComplexity.CRITICAL, strategy=RoutingStrategy.BALANCED)
    assert critical.selected_model.quality_score >= trivial.selected_model.quality_score


def test_estimated_cost_scales_with_complexity(router):
    low = router.route(complexity=TaskComplexity.LOW, strategy=RoutingStrategy.BEST_QUALITY)
    high = router.route(complexity=TaskComplexity.HIGH, strategy=RoutingStrategy.BEST_QUALITY)
    assert high.estimated_cost > low.estimated_cost


def test_record_usage_tracks_costs(router):
    router.record_usage(UsageRecord(
        model_id="claude-sonnet", provider=ModelProvider.ANTHROPIC,
        input_tokens=1000, output_tokens=500, cost=0.01, latency_ms=900, success=True,
    ))
    summary = router.get_cost_summary()
    assert summary["total_cost"] == 0.01
    assert summary["request_count"] == 1


def test_failure_penalizes_model(router):
    for _ in range(20):
        router.record_usage(UsageRecord(
            model_id="local-llama", provider=ModelProvider.LOCAL,
            input_tokens=100, output_tokens=50, cost=0.0, latency_ms=200, success=False,
        ))
    decision = router.route(strategy=RoutingStrategy.CHEAPEST)
    assert decision.selected_model.model_id != "local-llama"


def test_budget_check(router):
    assert router.is_within_budget(0.5)
    assert not router.is_within_budget(2.0)


def test_model_health_unknown_when_no_usage(router):
    health = router.get_model_health("claude-opus")
    assert health["status"] == "unknown"


def test_model_health_after_usage(router):
    for _ in range(5):
        router.record_usage(UsageRecord(
            model_id="claude-sonnet", provider=ModelProvider.ANTHROPIC,
            input_tokens=1000, output_tokens=500, cost=0.01, latency_ms=900, success=True,
        ))
    health = router.get_model_health("claude-sonnet")
    assert health["status"] == "healthy"
    assert health["success_rate"] == 1.0


def test_register_and_unregister_model(router):
    new_model = _make_model("mistral-large", ModelProvider.MISTRAL, quality=0.88)
    router.register_model(new_model)
    decision = router.route(prefer_provider=ModelProvider.MISTRAL)
    assert decision.selected_model.model_id == "mistral-large"

    router.unregister_model("mistral-large")
    decision = router.route(prefer_provider=ModelProvider.MISTRAL)
    assert decision.selected_model.provider != ModelProvider.MISTRAL


def test_no_available_models_raises():
    registry = ModelRegistry(models=(
        _make_model("offline", available=False),
    ))
    router = ModelRouter(registry)
    with pytest.raises(ValueError, match="No available models"):
        router.route()


def test_max_latency_filter(router):
    decision = router.route(max_latency_ms=1000)
    assert decision.selected_model.avg_latency_ms <= 1000
