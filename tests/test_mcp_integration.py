"""Integration tests for MCP with simulated real server scenarios.

These tests demonstrate the full MCP integration flow including:
- Server connection and capability discovery
- Tool invocation with policy enforcement
- Resource access
- Error handling and reconnection
- Multi-server coordination
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from reins.execution.mcp.session import McpSessionManager
from reins.execution.mcp.transport import JsonRpcResponse
from reins.kernel.orchestrator import RunOrchestrator
from reins.kernel.intent.envelope import IntentEnvelope, CommandProposal
from reins.kernel.event.journal import EventJournal
from reins.kernel.snapshot.store import SnapshotStore
from reins.memory.checkpoint import CheckpointStore
from reins.policy.engine import PolicyEngine
from reins.context.compiler import ContextCompiler
from reins.execution.dispatcher import ExecutionDispatcher
from reins.policy.approval.ledger import ApprovalLedger


@pytest.mark.asyncio
async def test_mcp_filesystem_server_integration(tmp_path):
    """Test integration with a simulated filesystem MCP server."""
    manager = McpSessionManager()

    mock_transport = MagicMock()

    # Simulate filesystem server capabilities
    def mock_send(request):
        if request.method == "tools/list":
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                result={
                    "tools": [
                        {
                            "name": "read_file",
                            "input_schema": {
                                "type": "object",
                                "properties": {"path": {"type": "string"}},
                            },
                        },
                        {
                            "name": "write_file",
                            "input_schema": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string"},
                                    "content": {"type": "string"},
                                },
                            },
                        },
                    ]
                },
            )
        elif request.method == "tools/call":
            tool_name = request.params.get("name")
            args = request.params.get("arguments", {})

            if tool_name == "read_file":
                return JsonRpcResponse(
                    jsonrpc="2.0",
                    id=request.id,
                    result={"content": "file content", "path": args.get("path")},
                )
            elif tool_name == "write_file":
                return JsonRpcResponse(
                    jsonrpc="2.0",
                    id=request.id,
                    result={"success": True, "path": args.get("path")},
                )

        return JsonRpcResponse(jsonrpc="2.0", id=request.id, result={})

    mock_transport.send = AsyncMock(side_effect=mock_send)

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        # Connect to filesystem server
        session = await manager.connect(
            server_id="filesystem",
            name="Filesystem Server",
            endpoint="http://localhost:8080/rpc",
            negotiate_capabilities=True,
        )

        # Verify capabilities discovered
        assert len(session.tools) == 2
        tool_names = {t.name for t in session.tools}
        assert "read_file" in tool_names
        assert "write_file" in tool_names

        # Invoke read_file tool
        result = await manager.invoke_tool(
            server_id="filesystem",
            tool_name="read_file",
            args={"path": "/test/file.txt"},
            run_id="test-run",
        )

        assert result["status"] == "success"
        assert result["result"]["content"] == "file content"

        # Invoke write_file tool
        result = await manager.invoke_tool(
            server_id="filesystem",
            tool_name="write_file",
            args={"path": "/test/output.txt", "content": "new content"},
            run_id="test-run",
        )

        assert result["status"] == "success"
        assert result["result"]["success"] is True


@pytest.mark.asyncio
async def test_mcp_git_server_integration(tmp_path):
    """Test integration with a simulated git MCP server."""
    manager = McpSessionManager()

    mock_transport = MagicMock()

    # Simulate git server capabilities
    def mock_send(request):
        if request.method == "tools/list":
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                result={
                    "tools": [
                        {"name": "git_status", "input_schema": {}},
                        {"name": "git_log", "input_schema": {}},
                        {"name": "git_diff", "input_schema": {}},
                    ]
                },
            )
        elif request.method == "tools/call":
            tool_name = request.params.get("name")

            if tool_name == "git_status":
                return JsonRpcResponse(
                    jsonrpc="2.0",
                    id=request.id,
                    result={
                        "branch": "main",
                        "modified": ["file1.py", "file2.py"],
                        "untracked": ["file3.py"],
                    },
                )
            elif tool_name == "git_log":
                return JsonRpcResponse(
                    jsonrpc="2.0",
                    id=request.id,
                    result={
                        "commits": [
                            {"hash": "abc123", "message": "Initial commit"},
                            {"hash": "def456", "message": "Add feature"},
                        ]
                    },
                )

        return JsonRpcResponse(jsonrpc="2.0", id=request.id, result={})

    mock_transport.send = AsyncMock(side_effect=mock_send)

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        session = await manager.connect(
            server_id="git",
            name="Git Server",
            endpoint="http://localhost:8081/rpc",
            negotiate_capabilities=True,
        )

        assert len(session.tools) == 3

        # Get git status
        result = await manager.invoke_tool(
            server_id="git",
            tool_name="git_status",
            args={},
            run_id="test-run",
        )

        assert result["status"] == "success"
        assert result["result"]["branch"] == "main"
        assert len(result["result"]["modified"]) == 2


@pytest.mark.asyncio
async def test_mcp_multi_server_coordination(tmp_path):
    """Test coordinating multiple MCP servers."""
    manager = McpSessionManager()

    mock_transport = MagicMock()

    def mock_send(request):
        if request.method == "tools/list":
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                result={"tools": [{"name": "test_tool", "input_schema": {}}]},
            )
        elif request.method == "tools/call":
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                result={"output": "success"},
            )
        return JsonRpcResponse(jsonrpc="2.0", id=request.id, result={})

    mock_transport.send = AsyncMock(side_effect=mock_send)

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        # Connect to multiple servers
        await manager.connect(
            server_id="server1",
            name="Server 1",
            endpoint="http://localhost:8080/rpc",
            negotiate_capabilities=True,
        )

        await manager.connect(
            server_id="server2",
            name="Server 2",
            endpoint="http://localhost:8081/rpc",
            negotiate_capabilities=True,
        )

        await manager.connect(
            server_id="server3",
            name="Server 3",
            endpoint="http://localhost:8082/rpc",
            negotiate_capabilities=True,
        )

        # Verify all servers active
        assert len(manager.active_servers) == 3
        assert "server1" in manager.active_servers
        assert "server2" in manager.active_servers
        assert "server3" in manager.active_servers

        # List all tools across servers
        all_tools = manager.list_tools()
        assert len(all_tools) == 3

        # Invoke tools on different servers
        result1 = await manager.invoke_tool(
            server_id="server1",
            tool_name="test_tool",
            args={},
            run_id="test-run",
        )
        assert result1["status"] == "success"

        result2 = await manager.invoke_tool(
            server_id="server2",
            tool_name="test_tool",
            args={},
            run_id="test-run",
        )
        assert result2["status"] == "success"


@pytest.mark.asyncio
async def test_mcp_with_orchestrator_integration(tmp_path):
    """Test MCP integration with the full orchestrator."""
    # Set up orchestrator
    journal = EventJournal(tmp_path / "journal.jsonl")
    snapshots = SnapshotStore(tmp_path / "snapshots")
    checkpoints = CheckpointStore(tmp_path / "checkpoints")
    policy = PolicyEngine()
    context = ContextCompiler()
    dispatcher = ExecutionDispatcher()
    approval_ledger = ApprovalLedger(tmp_path / "approvals")

    orch = RunOrchestrator(
        journal,
        snapshots,
        checkpoints,
        policy,
        context,
        approval_ledger=approval_ledger,
        dispatcher=dispatcher,
    )

    # Start a run
    await orch.intake(IntentEnvelope(run_id="test-run", objective="test mcp"))
    await orch.route()

    # Create MCP tool invocation proposal
    proposal = CommandProposal(
        run_id="test-run",
        source="model",
        kind="mcp.tool.invoke",
        args={
            "server_id": "filesystem",
            "tool_name": "read_file",
            "path": "/test/file.txt",
        },
    )

    # Process proposal - should require approval (T2)
    result = await orch.process_proposal(proposal)

    # MCP tool invocation is T2, requires approval
    assert result["needs_approval"] is True
    assert "request_id" in result


@pytest.mark.asyncio
async def test_mcp_server_failure_and_recovery(tmp_path):
    """Test MCP server failure and automatic recovery."""
    manager = McpSessionManager(max_reconnect_attempts=3)

    mock_transport = MagicMock()
    mock_transport.close = AsyncMock()

    call_count = [0]

    def mock_send(request):
        call_count[0] += 1

        # First 3 calls succeed (capability negotiation)
        if call_count[0] <= 3:
            if request.method == "tools/list":
                return JsonRpcResponse(
                    jsonrpc="2.0",
                    id=request.id,
                    result={"tools": [{"name": "test_tool", "input_schema": {}}]},
                )
            return JsonRpcResponse(jsonrpc="2.0", id=request.id, result={})

        # 4th call fails (tool invocation)
        if call_count[0] == 4:
            raise Exception("Connection lost")

        # 5th call succeeds (after reconnection)
        return JsonRpcResponse(
            jsonrpc="2.0",
            id=request.id,
            result={"output": "success after reconnect"},
        )

    mock_transport.send = AsyncMock(side_effect=mock_send)

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        session = await manager.connect(
            server_id="unstable-server",
            name="Unstable Server",
            endpoint="http://localhost:8080/rpc",
            negotiate_capabilities=True,
        )

        # First invocation fails, triggers reconnection
        result = await manager.invoke_tool(
            server_id="unstable-server",
            tool_name="test_tool",
            args={},
            run_id="test-run",
            auto_reconnect=True,
        )

        # Should succeed after automatic reconnection
        assert result["status"] == "success"
        assert "after reconnect" in result["result"]["output"]


@pytest.mark.asyncio
async def test_mcp_audit_trail(tmp_path):
    """Test that all MCP operations are properly audited."""
    manager = McpSessionManager()

    mock_transport = MagicMock()
    mock_transport.send = AsyncMock(
        return_value=JsonRpcResponse(
            jsonrpc="2.0",
            id="1",
            result={"output": "success"},
        )
    )

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
            negotiate_capabilities=False,
        )

        # Invoke multiple tools
        await manager.invoke_tool(
            server_id="test-server",
            tool_name="tool1",
            args={"arg1": "value1"},
            run_id="run-1",
        )

        await manager.invoke_tool(
            server_id="test-server",
            tool_name="tool2",
            args={"arg2": "value2"},
            run_id="run-1",
        )

        await manager.invoke_tool(
            server_id="test-server",
            tool_name="tool3",
            args={},
            run_id="run-2",
        )

        # Verify audit log
        audit_log = manager.audit_log
        assert len(audit_log) == 3

        # Check first entry
        assert audit_log[0]["server_id"] == "test-server"
        assert audit_log[0]["tool_name"] == "tool1"
        assert audit_log[0]["args"] == {"arg1": "value1"}
        assert audit_log[0]["run_id"] == "run-1"
        assert "call_id" in audit_log[0]
        assert "ts" in audit_log[0]

        # Check run_id filtering
        run1_calls = [e for e in audit_log if e["run_id"] == "run-1"]
        assert len(run1_calls) == 2

        run2_calls = [e for e in audit_log if e["run_id"] == "run-2"]
        assert len(run2_calls) == 1
