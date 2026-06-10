from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import ulid
from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field, field_validator

from reins.api.metrics import MetricsCollector
from reins.coordination.protocol import _normalize_datetime


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_ulid() -> str:
    return str(ulid.new())


class StreamEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=_new_ulid, min_length=1)
    type: str = Field(..., min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utc_now)
    agent_id: str | None = None
    job_id: str | None = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def _validate_timestamp(cls, value: datetime | str) -> datetime:
        return _normalize_datetime(value)


@dataclass(frozen=True)
class EventFilter:
    event_types: tuple[str, ...] = ()
    agent_id: str | None = None
    job_id: str | None = None

    def matches(self, event: StreamEvent) -> bool:
        if self.event_types and event.type not in self.event_types:
            return False
        if self.agent_id is not None and event.agent_id != self.agent_id:
            return False
        if self.job_id is not None and event.job_id != self.job_id:
            return False
        return True


@dataclass
class _Subscriber:
    subscriber_id: str
    event_filter: EventFilter
    queue: asyncio.Queue[StreamEvent]


class EventStream:
    """SSE event stream for real-time observability."""

    def __init__(
        self,
        *,
        metrics: MetricsCollector | None = None,
        heartbeat_seconds: float = 15.0,
        queue_size: int = 100,
    ) -> None:
        self.metrics = metrics
        self.heartbeat_seconds = heartbeat_seconds
        self.queue_size = queue_size
        self._subscribers: dict[str, _Subscriber] = {}
        self._lock = asyncio.Lock()

    @property
    def connection_count(self) -> int:
        return len(self._subscribers)

    async def publish(self, event: StreamEvent) -> None:
        if self.metrics is not None:
            self.metrics.record_event()
        async with self._lock:
            subscribers = tuple(self._subscribers.values())
        for subscriber in subscribers:
            if not subscriber.event_filter.matches(event):
                continue
            self._offer(subscriber.queue, event)

    async def stream(self, request: web.Request, event_filter: EventFilter) -> web.StreamResponse:
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)

        subscriber_id, queue = await self.subscribe(event_filter)
        try:
            await response.write(b": connected\n\n")
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=self.heartbeat_seconds)
                except TimeoutError:
                    await response.write(b": heartbeat\n\n")
                    continue
                await response.write(self.format_event(event))
        except (asyncio.CancelledError, ConnectionResetError):
            raise
        except OSError:
            pass
        finally:
            await self.unsubscribe(subscriber_id)
            with suppress(Exception):
                await response.write_eof()
        return response

    async def subscribe(
        self,
        event_filter: EventFilter,
    ) -> tuple[str, asyncio.Queue[StreamEvent]]:
        subscriber_id = _new_ulid()
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue(maxsize=self.queue_size)
        subscriber = _Subscriber(
            subscriber_id=subscriber_id,
            event_filter=event_filter,
            queue=queue,
        )
        async with self._lock:
            self._subscribers[subscriber_id] = subscriber
            self._refresh_connection_metric()
        return subscriber_id, queue

    async def unsubscribe(self, subscriber_id: str) -> None:
        async with self._lock:
            self._subscribers.pop(subscriber_id, None)
            self._refresh_connection_metric()

    @staticmethod
    def format_event(event: StreamEvent) -> bytes:
        data = json.dumps(event.model_dump(mode="json"), sort_keys=True)
        return f"id: {event.event_id}\nevent: {event.type}\ndata: {data}\n\n".encode("utf-8")

    def _offer(self, queue: asyncio.Queue[StreamEvent], event: StreamEvent) -> None:
        if queue.full():
            with suppress(asyncio.QueueEmpty):
                queue.get_nowait()
        with suppress(asyncio.QueueFull):
            queue.put_nowait(event)

    def _refresh_connection_metric(self) -> None:
        if self.metrics is not None:
            self.metrics.set_stream_connections(len(self._subscribers))


def parse_event_filter(
    request: web.Request,
    *,
    agent_id: str | None = None,
    job_id: str | None = None,
) -> EventFilter:
    raw_types = request.query.get("type", "")
    event_types = tuple(item.strip() for item in raw_types.split(",") if item.strip())
    return EventFilter(event_types=event_types, agent_id=agent_id, job_id=job_id)
