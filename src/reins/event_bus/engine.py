from __future__ import annotations

import asyncio
import fnmatch
from collections import defaultdict
from typing import Any, Awaitable, Callable

from reins.event_bus.types import (
    BusEvent,
    DeadLetter,
    DeliveryGuarantee,
    EventBusStats,
    EventPriority,
    Subscription,
)

AsyncHandler = Callable[[BusEvent], Awaitable[None]]
SyncHandler = Callable[[BusEvent], None]
Handler = AsyncHandler | SyncHandler
FilterFn = Callable[[BusEvent], bool]


class EventBus:
    """Async event bus with topic-based pub/sub, filtering, and dead-letter queue."""

    def __init__(self, guarantee: DeliveryGuarantee = DeliveryGuarantee.AT_LEAST_ONCE,
                 max_retries: int = 3) -> None:
        self._guarantee = guarantee
        self._max_retries = max_retries
        self._subscriptions: dict[str, Subscription] = {}
        self._handlers: dict[str, Handler] = {}
        self._filters: dict[str, FilterFn] = {}
        self._dead_letters: list[DeadLetter] = []
        self._published: int = 0
        self._delivered: int = 0
        self._topic_counts: dict[str, int] = defaultdict(int)
        self._history: list[BusEvent] = []

    def subscribe(self, topic_pattern: str, subscriber_id: str,
                  handler: Handler, filter_fn: FilterFn | None = None) -> Subscription:
        sub = Subscription(topic_pattern=topic_pattern, subscriber_id=subscriber_id)
        self._subscriptions[sub.sub_id] = sub
        self._handlers[sub.sub_id] = handler
        if filter_fn:
            self._filters[sub.sub_id] = filter_fn
        return sub

    def unsubscribe(self, sub_id: str) -> bool:
        if sub_id in self._subscriptions:
            del self._subscriptions[sub_id]
            self._handlers.pop(sub_id, None)
            self._filters.pop(sub_id, None)
            return True
        return False

    async def publish(self, topic: str, source: str,
                      payload: dict[str, Any] | None = None,
                      priority: EventPriority = EventPriority.NORMAL,
                      correlation_id: str | None = None,
                      causation_id: str | None = None) -> BusEvent:
        event = BusEvent(
            topic=topic, source=source, payload=payload or {},
            priority=priority, correlation_id=correlation_id,
            causation_id=causation_id,
        )
        self._published += 1
        self._topic_counts[topic] += 1
        self._history.append(event)

        matching = self._get_matching_subs(event)
        for sub_id in matching:
            await self._deliver(event, sub_id)

        return event

    def publish_sync(self, topic: str, source: str,
                     payload: dict[str, Any] | None = None,
                     priority: EventPriority = EventPriority.NORMAL) -> BusEvent:
        event = BusEvent(
            topic=topic, source=source, payload=payload or {},
            priority=priority,
        )
        self._published += 1
        self._topic_counts[topic] += 1
        self._history.append(event)

        matching = self._get_matching_subs(event)
        for sub_id in matching:
            handler = self._handlers.get(sub_id)
            if handler and not asyncio.iscoroutinefunction(handler):
                try:
                    handler(event)  # type: ignore[arg-type]
                    self._delivered += 1
                except Exception as e:
                    self._dead_letters.append(DeadLetter(
                        event=event, subscriber_id=self._subscriptions[sub_id].subscriber_id,
                        error=str(e),
                    ))
        return event

    async def publish_batch(self, events: list[tuple[str, str, dict[str, Any]]]) -> list[BusEvent]:
        results = []
        for topic, source, payload in events:
            ev = await self.publish(topic, source, payload)
            results.append(ev)
        return results

    def get_dead_letters(self, subscriber_id: str | None = None) -> list[DeadLetter]:
        if subscriber_id:
            return [d for d in self._dead_letters if d.subscriber_id == subscriber_id]
        return list(self._dead_letters)

    def replay(self, topic_pattern: str | None = None,
               since: int = 0) -> list[BusEvent]:
        events = self._history[since:]
        if topic_pattern:
            events = [e for e in events if fnmatch.fnmatch(e.topic, topic_pattern)]
        return events

    def get_stats(self) -> EventBusStats:
        topics = set(self._topic_counts.keys())
        return EventBusStats(
            total_published=self._published,
            total_delivered=self._delivered,
            total_dead_letters=len(self._dead_letters),
            active_subscriptions=len(self._subscriptions),
            topics=len(topics),
            by_topic=dict(self._topic_counts),
        )

    def _get_matching_subs(self, event: BusEvent) -> list[str]:
        matching = []
        for sub_id, sub in self._subscriptions.items():
            if fnmatch.fnmatch(event.topic, sub.topic_pattern):
                filter_fn = self._filters.get(sub_id)
                if filter_fn and not filter_fn(event):
                    continue
                matching.append(sub_id)
        return matching

    async def _deliver(self, event: BusEvent, sub_id: str) -> None:
        handler = self._handlers.get(sub_id)
        if not handler:
            return

        attempts = 0
        while attempts < self._max_retries:
            attempts += 1
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)  # type: ignore[arg-type]
                self._delivered += 1
                return
            except Exception as e:
                if attempts >= self._max_retries:
                    sub = self._subscriptions.get(sub_id)
                    self._dead_letters.append(DeadLetter(
                        event=event,
                        subscriber_id=sub.subscriber_id if sub else "unknown",
                        error=str(e),
                        attempts=attempts,
                    ))
                    return
                if self._guarantee == DeliveryGuarantee.AT_MOST_ONCE:
                    return
