"""Tests for MCP session manager with JSON-RPC integration."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from reins.execution.mcp.session import McpSessionManager
from reins.execution.mcp.transport import JsonRpcResponse


@pytest.mark.asyncio
async def test_session_connect_creates_transport():
    """Test that connecting creates a transport."""
    manager = McpSessionManager()

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_transport = MagicMock()
        mock_create.return_value = mock_transport

        session = await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
            tools=[{"name": "test_tool", "input_schema": {}}],
        )

        assert session.transport is mock_transport
        mock_create.assert_called_once_with("http://localhost:8080/rpc")


@pytest.mark.asyncio
async def test_session_disconnect_closes_transport():
    """Test that disconnecting closes the transport."""
    manager = McpSessionManager()

    mock_transport = MagicMock()
    mock_transport.close = AsyncMock()

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
        )

        await manager.disconnect("test-server")

        mock_transport.close.assert_called_once()


@pytest.mark.asyncio
async def test_invoke_tool_success():
    """Test successful tool invocation via JSON-RPC."""
    manager = McpSessionManager()

    mock_transport = MagicMock()
    mock_transport.send = AsyncMock(
        return_value=JsonRpcResponse(
            jsonrpc="2.0",
            id="call-id",
            result={"output": "success"},
        )
    )

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
            tools=[{"name": "test_tool", "input_schema": {}}],
        )

        result = await manager.invoke_tool(
            server_id="test-server",
            tool_name="test_tool",
            args={"arg1": "value1"},
            run_id="test-run",
        )

        assert result["status"] == "success"
        assert result["result"] == {"output": "success"}
        assert "call_id" in result


@pytest.mark.asyncio
async def test_invoke_tool_json_rpc_error():
    """Test tool invocation with JSON-RPC error."""
    manager = McpSessionManager()

    mock_transport = MagicMock()
    mock_transport.send = AsyncMock(
        return_value=JsonRpcResponse(
            jsonrpc="2.0",
            id="call-id",
            error={"code": -32601, "message": "Method not found"},
        )
    )

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
        )

        result = await manager.invoke_tool(
            server_id="test-server",
            tool_name="unknown_tool",
            args={},
            run_id="test-run",
        )

        assert result["status"] == "error"
        assert result["error"]["code"] == -32601
        assert "Method not found" in result["error"]["message"]


@pytest.mark.asyncio
async def test_invoke_tool_server_not_connected():
    """Test tool invocation when server is not connected."""
    manager = McpSessionManager()

    result = await manager.invoke_tool(
        server_id="nonexistent-server",
        tool_name="test_tool",
        args={},
        run_id="test-run",
    )

    assert result["status"] == "error"
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_invoke_tool_no_transport():
    """Test tool invocation when transport is missing."""
    manager = McpSessionManager()

    # Manually create session without transport
    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = None

        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
        )

        result = await manager.invoke_tool(
            server_id="test-server",
            tool_name="test_tool",
            args={},
            run_id="test-run",
        )

        assert result["status"] == "error"
        assert "No transport available" in result["error"]


@pytest.mark.asyncio
async def test_invoke_tool_audit_log():
    """Test that tool invocations are logged."""
    manager = McpSessionManager()

    mock_transport = MagicMock()
    mock_transport.send = AsyncMock(
        return_value=JsonRpcResponse(
            jsonrpc="2.0",
            id="call-id",
            result={"output": "success"},
        )
    )

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
        )

        await manager.invoke_tool(
            server_id="test-server",
            tool_name="test_tool",
            args={"arg1": "value1"},
            run_id="test-run",
        )

        audit_log = manager.audit_log
        assert len(audit_log) == 1
        assert audit_log[0]["server_id"] == "test-server"
        assert audit_log[0]["tool_name"] == "test_tool"
        assert audit_log[0]["args"] == {"arg1": "value1"}
        assert audit_log[0]["run_id"] == "test-run"


@pytest.mark.asyncio
async def test_multiple_tool_invocations():
    """Test multiple tool invocations are logged correctly."""
    manager = McpSessionManager()

    mock_transport = MagicMock()
    mock_transport.send = AsyncMock(
        return_value=JsonRpcResponse(
            jsonrpc="2.0",
            id="call-id",
            result={"output": "success"},
        )
    )

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
        )

        await manager.invoke_tool(
            server_id="test-server",
            tool_name="tool1",
            args={},
            run_id="test-run",
        )

        await manager.invoke_tool(
            server_id="test-server",
            tool_name="tool2",
            args={},
            run_id="test-run",
        )

        audit_log = manager.audit_log
        assert len(audit_log) == 2
        assert audit_log[0]["tool_name"] == "tool1"
        assert audit_log[1]["tool_name"] == "tool2"
