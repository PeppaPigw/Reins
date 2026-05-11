"""Integration tests for policy engine enforcement — no bypass vectors."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "reins"


class TestDispatcherImportRestriction:
    """Verify ExecutionDispatcher is only imported by authorized modules."""

    ALLOWED_IMPORTERS = {
        "kernel/orchestrator.py",
        "api/registry.py",
        "execution/__init__.py",
        "execution/dispatcher.py",
        "execution/adapters/mcp_adapter.py",  # docstring reference only
    }

    def test_dispatcher_only_imported_by_allowed_files(self) -> None:
        """Grep src/reins/ for ExecutionDispatcher imports and verify only allowed files."""
        violations: list[str] = []
        for py_file in SRC_ROOT.rglob("*.py"):
            relative = py_file.relative_to(SRC_ROOT).as_posix()
            if relative in self.ALLOWED_IMPORTERS:
                continue
            content = py_file.read_text(encoding="utf-8")
            if "ExecutionDispatcher" in content:
                violations.append(relative)
        assert violations == [], (
            f"ExecutionDispatcher imported in unauthorized files: {violations}"
        )


class TestDispatcherDispatchCallRestriction:
    """Verify .dispatch() is only called from the orchestrator."""

    ALLOWED_CALLERS = {
        "kernel/orchestrator.py",
        "execution/dispatcher.py",
    }

    def test_dispatch_only_called_from_orchestrator(self) -> None:
        """Grep for .dispatch( calls and verify only orchestrator.py calls it."""
        # Pattern: method call on dispatcher — obj.dispatch(
        pattern = re.compile(r"\.\s*dispatch\s*\(")
        violations: list[str] = []
        for py_file in SRC_ROOT.rglob("*.py"):
            relative = py_file.relative_to(SRC_ROOT).as_posix()
            if relative in self.ALLOWED_CALLERS:
                continue
            content = py_file.read_text(encoding="utf-8")
            # Skip test files and __pycache__
            if "__pycache__" in str(py_file):
                continue
            for i, line in enumerate(content.splitlines(), 1):
                # Skip comments and strings
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if pattern.search(line) and "dispatcher" in line.lower():
                    violations.append(f"{relative}:{i}")
        assert violations == [], (
            f".dispatch() called from unauthorized locations: {violations}"
        )


class TestPolicyBeforeDispatch:
    """Verify policy engine is always consulted before dispatch."""

    @pytest.mark.asyncio
    async def test_process_proposal_calls_policy_before_dispatch(self) -> None:
        """Mock policy engine + dispatcher, verify ordering."""
        from reins.kernel.orchestrator import RunOrchestrator
        from reins.kernel.intent.envelope import CommandProposal, IntentEnvelope, IntentIssuer
        from reins.kernel.event.journal import EventJournal
        from reins.kernel.snapshot.store import SnapshotStore
        from reins.memory.checkpoint import CheckpointStore
        from reins.policy.engine import PolicyEngine
        from reins.context.compiler import ContextCompiler
        from reins.execution.dispatcher import ExecutionDispatcher

        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp())
        journal = EventJournal(tmp / "journals")
        (tmp / "journals").mkdir(exist_ok=True)
        snapshot_store = SnapshotStore(tmp / "snapshots")
        (tmp / "snapshots").mkdir(exist_ok=True)
        checkpoint_store = CheckpointStore(tmp / "checkpoints")
        (tmp / "checkpoints").mkdir(exist_ok=True)

        # Track call order
        call_order: list[str] = []

        policy_engine = PolicyEngine()
        original_evaluate = policy_engine.evaluate

        async def mock_evaluate(*args, **kwargs):
            call_order.append("policy")
            return await original_evaluate(*args, **kwargs)

        policy_engine.evaluate = mock_evaluate

        dispatcher = ExecutionDispatcher()
        original_dispatch = dispatcher.dispatch

        async def mock_dispatch(*args, **kwargs):
            call_order.append("dispatch")
            return await original_dispatch(*args, **kwargs)

        dispatcher.dispatch = mock_dispatch

        orch = RunOrchestrator(
            journal=journal,
            snapshot_store=snapshot_store,
            checkpoint_store=checkpoint_store,
            policy_engine=policy_engine,
            context_compiler=ContextCompiler(),
            dispatcher=dispatcher,
        )

        intent = IntentEnvelope(
            run_id="test-run-001",
            issuer=IntentIssuer.user,
            objective="test",
            constraints=[],
            requested_capabilities=["fs.read"],
        )
        await orch.intake(intent)

        proposal = CommandProposal(
            run_id="test-run-001",
            source="model",
            kind="fs.read",
            args={"path": "/tmp/test.txt"},
        )
        await orch.process_proposal(proposal)

        assert "policy" in call_order, "Policy engine was never called"
        if "dispatch" in call_order:
            policy_idx = call_order.index("policy")
            dispatch_idx = call_order.index("dispatch")
            assert policy_idx < dispatch_idx, (
                f"Policy called at index {policy_idx}, dispatch at {dispatch_idx}"
            )

    @pytest.mark.asyncio
    async def test_policy_deny_prevents_dispatch(self) -> None:
        """Mock policy that denies, verify dispatch never called."""
        from reins.kernel.orchestrator import RunOrchestrator
        from reins.kernel.intent.envelope import CommandProposal, IntentEnvelope, IntentIssuer
        from reins.kernel.event.journal import EventJournal
        from reins.kernel.snapshot.store import SnapshotStore
        from reins.memory.checkpoint import CheckpointStore
        from reins.policy.engine import PolicyEngine, PolicyDecision
        from reins.context.compiler import ContextCompiler
        from reins.execution.dispatcher import ExecutionDispatcher
        from reins.kernel.types import RiskTier

        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp())
        journal = EventJournal(tmp / "journals")
        (tmp / "journals").mkdir(exist_ok=True)
        snapshot_store = SnapshotStore(tmp / "snapshots")
        (tmp / "snapshots").mkdir(exist_ok=True)
        checkpoint_store = CheckpointStore(tmp / "checkpoints")
        (tmp / "checkpoints").mkdir(exist_ok=True)

        dispatch_called = False

        policy_engine = PolicyEngine()

        async def deny_all(*args, **kwargs):
            return PolicyDecision(
                decision="deny",
                reason="test denial",
                risk_tier=RiskTier.T3,
                grant_id=None,
            )

        policy_engine.evaluate = deny_all

        dispatcher = ExecutionDispatcher()
        original_dispatch = dispatcher.dispatch

        async def track_dispatch(*args, **kwargs):
            nonlocal dispatch_called
            dispatch_called = True
            return await original_dispatch(*args, **kwargs)

        dispatcher.dispatch = track_dispatch

        orch = RunOrchestrator(
            journal=journal,
            snapshot_store=snapshot_store,
            checkpoint_store=checkpoint_store,
            policy_engine=policy_engine,
            context_compiler=ContextCompiler(),
            dispatcher=dispatcher,
        )

        intent = IntentEnvelope(
            run_id="test-run-002",
            issuer=IntentIssuer.user,
            objective="test",
            constraints=[],
            requested_capabilities=["fs.read"],
        )
        await orch.intake(intent)

        proposal = CommandProposal(
            run_id="test-run-002",
            source="model",
            kind="fs.read",
            args={"path": "/tmp/test.txt"},
        )
        result = await orch.process_proposal(proposal)

        assert result["granted"] is False
        assert "denial" in result.get("reason", "").lower() or "deny" in result.get("reason", "").lower()
        assert dispatch_called is False, "Dispatch was called despite policy denial"


class TestNoShellTrueBypass:
    """Verify no shell=True usage outside of hooks (potential command injection)."""

    def test_no_shell_true_in_non_hook_code(self) -> None:
        """Grep for shell=True excluding hooks.py, verify count is 0."""
        pattern = re.compile(r"shell\s*=\s*True")
        violations: list[str] = []
        for py_file in SRC_ROOT.rglob("*.py"):
            relative = py_file.relative_to(SRC_ROOT).as_posix()
            # Allow hooks to use shell=True (they run user-defined commands)
            if "hook" in relative.lower():
                continue
            if "__pycache__" in str(py_file):
                continue
            content = py_file.read_text(encoding="utf-8")
            for i, line in enumerate(content.splitlines(), 1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if pattern.search(line):
                    violations.append(f"{relative}:{i}")
        assert violations == [], (
            f"shell=True found in non-hook code (potential command injection): {violations}"
        )
