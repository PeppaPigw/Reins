"""Tests for capability discovery and composition engine."""

from __future__ import annotations

import pytest

from reins.capabilities import (
    Capability,
    CapabilityProvider,
    CapabilityRegistry,
    CapabilityRequest,
    CapabilityStatus,
    CompositionMode,
    NegotiationOutcome,
)


@pytest.fixture
def registry() -> CapabilityRegistry:
    return CapabilityRegistry()


@pytest.fixture
def provider_a() -> CapabilityProvider:
    return CapabilityProvider(
        agent_id="agent-a",
        capabilities=(
            Capability(name="code_review", cost_per_call=0.05, avg_latency_ms=2000),
            Capability(name="testing", cost_per_call=0.02, avg_latency_ms=1000),
        ),
        priority=10,
    )


@pytest.fixture
def provider_b() -> CapabilityProvider:
    return CapabilityProvider(
        agent_id="agent-b",
        capabilities=(
            Capability(name="code_review", cost_per_call=0.10, avg_latency_ms=500),
            Capability(name="deployment", cost_per_call=0.01, avg_latency_ms=3000),
        ),
        priority=5,
    )


def test_register_provider(registry, provider_a):
    registry.register_provider(provider_a)
    assert registry.provider_count == 1
    assert "code_review" in registry.capability_names


def test_discover_capability(registry, provider_a, provider_b):
    registry.register_provider(provider_a)
    registry.register_provider(provider_b)
    providers = registry.discover("code_review")
    assert len(providers) == 2
    assert providers[0].priority >= providers[1].priority


def test_discover_nonexistent(registry):
    assert registry.discover("nonexistent") == []


def test_discover_with_status_filter(registry, provider_a):
    registry.register_provider(provider_a)
    busy_provider = CapabilityProvider(
        agent_id="agent-busy",
        capabilities=(Capability(name="code_review"),),
        status=CapabilityStatus.BUSY,
    )
    registry.register_provider(busy_provider)
    available = registry.discover("code_review", CapabilityStatus.AVAILABLE)
    assert len(available) == 1
    assert available[0].agent_id == "agent-a"


def test_unregister_provider(registry, provider_a):
    registry.register_provider(provider_a)
    assert registry.unregister_provider(provider_a.provider_id)
    assert registry.provider_count == 0
    assert registry.discover("code_review") == []


def test_unregister_nonexistent(registry):
    assert not registry.unregister_provider("nonexistent")


def test_negotiate_granted(registry, provider_a):
    registry.register_provider(provider_a)
    request = CapabilityRequest(requester_id="client-1", capability_name="code_review")
    result = registry.negotiate(request)
    assert result.outcome == NegotiationOutcome.GRANTED
    assert result.provider_id == provider_a.provider_id


def test_negotiate_denied_no_providers(registry):
    request = CapabilityRequest(requester_id="client-1", capability_name="nonexistent")
    result = registry.negotiate(request)
    assert result.outcome == NegotiationOutcome.DENIED


def test_negotiate_cost_constraint(registry, provider_a, provider_b):
    registry.register_provider(provider_a)
    registry.register_provider(provider_b)
    request = CapabilityRequest(
        requester_id="client-1",
        capability_name="code_review",
        max_cost=0.06,
    )
    result = registry.negotiate(request)
    assert result.outcome == NegotiationOutcome.GRANTED
    matched = [p for p in [provider_a, provider_b] if p.provider_id == result.provider_id]
    cap = next(c for c in matched[0].capabilities if c.name == "code_review")
    assert cap.cost_per_call <= 0.06


def test_negotiate_latency_constraint(registry, provider_a, provider_b):
    registry.register_provider(provider_a)
    registry.register_provider(provider_b)
    request = CapabilityRequest(
        requester_id="client-1",
        capability_name="code_review",
        max_latency_ms=1000,
    )
    result = registry.negotiate(request)
    assert result.outcome == NegotiationOutcome.GRANTED


def test_negotiate_preferred_provider(registry, provider_a, provider_b):
    registry.register_provider(provider_a)
    registry.register_provider(provider_b)
    request = CapabilityRequest(
        requester_id="client-1",
        capability_name="code_review",
        preferred_providers=("agent-b",),
    )
    result = registry.negotiate(request)
    assert result.outcome == NegotiationOutcome.GRANTED
    assert result.provider_id == provider_b.provider_id


def test_invoke_with_handler(registry):
    registry.register_handler("uppercase", lambda data: data.get("text", "").upper())
    result = registry.invoke("uppercase", {"text": "hello"})
    assert result.success
    assert result.output == "HELLO"
    assert result.latency_ms >= 0


def test_invoke_no_handler(registry):
    result = registry.invoke("missing", {})
    assert not result.success
    assert "No handler" in result.error


def test_invoke_handler_error(registry):
    registry.register_handler("broken", lambda data: 1 / 0)
    result = registry.invoke("broken", {})
    assert not result.success
    assert "division by zero" in result.error


def test_compose_sequential(registry):
    registry.register_handler("step1", lambda d: {"val": d.get("val", 0) + 1})
    registry.register_handler("step2", lambda d: {"val": d.get("val", 0) + 10})

    registry.compose("pipeline", CompositionMode.SEQUENTIAL, ["step1", "step2"])
    results = registry.invoke_composed("pipeline", {"val": 0})
    assert len(results) == 2
    assert all(r.success for r in results)


def test_compose_parallel(registry):
    registry.register_handler("fast", lambda d: "fast_result")
    registry.register_handler("slow", lambda d: "slow_result")

    registry.compose("both", CompositionMode.PARALLEL, ["fast", "slow"])
    results = registry.invoke_composed("both", {})
    assert len(results) == 2
    assert all(r.success for r in results)


def test_compose_fallback(registry):
    registry.register_handler("primary", lambda d: 1 / 0)
    registry.register_handler("backup", lambda d: "recovered")

    registry.compose("resilient", CompositionMode.FALLBACK, ["primary", "backup"])
    results = registry.invoke_composed("resilient", {})
    assert len(results) == 2
    assert not results[0].success
    assert results[1].success
    assert results[1].output == "recovered"


def test_compose_fallback_stops_on_success(registry):
    registry.register_handler("works", lambda d: "ok")
    registry.register_handler("never_called", lambda d: "nope")

    registry.compose("early_exit", CompositionMode.FALLBACK, ["works", "never_called"])
    results = registry.invoke_composed("early_exit", {})
    assert len(results) == 1
    assert results[0].success


def test_invoke_composed_nonexistent(registry):
    results = registry.invoke_composed("nonexistent", {})
    assert len(results) == 1
    assert not results[0].success


def test_get_stats(registry, provider_a):
    registry.register_provider(provider_a)
    registry.register_handler("code_review", lambda d: "reviewed")
    registry.invoke("code_review", {})
    registry.invoke("code_review", {})

    stats = registry.get_stats()
    assert stats["total_invocations"] == 2
    assert stats["success_rate"] == 1.0
    assert stats["providers"] == 1
