"""Event loop starvation detection and monitoring.

Detects when the asyncio event loop is blocked beyond a configurable threshold,
reports starvation events, and provides health status for the runtime.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class StarvationEvent:
    """Record of a detected event loop starvation incident."""

    timestamp: float
    delay_ms: float
    threshold_ms: float
    context: str


@dataclass(frozen=True)
class EventLoopHealth:
    """Current health status of the event loop."""

    is_healthy: bool
    current_delay_ms: float
    max_delay_ms: float
    starvation_count: int
    last_starvation: StarvationEvent | None


class EventLoopMonitor:
    """Background monitor that detects event loop starvation.

    Periodically schedules a callback and measures the actual delay versus the
    expected delay. If the measured delay exceeds the threshold, a StarvationEvent
    is emitted and the optional callback is invoked.
    """

    def __init__(
        self,
        threshold_ms: float = 100.0,
        check_interval_ms: float = 50.0,
        callback: Callable[[StarvationEvent], None] | None = None,
    ) -> None:
        self._threshold_ms = threshold_ms
        self._check_interval = check_interval_ms / 1000.0
        self._callback = callback
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._starvation_events: list[StarvationEvent] = []
        self._max_delay_ms: float = 0.0
        self._last_check: float = 0.0
        self._current_delay_ms: float = 0.0

    async def start(self) -> None:
        """Start the monitoring loop as a background asyncio task."""
        if self._running:
            return
        self._running = True
        self._last_check = time.monotonic()
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """Stop the monitoring loop and cancel the background task."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _monitor_loop(self) -> None:
        """Periodically check event loop responsiveness."""
        while self._running:
            expected_wake = time.monotonic() + self._check_interval
            await asyncio.sleep(self._check_interval)

            now = time.monotonic()
            actual_delay_ms = (now - expected_wake) * 1000.0
            # The total delay includes the sleep overshoot
            total_delay_ms = (now - self._last_check) * 1000.0 - (self._check_interval * 1000.0)
            self._last_check = now

            # Use the overshoot as the meaningful delay metric
            delay = max(actual_delay_ms, 0.0)
            self._current_delay_ms = delay
            self._max_delay_ms = max(self._max_delay_ms, delay)

            if delay > self._threshold_ms:
                event = StarvationEvent(
                    timestamp=time.time(),
                    delay_ms=delay,
                    threshold_ms=self._threshold_ms,
                    context=f"Event loop blocked for {delay:.1f}ms (threshold: {self._threshold_ms:.1f}ms)",
                )
                self._starvation_events.append(event)
                logger.warning(
                    "event_loop_starvation_detected",
                    delay_ms=delay,
                    threshold_ms=self._threshold_ms,
                )
                if self._callback is not None:
                    self._callback(event)

    def get_health(self) -> EventLoopHealth:
        """Return current health status of the event loop."""
        last = self._starvation_events[-1] if self._starvation_events else None
        return EventLoopHealth(
            is_healthy=len(self._starvation_events) == 0,
            current_delay_ms=self._current_delay_ms,
            max_delay_ms=self._max_delay_ms,
            starvation_count=len(self._starvation_events),
            last_starvation=last,
        )

    def get_starvation_events(self) -> list[StarvationEvent]:
        """Return all detected starvation events."""
        return list(self._starvation_events)

    def reset(self) -> None:
        """Clear starvation history and reset metrics."""
        self._starvation_events.clear()
        self._max_delay_ms = 0.0
        self._current_delay_ms = 0.0

    @property
    def is_running(self) -> bool:
        """Return True if the monitor is currently active."""
        return self._running


@contextmanager
def detect_blocking_call(
    threshold_ms: float = 50.0,
) -> Generator[None, None, None]:
    """Context manager that warns if a block takes longer than threshold.

    Use this to wrap suspected blocking calls in async code to detect
    synchronous operations that starve the event loop.
    """
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        if elapsed_ms > threshold_ms:
            logger.warning(
                "blocking_call_detected",
                elapsed_ms=round(elapsed_ms, 2),
                threshold_ms=threshold_ms,
            )
