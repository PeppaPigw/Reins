"""RunRegistry — in-process orchestrator registry for the API server.

Maps run_id → RunOrchestrator.  Creates supporting stores under a
configurable base directory (default: .reins_state/).

For v1 this is in-process and file-backed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import ulid

from reins.context.compiler import ContextCompiler
from reins.execution.dispatcher import ExecutionDispatcher
from reins.evaluation.runner import EvaluationRunner
from reins.kernel.event.journal import EventJournal
from reins.kernel.intent.envelope import CommandProposal, IntentEnvelope, IntentIssuer
from reins.kernel.orchestrator import RunOrchestrator
from reins.kernel.reducer.state import RunState

from reins.memory.checkpoint import CheckpointStore
from reins.policy.approval.ledger import ApprovalLedger
from reins.policy.engine import PolicyEngine
from reins.kernel.snapshot.store import SnapshotStore
from reins.timeline.builder import TimelineBuilder


class RunRegistry:
    """Creates, tracks, and drives RunOrchestrators for HTTP clients."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = (base_dir or Path(".reins_state")).resolve()
        self._orchestrators: dict[str, RunOrchestrator] = {}
        self._journals: dict[str, EventJournal] = {}

    def _make_orchestrator(self, run_id: str) -> RunOrchestrator:
        journal_dir = self._base / "journals"
        snap_dir = self._base / "snapshots"
        ckpt_dir = self._base / "checkpoints"
        for d in (journal_dir, snap_dir, ckpt_dir):
            d.mkdir(parents=True, exist_ok=True)

        journal = EventJournal(journal_dir)
        snapshot_store = SnapshotStore(snap_dir)
        checkpoint_store = CheckpointStore(ckpt_dir)
        policy_engine = PolicyEngine()
        approval_ledger = ApprovalLedger(self._base / "approvals")
        context_compiler = ContextCompiler()
        dispatcher = ExecutionDispatcher()
        evaluation_runner = EvaluationRunner(evaluators={})

        orch = RunOrchestrator(
            journal=journal,
            snapshot_store=snapshot_store,
            checkpoint_store=checkpoint_store,
            policy_engine=policy_engine,
            context_compiler=context_compiler,
            approval_ledger=approval_ledger,
            dispatcher=dispatcher,
            evaluation_runner=evaluation_runner,
        )
        self._journals[run_id] = journal
        return orch

    async def create_run(
        self,
        objective: str,
        issuer: str = "user",
        constraints: list[str] | None = None,
        requested_capabilities: list[str] | None = None,
    ) -> RunState:
        run_id = str(ulid.new())
        try:
            issuer_enum = IntentIssuer(issuer)
        except ValueError:
            issuer_enum = IntentIssuer.user
        intent = IntentEnvelope(
            run_id=run_id,
            issuer=issuer_enum,
            objective=objective,
            constraints=constraints or [],
            requested_capabilities=requested_capabilities or [],
        )
        orch = self._make_orchestrator(run_id)
        state = await orch.intake(intent)
        self._orchestrators[run_id] = orch
        return state

    def get_state(self, run_id: str) -> RunState | None:
        orch = self._orchestrators.get(run_id)
        return orch.state if orch else None

    def _require(self, run_id: str) -> RunOrchestrator:
        orch = self._orchestrators.get(run_id)
        if orch is None:
            raise KeyError(run_id)
        return orch

    async def submit_command(
        self,
        run_id: str,
        kind: str,
        args: dict[str, Any],
        source: str = "model",
        rationale_ref: str | None = None,
        idempotency_key: str | None = None,
        evaluate: bool = False,
    ) -> dict[str, Any]:
        orch = self._require(run_id)
        proposal = CommandProposal(
            run_id=run_id,
            source=source,
            kind=kind,
            args=args,
            rationale_ref=rationale_ref,
            idempotency_key=idempotency_key or f"{run_id}:{kind}",
        )
        return await orch.process_proposal(proposal, evaluate=evaluate)

    async def approve(self, run_id: str, request_id: str, granted_by: str = "human"):
        return await self._require(run_id).approve(request_id, granted_by)

    async def reject(self, run_id: str, request_id: str, reason: str, rejected_by: str = "human"):
        return await self._require(run_id).reject(request_id, reason, rejected_by)

    async def abort(self, run_id: str, reason: str) -> RunState:
        return await self._require(run_id).abort(reason)

    async def resume(self, run_id: str, checkpoint_id: str | None) -> RunState:
        orch = self._orchestrators.get(run_id)
        if orch is None:
            # Cold resume — create a fresh orchestrator then hydrate
            orch = self._make_orchestrator(run_id)
            self._orchestrators[run_id] = orch
        if checkpoint_id is None:
            state = orch.state
            if state is None or state.last_checkpoint_id is None:
                raise KeyError(run_id)
            checkpoint_id = state.last_checkpoint_id
        return await orch.hydrate(checkpoint_id)

    async def get_timeline(self, run_id: str) -> dict[str, Any]:
        journal = self._journals.get(run_id)
        if journal is None:
            # Try to load from disk
            journal_dir = self._base / "journals"
            if not journal_dir.exists():
                raise KeyError(run_id)
            journal = EventJournal(journal_dir)
        builder = TimelineBuilder(journal)
        return await builder.build_summary(run_id)
