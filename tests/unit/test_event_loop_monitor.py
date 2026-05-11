"""Tests for event loop starvation detection and monitoring."""

from __future__ import annotations

import asyncio
import time

import pytest

from reins.observability.event_loop import (
    EventLoopHealth,
    EventLoopMonitor,
    StarvationEvent,
    detect_blocking_call,
)


@pytest.mark.asyncio
async def test_monitor_starts_and_stops() -> None:
    """Monitor can be started and stopped cleanly."""
    monitor = EventLoopMonitor(threshold_ms=100.0, check_interval_ms=20.0)
    assert not monitor.is_running

    await monitor.start()
    assert monitor.is_running

    await monitor.stop()
    assert not monitor.is_running


@pytest.mark.asyncio
async def test_monitor_detects_starvation() -> None:
    """Monitor detects when the event loop is blocked beyond threshold."""
    monitor = EventLoopMonitor(threshold_ms=20.0, check_interval_ms=10.0)
    await monitor.start()

    # Give the monitor a cycle to establish baseline
    await asyncio.sleep(0.03)

    # Block the event loop with a synchronous sleep
    time.sleep(0.05)

    # Allow the monitor to detect the starvation
    await asyncio.sleep(0.05)

    await monitor.stop()

    events = monitor.get_starvation_events()
    assert len(events) >= 1
    assert events[0].delay_ms > 20.0


@pytest.mark.asyncio
async def test_monitor_no_false_positives() -> None:
    """Normal async operations do not trigger starvation detection."""
    monitor = EventLoopMonitor(threshold_ms=100.0, check_interval_ms=10.0)
    await monitor.start()

    # Only do non-blocking async work
    for _ in range(5):
        await asyncio.sleep(0.01)

    await monitor.stop()

    events = monitor.get_starvation_events()
    assert len(events) == 0


def test_starvation_event_has_fields() -> None:
    """StarvationEvent dataclass has all expected fields."""
    event = StarvationEvent(
        timestamp=time.time(),
        delay_ms=150.0,
        threshold_ms=100.0,
        context="test context",
    )
    assert event.timestamp > 0
    assert event.delay_ms == 150.0
    assert event.threshold_ms == 100.0
    assert event.context == "test context"


@pytest.mark.asyncio
async def test_health_reports_healthy_when_no_starvation() -> None:
    """Health status is healthy when no starvation has been detected."""
    monitor = EventLoopMonitor(threshold_ms=100.0, check_interval_ms=10.0)
    await monitor.start()
    await asyncio.sleep(0.03)
    await monitor.stop()

    health = monitor.get_health()
    assert health.is_healthy is True
    assert health.starvation_count == 0
    assert health.last_starvation is None


@pytest.mark.asyncio
async def test_health_reports_unhealthy_after_starvation() -> None:
    """Health status is unhealthy after starvation is detected."""
    monitor = EventLoopMonitor(threshold_ms=20.0, check_interval_ms=10.0)
    await monitor.start()

    await asyncio.sleep(0.03)
    time.sleep(0.05)
    await asyncio.sleep(0.05)

    await monitor.stop()

    health = monitor.get_health()
    assert health.is_healthy is False
    assert health.starvation_count >= 1
    assert health.last_starvation is not None
    assert health.last_starvation.delay_ms > 20.0


@pytest.mark.asyncio
async def test_callback_invoked_on_starvation() -> None:
    """Callback function is called when starvation is detected."""
    received_events: list[StarvationEvent] = []

    def on_starvation(event: StarvationEvent) -> None:
        received_events.append(event)

    monitor = EventLoopMonitor(
        threshold_ms=20.0, check_interval_ms=10.0, callback=on_starvation
    )
    await monitor.start()

    await asyncio.sleep(0.03)
    time.sleep(0.05)
    await asyncio.sleep(0.05)

    await monitor.stop()

    assert len(received_events) >= 1
    assert received_events[0].delay_ms > 20.0


@pytest.mark.asyncio
async def test_get_starvation_events_returns_history() -> None:
    """get_starvation_events returns all historical events."""
    monitor = EventLoopMonitor(threshold_ms=20.0, check_interval_ms=10.0)
    await monitor.start()

    # Trigger multiple starvation events
    await asyncio.sleep(0.03)
    time.sleep(0.05)
    await asyncio.sleep(0.05)
    time.sleep(0.05)
    await asyncio.sleep(0.05)

    await monitor.stop()

    events = monitor.get_starvation_events()
    assert len(events) >= 1
    # Each event should have proper fields
    for event in events:
        assert event.delay_ms > 0
        assert event.threshold_ms == 20.0
        assert event.timestamp > 0


@pytest.mark.asyncio
async def test_reset_clears_history() -> None:
    """reset() clears starvation history and metrics."""
    monitor = EventLoopMonitor(threshold_ms=20.0, check_interval_ms=10.0)
    await monitor.start()

    await asyncio.sleep(0.03)
    time.sleep(0.05)
    await asyncio.sleep(0.05)

    await monitor.stop()

    assert len(monitor.get_starvation_events()) >= 1
    assert monitor.get_health().max_delay_ms > 0

    monitor.reset()

    assert len(monitor.get_starvation_events()) == 0
    health = monitor.get_health()
    assert health.is_healthy is True
    assert health.max_delay_ms == 0.0
    assert health.starvation_count == 0


def test_detect_blocking_call_warns_on_slow(capsys: pytest.CaptureFixture[str]) -> None:
    """detect_blocking_call logs a warning when block exceeds threshold."""
    with detect_blocking_call(threshold_ms=10.0):
        time.sleep(0.03)

    captured = capsys.readouterr()
    assert "blocking_call_detected" in captured.out


def test_detect_blocking_call_silent_on_fast(capsys: pytest.CaptureFixture[str]) -> None:
    """detect_blocking_call does not warn when block is fast."""
    with detect_blocking_call(threshold_ms=100.0):
        time.sleep(0.001)

    captured = capsys.readouterr()
    assert "blocking_call_detected" not in captured.out


@pytest.mark.asyncio
async def test_custom_threshold_configuration() -> None:
    """Monitor respects custom threshold configuration."""
    # High threshold should not trigger on small delays
    monitor = EventLoopMonitor(threshold_ms=500.0, check_interval_ms=10.0)
    await monitor.start()

    await asyncio.sleep(0.03)
    time.sleep(0.02)  # 20ms block, well under 500ms threshold
    await asyncio.sleep(0.03)

    await monitor.stop()

    events = monitor.get_starvation_events()
    assert len(events) == 0
