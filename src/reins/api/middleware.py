from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import ulid
from aiohttp import web

from reins.policy.approval.ledger import EffectDescriptor
from reins.policy.engine import PolicyDecision, PolicyEngine


Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def _json_response(data: dict[str, Any], status: int) -> web.Response:
    return web.Response(
        status=status,
        content_type="application/json",
        body=json.dumps(data, default=str),
    )


class RequestIdMiddleware:
    def __init__(self, header_name: str = "X-Request-Id") -> None:
        self.header_name = header_name

    @property
    def middleware(self) -> web.Middleware:
        @web.middleware
        async def _middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
            request_id = request.headers.get(self.header_name) or str(ulid.new())
            request["request_id"] = request_id
            response = await handler(request)
            response.headers[self.header_name] = request_id
            return response

        return _middleware


class CORSMiddleware:
    def __init__(
        self,
        *,
        allow_origin: str = "*",
        allow_headers: str = "Content-Type, Authorization, X-Request-Id",
    ) -> None:
        self.allow_origin = allow_origin
        self.allow_headers = allow_headers

    @property
    def middleware(self) -> web.Middleware:
        @web.middleware
        async def _middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
            if request.method == "OPTIONS":
                response: web.StreamResponse = web.Response(status=204)
            else:
                response = await handler(request)
            response.headers["Access-Control-Allow-Origin"] = self.allow_origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = self.allow_headers
            return response

        return _middleware


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class RateLimitMiddleware:
    def __init__(
        self,
        *,
        capacity: int = 120,
        refill_rate: float = 2.0,
        key_header: str = "X-Forwarded-For",
    ) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.key_header = key_header
        self._buckets: dict[str, _Bucket] = {}

    @property
    def middleware(self) -> web.Middleware:
        @web.middleware
        async def _middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
            if request.method == "OPTIONS":
                return await handler(request)
            key = self._key(request)
            now = time.monotonic()
            bucket = self._buckets.get(key, _Bucket(tokens=float(self.capacity), updated_at=now))
            elapsed = max(now - bucket.updated_at, 0.0)
            bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.refill_rate)
            bucket.updated_at = now
            if bucket.tokens < 1:
                self._buckets[key] = bucket
                return _json_response({"error": "rate limit exceeded"}, 429)
            bucket.tokens -= 1
            self._buckets[key] = bucket
            return await handler(request)

        return _middleware

    def _key(self, request: web.Request) -> str:
        forwarded = request.headers.get(self.key_header)
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
        return request.remote or "unknown"


class PolicyMiddleware:
    def __init__(self, policy_engine: PolicyEngine) -> None:
        self.policy_engine = policy_engine

    @property
    def middleware(self) -> web.Middleware:
        @web.middleware
        async def _middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
            if not self._should_evaluate(request):
                return await handler(request)

            body = await self._read_json(request)
            if body is None:
                return await handler(request)

            decision = await self._evaluate(request, body)
            await self._record(request, decision, body)
            if decision.decision == "deny":
                return _json_response(
                    {
                        "error": "policy denied request",
                        "decision": decision.decision,
                        "reason": decision.reason,
                        "risk_tier": int(decision.risk_tier),
                    },
                    403,
                )
            return await handler(request)

        return _middleware

    def _should_evaluate(self, request: web.Request) -> bool:
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return False
        path = request.path
        if path == "/policy/evaluate":
            return False
        return path.startswith("/agents") or path.startswith("/jobs")

    async def _read_json(self, request: web.Request) -> dict[str, Any] | None:
        if request.can_read_body:
            try:
                body = await request.json()
            except Exception:
                return None
            return body if isinstance(body, dict) else None
        return {}

    async def _evaluate(self, request: web.Request, body: dict[str, Any]) -> PolicyDecision:
        capability = str(
            body.get("policy_capability")
            or body.get("capability")
            or self._default_capability(request)
        )
        resource = body.get("resource") or body.get("objective") or request.path
        effect = EffectDescriptor(
            capability=capability,
            resource=str(resource),
            intent_ref=str(body.get("run_id") or "control-plane"),
            command_id=str(request.get("request_id") or ulid.new()),
            reversibility="reversible",
            rollback_strategy="compensating_action",
        )
        return await self.policy_engine.evaluate(
            capability=capability,
            run_id=str(body.get("run_id") or "control-plane"),
            requested_by=str(body.get("requested_by") or "api"),
            effect_descriptor=effect,
            context={"request": {"path": request.path, "method": request.method}},
        )

    def _default_capability(self, request: web.Request) -> str:
        if request.path == "/agents/register":
            return "a2a.agent.discover"
        return "a2a.agent.call"

    async def _record(
        self,
        request: web.Request,
        decision: PolicyDecision,
        body: dict[str, Any],
    ) -> None:
        control_plane = request.app.get("control_plane")
        metrics = getattr(control_plane, "metrics", None)
        if metrics is not None:
            metrics.record_policy_evaluation(denied=decision.decision == "deny")
        if control_plane is None:
            return
        emit_event = getattr(control_plane, "emit_event", None)
        if emit_event is None:
            return
        await emit_event(
            "policy.evaluated",
            {
                "capability": body.get("policy_capability") or body.get("capability"),
                "decision": decision.decision,
                "reason": decision.reason,
                "risk_tier": int(decision.risk_tier),
                "request_id": request.get("request_id"),
                "path": request.path,
            },
        )


def create_api_middlewares(policy_engine: PolicyEngine) -> list[web.Middleware]:
    return [
        RequestIdMiddleware().middleware,
        CORSMiddleware().middleware,
        RateLimitMiddleware().middleware,
        PolicyMiddleware(policy_engine).middleware,
    ]
