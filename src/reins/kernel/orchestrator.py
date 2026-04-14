"""Run orchestrator — the supervisor loop that drives a single Reins run.

Lifecycle (from SystemDesign §5.4):
  intake → route → [plan] → execute → evaluate → decide → [checkpoint]

This is the top-level entry point for turning an IntentEnvelope into
executed work with durable state.  It coordinates all planes.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import ulid

from reins.context.compiler import ContextCompiler
from reins.execution.adapter import Observation
from reins.execution.dispatcher import ExecutionDispatcher
from reins.evaluation.classifier import FailureClassifier
from reins.evaluation.runner import EvaluationRunner
from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.journal import EventJournal
from reins.kernel.intent.envelope import CommandEnvelope, CommandProposal, IntentEnvelope
from reins.kernel.reducer.reducer import REDUCER_VERSION, reduce
from reins.kernel.reducer.state import RunState, StateSnapshot
from reins.kernel.routing.router import route
from reins.kernel.snapshot.store import SnapshotStore
from reins.kernel.types import FailureClass, PathKind, RiskTier
from reins.memory.checkpoint import CheckpointStore, DehydrationMachine
from reins.policy.approval.ledger import ApprovalGrant, ApprovalLedger, ApprovalRejection, EffectDescriptor
from reins.policy.capabilities import CAPABILITY_RISK_TIERS
from reins.policy.engine import PolicyEngine
from reins.serde import to_primitive


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
        approval_ledger: ApprovalLedger | None = None,
        dispatcher: ExecutionDispatcher | None = None,
        evaluation_runner: EvaluationRunner | None = None,
    ) -> None:
        self._builder = EventBuilder(journal)
        self._journal = journal
        self._snapshots = snapshot_store
        self._checkpoints = checkpoint_store
        self._policy = policy_engine
        self._context = context_compiler
        self._approvals = approval_ledger
        self._dispatcher = dispatcher
        self._classifier = FailureClassifier()
        self._evaluation_runner = evaluation_runner
        self._dehydrator = DehydrationMachine()
        self._state: RunState | None = None
        self._intent: IntentEnvelope | None = None

    @property
    def state(self) -> RunState | None:
        return self._state

    # ------------------------------------------------------------------
    # Phase 1: Intake — normalize intent into a run
    # ------------------------------------------------------------------
    async def intake(self, intent: IntentEnvelope) -> RunState:
        """Start a new run from an intent. Returns initial RunState."""
        self._intent = intent
        self._state = RunState(run_id=intent.run_id)
        event = await self._builder.emit_run_started(
            intent.run_id, intent.objective,
        )
        self.apply_event(event)
        return self._state

    # ------------------------------------------------------------------
    # Phase 2: Route — fast path vs deliberative
    # ------------------------------------------------------------------
    async def route(self, ambiguity_score: float = 0.0, retry_count: int = 0) -> PathKind:
        """Route the run to fast or deliberative path."""
        assert self._state is not None
        requested_capabilities = (
            list(self._intent.requested_capabilities) if self._intent is not None else []
        )
        path = route(
            requested_capabilities=requested_capabilities,
            ambiguity_score=ambiguity_score,
            retry_count=retry_count,
            pending_approval=bool(self._state.pending_approvals),
        )
        event = await self._builder.emit_path_routed(self._state.run_id, path.value)
        self.apply_event(event)
        return path

    # ------------------------------------------------------------------
    # Phase 3: Process a command proposal from the model
    # ------------------------------------------------------------------
    async def process_proposal(
        self,
        proposal: CommandProposal,
        evaluate: bool = False,
        eval_context: dict[str, Any] | None = None,
    ) -> dict:
        """Validate, policy-check, and execute a command proposal.

        Args:
            proposal: the untrusted proposal from the model
            evaluate: whether to run evaluators after execution
            eval_context: optional context for evaluators

        Returns:
            Result dict with keys: granted, executed, eval_passed, observation
        """
        assert self._state is not None
        run_id = self._state.run_id
        if proposal.run_id != run_id:
            return {"granted": False, "reason": f"proposal run mismatch: {proposal.run_id} != {run_id}"}

        command = self._materialize_command(proposal)
        validation_error = self._validate_command(command)
        if validation_error is not None:
            return {
                "granted": False,
                "command_id": command.command_id,
                "reason": validation_error,
            }

        effect = self._build_effect_descriptor(command)

        # 1. Policy check
        decision = await self._policy.evaluate(
            capability=command.normalized_kind,
            run_id=run_id,
            requested_by=proposal.source,
            effect_descriptor=effect,
            active_grants=self._state.active_grants,
        )

        if decision.decision == "deny":
            return {"granted": False, "command_id": command.command_id, "reason": decision.reason}

        if decision.decision == "route_remote":
            event = await self._builder.commit(
                run_id=run_id,
                event_type="integration.remote_required",
                payload={
                    "capability": command.normalized_kind,
                    "command_id": command.command_id,
                    "resource": effect.resource,
                    "reason": decision.reason,
                },
            )
            self.apply_event(event)
            return {
                "granted": False,
                "command_id": command.command_id,
                "routed_remote": True,
                "reason": decision.reason,
            }

        if decision.decision == "ask":
            if self._approvals is None:
                return {
                    "granted": False,
                    "command_id": command.command_id,
                    "reason": "approval required but no approval ledger is configured",
                }
            request = await self._approvals.request(run_id, effect, proposal.source)
            event = await self._builder.emit_approval_requested(
                run_id, request.request_id, effect.summary,
                descriptor_hash=effect.descriptor_hash,
            )
            self.apply_event(event)
            return {
                "granted": False,
                "command_id": command.command_id,
                "needs_approval": True,
                "request_id": request.request_id,
                "descriptor_hash": effect.descriptor_hash,
                "reason": decision.reason,
            }

        # 2. Grant issued
        if decision.grant_id:
            event = await self._builder.emit_grant_issued(
                run_id, decision.grant_id, command.normalized_kind,
                scope=effect.resource, issued_to=proposal.source,
                ttl_seconds=600,
            )
            self.apply_event(event)

        pending_repair = self._state.pending_repair
        if pending_repair is not None and self._should_start_repair(command):
            repair_started = await self._builder.emit_repair_started(
                run_id,
                command.command_id,
                pending_repair.eval_id,
                pending_repair.failure_class.value,
            )
            self.apply_event(repair_started)

        # 3. Execute - dispatcher is required
        if self._dispatcher is None:
            return {
                "granted": False,
                "command_id": command.command_id,
                "reason": "no execution dispatcher configured",
            }

        if not self._dispatcher.supports(command.normalized_kind):
            return {
                "granted": False,
                "command_id": command.command_id,
                "reason": f"unsupported capability: {command.normalized_kind}",
            }

        dispatch = await self._dispatcher.dispatch(run_id, command)
        if dispatch.opened_new_handle:
            opened = await self._builder.emit_handle_opened(run_id, dispatch.handle_ref)
            self.apply_event(opened)

        observation = self._normalize_observation(dispatch.observation)
        observation.setdefault("effect_descriptor", to_primitive(effect))

        event = await self._builder.emit_command_executed(
            run_id, command.command_id, observation,
        )
        self.apply_event(event)

        outcome = None
        if evaluate and self._evaluation_runner is not None:
            outcome = await self._evaluation_runner.evaluate(
                command,
                observation,
                eval_context,
            )
            for result in outcome.results:
                classified_failure = result.failure_class
                if classified_failure is None and not result.passed:
                    classified_failure = outcome.failure_class
                eval_event = await self._builder.emit_eval_completed(
                    run_id,
                    result.eval_id,
                    result.passed,
                    failure_class=(
                        classified_failure.value
                        if classified_failure is not None
                        else None
                    ),
                    details=str(result.details),
                )
                self.apply_event(eval_event)
            if outcome.passed and self._state.repairing_command_id == command.command_id:
                finishing_eval = outcome.results[-1]
                repair_finished = await self._builder.emit_repair_finished(
                    run_id,
                    command.command_id,
                    finishing_eval.eval_id,
                    resolved_failure_class=(
                        self._state.last_failure_class.value
                        if self._state.last_failure_class is not None
                        else None
                    ),
                )
                self.apply_event(repair_finished)
            if not outcome.passed and outcome.failure_class is not None:
                failing = next((result for result in outcome.results if not result.passed), None)
                repair_event = await self._builder.emit_repair_required(
                    run_id,
                    failing.eval_id if failing is not None else command.command_id,
                    outcome.failure_class.value,
                    outcome.repair_route or "change_hypothesis",
                    bool(outcome.retry_allowed),
                    str(failing.details) if failing is not None else "",
                    list(failing.repair_hints) if failing is not None else [],
                    command_id=command.command_id,
                )
                self.apply_event(repair_event)

        response = {
            "granted": True,
            "executed": True,
            "command_id": command.command_id,
            "observation": observation,
        }
        if outcome is not None:
            response.update({
                "eval_passed": outcome.passed,
                "eval_results": [to_primitive(result) for result in outcome.results],
                "failure_class": outcome.failure_class.value if outcome.failure_class else None,
                "repair_route": outcome.repair_route,
                "retry_allowed": outcome.retry_allowed,
            })
        return response

    async def approve(
        self, request_id: str, granted_by: str = "human",
    ) -> ApprovalGrant | None:
        """Resolve a pending approval request into a grant."""
        assert self._state is not None
        if self._approvals is None:
            return None
        grant = await self._approvals.approve(request_id, granted_by)
        if grant is None:
            return None

        resolved = await self._builder.emit_approval_resolved(
            self._state.run_id, request_id, "approved",
        )
        self.apply_event(resolved)
        issued = await self._builder.emit_grant_issued(
            self._state.run_id,
            grant.grant_id,
            grant.capability,
            grant.scope,
            granted_by,
            grant.ttl_seconds,
            approval_hash=grant.descriptor_hash,
        )
        self.apply_event(issued)
        return grant

    async def reject(
        self, request_id: str, reason: str, rejected_by: str = "human",
    ) -> ApprovalRejection | None:
        """Resolve a pending approval request into a rejection."""
        assert self._state is not None
        if self._approvals is None:
            return None
        rejection = await self._approvals.reject(request_id, reason, rejected_by)
        if rejection is None:
            return None
        resolved = await self._builder.emit_approval_resolved(
            self._state.run_id, request_id, "rejected",
        )
        self.apply_event(resolved)
        return rejection

    # ------------------------------------------------------------------
    # Phase 4: Complete or fail the run
    # ------------------------------------------------------------------
    async def complete(self) -> RunState:
        """Mark the run as completed."""
        assert self._state is not None
        event = await self._builder.emit_run_completed(self._state.run_id)
        self.apply_event(event)
        return self._state

    async def fail(self, failure_class: FailureClass, reason: str) -> RunState:
        """Mark the run as failed with a typed failure class."""
        assert self._state is not None
        event = await self._builder.emit_run_failed(
            self._state.run_id, failure_class.value, reason,
        )
        self.apply_event(event)
        return self._state

    async def abort(self, reason: str) -> RunState:
        """Abort the run (human-initiated kill switch)."""
        assert self._state is not None
        event = await self._builder.emit_run_aborted(self._state.run_id, reason)
        self.apply_event(event)
        return self._state

    # ------------------------------------------------------------------
    # Phase 5: Dehydrate / hydrate
    # ------------------------------------------------------------------
    async def dehydrate(self) -> str:
        """Dehydrate the run into a checkpoint. Returns checkpoint_id."""
        assert self._state is not None
        snapshot = await self._save_snapshot(self._state)
        frozen_handles = None
        if self._dispatcher is not None:
            frozen_handles = await self._dispatcher.freeze_run(self._state.run_id)
        manifest = await self._dehydrator.dehydrate(
            replace(self._state, snapshot_id=snapshot.snapshot_id),
            self._journal,
            frozen_handles=frozen_handles,
        )
        await self._checkpoints.save(manifest)
        event = await self._builder.emit_run_dehydrated(
            self._state.run_id, manifest.checkpoint_id, snapshot.snapshot_id,
        )
        self.apply_event(event)
        return manifest.checkpoint_id

    async def hydrate(self, checkpoint_id: str) -> RunState:
        """Hydrate a run from a checkpoint."""
        manifest = await self._load_checkpoint(checkpoint_id)
        snapshot = None
        if manifest.snapshot_id is not None:
            snapshot = await self._snapshots.load(manifest.run_id, manifest.snapshot_id)
        self._state = await self._dehydrator.hydrate(manifest, snapshot)
        if self._dispatcher is not None and manifest.frozen_handles:
            restored_handles = await self._dispatcher.thaw_run(
                manifest.run_id, manifest.frozen_handles,
            )
            self._state = replace(self._state, open_handles=restored_handles)
        event = await self._builder.emit_run_hydrated(
            self._state.run_id,
            manifest.checkpoint_id,
            self._state.snapshot_id,
        )
        self.apply_event(event)
        return self._state

    def apply_event(self, event: EventEnvelope) -> RunState:
        """Apply a committed event to the in-memory reducer state."""
        assert self._state is not None
        self._state = reduce(self._state, event)
        return self._state

    def _build_effect_descriptor(self, command: CommandEnvelope) -> EffectDescriptor:
        resource = self._infer_resource(command.args)
        return EffectDescriptor(
            capability=command.normalized_kind,
            resource=resource,
            intent_ref=self._intent.intent_id if self._intent is not None else command.run_id,
            command_id=command.command_id,
            preview_ref=command.evidence_refs[0] if command.evidence_refs else None,
            side_effects=[command.normalized_kind],
        )

    @staticmethod
    def _infer_resource(args: dict[str, Any]) -> str:
        for key in ("path", "target", "branch", "resource", "agent", "uri", "repo", "cwd"):
            value = args.get(key)
            if value:
                return str(value)
        if args:
            first_key = next(iter(args))
            return f"{first_key}={args[first_key]}"
        return "workspace"

    @staticmethod
    def _normalize_observation(result: Observation | dict[str, Any]) -> dict[str, Any]:
        if isinstance(result, Observation):
            return to_primitive(result)
        return dict(result)

    def _materialize_command(self, proposal: CommandProposal) -> CommandEnvelope:
        resource = self._infer_resource(proposal.args)
        risk_tier = RiskTier(CAPABILITY_RISK_TIERS.get(proposal.kind, RiskTier.T4))
        return CommandEnvelope(
            run_id=proposal.run_id,
            normalized_kind=proposal.kind,
            args=dict(proposal.args),
            parent_proposal_id=proposal.proposal_id,
            preconditions={},
            policy_scope={"resource": resource},
            risk_tier=risk_tier,
            idempotency_key=(
                proposal.idempotency_key
                or f"{proposal.run_id}:{proposal.kind}:{resource}"
            ),
            evidence_refs=[proposal.rationale_ref] if proposal.rationale_ref else [],
        )

    def _validate_command(self, command: CommandEnvelope) -> str | None:
        if command.normalized_kind not in CAPABILITY_RISK_TIERS:
            return f"unknown capability: {command.normalized_kind}"

        args = command.args
        required_args = {
            "fs.read": ("path",),
            "fs.write.workspace": ("path",),
            "git.commit": ("message",),
            "exec.shell.sandboxed": ("cmd",),
            "exec.shell.network": ("cmd",),
            "a2a.agent.call": ("agent",),
        }
        missing = [
            name for name in required_args.get(command.normalized_kind, ())
            if not args.get(name)
        ]
        if missing:
            return f"missing required args for {command.normalized_kind}: {', '.join(missing)}"
        if command.normalized_kind == "test.run" and "args" in args and not isinstance(args["args"], list):
            return "test.run args must be a list"
        if command.normalized_kind.startswith("git.") and "repo" in args and not isinstance(args["repo"], str):
            return "git repo must be a string path"
        return None

    async def _save_snapshot(self, state: RunState) -> StateSnapshot:
        event_seq = await self._journal.get_seq(state.run_id)
        snapshot = StateSnapshot(
            snapshot_id=str(ulid.new()),
            run_id=state.run_id,
            event_seq=event_seq,
            reducer_version=REDUCER_VERSION,
            run_phase=state.status.value,
            current_node_id=state.current_node_id,
            active_grants=list(state.active_grants),
            pending_approvals=list(state.pending_approvals),
            open_questions=list(state.open_questions),
            last_failure_class=state.last_failure_class,
            pending_repair=state.pending_repair,
            repairing_command_id=state.repairing_command_id,
            last_completed_repair=state.last_completed_repair,
            working_set_manifest_ref=state.working_set_manifest_ref,
        )
        await self._snapshots.save(snapshot)
        return snapshot

    async def _load_checkpoint(self, checkpoint_id: str):
        if self._state is not None:
            return await self._checkpoints.load(self._state.run_id, checkpoint_id)
        return await self._checkpoints.load_any(checkpoint_id)

    def _should_start_repair(self, command: CommandEnvelope) -> bool:
        assert self._state is not None
        if self._state.pending_repair is None:
            return False
        return command.risk_tier >= RiskTier.T1
