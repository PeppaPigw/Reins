"""Core orchestration engine for multi-agent workflows.

This module provides a lightweight orchestration surface on top of the
existing kernel primitives. It is intentionally narrow:

- route an intent to the fast or deliberative path
- evaluate policy for requested capabilities
- request approvals for high-risk operations
- spawn a logical subagent handle for deliberative work
- collect structured results from the event journal

The implementation avoids taking dependencies on the unfinished
``reins.orchestration`` helpers that currently rely on non-existent
``EventJournal`` APIs. Instead, it writes and reads directly from the
existing append-only journal contract.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Mapping

import ulid

from reins.approval.ledger import ApprovalLedger, ApprovalRequest, EffectDescriptor
from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal
from reins.kernel.intent.envelope import IntentEnvelope
from reins.kernel.routing.router import route
from reins.kernel.types import Actor, PathKind, RiskTier
from reins.policy.engine import PolicyDecision, PolicyEngine


@dataclass(frozen=True)
class AgentHandle:
    """Track a spawned orchestration subagent."""

    agent_id: str
    agent_type: str
    run_id: str
    context: dict[str, Any] = field(default_factory=dict)
    spawned_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class AgentResult:
    """Structured result collected from a subagent event stream."""

    agent_id: str
    agent_type: str
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    exit_code: int | None = None
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ExecutionResult:
    """Outcome of orchestrating an intent."""

    run_id: str
    path: PathKind
    status: str
    policy_decisions: tuple[PolicyDecision, ...] = ()
    approval_requests: tuple[ApprovalRequest, ...] = ()
    subagent_handle: AgentHandle | None = None
    agent_result: AgentResult | None = None
    output: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None


class Orchestrator:
    """Central orchestration engine for fast vs deliberative execution."""

    def __init__(
        self,
        *,
        journal: EventJournal,
        policy_engine: PolicyEngine,
        approval_ledger: ApprovalLedger | None = None,
        poll_interval_seconds: float = 0.01,
    ) -> None:
        self._journal = journal
        self._policy = policy_engine
        self._approvals = approval_ledger
        self._poll_interval_seconds = poll_interval_seconds
        self._handles: dict[str, AgentHandle] = {}

    async def execute_intent(self, intent: IntentEnvelope) -> ExecutionResult:
        """Route an intent, evaluate policy, and execute the chosen path."""
        await self._emit_event(
            run_id=intent.run_id,
            event_type="orchestrator.intent_received",
            payload={
                "intent_id": intent.intent_id,
                "objective": intent.objective,
                "requested_capabilities": list(intent.requested_capabilities),
                "issuer": intent.issuer.value,
            },
        )

        policy_decisions = await self._evaluate_policy(intent)
        approval_requests = await self._request_approvals(intent, policy_decisions)
        path = self._decide_path(intent, approval_requests=approval_requests)

        await self._emit_event(
            run_id=intent.run_id,
            event_type="orchestrator.route_decided",
            payload={
                "intent_id": intent.intent_id,
                "path": path.value,
                "policy_decisions": [decision.decision for decision in policy_decisions],
                "approval_request_ids": [request.request_id for request in approval_requests],
            },
        )

        if path is PathKind.fast:
            output = {
                "mode": "fast",
                "objective": intent.objective,
                "capabilities": list(intent.requested_capabilities),
            }
            return ExecutionResult(
                run_id=intent.run_id,
                path=path,
                status="completed",
                policy_decisions=tuple(policy_decisions),
                approval_requests=tuple(approval_requests),
                output=output,
            )

        handle = await self.spawn_subagent(
            agent_type="deliberative",
            context={
                "intent_id": intent.intent_id,
                "objective": intent.objective,
                "requested_capabilities": list(intent.requested_capabilities),
                "attachments": [artifact.artifact_id for artifact in intent.attachments],
                "constraints": list(intent.constraints),
                "run_id": intent.run_id,
            },
        )
        self._handles[handle.agent_id] = handle

        if approval_requests:
            await self._emit_event(
                run_id=intent.run_id,
                event_type="orchestrator.subagent_failed",
                payload={
                    "agent_id": handle.agent_id,
                    "agent_type": handle.agent_type,
                    "status": "approval_required",
                    "error_message": "approval required before deliberative execution",
                    "approval_request_ids": [request.request_id for request in approval_requests],
                    "output": {},
                    "exit_code": None,
                },
            )
        else:
            await self._emit_event(
                run_id=intent.run_id,
                event_type="orchestrator.subagent_completed",
                payload={
                    "agent_id": handle.agent_id,
                    "agent_type": handle.agent_type,
                    "status": "completed",
                    "output": {
                        "mode": "deliberative",
                        "objective": intent.objective,
                    },
                    "exit_code": 0,
                },
            )

        agent_result = await self.collect_results(handle)
        status = "completed" if agent_result.status == "completed" else agent_result.status
        return ExecutionResult(
            run_id=intent.run_id,
            path=path,
            status=status,
            policy_decisions=tuple(policy_decisions),
            approval_requests=tuple(approval_requests),
            subagent_handle=handle,
            agent_result=agent_result,
            output=agent_result.output,
            error_message=agent_result.error_message,
        )

    async def spawn_subagent(self, agent_type: str, context: dict[str, Any]) -> AgentHandle:
        """Create a logical subagent handle and journal the spawn event."""
        run_id = str(context.get("run_id") or ulid.new())
        handle = AgentHandle(
            agent_id=f"agent-{ulid.new()}",
            agent_type=agent_type,
            run_id=run_id,
            context=dict(context),
        )
        self._handles[handle.agent_id] = handle

        await self._emit_event(
            run_id=run_id,
            event_type="orchestrator.subagent_spawned",
            payload={
                "agent_id": handle.agent_id,
                "agent_type": handle.agent_type,
                "context_keys": sorted(handle.context.keys()),
            },
        )
        return handle

    async def collect_results(self, handle: AgentHandle) -> AgentResult:
        """Wait for subagent terminal events and return a structured result."""
        from_seq = 0
        while True:
            seen_event = False
            async for event in self._journal.read_from(handle.run_id, from_seq=from_seq):
                seen_event = True
                from_seq = max(from_seq, event.seq + 1)
                if event.type not in {
                    "orchestrator.subagent_completed",
                    "orchestrator.subagent_failed",
                }:
                    continue
                if event.payload.get("agent_id") != handle.agent_id:
                    continue

                status = (
                    "completed"
                    if event.type == "orchestrator.subagent_completed"
                    else str(event.payload.get("status") or "failed")
                )
                return AgentResult(
                    agent_id=handle.agent_id,
                    agent_type=handle.agent_type,
                    status=status,
                    output=self._coerce_mapping(event.payload.get("output")),
                    error_message=self._coerce_optional_str(event.payload.get("error_message")),
                    exit_code=self._coerce_optional_int(event.payload.get("exit_code")),
                    completed_at=event.ts,
                )

            if not seen_event:
                await asyncio.sleep(self._poll_interval_seconds)

    def _decide_path(
        self,
        intent: IntentEnvelope,
        *,
        approval_requests: list[ApprovalRequest],
    ) -> PathKind:
        return route(
            requested_capabilities=list(intent.requested_capabilities),
            pending_approval=bool(approval_requests),
        )

    async def _evaluate_policy(self, intent: IntentEnvelope) -> list[PolicyDecision]:
        decisions: list[PolicyDecision] = []
        for capability in intent.requested_capabilities:
            effect = self._build_effect_descriptor(intent, capability)
            decision = await self._policy.evaluate(
                capability=capability,
                run_id=intent.run_id,
                requested_by=intent.issuer.value,
                effect_descriptor=effect,
            )
            decisions.append(decision)
        return decisions

    async def _request_approvals(
        self,
        intent: IntentEnvelope,
        policy_decisions: list[PolicyDecision],
    ) -> list[ApprovalRequest]:
        requests: list[ApprovalRequest] = []
        if self._approvals is None:
            return requests

        for capability, decision in zip(intent.requested_capabilities, policy_decisions, strict=False):
            if decision.decision != "ask":
                continue
            effect = self._build_effect_descriptor(intent, capability)
            request = await self._approvals.request(
                intent.run_id,
                effect,
                intent.issuer.value,
                reason=decision.reason,
            )
            requests.append(request)
        return requests

    def _build_effect_descriptor(
        self,
        intent: IntentEnvelope,
        capability: str,
    ) -> EffectDescriptor:
        resource = intent.objective
        rollback_strategy = "none"
        reversibility = "irreversible"

        tier_value = self._policy_capability_tier(capability)
        if tier_value <= RiskTier.T1:
            reversibility = "reversible"
            rollback_strategy = "compensating_action"

        return EffectDescriptor(
            capability=capability,
            resource=resource,
            intent_ref=intent.intent_id,
            command_id=f"intent-{intent.intent_id}:{capability}",
            rollback_strategy=rollback_strategy,
            reversibility=reversibility,
        )

    @staticmethod
    def _policy_capability_tier(capability: str) -> RiskTier:
        from reins.policy.capabilities import CAPABILITY_RISK_TIERS

        return RiskTier(CAPABILITY_RISK_TIERS.get(capability, RiskTier.T4))

    async def _emit_event(
        self,
        *,
        run_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> EventEnvelope:
        event = EventEnvelope(
            run_id=run_id,
            actor=Actor.runtime,
            type=event_type,
            payload=dict(payload),
        )
        return await self._journal.append(event)

    @staticmethod
    def _coerce_mapping(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    @staticmethod
    def _coerce_optional_str(value: Any) -> str | None:
        return value if isinstance(value, str) else None

    @staticmethod
    def _coerce_optional_int(value: Any) -> int | None:
        return value if isinstance(value, int) else None
