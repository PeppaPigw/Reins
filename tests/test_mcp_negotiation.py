"""Tests for MCP capability negotiation."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from reins.execution.mcp.session import McpSessionManager
from reins.execution.mcp.transport import JsonRpcResponse


@pytest.mark.asyncio
async def test_connect_with_manual_capabilities():
    """Test connecting with manually specified capabilities."""
    manager = McpSessionManager()

    mock_transport = MagicMock()
    mock_transport.send = AsyncMock(
        return_value=JsonRpcResponse(jsonrpc="2.0", id="1", result={})
    )

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        session = await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
            tools=[
                {"name": "search", "input_schema": {"type": "object"}},
                {"name": "analyze", "input_schema": {"type": "object"}},
            ],
            resources=[
                {"uri": "file://data.json"},
            ],
            negotiate_capabilities=False,
        )

        assert len(session.tools) == 2
        assert session.tools[0].name == "search"
        assert session.tools[1].name == "analyze"
        assert len(session.resources) == 1
        assert session.resources[0].uri == "file://data.json"


@pytest.mark.asyncio
async def test_connect_with_capability_negotiation():
    """Test connecting with automatic capability negotiation."""
    manager = McpSessionManager()

    mock_transport = MagicMock()

    # Mock responses for capability queries
    def mock_send(request):
        if request.method == "tools/list":
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                result={
                    "tools": [
                        {"name": "tool1", "input_schema": {}},
                        {"name": "tool2", "input_schema": {}},
                    ]
                },
            )
        elif request.method == "resources/list":
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                result={
                    "resources": [
                        {"uri": "resource://1"},
                        {"uri": "resource://2"},
                    ]
                },
            )
        elif request.method == "prompts/list":
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                result={
                    "prompts": [
                        {"name": "prompt1", "args_schema": {}},
                    ]
                },
            )
        return JsonRpcResponse(jsonrpc="2.0", id=request.id, result={})

    mock_transport.send = AsyncMock(side_effect=mock_send)

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        session = await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
            negotiate_capabilities=True,
        )

        assert len(session.tools) == 2
        assert session.tools[0].name == "tool1"
        assert session.tools[1].name == "tool2"
        assert len(session.resources) == 2
        assert session.resources[0].uri == "resource://1"
        assert len(session.prompts) == 1
        assert session.prompts[0].name == "prompt1"


@pytest.mark.asyncio
async def test_negotiate_capabilities_partial_failure():
    """Test capability negotiation when some queries fail."""
    manager = McpSessionManager()

    mock_transport = MagicMock()

    # Mock responses - tools succeed, resources fail, prompts succeed
    def mock_send(request):
        if request.method == "tools/list":
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                result={"tools": [{"name": "tool1", "input_schema": {}}]},
            )
        elif request.method == "resources/list":
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                error={"code": -32601, "message": "Method not found"},
            )
        elif request.method == "prompts/list":
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                result={"prompts": [{"name": "prompt1", "args_schema": {}}]},
            )
        return JsonRpcResponse(jsonrpc="2.0", id=request.id, result={})

    mock_transport.send = AsyncMock(side_effect=mock_send)

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        session = await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
            negotiate_capabilities=True,
        )

        # Should have tools and prompts, but no resources
        assert len(session.tools) == 1
        assert len(session.resources) == 0
        assert len(session.prompts) == 1


@pytest.mark.asyncio
async def test_negotiate_capabilities_all_fail():
    """Test capability negotiation when all queries fail."""
    manager = McpSessionManager()

    mock_transport = MagicMock()
    mock_transport.send = AsyncMock(
        return_value=JsonRpcResponse(
            jsonrpc="2.0",
            id="1",
            error={"code": -32601, "message": "Method not found"},
        )
    )

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        session = await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
            negotiate_capabilities=True,
        )

        # Should have empty capabilities
        assert len(session.tools) == 0
        assert len(session.resources) == 0
        assert len(session.prompts) == 0


@pytest.mark.asyncio
async def test_refresh_capabilities_success():
    """Test refreshing capabilities of an existing session."""
    manager = McpSessionManager()

    mock_transport = MagicMock()

    # Mock responses for initial connection and refresh
    call_count = [0]

    def mock_send(request):
        call_count[0] += 1
        if call_count[0] == 1:
            # Initial tools/list call
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                result={"tools": [{"name": "tool1", "input_schema": {}}]},
            )
        else:
            # Refresh tools/list call
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                result={
                    "tools": [
                        {"name": "tool1", "input_schema": {}},
                        {"name": "tool2", "input_schema": {}},
                    ]
                },
            )

    mock_transport.send = AsyncMock(side_effect=mock_send)

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        session = await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
            negotiate_capabilities=True,
        )

        assert len(session.tools) == 1

        # Refresh capabilities
        result = await manager.refresh_capabilities("test-server")

        assert result is True
        assert len(session.tools) == 2


@pytest.mark.asyncio
async def test_refresh_capabilities_server_not_found():
    """Test refreshing capabilities for non-existent server."""
    manager = McpSessionManager()

    result = await manager.refresh_capabilities("nonexistent-server")

    assert result is False


@pytest.mark.asyncio
async def test_refresh_capabilities_inactive_server():
    """Test refreshing capabilities for inactive server."""
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
            negotiate_capabilities=False,
        )

        session = manager.get_session("test-server")
        session.active = False

        result = await manager.refresh_capabilities("test-server")

        assert result is False


@pytest.mark.asyncio
async def test_refresh_capabilities_with_error():
    """Test refreshing capabilities when negotiation fails."""
    manager = McpSessionManager()

    mock_transport = MagicMock()

    # Mock responses - initial succeeds, refresh raises exception
    call_count = [0]

    def mock_send(request):
        call_count[0] += 1
        if call_count[0] <= 3:
            # Initial calls for tools/resources/prompts succeed
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                result={"tools": [{"name": "tool1", "input_schema": {}}]},
            )
        else:
            # Refresh calls fail
            raise Exception("Connection error")

    mock_transport.send = AsyncMock(side_effect=mock_send)

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
            negotiate_capabilities=True,
        )

        result = await manager.refresh_capabilities("test-server")

        # Refresh succeeds but returns empty capabilities since all queries fail
        assert result is True
        session = manager.get_session("test-server")
        # Tools should be empty after failed refresh
        assert len(session.tools) == 0


@pytest.mark.asyncio
async def test_capability_negotiation_with_metadata():
    """Test that capability metadata is preserved during negotiation."""
    manager = McpSessionManager()

    mock_transport = MagicMock()
    mock_transport.send = AsyncMock(
        return_value=JsonRpcResponse(
            jsonrpc="2.0",
            id="1",
            result={
                "tools": [
                    {
                        "name": "expensive_tool",
                        "input_schema": {},
                        "cost_class": "expensive",
                        "risk_tier": 3,
                    }
                ]
            },
        )
    )

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        session = await manager.connect(
            server_id="test-server",
            name="Test Server",
            endpoint="http://localhost:8080/rpc",
            negotiate_capabilities=True,
        )

        assert len(session.tools) == 1
        tool = session.tools[0]
        assert tool.name == "expensive_tool"
        assert tool.cost_class.value == "expensive"
        assert tool.risk_tier == 3
