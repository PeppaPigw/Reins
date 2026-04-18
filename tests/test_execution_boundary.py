"""Comprehensive tests for execution boundary enforcement.

Tests that verify:
1. Path containment in filesystem operations
2. Sandbox vs network shell separation
3. Capability rejection for unsupported operations
4. No dry-run execution journaling
"""

import pytest
from pathlib import Path

from reins.execution.adapters.fs import FilesystemAdapter
from reins.execution.adapters.shell import NetworkShellAdapter, SandboxedShellAdapter
from reins.execution.dispatcher import ExecutionDispatcher
from reins.kernel.event.journal import EventJournal
from reins.kernel.intent.envelope import CommandProposal, IntentEnvelope
from reins.kernel.orchestrator import RunOrchestrator
from reins.kernel.snapshot.store import SnapshotStore
from reins.memory.checkpoint import CheckpointStore
from reins.policy.engine import PolicyEngine
from reins.context.compiler import ContextCompiler


def _make_orchestrator(tmp_path: Path) -> RunOrchestrator:
    journal = EventJournal(tmp_path / "journal.jsonl")
    snapshots = SnapshotStore(tmp_path / "snapshots")
    checkpoints = CheckpointStore(tmp_path / "checkpoints")
    policy = PolicyEngine()
    context = ContextCompiler()
    dispatcher = ExecutionDispatcher()
    return RunOrchestrator(
        journal, snapshots, checkpoints, policy, context, dispatcher=dispatcher
    )


@pytest.mark.asyncio
async def test_filesystem_path_escape_rejected(tmp_path):
    """Filesystem adapter must reject path escape attempts."""
    adapter = FilesystemAdapter()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Create file outside workspace
    outside = tmp_path / "secret.txt"
    outside.write_text("confidential")

    handle = await adapter.open({"root": str(workspace)})

    # Attempt 1: ../ escape
    result = await adapter.exec(handle, {"op": "read", "path": "../secret.txt"})
    assert result.exit_code != 0
    assert "path escape" in result.stderr

    # Attempt 2: Absolute path
    result = await adapter.exec(handle, {"op": "read", "path": str(outside)})
    assert result.exit_code != 0
    assert "path escape" in result.stderr

    # Attempt 3: Move to outside
    (workspace / "data.txt").write_text("data")
    result = await adapter.exec(
        handle, {"op": "move", "path": "data.txt", "dest": "../escaped.txt"}
    )
    assert result.exit_code != 0
    assert "path escape" in result.stderr

    await adapter.close(handle)


@pytest.mark.asyncio
async def test_sandboxed_shell_removes_network_env(tmp_path):
    """Sandboxed shell must strip network-related environment variables."""
    adapter = SandboxedShellAdapter()
    handle = await adapter.open(
        {
            "cwd": str(tmp_path),
            "env": {
                "http_proxy": "http://proxy:8080",
                "HTTPS_PROXY": "https://proxy:8443",
                "CUSTOM_VAR": "keep_this",
            },
        }
    )

    # Execute command that prints environment
    result = await adapter.exec(handle, {"cmd": "env"})
    assert result.exit_code == 0

    # Network vars should be removed
    assert "http_proxy" not in result.stdout
    assert "HTTPS_PROXY" not in result.stdout

    # Custom vars should be kept
    assert "CUSTOM_VAR" in result.stdout or "keep_this" in result.stdout

    # Sandboxed marker in effect descriptor
    assert result.effect_descriptor.get("sandboxed") is True

    await adapter.close(handle)


@pytest.mark.asyncio
async def test_network_shell_preserves_env(tmp_path):
    """Network shell must preserve all environment variables."""
    adapter = NetworkShellAdapter()
    handle = await adapter.open(
        {
            "cwd": str(tmp_path),
            "env": {
                "http_proxy": "http://proxy:8080",
                "CUSTOM_VAR": "value",
            },
        }
    )

    result = await adapter.exec(handle, {"cmd": "env"})
    assert result.exit_code == 0

    # Network vars should be preserved
    assert "http_proxy" in result.stdout or "HTTP_PROXY" in result.stdout

    # Network marker in effect descriptor
    assert result.effect_descriptor.get("network") is True

    await adapter.close(handle)


@pytest.mark.asyncio
async def test_dispatcher_routes_to_correct_shell_adapter(tmp_path):
    """Dispatcher must route sandboxed and network capabilities to different adapters."""
    dispatcher = ExecutionDispatcher()

    # Test sandboxed routing
    from reins.kernel.intent.envelope import CommandEnvelope
    from reins.kernel.types import RiskTier

    sandboxed_cmd = CommandEnvelope(
        run_id="test",
        normalized_kind="exec.shell.sandboxed",
        args={"cmd": "echo test", "cwd": str(tmp_path)},
        risk_tier=RiskTier.T1,
    )

    result = await dispatcher.dispatch("test", sandboxed_cmd)
    assert result.observation.effect_descriptor.get("sandboxed") is True

    # Test network routing
    network_cmd = CommandEnvelope(
        run_id="test",
        normalized_kind="exec.shell.network",
        args={"cmd": "echo test", "cwd": str(tmp_path)},
        risk_tier=RiskTier.T2,
    )

    result = await dispatcher.dispatch("test", network_cmd)
    assert result.observation.effect_descriptor.get("network") is True


@pytest.mark.asyncio
async def test_unsupported_capability_no_dry_run_event(tmp_path):
    """Unsupported capabilities must not emit command.executed events."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="test-unsupported", objective="test"))
    await orch.route()

    # Try unsupported capability
    proposal = CommandProposal(
        run_id="test-unsupported",
        source="model",
        kind="email.send",  # Not in CAPABILITY_RISK_TIERS
        args={"to": "test@example.com"},
    )

    result = await orch.process_proposal(proposal)
    assert result["granted"] is False
    assert "unknown capability" in result["reason"]

    # Verify no command.executed event
    journal = EventJournal(tmp_path / "journal.jsonl")
    events = [event async for event in journal.read_from("test-unsupported")]
    executed_events = [e for e in events if e.type == "command.executed"]
    assert len(executed_events) == 0


@pytest.mark.asyncio
async def test_dispatcher_required_for_execution(tmp_path):
    """Orchestrator without dispatcher must reject all execution."""
    journal = EventJournal(tmp_path / "journal.jsonl")
    snapshots = SnapshotStore(tmp_path / "snapshots")
    checkpoints = CheckpointStore(tmp_path / "checkpoints")
    policy = PolicyEngine()
    context = ContextCompiler()

    # Create orchestrator WITHOUT dispatcher
    orch = RunOrchestrator(
        journal, snapshots, checkpoints, policy, context, dispatcher=None
    )

    await orch.intake(IntentEnvelope(run_id="test-no-dispatcher", objective="test"))
    await orch.route()

    proposal = CommandProposal(
        run_id="test-no-dispatcher",
        source="model",
        kind="fs.read",
        args={"path": "test.txt"},
    )

    result = await orch.process_proposal(proposal)
    assert result["granted"] is False
    assert "no execution dispatcher" in result["reason"]


@pytest.mark.asyncio
async def test_valid_operations_within_boundaries(tmp_path):
    """Valid operations within boundaries must succeed."""
    orch = _make_orchestrator(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    await orch.intake(IntentEnvelope(run_id="test-valid", objective="test"))
    await orch.route()

    # Write file
    write_proposal = CommandProposal(
        run_id="test-valid",
        source="model",
        kind="fs.write.workspace",
        args={"root": str(workspace), "path": "data.txt", "content": "hello"},
    )
    result = await orch.process_proposal(write_proposal)
    assert result["granted"] is True
    assert result["executed"] is True

    # Read file
    read_proposal = CommandProposal(
        run_id="test-valid",
        source="model",
        kind="fs.read",
        args={"root": str(workspace), "path": "data.txt"},
    )
    result = await orch.process_proposal(read_proposal)
    assert result["granted"] is True
    assert result["executed"] is True
    assert "hello" in result["observation"]["stdout"]

    # Sandboxed shell
    shell_proposal = CommandProposal(
        run_id="test-valid",
        source="model",
        kind="exec.shell.sandboxed",
        args={"cmd": "echo test", "cwd": str(workspace)},
    )
    result = await orch.process_proposal(shell_proposal)
    assert result["granted"] is True
    assert result["executed"] is True
