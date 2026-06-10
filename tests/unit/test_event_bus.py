"""Tests for async event bus."""

from __future__ import annotations

import pytest

from reins.event_bus import (
    BusEvent,
    DeliveryGuarantee,
    EventBus,
    EventPriority,
)


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.mark.asyncio
async def test_publish_and_subscribe(bus):
    received = []
    bus.subscribe("agent.*", "listener-1", lambda e: received.append(e))
    await bus.publish("agent.started", "kernel")
    assert len(received) == 1
    assert received[0].topic == "agent.started"


@pytest.mark.asyncio
async def test_topic_pattern_matching(bus):
    received = []
    bus.subscribe("safety.*", "s1", lambda e: received.append(e))
    await bus.publish("safety.gate.passed", "kernel")
    await bus.publish("agent.started", "kernel")
    assert len(received) == 1


@pytest.mark.asyncio
async def test_multiple_subscribers(bus):
    r1, r2 = [], []
    bus.subscribe("*", "s1", lambda e: r1.append(e))
    bus.subscribe("*", "s2", lambda e: r2.append(e))
    await bus.publish("test", "src")
    assert len(r1) == 1
    assert len(r2) == 1


@pytest.mark.asyncio
async def test_filter_fn(bus):
    received = []
    bus.subscribe("*", "s1", lambda e: received.append(e),
                  filter_fn=lambda e: e.payload.get("important", False))
    await bus.publish("test", "src", {"important": True})
    await bus.publish("test", "src", {"important": False})
    assert len(received) == 1


@pytest.mark.asyncio
async def test_unsubscribe(bus):
    received = []
    sub = bus.subscribe("*", "s1", lambda e: received.append(e))
    await bus.publish("a", "src")
    bus.unsubscribe(sub.sub_id)
    await bus.publish("b", "src")
    assert len(received) == 1


@pytest.mark.asyncio
async def test_async_handler(bus):
    received = []

    async def handler(e: BusEvent):
        received.append(e)

    bus.subscribe("*", "s1", handler)
    await bus.publish("test", "src")
    assert len(received) == 1


@pytest.mark.asyncio
async def test_dead_letter_on_failure(bus):
    def bad_handler(e):
        raise RuntimeError("boom")

    bus.subscribe("*", "s1", bad_handler)
    await bus.publish("test", "src")
    dls = bus.get_dead_letters()
    assert len(dls) == 1
    assert dls[0].error == "boom"


@pytest.mark.asyncio
async def test_dead_letter_retries():
    bus = EventBus(max_retries=2)
    calls = []

    def flaky(e):
        calls.append(1)
        raise RuntimeError("fail")

    bus.subscribe("*", "s1", flaky)
    await bus.publish("test", "src")
    assert len(calls) == 2
    assert len(bus.get_dead_letters()) == 1


@pytest.mark.asyncio
async def test_correlation_and_causation(bus):
    received = []
    bus.subscribe("*", "s1", lambda e: received.append(e))
    await bus.publish("test", "src", correlation_id="corr-1", causation_id="cause-1")
    assert received[0].correlation_id == "corr-1"
    assert received[0].causation_id == "cause-1"


@pytest.mark.asyncio
async def test_replay(bus):
    await bus.publish("a", "src")
    await bus.publish("b", "src")
    await bus.publish("a.sub", "src")
    all_events = bus.replay()
    assert len(all_events) == 3
    a_events = bus.replay("a*")
    assert len(a_events) == 2


@pytest.mark.asyncio
async def test_replay_since(bus):
    await bus.publish("a", "src")
    await bus.publish("b", "src")
    events = bus.replay(since=1)
    assert len(events) == 1
    assert events[0].topic == "b"


def test_publish_sync(bus):
    received = []
    bus.subscribe("*", "s1", lambda e: received.append(e))
    bus.publish_sync("test", "src", {"key": "val"})
    assert len(received) == 1
    assert received[0].payload["key"] == "val"


@pytest.mark.asyncio
async def test_publish_batch(bus):
    received = []
    bus.subscribe("*", "s1", lambda e: received.append(e))
    events = await bus.publish_batch([
        ("a", "src", {}),
        ("b", "src", {"x": 1}),
    ])
    assert len(events) == 2
    assert len(received) == 2


@pytest.mark.asyncio
async def test_priority(bus):
    received = []
    bus.subscribe("*", "s1", lambda e: received.append(e))
    await bus.publish("alert", "src", priority=EventPriority.CRITICAL)
    assert received[0].priority == EventPriority.CRITICAL


@pytest.mark.asyncio
async def test_stats(bus):
    received = []
    bus.subscribe("a.*", "s1", lambda e: received.append(e))
    await bus.publish("a.1", "src")
    await bus.publish("a.2", "src")
    await bus.publish("b.1", "src")
    stats = bus.get_stats()
    assert stats.total_published == 3
    assert stats.total_delivered == 2
    assert stats.active_subscriptions == 1
    assert stats.topics == 3


@pytest.mark.asyncio
async def test_dead_letter_by_subscriber(bus):
    def bad(e):
        raise ValueError("oops")

    bus.subscribe("*", "bad-sub", bad)
    bus.subscribe("*", "good-sub", lambda e: None)
    await bus.publish("test", "src")
    assert len(bus.get_dead_letters("bad-sub")) == 1
    assert len(bus.get_dead_letters("good-sub")) == 0
