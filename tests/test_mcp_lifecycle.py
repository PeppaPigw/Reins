"""Tests for MCP server lifecycle management."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from reins.execution.mcp.session import McpSessionManager
from reins.execution.mcp.transport import JsonRpcResponse


@pytest.mark.asyncio
async def test_reconnect_success():
    """Test successful reconnection to a server."""
    manager = McpSessionManager(max_reconnect_attempts=3)

    mock_transport = MagicMock()
    mock_transport.send = AsyncMock(
        return_value=JsonRpcResponse(jsonrpc="2.0", id="1", result={})
    )
    mock_transport.close = AsyncMock()

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        # Connect initially
        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
        )

        # Simulate disconnection
        session = manager.get_session("test-server")
        session.active = False

        # Reconnect
        result = await manager.reconnect("test-server")

        assert result is True
        assert session.active is True
        assert session.reconnect_attempts == 1
        assert session.last_error is None


@pytest.mark.asyncio
async def test_reconnect_max_attempts_exceeded():
    """Test that reconnection stops after max attempts."""
    manager = McpSessionManager(max_reconnect_attempts=2)

    mock_transport = MagicMock()
    mock_transport.send = AsyncMock(
        return_value=JsonRpcResponse(jsonrpc="2.0", id="1", result={})
    )

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
        )

        session = manager.get_session("test-server")
        session.reconnect_attempts = 2  # Already at max

        result = await manager.reconnect("test-server")

        assert result is False
        assert "Max reconnection attempts exceeded" in session.last_error


@pytest.mark.asyncio
async def test_reconnect_transport_creation_fails():
    """Test reconnection when transport creation fails."""
    manager = McpSessionManager(max_reconnect_attempts=3)

    mock_transport = MagicMock()
    mock_transport.send = AsyncMock(
        return_value=JsonRpcResponse(jsonrpc="2.0", id="1", result={})
    )

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        # First call succeeds (initial connect)
        mock_create.return_value = mock_transport

        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
        )

        session = manager.get_session("test-server")
        session.active = False

        # Second call fails (reconnect)
        mock_create.side_effect = Exception("Connection refused")

        result = await manager.reconnect("test-server")

        assert result is False
        assert session.active is False
        assert "Connection refused" in session.last_error
        assert session.reconnect_attempts == 1


@pytest.mark.asyncio
async def test_health_check_healthy():
    """Test health check on a healthy server."""
    manager = McpSessionManager()

    mock_transport = MagicMock()
    mock_transport.send = AsyncMock(
        return_value=JsonRpcResponse(jsonrpc="2.0", id="1", result={"pong": True})
    )

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
        )

        health = await manager.health_check("test-server")

        assert health["status"] == "healthy"
        assert "last_activity" in health


@pytest.mark.asyncio
async def test_health_check_inactive():
    """Test health check on an inactive server."""
    manager = McpSessionManager()

    mock_transport = MagicMock()
    mock_transport.send = AsyncMock(
        return_value=JsonRpcResponse(jsonrpc="2.0", id="1", result={})
    )

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
        )

        session = manager.get_session("test-server")
        session.active = False
        session.last_error = "Connection lost"

        health = await manager.health_check("test-server")

        assert health["status"] == "inactive"
        assert health["last_error"] == "Connection lost"


@pytest.mark.asyncio
async def test_health_check_not_found():
    """Test health check on a non-existent server."""
    manager = McpSessionManager()

    health = await manager.health_check("nonexistent-server")

    assert health["status"] == "not_found"


@pytest.mark.asyncio
async def test_health_check_unhealthy():
    """Test health check when server returns error."""
    manager = McpSessionManager()

    mock_transport = MagicMock()
    mock_transport.send = AsyncMock(
        return_value=JsonRpcResponse(
            jsonrpc="2.0",
            id="1",
            error={"code": -32600, "message": "Invalid Request"},
        )
    )

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
        )

        health = await manager.health_check("test-server")

        assert health["status"] == "unhealthy"
        assert "error" in health


@pytest.mark.asyncio
async def test_invoke_tool_auto_reconnect_on_inactive():
    """Test that invoke_tool auto-reconnects when server is inactive."""
    manager = McpSessionManager()

    mock_transport = MagicMock()
    mock_transport.send = AsyncMock(
        return_value=JsonRpcResponse(jsonrpc="2.0", id="1", result={"output": "success"})
    )
    mock_transport.close = AsyncMock()

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
        )

        # Simulate disconnection
        session = manager.get_session("test-server")
        session.active = False

        # Invoke tool with auto-reconnect
        result = await manager.invoke_tool(
            server_id="test-server",
            tool_name="test_tool",
            args={},
            run_id="test-run",
            auto_reconnect=True,
        )

        assert result["status"] == "success"
        assert session.active is True


@pytest.mark.asyncio
async def test_invoke_tool_no_auto_reconnect():
    """Test that invoke_tool fails when auto_reconnect is disabled."""
    manager = McpSessionManager()

    mock_transport = MagicMock()
    mock_transport.send = AsyncMock(
        return_value=JsonRpcResponse(jsonrpc="2.0", id="1", result={})
    )

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
        )

        session = manager.get_session("test-server")
        session.active = False

        result = await manager.invoke_tool(
            server_id="test-server",
            tool_name="test_tool",
            args={},
            run_id="test-run",
            auto_reconnect=False,
        )

        assert result["status"] == "error"
        assert "not connected" in result["error"]


@pytest.mark.asyncio
async def test_invoke_tool_reconnect_on_transport_error():
    """Test that invoke_tool reconnects on transport errors."""
    manager = McpSessionManager()

    mock_transport = MagicMock()
    mock_transport.close = AsyncMock()

    # First call returns transport error, second call succeeds
    mock_transport.send = AsyncMock(
        side_effect=[
            JsonRpcResponse(
                jsonrpc="2.0",
                id="1",
                error={"code": -32000, "message": "Transport error"},
            ),
            JsonRpcResponse(jsonrpc="2.0", id="2", result={"output": "success"}),
        ]
    )

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
            negotiate_capabilities=False,
        )

        result = await manager.invoke_tool(
            server_id="test-server",
            tool_name="test_tool",
            args={},
            run_id="test-run",
            auto_reconnect=True,
        )

        # Should succeed after reconnection
        assert result["status"] == "success"


@pytest.mark.asyncio
async def test_invoke_tool_exception_triggers_reconnect():
    """Test that exceptions during invocation trigger reconnection."""
    manager = McpSessionManager()

    mock_transport = MagicMock()
    mock_transport.close = AsyncMock()

    # First call raises exception, second call succeeds
    mock_transport.send = AsyncMock(
        side_effect=[
            Exception("Network error"),
            JsonRpcResponse(jsonrpc="2.0", id="1", result={"output": "success"}),
        ]
    )

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
            negotiate_capabilities=False,
        )

        result = await manager.invoke_tool(
            server_id="test-server",
            tool_name="test_tool",
            args={},
            run_id="test-run",
            auto_reconnect=True,
        )

        # Should succeed after reconnection
        assert result["status"] == "success"
