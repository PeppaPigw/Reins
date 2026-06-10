from __future__ import annotations

import time
from collections import defaultdict

from reins.throttle.types import (
    BackpressureAction,
    QueueEntry,
    RateLimitConfig,
    ThrottleDecision,
    ThrottleScope,
    ThrottleStats,
    ThrottleStrategy,
)


class _TokenBucket:
    def __init__(self, max_tokens: float, refill_rate: float) -> None:
        self.max_tokens = max_tokens
        self.tokens = max_tokens
        self.refill_rate = refill_rate
        self.last_refill = time.monotonic()

    def try_consume(self, tokens: float = 1.0) -> tuple[bool, float]:
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True, self.tokens
        wait_ms = ((tokens - self.tokens) / self.refill_rate) * 1000 if self.refill_rate > 0 else 0
        return False, wait_ms

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now


class ThrottleEngine:
    """Adaptive rate limiting with token bucket, backpressure, and fair queuing.

    Prevents agent overload through configurable throttling strategies,
    priority-based queuing, and load shedding under pressure.
    """

    def __init__(self) -> None:
        self._configs: dict[str, RateLimitConfig] = {}
        self._buckets: dict[str, _TokenBucket] = {}
        self._queue: list[QueueEntry] = []
        self._decisions: list[ThrottleDecision] = []
        self._request_counts: dict[str, int] = defaultdict(int)
        self._resource_counts: dict[str, int] = defaultdict(int)

    def register_config(self, config: RateLimitConfig) -> RateLimitConfig:
        self._configs[config.config_id] = config
        return config

    def get_config(self, config_id: str) -> RateLimitConfig | None:
        return self._configs.get(config_id)

    def request(self, agent_id: str, resource: str = "",
                config_id: str | None = None, tokens: float = 1.0) -> ThrottleDecision:
        self._request_counts[agent_id] += 1
        if resource:
            self._resource_counts[resource] += 1

        config = self._configs.get(config_id) if config_id else self._get_default_config()
        if not config:
            decision = ThrottleDecision(
                agent_id=agent_id, resource=resource,
                action=BackpressureAction.ALLOW, reason="No config — allowing.",
            )
            self._decisions.append(decision)
            return decision

        bucket_key = self._bucket_key(config, agent_id, resource)
        bucket = self._get_or_create_bucket(bucket_key, config)

        allowed, remaining = bucket.try_consume(tokens)

        if allowed:
            decision = ThrottleDecision(
                agent_id=agent_id, resource=resource,
                action=BackpressureAction.ALLOW,
                tokens_remaining=remaining,
                reason="Within rate limit.",
            )
        else:
            if len(self._queue) < config.burst_size * 2:
                action = BackpressureAction.THROTTLE
                reason = f"Rate exceeded. Wait ~{remaining:.0f}ms."
            else:
                action = BackpressureAction.REJECT
                reason = "Rate exceeded and queue full."

            decision = ThrottleDecision(
                agent_id=agent_id, resource=resource,
                action=action,
                tokens_remaining=0.0,
                wait_ms=remaining,
                reason=reason,
            )

        self._decisions.append(decision)
        return decision

    def enqueue(self, agent_id: str, resource: str = "", priority: int = 0) -> QueueEntry:
        entry = QueueEntry(agent_id=agent_id, resource=resource, priority=priority)
        self._queue.append(entry)
        self._queue.sort(key=lambda e: -e.priority)
        return entry

    def dequeue(self) -> QueueEntry | None:
        if not self._queue:
            return None
        return self._queue.pop(0)

    def get_queue_size(self) -> int:
        return len(self._queue)

    def get_decisions(self, agent_id: str | None = None,
                      action: BackpressureAction | None = None) -> list[ThrottleDecision]:
        decisions = self._decisions
        if agent_id:
            decisions = [d for d in decisions if d.agent_id == agent_id]
        if action:
            decisions = [d for d in decisions if d.action == action]
        return decisions

    def reset_bucket(self, agent_id: str, resource: str = "") -> None:
        keys_to_remove = [
            k for k in self._buckets
            if agent_id in k and (not resource or resource in k)
        ]
        for k in keys_to_remove:
            del self._buckets[k]

    def get_stats(self) -> ThrottleStats:
        allowed = sum(1 for d in self._decisions if d.action == BackpressureAction.ALLOW)
        throttled = sum(1 for d in self._decisions if d.action == BackpressureAction.THROTTLE)
        queued = sum(1 for d in self._decisions if d.action == BackpressureAction.QUEUE)
        rejected = sum(1 for d in self._decisions if d.action == BackpressureAction.REJECT)

        waits = [d.wait_ms for d in self._decisions if d.wait_ms > 0]
        avg_wait = sum(waits) / len(waits) if waits else 0.0

        return ThrottleStats(
            total_requests=len(self._decisions),
            allowed=allowed,
            throttled=throttled,
            queued=queued,
            rejected=rejected,
            avg_wait_ms=avg_wait,
            by_agent=dict(self._request_counts),
            by_resource=dict(self._resource_counts),
        )

    def _get_default_config(self) -> RateLimitConfig | None:
        if self._configs:
            return next(iter(self._configs.values()))
        return None

    def _bucket_key(self, config: RateLimitConfig, agent_id: str, resource: str) -> str:
        if config.scope == ThrottleScope.GLOBAL:
            return f"global:{config.config_id}"
        elif config.scope == ThrottleScope.PER_AGENT:
            return f"agent:{agent_id}:{config.config_id}"
        elif config.scope == ThrottleScope.PER_RESOURCE:
            return f"resource:{resource}:{config.config_id}"
        return f"op:{agent_id}:{resource}:{config.config_id}"

    def _get_or_create_bucket(self, key: str, config: RateLimitConfig) -> _TokenBucket:
        if key not in self._buckets:
            refill_rate = config.max_rate / config.window_seconds
            self._buckets[key] = _TokenBucket(
                max_tokens=float(config.burst_size),
                refill_rate=refill_rate,
            )
        return self._buckets[key]
