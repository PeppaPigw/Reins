from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web

from reins.api.control_plane import (
    AgentRegistrationRequest,
    ControlPlane,
    JobSubmissionRequest,
    PolicyEvaluateRequest,
)
from reins.api.middleware import RateLimitMiddleware, RequestIdMiddleware
from reins.api.server import build_app
from reins.api.streaming import EventFilter, EventStream, StreamEvent


class _FakeRequest(dict[str, Any]):
    method = "GET"
    path = "/"
    headers: dict[str, str] = {}
    remote = "127.0.0.1"


@pytest.mark.asyncio
async def test_agent_registration_and_deregistration(tmp_path: Path) -> None:
    control_plane = ControlPlane(state_dir=tmp_path)

    node = await control_plane.register_agent(
        AgentRegistrationRequest(
            node_id="agent-1",
            endpoint="https://agent-1.example.test",
            capabilities=("python", "tests"),
            max_concurrent_tasks=2,
        )
    )

    assert node.node_id == "agent-1"
    assert node.capabilities == ("python", "tests")
    assert [item.node_id for item in await control_plane.registry.list_nodes()] == ["agent-1"]

    removed = await control_plane.deregister_agent("agent-1")
    assert removed is True
    assert await control_plane.registry.list_nodes() == []


@pytest.mark.asyncio
async def test_job_submission_assigns_matching_agent_and_persists_jsonl(tmp_path: Path) -> None:
    control_plane = ControlPlane(state_dir=tmp_path)
    await control_plane.register_agent(
        AgentRegistrationRequest(
            node_id="agent-python",
            endpoint="https://agent-python.example.test",
            capabilities=("python",),
        )
    )

    job = await control_plane.submit_job(
        JobSubmissionRequest(
            objective="run tests",
            required_capabilities=("python",),
            priority=90,
        )
    )

    assert job.status.value == "assigned"
    assert job.assigned_agent_id == "agent-python"
    assert (tmp_path / "control-plane" / "jobs.jsonl").exists()

    reopened = ControlPlane(state_dir=tmp_path)
    replayed = await reopened.get_job(job.job_id)
    assert replayed is not None
    assert replayed.assigned_agent_id == "agent-python"


@pytest.mark.asyncio
async def test_pending_job_is_assigned_when_agent_registers(tmp_path: Path) -> None:
    control_plane = ControlPlane(state_dir=tmp_path)
    pending = await control_plane.submit_job(
        JobSubmissionRequest(objective="write docs", required_capabilities=("docs",))
    )
    assert pending.status.value == "pending"

    await control_plane.register_agent(
        AgentRegistrationRequest(
            node_id="agent-docs",
            endpoint="https://agent-docs.example.test",
            capabilities=("docs",),
        )
    )

    assigned = await control_plane.get_job(pending.job_id)
    assert assigned is not None
    assert assigned.status.value == "assigned"
    assert assigned.assigned_agent_id == "agent-docs"


@pytest.mark.asyncio
async def test_cancelling_assigned_job_releases_agent_load(tmp_path: Path) -> None:
    control_plane = ControlPlane(state_dir=tmp_path)
    await control_plane.register_agent(
        AgentRegistrationRequest(
            node_id="agent-cancel",
            endpoint="https://agent-cancel.example.test",
            capabilities=("python",),
        )
    )
    job = await control_plane.submit_job(
        JobSubmissionRequest(objective="run tests", required_capabilities=("python",))
    )

    cancelled = await control_plane.cancel_job(job.job_id, "operator stopped it")
    node = await control_plane.registry.get_node("agent-cancel")

    assert cancelled is not None
    assert cancelled.status.value == "cancelled"
    assert node is not None
    assert node.current_load == 0
    assert node.status.value == "idle"


@pytest.mark.asyncio
async def test_deregistering_agent_requeues_and_reassigns_jobs(tmp_path: Path) -> None:
    control_plane = ControlPlane(state_dir=tmp_path)
    await control_plane.register_agent(
        AgentRegistrationRequest(
            node_id="agent-old",
            endpoint="https://agent-old.example.test",
            capabilities=("python",),
        )
    )
    await control_plane.register_agent(
        AgentRegistrationRequest(
            node_id="agent-new",
            endpoint="https://agent-new.example.test",
            capabilities=("python",),
        )
    )
    job = await control_plane.submit_job(
        JobSubmissionRequest(objective="implement feature", required_capabilities=("python",))
    )

    original_agent_id = job.assigned_agent_id
    removed = await control_plane.deregister_agent(original_agent_id or "")
    reassigned = await control_plane.get_job(job.job_id)

    assert removed is True
    assert reassigned is not None
    assert reassigned.status.value == "assigned"
    assert reassigned.assigned_agent_id is not None
    assert reassigned.assigned_agent_id != original_agent_id


@pytest.mark.asyncio
async def test_agent_heartbeat_job_progress_and_completion_events(tmp_path: Path) -> None:
    control_plane = ControlPlane(state_dir=tmp_path)
    subscriber_id, queue = await control_plane.stream.subscribe(EventFilter(agent_id="agent-1"))
    try:
        await control_plane.register_agent(
            AgentRegistrationRequest(
                node_id="agent-1",
                endpoint="https://agent-1.example.test",
                capabilities=("python",),
            )
        )
        job = await control_plane.submit_job(
            JobSubmissionRequest(objective="run tests", required_capabilities=("python",))
        )

        node = await control_plane.heartbeat_agent("agent-1")
        progress = await control_plane.report_job_progress(job.job_id, {"percent": 50})
        completed = await control_plane.complete_job(job.job_id, {"ok": True})

        assert node is not None
        assert progress is not None
        assert completed is not None
        assert completed.status.value == "completed"
        event_types = [await asyncio.wait_for(queue.get(), timeout=1) for _ in range(5)]
        assert {event.type for event in event_types} >= {
            "agent.registered",
            "agent.heartbeat",
            "job.assigned",
            "job.progress",
            "job.completed",
        }
    finally:
        await control_plane.stream.unsubscribe(subscriber_id)


@pytest.mark.asyncio
async def test_event_stream_filters_and_drops_oldest_for_slow_clients() -> None:
    stream = EventStream(heartbeat_seconds=0.1, queue_size=1)
    subscriber_id, queue = await stream.subscribe(EventFilter(agent_id="agent-1"))
    try:
        await stream.publish(StreamEvent(type="agent.registered", data={}, agent_id="agent-2"))
        assert queue.empty()

        await stream.publish(StreamEvent(type="job.progress", data={"step": 1}, agent_id="agent-1"))
        await stream.publish(StreamEvent(type="job.progress", data={"step": 2}, agent_id="agent-1"))

        event = await asyncio.wait_for(queue.get(), timeout=1)
        assert event.data == {"step": 2}
        encoded = EventStream.format_event(event).decode("utf-8")
        assert "event: job.progress" in encoded
        assert "data: " in encoded
    finally:
        await stream.unsubscribe(subscriber_id)


@pytest.mark.asyncio
async def test_policy_evaluation_at_api_boundary_records_metrics(tmp_path: Path) -> None:
    control_plane = ControlPlane(state_dir=tmp_path)

    decision = await control_plane.evaluate_policy(
        PolicyEvaluateRequest(capability="unknown.capability", resource="workspace")
    )

    assert decision.decision == "deny"
    assert "unknown capability" in decision.reason
    assert control_plane.metrics.policy_evaluations_total == 1
    assert control_plane.metrics.policy_denials_total == 1


@pytest.mark.asyncio
async def test_metrics_collection_and_dashboard_data(tmp_path: Path) -> None:
    control_plane = ControlPlane(state_dir=tmp_path)
    await control_plane.register_agent(
        AgentRegistrationRequest(
            node_id="agent-dashboard",
            endpoint="https://agent-dashboard.example.test",
            capabilities=("python",),
        )
    )
    await control_plane.submit_job(
        JobSubmissionRequest(objective="implement feature", required_capabilities=("python",))
    )

    response = await control_plane.handle_dashboard(_FakeRequest())
    assert response.status == 200
    body = json.loads(response.text)
    assert body["agents"]["total"] == 1
    assert body["agents"]["active"] == 1
    assert body["jobs"]["total"] == 1
    assert body["jobs"]["by_status"]["assigned"] == 1

    metrics = control_plane.metrics.render_prometheus()
    assert "reins_agents_total 1" in metrics
    assert "reins_jobs_total 1" in metrics


@pytest.mark.asyncio
async def test_rate_limiting_returns_429_without_socket_server() -> None:
    limiter = RateLimitMiddleware(capacity=1, refill_rate=0.0).middleware
    request = _FakeRequest()

    async def handler(_: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    first = await limiter(request, handler)  # type: ignore[arg-type]
    assert first.status == 200

    second = await limiter(request, handler)  # type: ignore[arg-type]
    assert second.status == 429
    assert json.loads(second.text)["error"] == "rate limit exceeded"


@pytest.mark.asyncio
async def test_request_id_middleware_sets_header() -> None:
    middleware = RequestIdMiddleware().middleware
    request = _FakeRequest()

    async def handler(_: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    response = await middleware(request, handler)  # type: ignore[arg-type]

    assert response.headers["X-Request-Id"]
    assert request["request_id"] == response.headers["X-Request-Id"]


def test_build_app_wires_control_plane_routes(tmp_path: Path) -> None:
    app = build_app(tmp_path)
    route_signatures = {
        (route.method, route.resource.canonical)
        for route in app.router.routes()
        if route.resource is not None
    }

    assert ("POST", "/agents/register") in route_signatures
    assert ("GET", "/stream") in route_signatures
    assert ("GET", "/metrics") in route_signatures
    assert ("GET", "/dashboard") in route_signatures
