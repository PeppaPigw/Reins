"""Tests for unified safety kernel pipeline."""

from __future__ import annotations

import pytest

from reins.safety_kernel import (
    GateResult,
    GateStage,
    GateVerdict,
    PipelineResult,
    SafetyKernel,
    SafetyKernelStats,
)


@pytest.fixture
def kernel() -> SafetyKernel:
    return SafetyKernel()


def test_evaluate_no_gates_allows(kernel):
    result = kernel.evaluate({"agent": "a"})
    assert result.final_verdict == GateVerdict.ALLOW
    assert len(result.gates) == 5


def test_register_and_evaluate_allow(kernel):
    kernel.register_gate(GateStage.IDENTITY, lambda ctx: GateVerdict.ALLOW)
    result = kernel.evaluate({"agent": "a"})
    assert result.final_verdict == GateVerdict.ALLOW


def test_deny_short_circuits(kernel):
    kernel.register_gate(GateStage.IDENTITY, lambda ctx: GateVerdict.DENY)
    kernel.register_gate(GateStage.PROTOCOL, lambda ctx: GateVerdict.ALLOW)
    result = kernel.evaluate({"agent": "a"})
    assert result.final_verdict == GateVerdict.DENY
    assert result.denied_at == GateStage.IDENTITY
    assert len(result.gates) == 1


def test_escalate_continues(kernel):
    kernel.register_gate(GateStage.IDENTITY, lambda ctx: GateVerdict.ALLOW)
    kernel.register_gate(GateStage.PROTOCOL, lambda ctx: GateVerdict.ESCALATE)
    kernel.register_gate(GateStage.COMPOSABILITY, lambda ctx: GateVerdict.ALLOW)
    result = kernel.evaluate({"agent": "a"})
    assert result.final_verdict == GateVerdict.ESCALATE
    assert result.denied_at is None


def test_gate_exception_denies(kernel):
    def bad_gate(ctx):
        raise RuntimeError("crash")
    kernel.register_gate(GateStage.INVARIANTS, bad_gate)
    result = kernel.evaluate({})
    assert result.final_verdict == GateVerdict.DENY
    assert result.denied_at == GateStage.INVARIANTS
    assert "Gate error" in result.gates[-1].message


def test_remove_gate(kernel):
    kernel.register_gate(GateStage.IDENTITY, lambda ctx: GateVerdict.DENY)
    assert kernel.remove_gate(GateStage.IDENTITY) is True
    result = kernel.evaluate({})
    assert result.final_verdict == GateVerdict.ALLOW


def test_remove_nonexistent(kernel):
    assert kernel.remove_gate(GateStage.ENVELOPE) is False


def test_stage_order_respected(kernel):
    order = []
    kernel.register_gate(GateStage.ENVELOPE,
                         lambda ctx: (order.append("envelope"), GateVerdict.ALLOW)[1])
    kernel.register_gate(GateStage.IDENTITY,
                         lambda ctx: (order.append("identity"), GateVerdict.ALLOW)[1])
    kernel.register_gate(GateStage.COMPOSABILITY,
                         lambda ctx: (order.append("composability"), GateVerdict.ALLOW)[1])
    kernel.evaluate({})
    assert order == ["identity", "composability", "envelope"]


def test_context_passed_to_gates(kernel):
    received = {}

    def capture(ctx):
        received.update(ctx)
        return GateVerdict.ALLOW

    kernel.register_gate(GateStage.IDENTITY, capture)
    kernel.evaluate({"agent": "test-agent", "action": "write"})
    assert received["agent"] == "test-agent"
    assert received["action"] == "write"


def test_evaluate_batch(kernel):
    kernel.register_gate(GateStage.IDENTITY,
                         lambda ctx: GateVerdict.DENY if ctx.get("bad") else GateVerdict.ALLOW)
    results = kernel.evaluate_batch([{"bad": False}, {"bad": True}, {"bad": False}])
    assert len(results) == 3
    assert results[0].final_verdict == GateVerdict.ALLOW
    assert results[1].final_verdict == GateVerdict.DENY
    assert results[2].final_verdict == GateVerdict.ALLOW


def test_get_results_filter(kernel):
    kernel.register_gate(GateStage.IDENTITY,
                         lambda ctx: GateVerdict.DENY if ctx.get("deny") else GateVerdict.ALLOW)
    kernel.evaluate({"deny": False})
    kernel.evaluate({"deny": True})
    assert len(kernel.get_results()) == 2
    assert len(kernel.get_results(verdict=GateVerdict.ALLOW)) == 1
    assert len(kernel.get_results(verdict=GateVerdict.DENY)) == 1


def test_stats_empty(kernel):
    stats = kernel.get_stats()
    assert stats.total_evaluations == 0


def test_stats_populated(kernel):
    kernel.register_gate(GateStage.IDENTITY,
                         lambda ctx: GateVerdict.DENY if ctx.get("deny") else GateVerdict.ALLOW)
    kernel.evaluate({"deny": False})
    kernel.evaluate({"deny": True})
    kernel.evaluate({"deny": False})
    stats = kernel.get_stats()
    assert stats.total_evaluations == 3
    assert stats.allowed == 2
    assert stats.denied == 1
    assert stats.denial_by_stage["identity"] == 1
    assert stats.avg_duration_ms > 0


def test_duration_tracked(kernel):
    kernel.register_gate(GateStage.IDENTITY, lambda ctx: GateVerdict.ALLOW)
    result = kernel.evaluate({})
    assert result.total_duration_ms >= 0
    for gate in result.gates:
        if gate.stage == GateStage.IDENTITY:
            assert gate.duration_ms >= 0


def test_full_pipeline_all_stages(kernel):
    for stage in GateStage:
        kernel.register_gate(stage, lambda ctx: GateVerdict.ALLOW)
    result = kernel.evaluate({"agent": "a"})
    assert result.final_verdict == GateVerdict.ALLOW
    assert len(result.gates) == 5


def test_deny_at_last_stage(kernel):
    kernel.register_gate(GateStage.IDENTITY, lambda ctx: GateVerdict.ALLOW)
    kernel.register_gate(GateStage.PROTOCOL, lambda ctx: GateVerdict.ALLOW)
    kernel.register_gate(GateStage.COMPOSABILITY, lambda ctx: GateVerdict.ALLOW)
    kernel.register_gate(GateStage.INVARIANTS, lambda ctx: GateVerdict.ALLOW)
    kernel.register_gate(GateStage.ENVELOPE, lambda ctx: GateVerdict.DENY)
    result = kernel.evaluate({})
    assert result.final_verdict == GateVerdict.DENY
    assert result.denied_at == GateStage.ENVELOPE
    assert len(result.gates) == 5
