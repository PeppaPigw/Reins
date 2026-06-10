"""Tests for stigmergy engine."""

from __future__ import annotations

import pytest

from reins.stigmergy import (
    DecayModel,
    StigmergyEngine,
    Trace,
    TraceKind,
)


@pytest.fixture
def engine() -> StigmergyEngine:
    return StigmergyEngine(decay_model=DecayModel.EXPONENTIAL, decay_rate=0.1)


def test_deposit_trace(engine):
    trace = engine.deposit("agent-1", TraceKind.SUCCESS, "src/main.py")
    assert trace.agent_id == "agent-1"
    assert trace.kind == TraceKind.SUCCESS
    assert trace.intensity == 1.0


def test_deposit_reinforces(engine):
    engine.deposit("a", TraceKind.SUCCESS, "path/file.py", intensity=1.0)
    trace = engine.deposit("a", TraceKind.SUCCESS, "path/file.py", intensity=0.5)
    assert trace.intensity > 1.0


def test_sense_at_location(engine):
    engine.deposit("a", TraceKind.SUCCESS, "loc1")
    engine.deposit("b", TraceKind.FAILURE, "loc1")
    engine.deposit("c", TraceKind.SUCCESS, "loc2")
    traces = engine.sense("loc1")
    assert len(traces) == 2


def test_sense_by_kind(engine):
    engine.deposit("a", TraceKind.SUCCESS, "loc")
    engine.deposit("b", TraceKind.FAILURE, "loc")
    traces = engine.sense("loc", kind=TraceKind.SUCCESS)
    assert len(traces) == 1


def test_sense_min_intensity(engine):
    engine.deposit("a", TraceKind.SUCCESS, "loc", intensity=0.5)
    engine.deposit("b", TraceKind.SUCCESS, "loc", intensity=0.1)
    traces = engine.sense("loc", min_intensity=0.3)
    assert len(traces) == 1


def test_get_intensity_at(engine):
    engine.deposit("a", TraceKind.SUCCESS, "loc", intensity=0.5)
    engine.deposit("b", TraceKind.SUCCESS, "loc", intensity=0.3)
    total = engine.get_intensity_at("loc")
    assert total == pytest.approx(0.8, abs=0.01)


def test_get_gradient(engine):
    engine.deposit("a", TraceKind.SUCCESS, "hot", intensity=5.0)
    engine.deposit("b", TraceKind.SUCCESS, "warm", intensity=2.0)
    engine.deposit("c", TraceKind.SUCCESS, "cold", intensity=0.5)
    gradient = engine.get_gradient(["cold", "hot", "warm"])
    assert gradient[0][0] == "hot"
    assert gradient[-1][0] == "cold"


def test_decay_reduces_intensity(engine):
    engine.deposit("a", TraceKind.SUCCESS, "loc", intensity=1.0)
    engine.decay(elapsed_seconds=2.0)
    traces = engine.sense("loc")
    assert traces[0].intensity < 1.0


def test_decay_evaporates(engine):
    engine.deposit("a", TraceKind.SUCCESS, "loc", intensity=0.02)
    evaporated = engine.decay(elapsed_seconds=10.0)
    assert evaporated == 1
    assert engine.sense("loc") == []


def test_decay_none_model():
    e = StigmergyEngine(decay_model=DecayModel.NONE)
    e.deposit("a", TraceKind.SUCCESS, "loc", intensity=1.0)
    e.decay(elapsed_seconds=100.0)
    traces = e.sense("loc")
    assert traces[0].intensity == 1.0


def test_linear_decay():
    e = StigmergyEngine(decay_model=DecayModel.LINEAR, decay_rate=0.5)
    e.deposit("a", TraceKind.SUCCESS, "loc", intensity=1.0)
    e.decay(elapsed_seconds=1.0)
    traces = e.sense("loc")
    assert traces[0].intensity == pytest.approx(0.5, abs=0.01)


def test_sense_nearby(engine):
    engine.deposit("a", TraceKind.SUCCESS, "src/main.py")
    engine.deposit("b", TraceKind.SUCCESS, "src/utils.py")
    engine.deposit("c", TraceKind.SUCCESS, "tests/test.py")
    nearby = engine.sense_nearby("src/main.py", radius=2)
    assert len(nearby) >= 2


def test_get_hotspots(engine):
    for _ in range(5):
        engine.deposit("a", TraceKind.SUCCESS, "hot_spot", intensity=2.0)
    engine.deposit("b", TraceKind.SUCCESS, "cold_spot", intensity=0.1)
    hotspots = engine.get_hotspots(top_n=1)
    assert hotspots[0][0] == "hot_spot"


def test_payload_preserved(engine):
    trace = engine.deposit("a", TraceKind.RECOMMENDATION, "loc",
                           payload={"tool": "grep", "confidence": 0.9})
    assert trace.payload["tool"] == "grep"


def test_stats_empty():
    e = StigmergyEngine()
    stats = e.get_stats()
    assert stats.total_traces == 0
    assert stats.active_traces == 0


def test_stats_with_data(engine):
    engine.deposit("a", TraceKind.SUCCESS, "loc1")
    engine.deposit("b", TraceKind.FAILURE, "loc2")
    engine.deposit("c", TraceKind.SUCCESS, "loc1")
    stats = engine.get_stats()
    assert stats.active_traces == 3
    assert "success" in stats.by_kind
    assert len(stats.hotspots) >= 1
