"""Run orchestrator — the supervisor loop that drives a single Reins run.

Lifecycle (from SystemDesign §5.4):
  intake → route → [plan] → execute → evaluate → decide → [checkpoint]

This is the top-level entry point for turning an IntentEnvelope into
executed work with durable state.  It coordinates all planes.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import ulid

from reins.context.compiler import ContextCompiler
from reins.evaluation.classifier import FailureClassifier
from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.journal import EventJournal
from reins.kernel.intent.envelope import CommandProposal, IntentEnvelope
from reins.kernel.reducer.reducer import reduce
from reins.kernel.reducer.state import RunState
from reins.kernel.routing.router import route
from reins.kernel.snapshot.store import SnapshotStore
from reins.kernel.types import Actor, FailureClass, PathKind, RunStatus
from reins.memory.checkpoint import CheckpointStore, DehydrationMachine
from reins.policy.engine import PolicyEngine


class RunOrchestrator:
    """Supervisor loop for a single Reins run.

    Coordinates: intent intake, routing, policy, execution,
    evaluation, state reduction, and checkpoint/dehydration.

    The orchestrator does NOT call the model.  It receives
    CommandProposals from an external model adapter and processes
    them through the trusted pipeline.
    """

    def __init__(
        self,
        journal: EventJournal,
        snapshot_store: SnapshotStore,
        checkpoint_store: CheckpointStore,
        policy_engine: PolicyEngine,
        context_compiler: ContextCompiler,
    ) -> None:
        self._builder = EventBuilder(journal)
        self._journal = journal
        self._snapshots = snapshot_store
        self._checkpoints = checkpoint_store
        self._policy = policy_engine
        self._context = context_compiler
        self._classifier = FailureClassifier()
        self._dehydrator = DehydrationMachine()
        self._state: RunState | None = None

    @property
    def state(self) -> RunState | None:
        return self._state

    # ------------------------------------------------------------------
    # Phase 1: Intake — normalize intent into a run
    # ------------------------------------------------------------------
    async def intake(self, intent: IntentEnvelope) -> RunState:
        """Start a new run from an intent. Returns initial RunState."""
        self._state = RunState(run_id=intent.run_id)
        event = await self._builder.emit_run_started(
            intent.run_id, intent.objective,
        )
        self._state = reduce(self._state, event)
        return self._state

    # ------------------------------------------------------------------
    # Phase 2: Route — fast path vs deliberative
    # ------------------------------------------------------------------
    async def route(self) -> PathKind:
        """Route the run to fast or deliberative path."""
        assert self._state is not None
        path = route(
            requested_capabilities=[],  # filled by intent analysis
            ambiguity_score=0.0,
            retry_count=0,
            pending_approval=bool(self._state.pending_approvals),
        )
        event = await self._builder.emit_path_routed(self._state.run_id, path.value)
        self._state = reduce(self._state, event)
        return path

    # ------------------------------------------------------------------
    # Phase 3: Process a command proposal from the model
    # ------------------------------------------------------------------
    async def process_proposal(
        self,
        proposal: CommandProposal,
        execute_fn: Any = None,
    ) -> dict:
        """Validate, policy-check, and execute a command proposal.

        Args:
            proposal: the untrusted proposal from the model
            execute_fn: optional async callable(kind, args) -> observation dict
                        If None, returns a dry-run observation.

        Returns:
            Result dict with keys: granted, executed, eval_passed, observation
        """
        assert self._state is not None
        run_id = self._state.run_id

        # 1. Policy check
        decision = await self._policy.evaluate(
            capability=proposal.kind,
            run_id=run_id,
            requested_by=proposal.source,
        )

        if decision.decision == "deny":
            return {"granted": False, "reason": decision.reason}

        if decision.decision == "ask":
            approval_id = str(ulid.new())
            event = await self._builder.emit_approval_requested(
                run_id, approval_id, decision.reason,
            )
            self._state = reduce(self._state, event)
            return {"granted": False, "needs_approval": True, "reason": decision.reason}

        # 2. Grant issued
        if decision.grant_id:
            event = await self._builder.emit_grant_issued(
                run_id, decision.grant_id, proposal.kind,
                scope="workspace", issued_to=proposal.source,
                ttl_seconds=600,
            )
            self._state = reduce(self._state, event)

        # 3. Execute
        observation: dict = {}
        if execute_fn is not None:
            observation = await execute_fn(proposal.kind, proposal.args)
        else:
            observation = {"dry_run": True, "kind": proposal.kind, "args": proposal.args}

        event = await self._builder.emit_command_executed(
            run_id, proposal.proposal_id, observation,
        )
        self._state = reduce(self._state, event)

        return {
            "granted": True,
            "executed": True,
            "observation": observation,
        }

    # ------------------------------------------------------------------
    # Phase 4: Complete or fail the run
    # ------------------------------------------------------------------
    async def complete(self) -> RunState:
        """Mark the run as completed."""
        assert self._state is not None
        event = await self._builder.emit_run_completed(self._state.run_id)
        self._state = reduce(self._state, event)
        return self._state

    async def fail(self, failure_class: FailureClass, reason: str) -> RunState:
        """Mark the run as failed with a typed failure class."""
        assert self._state is not None
        event = await self._builder.emit_run_failed(
            self._state.run_id, failure_class.value, reason,
        )
        self._state = reduce(self._state, event)
        return self._state

    async def abort(self, reason: str) -> RunState:
        """Abort the run (human-initiated kill switch)."""
        assert self._state is not None
        event = await self._builder.emit_run_aborted(self._state.run_id, reason)
        self._state = reduce(self._state, event)
        return self._state

    # ------------------------------------------------------------------
    # Phase 5: Dehydrate / hydrate
    # ------------------------------------------------------------------
    async def dehydrate(self) -> str:
        """Dehydrate the run into a checkpoint. Returns checkpoint_id."""
        assert self._state is not None
        manifest = await self._dehydrator.dehydrate(self._state, self._journal)
        await self._checkpoints.save(manifest)
        event = await self._builder.emit_run_dehydrated(
            self._state.run_id, manifest.checkpoint_id,
        )
        self._state = reduce(self._state, event)
        return manifest.checkpoint_id

    async def hydrate(self, checkpoint_id: str) -> RunState:
        """Hydrate a run from a checkpoint."""
        assert self._state is not None
        manifest = await self._checkpoints.load(self._state.run_id, checkpoint_id)
        self._state = await self._dehydrator.hydrate(manifest)
        return self._state
