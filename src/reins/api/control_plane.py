from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

import aiofiles  # type: ignore[import-untyped]
import ulid
from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from reins.api.metrics import MetricsCollector
from reins.api.streaming import EventStream, StreamEvent, parse_event_filter
from reins.coordination.protocol import (
    AgentNode,
    CoordinationProtocol,
    NodeStatus,
    RiskTier,
    TaskAssignment,
    _normalize_datetime,
)
from reins.coordination.registry import NodeRegistry
from reins.intelligence.types import TrustLevel
from reins.policy.approval.ledger import EffectDescriptor
from reins.policy.engine import PolicyDecision, PolicyEngine


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_ulid() -> str:
    return str(ulid.new())


def _json(data: Any, status: int = 200) -> web.Response:
    return web.Response(
        status=status,
        content_type="application/json",
        body=json.dumps(data, default=str),
    )


def _error(message: str, status: int = 400, *, code: str = "BAD_REQUEST") -> web.Response:
    return _json({"error": message, "code": code}, status=status)


def _validation_error(exc: ValidationError) -> web.Response:
    return _json(
        {
            "error": "Validation failed",
            "code": "VALIDATION_ERROR",
            "details": {"errors": exc.errors()},
        },
        status=422,
    )


def _normalize_unique(value: Iterable[object] | None, *, sort: bool = True) -> tuple[str, ...]:
    if value is None:
        return ()
    items = [str(item).strip() for item in value if str(item).strip()]
    unique = tuple(dict.fromkeys(items))
    return tuple(sorted(unique)) if sort else unique


class JobStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class JobRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: str = Field(default_factory=_new_ulid, min_length=1)
    objective: str = Field(..., min_length=1)
    required_capabilities: tuple[str, ...] = Field(default_factory=tuple)
    risk_tier: RiskTier = RiskTier.T1
    priority: int = Field(default=50, ge=0, le=100)
    status: JobStatus = JobStatus.PENDING
    assigned_agent_id: str | None = None
    task_id: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cancel_reason: str | None = None
    error: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("required_capabilities", mode="before")
    @classmethod
    def _validate_required_capabilities(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return _normalize_unique(value)

    @field_validator("created_at", "updated_at", "started_at", "finished_at", mode="before")
    @classmethod
    def _validate_datetime(cls, value: datetime | str | None) -> datetime | None:
        return _normalize_datetime(value) if value is not None else None


class JobJournalEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=_new_ulid, min_length=1)
    type: str = Field(..., min_length=1)
    job_id: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utc_now)
    schema_version: int = 1

    @field_validator("timestamp", mode="before")
    @classmethod
    def _validate_timestamp(cls, value: datetime | str) -> datetime:
        return _normalize_datetime(value)


class ControlPlaneEventRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=_new_ulid, min_length=1)
    type: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utc_now)
    agent_id: str | None = None
    job_id: str | None = None
    schema_version: int = 1

    @field_validator("timestamp", mode="before")
    @classmethod
    def _validate_timestamp(cls, value: datetime | str) -> datetime:
        return _normalize_datetime(value)


class AgentRegistrationRequest(BaseModel):
    node_id: str | None = Field(default=None, min_length=1)
    endpoint: str = Field(..., min_length=1)
    capabilities: tuple[str, ...] = Field(default_factory=tuple)
    trust_level: TrustLevel = TrustLevel.semi_auto
    max_concurrent_tasks: int = Field(default=1, ge=1)
    trust_score: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("capabilities", mode="before")
    @classmethod
    def _validate_capabilities(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return _normalize_unique(value)


class JobSubmissionRequest(BaseModel):
    objective: str = Field(..., min_length=1)
    required_capabilities: tuple[str, ...] = Field(default_factory=tuple)
    risk_tier: RiskTier = RiskTier.T1
    priority: int = Field(default=50, ge=0, le=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("required_capabilities", mode="before")
    @classmethod
    def _validate_required_capabilities(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return _normalize_unique(value)


class CancelJobRequest(BaseModel):
    reason: str = Field(default="cancelled by operator", max_length=2000)


class PolicyEvaluateRequest(BaseModel):
    capability: str = Field(..., min_length=1)
    run_id: str = Field(default="control-plane", min_length=1)
    requested_by: str = Field(default="api", min_length=1)
    resource: str = Field(default="control-plane", min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)


class ControlPlane:
    """HTTP control plane for distributed agent orchestration.

    Provides:
    - Multi-agent job queuing with priority scheduling
    - Real-time streaming observability (SSE)
    - Policy enforcement at the API boundary
    - Agent lifecycle management
    - Integration with Claude Code/Codex/Gemini CLI
    """

    def __init__(
        self,
        *,
        state_dir: Path | None = None,
        policy_engine: PolicyEngine | None = None,
        metrics: MetricsCollector | None = None,
        stream: EventStream | None = None,
    ) -> None:
        self.state_dir = (state_dir or Path(".reins_state")).resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.agent_journal_path = self.state_dir / "control-plane" / "agents.jsonl"
        self.job_journal_path = self.state_dir / "control-plane" / "jobs.jsonl"
        self.event_journal_path = self.state_dir / "control-plane" / "events.jsonl"
        self.job_journal_path.parent.mkdir(parents=True, exist_ok=True)
        self.job_journal_path.touch(exist_ok=True)
        self.event_journal_path.touch(exist_ok=True)

        self.metrics = metrics or MetricsCollector()
        self.stream = stream or EventStream(metrics=self.metrics)
        self.policy_engine = policy_engine or PolicyEngine()
        self.registry = NodeRegistry(self.agent_journal_path)
        self.protocol = CoordinationProtocol(self.registry)
        self._jobs: dict[str, JobRecord] = {}
        self._lock = asyncio.Lock()
        self._replay_jobs_sync()

    def add_routes(self, app: web.Application) -> None:
        app.router.add_post("/agents/register", self.handle_register_agent)
        app.router.add_delete("/agents/{id}", self.handle_deregister_agent)
        app.router.add_get("/agents", self.handle_list_agents)
        app.router.add_get("/agents/{id}/health", self.handle_agent_health)
        app.router.add_post("/jobs", self.handle_submit_job)
        app.router.add_get("/jobs", self.handle_list_jobs)
        app.router.add_get("/jobs/{id}", self.handle_get_job)
        app.router.add_post("/jobs/{id}/cancel", self.handle_cancel_job)
        app.router.add_get("/stream", self.handle_stream)
        app.router.add_get("/stream/agent/{id}", self.handle_agent_stream)
        app.router.add_get("/stream/job/{id}", self.handle_job_stream)
        app.router.add_post("/policy/evaluate", self.handle_evaluate_policy)
        app.router.add_get("/metrics", self.handle_metrics)
        app.router.add_get("/dashboard", self.handle_dashboard)

    async def register_agent(self, payload: AgentRegistrationRequest) -> AgentNode:
        node = AgentNode(
            node_id=payload.node_id or _new_ulid(),
            endpoint=payload.endpoint,
            capabilities=payload.capabilities,
            trust_level=payload.trust_level,
            max_concurrent_tasks=payload.max_concurrent_tasks,
            trust_score=payload.trust_score,
            metadata=payload.metadata,
        )
        await self.protocol.register_node(node)
        await self._refresh_agent_metrics()
        await self.emit_event(
            "agent.registered",
            {"agent": node.model_dump(mode="json")},
            agent_id=node.node_id,
        )
        await self._assign_pending_jobs()
        return node

    async def deregister_agent(self, agent_id: str) -> bool:
        existing = await self.registry.get_node(agent_id)
        if existing is None:
            return False
        affected_job_ids = await self._jobs_assigned_to(agent_id)
        await self.protocol.deregister_node(agent_id)
        await self._requeue_jobs(affected_job_ids)
        await self._refresh_agent_metrics()
        await self.emit_event("agent.deregistered", {"agent_id": agent_id}, agent_id=agent_id)
        await self._assign_pending_jobs()
        return True

    async def submit_job(self, payload: JobSubmissionRequest) -> JobRecord:
        job = JobRecord(
            objective=payload.objective,
            required_capabilities=payload.required_capabilities,
            risk_tier=payload.risk_tier,
            priority=payload.priority,
            metadata=payload.metadata,
        )
        async with self._lock:
            self._jobs[job.job_id] = job
            await self._append_job_event(
                JobJournalEvent(
                    type="job.submitted",
                    job_id=job.job_id,
                    payload={"job": job.model_dump(mode="json")},
                )
            )
        self.metrics.record_job_submitted()
        await self.emit_event(
            "job.submitted",
            {"job": job.model_dump(mode="json")},
            job_id=job.job_id,
        )
        return await self._assign_job(job.job_id)

    async def cancel_job(self, job_id: str, reason: str) -> JobRecord | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                return job
            updated = job.model_copy(
                update={
                    "status": JobStatus.CANCELLED,
                    "cancel_reason": reason,
                    "updated_at": _utc_now(),
                    "finished_at": _utc_now(),
                }
            )
            self._drop_protocol_task(job_id)
            self._jobs[job_id] = updated
            await self._append_job_event(
                JobJournalEvent(
                    type="job.cancelled",
                    job_id=job_id,
                    payload={"job": updated.model_dump(mode="json"), "reason": reason},
                )
            )
        await self._release_agent_load(job)
        await self.emit_event(
            "job.cancelled",
            {"job": updated.model_dump(mode="json"), "reason": reason},
            agent_id=updated.assigned_agent_id,
            job_id=job_id,
        )
        return updated

    async def heartbeat_agent(self, agent_id: str) -> AgentNode | None:
        try:
            await self.protocol.heartbeat(agent_id)
        except ValueError:
            return None
        node = await self.registry.get_node(agent_id)
        if node is None:
            return None
        await self._refresh_agent_metrics()
        await self.emit_event(
            "agent.heartbeat",
            {"agent": node.model_dump(mode="json")},
            agent_id=agent_id,
        )
        return node

    async def report_job_progress(self, job_id: str, progress: dict[str, Any]) -> JobRecord | None:
        job = await self.get_job(job_id)
        if job is None:
            return None
        await self.emit_event(
            "job.progress",
            {"job_id": job_id, "progress": progress},
            agent_id=job.assigned_agent_id,
            job_id=job_id,
        )
        return job

    async def complete_job(self, job_id: str, result: dict[str, Any]) -> JobRecord | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                return job
        try:
            await self.protocol.report_completion(job_id, result)
        except ValueError:
            await self._release_agent_load(job)
            self._drop_protocol_task(job_id)

        finished_at = _utc_now()
        updated = job.model_copy(
            update={
                "status": JobStatus.COMPLETED,
                "result": dict(result),
                "updated_at": finished_at,
                "finished_at": finished_at,
            }
        )
        async with self._lock:
            self._jobs[job_id] = updated
            await self._append_job_event(
                JobJournalEvent(
                    type="job.completed",
                    job_id=job_id,
                    payload={"job": updated.model_dump(mode="json")},
                )
            )
        self.metrics.record_job_completed(self._job_duration_seconds(updated))
        await self._refresh_agent_metrics()
        await self.emit_event(
            "job.completed",
            {"job": updated.model_dump(mode="json")},
            agent_id=updated.assigned_agent_id,
            job_id=job_id,
        )
        return updated

    async def fail_job(self, job_id: str, error: dict[str, Any]) -> JobRecord | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                return job
        try:
            await self.protocol.report_failure(job_id, error)
        except ValueError:
            await self._release_agent_load(job)
            self._drop_protocol_task(job_id)

        task = await self.protocol.get_task(job_id)
        if (
            task is not None
            and task.assigned_node_id
            and task.assigned_node_id != job.assigned_agent_id
        ):
            updated = job.model_copy(
                update={
                    "status": JobStatus.ASSIGNED,
                    "assigned_agent_id": task.assigned_node_id,
                    "error": dict(error),
                    "updated_at": _utc_now(),
                }
            )
            async with self._lock:
                self._jobs[job_id] = updated
                await self._append_job_event(
                    JobJournalEvent(
                        type="job.assigned",
                        job_id=job_id,
                        payload={"job": updated.model_dump(mode="json")},
                    )
                )
            await self.emit_event(
                "job.assigned",
                {"job": updated.model_dump(mode="json"), "previous_error": error},
                agent_id=updated.assigned_agent_id,
                job_id=job_id,
            )
            return updated

        finished_at = _utc_now()
        updated = job.model_copy(
            update={
                "status": JobStatus.FAILED,
                "error": dict(error),
                "updated_at": finished_at,
                "finished_at": finished_at,
            }
        )
        async with self._lock:
            self._jobs[job_id] = updated
            await self._append_job_event(
                JobJournalEvent(
                    type="job.failed",
                    job_id=job_id,
                    payload={"job": updated.model_dump(mode="json")},
                )
            )
        self.metrics.record_job_failed(self._job_duration_seconds(updated))
        await self._refresh_agent_metrics()
        await self.emit_event(
            "job.failed",
            {"job": updated.model_dump(mode="json")},
            agent_id=updated.assigned_agent_id,
            job_id=job_id,
        )
        return updated

    async def list_jobs(
        self,
        *,
        status: str | None = None,
        priority: int | None = None,
        agent_id: str | None = None,
    ) -> list[JobRecord]:
        async with self._lock:
            jobs = list(self._jobs.values())
        if status is not None:
            jobs = [job for job in jobs if job.status.value == status]
        if priority is not None:
            jobs = [job for job in jobs if job.priority == priority]
        if agent_id is not None:
            jobs = [job for job in jobs if job.assigned_agent_id == agent_id]
        return sorted(jobs, key=lambda job: (-job.priority, job.created_at, job.job_id))

    async def get_job(self, job_id: str) -> JobRecord | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def emit_event(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        agent_id: str | None = None,
        job_id: str | None = None,
    ) -> StreamEvent:
        event = StreamEvent(type=event_type, data=data, agent_id=agent_id, job_id=job_id)
        record = ControlPlaneEventRecord(
            event_id=event.event_id,
            type=event.type,
            payload=event.data,
            timestamp=event.timestamp,
            agent_id=agent_id,
            job_id=job_id,
        )
        await self._append_control_event(record)
        await self.stream.publish(event)
        return event

    async def handle_register_agent(self, request: web.Request) -> web.Response:
        body = await self._request_json(request)
        if isinstance(body, web.Response):
            return body
        try:
            payload = AgentRegistrationRequest.model_validate(body)
        except ValidationError as exc:
            return _validation_error(exc)
        try:
            node = await self.register_agent(payload)
        except ValidationError as exc:
            return _validation_error(exc)
        return _json({"agent": self._agent_response(node)}, status=201)

    async def handle_deregister_agent(self, request: web.Request) -> web.Response:
        agent_id = request.match_info["id"]
        removed = await self.deregister_agent(agent_id)
        if not removed:
            return _error(f"agent not found: {agent_id}", 404, code="NOT_FOUND")
        return _json({"agent_id": agent_id, "status": "deregistered"})

    async def handle_list_agents(self, request: web.Request) -> web.Response:
        await self._refresh_agent_metrics()
        nodes = await self.registry.list_nodes()
        return _json({"agents": [self._agent_response(node) for node in nodes]})

    async def handle_agent_health(self, request: web.Request) -> web.Response:
        agent_id = request.match_info["id"]
        node = await self.registry.get_node(agent_id)
        if node is None:
            return _error(f"agent not found: {agent_id}", 404, code="NOT_FOUND")
        is_active = node.status is not NodeStatus.OFFLINE
        return _json(
            {
                "agent_id": agent_id,
                "status": node.status.value,
                "active": is_active,
                "last_heartbeat": node.last_heartbeat.isoformat(),
                "current_load": node.current_load,
                "max_concurrent_tasks": node.max_concurrent_tasks,
            },
            status=200 if is_active else 503,
        )

    async def handle_submit_job(self, request: web.Request) -> web.Response:
        body = await self._request_json(request)
        if isinstance(body, web.Response):
            return body
        try:
            payload = JobSubmissionRequest.model_validate(body)
        except ValidationError as exc:
            return _validation_error(exc)
        job = await self.submit_job(payload)
        return _json({"job": job.model_dump(mode="json")}, status=201)

    async def handle_list_jobs(self, request: web.Request) -> web.Response:
        priority = None
        if request.query.get("priority") is not None:
            try:
                priority = int(request.query["priority"])
            except ValueError:
                return _error("priority must be an integer", 400)
        jobs = await self.list_jobs(
            status=request.query.get("status"),
            priority=priority,
            agent_id=request.query.get("agent"),
        )
        return _json({"jobs": [job.model_dump(mode="json") for job in jobs]})

    async def handle_get_job(self, request: web.Request) -> web.Response:
        job_id = request.match_info["id"]
        job = await self.get_job(job_id)
        if job is None:
            return _error(f"job not found: {job_id}", 404, code="NOT_FOUND")
        return _json({"job": job.model_dump(mode="json")})

    async def handle_cancel_job(self, request: web.Request) -> web.Response:
        body = await self._request_json(request, default={})
        if isinstance(body, web.Response):
            return body
        try:
            payload = CancelJobRequest.model_validate(body)
        except ValidationError as exc:
            return _validation_error(exc)
        job_id = request.match_info["id"]
        job = await self.cancel_job(job_id, payload.reason)
        if job is None:
            return _error(f"job not found: {job_id}", 404, code="NOT_FOUND")
        return _json({"job": job.model_dump(mode="json")})

    async def handle_stream(self, request: web.Request) -> web.StreamResponse:
        return await self.stream.stream(request, parse_event_filter(request))

    async def handle_agent_stream(self, request: web.Request) -> web.StreamResponse:
        return await self.stream.stream(
            request,
            parse_event_filter(request, agent_id=request.match_info["id"]),
        )

    async def handle_job_stream(self, request: web.Request) -> web.StreamResponse:
        return await self.stream.stream(
            request,
            parse_event_filter(request, job_id=request.match_info["id"]),
        )

    async def handle_evaluate_policy(self, request: web.Request) -> web.Response:
        body = await self._request_json(request)
        if isinstance(body, web.Response):
            return body
        try:
            payload = PolicyEvaluateRequest.model_validate(body)
        except ValidationError as exc:
            return _validation_error(exc)
        decision = await self.evaluate_policy(payload)
        return _json({"decision": self._policy_decision_response(decision)})

    async def handle_metrics(self, request: web.Request) -> web.Response:
        await self._refresh_agent_metrics()
        return web.Response(
            text=self.metrics.render_prometheus(),
            content_type="text/plain",
        )

    async def handle_dashboard(self, request: web.Request) -> web.Response:
        await self._refresh_agent_metrics()
        snapshot = self.metrics.snapshot()
        jobs = await self.list_jobs()
        by_status: dict[str, int] = {status.value: 0 for status in JobStatus}
        for job in jobs:
            by_status[job.status.value] += 1
        return _json(
            {
                "agents": {
                    "total": snapshot["reins_agents_total"],
                    "active": snapshot["reins_agents_active"],
                },
                "jobs": {
                    "total": len(jobs),
                    "by_status": by_status,
                    "throughput_per_minute": snapshot["job_throughput_per_minute"],
                    "completed": snapshot["reins_jobs_completed"],
                    "failed": snapshot["reins_jobs_failed"],
                },
                "policy": {
                    "evaluations": snapshot["reins_policy_evaluations_total"],
                    "denials": snapshot["reins_policy_denials_total"],
                },
                "events": {
                    "total": snapshot["reins_events_total"],
                    "stream_connections": snapshot["reins_stream_connections"],
                },
                "error_rate": snapshot["error_rate"],
            }
        )

    async def evaluate_policy(self, payload: PolicyEvaluateRequest) -> PolicyDecision:
        effect = EffectDescriptor(
            capability=payload.capability,
            resource=payload.resource,
            intent_ref=payload.run_id,
            command_id=_new_ulid(),
        )
        decision = await self.policy_engine.evaluate(
            capability=payload.capability,
            run_id=payload.run_id,
            requested_by=payload.requested_by,
            effect_descriptor=effect,
            context=payload.context,
        )
        self.metrics.record_policy_evaluation(denied=decision.decision == "deny")
        await self.emit_event(
            "policy.evaluated",
            {
                "capability": payload.capability,
                "decision": decision.decision,
                "reason": decision.reason,
                "risk_tier": int(decision.risk_tier),
                "matched_rule": decision.matched_rule,
            },
        )
        return decision

    async def _assign_pending_jobs(self) -> None:
        pending = await self.list_jobs(status=JobStatus.PENDING.value)
        for job in pending:
            await self._assign_job(job.job_id)

    async def _assign_job(self, job_id: str) -> JobRecord:
        async with self._lock:
            job = self._jobs[job_id]
            if job.status is not JobStatus.PENDING:
                return job

        task = TaskAssignment(
            task_id=job.job_id,
            objective=job.objective,
            required_capabilities=job.required_capabilities,
            risk_tier=job.risk_tier,
            priority=job.priority,
            metadata=job.metadata,
        )
        try:
            assigned_agent_id = await self.protocol.assign_task(task)
        except ValueError:
            return job

        now = _utc_now()
        async with self._lock:
            current = self._jobs[job_id]
            if current.status is not JobStatus.PENDING:
                return current
            updated = current.model_copy(
                update={
                    "status": JobStatus.ASSIGNED,
                    "assigned_agent_id": assigned_agent_id,
                    "task_id": task.task_id,
                    "started_at": now,
                    "updated_at": now,
                }
            )
            self._jobs[job_id] = updated
            await self._append_job_event(
                JobJournalEvent(
                    type="job.assigned",
                    job_id=job_id,
                    payload={"job": updated.model_dump(mode="json")},
                )
            )
        await self._refresh_agent_metrics()
        await self.emit_event(
            "job.assigned",
            {"job": updated.model_dump(mode="json")},
            agent_id=assigned_agent_id,
            job_id=job_id,
        )
        return updated

    async def _refresh_agent_metrics(self) -> None:
        nodes = await self.registry.list_nodes()
        active = len([node for node in nodes if node.status is not NodeStatus.OFFLINE])
        self.metrics.set_agents(total=len(nodes), active=active)

    async def _jobs_assigned_to(self, agent_id: str) -> list[str]:
        async with self._lock:
            return [
                job.job_id
                for job in self._jobs.values()
                if job.assigned_agent_id == agent_id and job.status is JobStatus.ASSIGNED
            ]

    async def _requeue_jobs(self, job_ids: list[str]) -> None:
        if not job_ids:
            return
        now = _utc_now()
        async with self._lock:
            for job_id in job_ids:
                job = self._jobs.get(job_id)
                if job is None:
                    continue
                updated = job.model_copy(
                    update={
                        "status": JobStatus.PENDING,
                        "assigned_agent_id": None,
                        "task_id": None,
                        "updated_at": now,
                    }
                )
                self._jobs[job_id] = updated
                self._drop_protocol_task(job_id)
                await self._append_job_event(
                    JobJournalEvent(
                        type="job.submitted",
                        job_id=job_id,
                        payload={"job": updated.model_dump(mode="json")},
                    )
                )

    async def _release_agent_load(self, job: JobRecord) -> None:
        if job.assigned_agent_id is None:
            return
        node = await self.registry.get_node(job.assigned_agent_id)
        if node is None:
            return
        current_load = max(0, node.current_load - 1)
        status = node.status
        if status not in {NodeStatus.DRAINING, NodeStatus.OFFLINE}:
            status = NodeStatus.BUSY if current_load else NodeStatus.IDLE
        current_task_id = None if node.current_task_id == job.job_id else node.current_task_id
        await self.registry.heartbeat(
            node.node_id,
            status=status,
            current_load=current_load,
            current_task_id=current_task_id,
        )
        await self._refresh_agent_metrics()

    def _drop_protocol_task(self, job_id: str) -> None:
        self.protocol._tasks.pop(job_id, None)

    def _job_duration_seconds(self, job: JobRecord) -> float:
        started_at = job.started_at or job.created_at
        finished_at = job.finished_at or _utc_now()
        return max((finished_at - started_at).total_seconds(), 0.0)

    def _replay_jobs_sync(self) -> None:
        self._jobs = {}
        for line in self.job_journal_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = JobJournalEvent.model_validate_json(line)
            self._apply_job_event(event)
        self.metrics.jobs_total = len(self._jobs)
        self.metrics.jobs_completed = len(
            [job for job in self._jobs.values() if job.status is JobStatus.COMPLETED]
        )
        self.metrics.jobs_failed = len(
            [job for job in self._jobs.values() if job.status is JobStatus.FAILED]
        )

    def _apply_job_event(self, event: JobJournalEvent) -> None:
        job_payload = event.payload.get("job")
        if isinstance(job_payload, dict):
            self._jobs[event.job_id] = JobRecord.model_validate(job_payload)

    async def _append_job_event(self, event: JobJournalEvent) -> None:
        line = json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n"
        async with aiofiles.open(self.job_journal_path, "a", encoding="utf-8") as handle:
            await handle.write(line)
            await handle.flush()
            await asyncio.to_thread(os.fsync, handle.fileno())

    async def _append_control_event(self, event: ControlPlaneEventRecord) -> None:
        line = json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n"
        async with aiofiles.open(self.event_journal_path, "a", encoding="utf-8") as handle:
            await handle.write(line)
            await handle.flush()
            await asyncio.to_thread(os.fsync, handle.fileno())

    async def _request_json(
        self,
        request: web.Request,
        *,
        default: dict[str, Any] | None = None,
    ) -> dict[str, Any] | web.Response:
        if not request.can_read_body:
            return default or {}
        try:
            body = await request.json()
        except Exception:
            if default is not None:
                return default
            return _error("invalid JSON body")
        if not isinstance(body, dict):
            return _error("JSON body must be an object")
        return body

    def _agent_response(self, node: AgentNode) -> dict[str, Any]:
        data = node.model_dump(mode="json")
        data["id"] = node.node_id
        data["load_ratio"] = node.load_ratio
        data["success_rate"] = node.success_rate
        return data

    def _policy_decision_response(self, decision: PolicyDecision) -> dict[str, Any]:
        return {
            "decision": decision.decision,
            "risk_tier": int(decision.risk_tier),
            "grant_id": decision.grant_id,
            "reason": decision.reason,
            "matched_rule": decision.matched_rule,
            "triggered_constraints": list(decision.triggered_constraints),
        }


def setup_control_plane(app: web.Application, state_dir: Path | None = None) -> ControlPlane:
    control_plane = ControlPlane(state_dir=state_dir)
    app["control_plane"] = control_plane
    app["control_plane_policy"] = control_plane.policy_engine
    app["metrics"] = control_plane.metrics
    app["event_stream"] = control_plane.stream
    control_plane.add_routes(app)
    return control_plane
