"""Event builder — the trusted gate between validated commands and the journal.

This is the CQRS enforcement point.  Only this module creates committed
EventEnvelope records.  Model proposals, human text, webhooks, and remote
outputs NEVER reach the journal except through this gate.

The pipeline:
  CommandEnvelope → static validation → policy check (already done upstream)
  → execution observation → EventBuilder.commit() → EventEnvelope → journal
"""

from __future__ import annotations

import time
import ulid

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal
from reins.kernel.types import Actor, HandleRef


class EventBuilder:
    """Trusted event builder. The only path to the journal.

    Invariant: models never call this directly. Only kernel-trusted code paths
    (adapter runtime, policy engine, evaluator, scheduler) produce events.
    """

    def __init__(self, journal: EventJournal) -> None:
        self._journal = journal

    async def commit(
        self,
        run_id: str,
        event_type: str,
        payload: dict,
        *,
        actor: Actor = Actor.runtime,
        command_id: str | None = None,
        causation_id: str | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> EventEnvelope:
        """Create and persist a committed event. This is irreversible."""
        event = EventEnvelope(
            run_id=run_id,
            actor=actor,
            type=event_type,
            payload=payload,
            command_id=command_id,
            causation_id=causation_id,
            correlation_id=correlation_id,
            trace_id=trace_id or str(ulid.new()),
        )
        return await self._journal.append(event)

    async def emit_run_started(self, run_id: str, objective: str) -> EventEnvelope:
        return await self.commit(
            run_id,
            "run.started",
            {"objective": objective},
            actor=Actor.runtime,
        )

    async def emit_path_routed(self, run_id: str, path: str) -> EventEnvelope:
        return await self.commit(
            run_id,
            "path.routed",
            {"path": path},
            actor=Actor.runtime,
        )

    async def emit_grant_issued(
        self,
        run_id: str,
        grant_id: str,
        capability: str,
        scope: str,
        issued_to: str,
        ttl_seconds: int,
        approval_hash: str | None = None,
        inherited: bool = False,
    ) -> EventEnvelope:
        return await self.commit(
            run_id,
            "policy.grant_issued",
            {
                "grant_id": grant_id,
                "capability": capability,
                "scope": scope,
                "issued_to": issued_to,
                "ttl_seconds": ttl_seconds,
                "approval_hash": approval_hash,
                "issued_at": time.time(),
                "inherited": inherited,
            },
            actor=Actor.policy,
        )

    async def emit_grant_revoked(self, run_id: str, grant_id: str) -> EventEnvelope:
        return await self.commit(
            run_id,
            "policy.grant_revoked",
            {"grant_id": grant_id},
            actor=Actor.policy,
        )

    async def emit_approval_requested(
        self,
        run_id: str,
        approval_id: str,
        effect_summary: str,
        descriptor_hash: str | None = None,
    ) -> EventEnvelope:
        return await self.commit(
            run_id,
            "approval.requested",
            {
                "approval_id": approval_id,
                "summary": effect_summary,
                "descriptor_hash": descriptor_hash,
            },
            actor=Actor.policy,
        )

    async def emit_approval_resolved(
        self,
        run_id: str,
        approval_id: str,
        decision: str,
    ) -> EventEnvelope:
        return await self.commit(
            run_id,
            "approval.resolved",
            {"approval_id": approval_id, "decision": decision},
            actor=Actor.human,
        )

    async def emit_command_executed(
        self,
        run_id: str,
        command_id: str,
        observation: dict,
    ) -> EventEnvelope:
        return await self.commit(
            run_id,
            "command.executed",
            {"command_id": command_id, "observation": observation},
            actor=Actor.runtime,
            command_id=command_id,
        )

    async def emit_handle_opened(self, run_id: str, handle: HandleRef) -> EventEnvelope:
        return await self.commit(
            run_id,
            "adapter.handle_opened",
            {
                "handle_id": handle.handle_id,
                "adapter_kind": handle.adapter_kind,
                "adapter_id": handle.adapter_id,
            },
            actor=Actor.runtime,
        )

    async def emit_eval_completed(
        self,
        run_id: str,
        eval_id: str,
        passed: bool,
        failure_class: str | None = None,
        details: str = "",
    ) -> EventEnvelope:
        return await self.commit(
            run_id,
            "eval.completed",
            {
                "eval_id": eval_id,
                "passed": passed,
                "failure_class": failure_class,
                "details": details,
            },
            actor=Actor.evaluator,
        )

    async def emit_repair_required(
        self,
        run_id: str,
        eval_id: str,
        failure_class: str,
        repair_route: str,
        retry_allowed: bool,
        details: str,
        repair_hints: list[str],
        command_id: str | None = None,
    ) -> EventEnvelope:
        return await self.commit(
            run_id,
            "repair.required",
            {
                "eval_id": eval_id,
                "failure_class": failure_class,
                "repair_route": repair_route,
                "retry_allowed": retry_allowed,
                "details": details,
                "repair_hints": repair_hints,
                "command_id": command_id,
            },
            actor=Actor.evaluator,
            command_id=command_id,
        )

    async def emit_repair_started(
        self,
        run_id: str,
        command_id: str,
        previous_eval_id: str,
        previous_failure_class: str,
    ) -> EventEnvelope:
        return await self.commit(
            run_id,
            "repair.started",
            {
                "command_id": command_id,
                "previous_eval_id": previous_eval_id,
                "previous_failure_class": previous_failure_class,
            },
            actor=Actor.runtime,
            command_id=command_id,
        )

    async def emit_repair_finished(
        self,
        run_id: str,
        command_id: str,
        eval_id: str,
        resolved_failure_class: str | None = None,
    ) -> EventEnvelope:
        return await self.commit(
            run_id,
            "repair.finished",
            {
                "command_id": command_id,
                "eval_id": eval_id,
                "resolved_failure_class": resolved_failure_class,
            },
            actor=Actor.runtime,
            command_id=command_id,
        )

    async def emit_run_completed(self, run_id: str) -> EventEnvelope:
        return await self.commit(run_id, "run.completed", {}, actor=Actor.runtime)

    async def emit_run_failed(
        self,
        run_id: str,
        failure_class: str,
        reason: str,
    ) -> EventEnvelope:
        return await self.commit(
            run_id,
            "run.failed",
            {"failure_class": failure_class, "reason": reason},
            actor=Actor.runtime,
        )

    async def emit_run_dehydrated(
        self,
        run_id: str,
        checkpoint_id: str,
        snapshot_id: str | None = None,
    ) -> EventEnvelope:
        return await self.commit(
            run_id,
            "run.dehydrated",
            {"checkpoint_id": checkpoint_id, "snapshot_id": snapshot_id},
            actor=Actor.runtime,
        )

    async def emit_run_hydrated(
        self,
        run_id: str,
        checkpoint_id: str,
        snapshot_id: str | None = None,
    ) -> EventEnvelope:
        return await self.commit(
            run_id,
            "run.hydrated",
            {"checkpoint_id": checkpoint_id, "snapshot_id": snapshot_id},
            actor=Actor.runtime,
        )

    async def emit_run_aborted(self, run_id: str, reason: str) -> EventEnvelope:
        return await self.commit(
            run_id,
            "run.aborted",
            {"reason": reason},
            actor=Actor.human,
        )
