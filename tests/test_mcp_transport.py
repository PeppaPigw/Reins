"""Tests for MCP JSON-RPC transport layer."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from reins.execution.mcp.transport import (
    HttpTransport,
    JsonRpcRequest,
    JsonRpcResponse,
    StdioTransport,
    create_transport,
)


@pytest.mark.asyncio
async def test_json_rpc_request_to_dict():
    """Test JSON-RPC request serialization."""
    request = JsonRpcRequest(
        method="test_method",
        params={"arg1": "value1"},
        id="test-id-1",
    )

    result = request.to_dict()

    assert result["jsonrpc"] == "2.0"
    assert result["method"] == "test_method"
    assert result["params"] == {"arg1": "value1"}
    assert result["id"] == "test-id-1"


@pytest.mark.asyncio
async def test_json_rpc_response_from_dict():
    """Test JSON-RPC response deserialization."""
    data = {
        "jsonrpc": "2.0",
        "id": "test-id-1",
        "result": {"output": "success"},
    }

    response = JsonRpcResponse.from_dict(data)

    assert response.jsonrpc == "2.0"
    assert response.id == "test-id-1"
    assert response.result == {"output": "success"}
    assert response.error is None
    assert not response.is_error()


@pytest.mark.asyncio
async def test_json_rpc_response_error():
    """Test JSON-RPC error response."""
    data = {
        "jsonrpc": "2.0",
        "id": "test-id-1",
        "error": {"code": -32600, "message": "Invalid Request"},
    }

    response = JsonRpcResponse.from_dict(data)

    assert response.is_error()
    assert response.error["code"] == -32600
    assert response.error["message"] == "Invalid Request"


@pytest.mark.asyncio
async def test_http_transport_success():
    """Test HTTP transport successful request."""
    transport = HttpTransport("http://localhost:8080/rpc")

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "jsonrpc": "2.0",
        "id": "test-id",
        "result": {"data": "test"},
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        request = JsonRpcRequest(method="test", params={}, id="test-id")
        response = await transport.send(request)

        assert not response.is_error()
        assert response.result == {"data": "test"}

    await transport.close()


@pytest.mark.asyncio
async def test_http_transport_http_error():
    """Test HTTP transport handles HTTP errors."""
    transport = HttpTransport("http://localhost:8080/rpc")

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )

        request = JsonRpcRequest(method="test", params={}, id="test-id")
        response = await transport.send(request)

        assert response.is_error()
        assert response.error["code"] == 500

    await transport.close()


@pytest.mark.asyncio
async def test_http_transport_connection_error():
    """Test HTTP transport handles connection errors."""
    transport = HttpTransport("http://localhost:8080/rpc")

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        import httpx
        mock_post.side_effect = httpx.ConnectError("Connection refused")

        request = JsonRpcRequest(method="test", params={}, id="test-id")
        response = await transport.send(request)

        assert response.is_error()
        assert response.error["code"] == -32000
        assert "Transport error" in response.error["message"]

    await transport.close()


@pytest.mark.asyncio
async def test_stdio_transport_success():
    """Test stdio transport successful request."""
    transport = StdioTransport(["echo", "test"])

    mock_process = MagicMock()
    mock_process.stdin = MagicMock()
    mock_process.stdin.write = MagicMock()
    mock_process.stdin.drain = AsyncMock()
    mock_process.stdin.close = MagicMock()
    mock_process.stdout = MagicMock()
    mock_process.stdout.readline = AsyncMock(
        return_value=b'{"jsonrpc":"2.0","id":"test-id","result":{"data":"test"}}\n'
    )
    mock_process.wait = AsyncMock()
    mock_process.kill = MagicMock()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_process

        request = JsonRpcRequest(method="test", params={}, id="test-id")
        response = await transport.send(request)

        assert not response.is_error()
        assert response.result == {"data": "test"}

    await transport.close()


@pytest.mark.asyncio
async def test_stdio_transport_no_response():
    """Test stdio transport handles no response."""
    transport = StdioTransport(["echo", "test"])

    mock_process = MagicMock()
    mock_process.stdin = MagicMock()
    mock_process.stdin.write = MagicMock()
    mock_process.stdin.drain = AsyncMock()
    mock_process.stdin.close = MagicMock()
    mock_process.stdout = MagicMock()
    mock_process.stdout.readline = AsyncMock(return_value=b"")
    mock_process.wait = AsyncMock()
    mock_process.kill = MagicMock()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_process

        request = JsonRpcRequest(method="test", params={}, id="test-id")
        response = await transport.send(request)

        assert response.is_error()
        assert "No response from process" in response.error["message"]

    await transport.close()


@pytest.mark.asyncio
async def test_stdio_transport_invalid_json():
    """Test stdio transport handles invalid JSON."""
    transport = StdioTransport(["echo", "test"])

    mock_process = MagicMock()
    mock_process.stdin = MagicMock()
    mock_process.stdin.write = MagicMock()
    mock_process.stdin.drain = AsyncMock()
    mock_process.stdin.close = MagicMock()
    mock_process.stdout = MagicMock()
    mock_process.stdout.readline = AsyncMock(return_value=b"invalid json\n")
    mock_process.wait = AsyncMock()
    mock_process.kill = MagicMock()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_process

        request = JsonRpcRequest(method="test", params={}, id="test-id")
        response = await transport.send(request)

        assert response.is_error()
        assert response.error["code"] == -32700
        assert "Parse error" in response.error["message"]

    await transport.close()


def test_create_transport_http():
    """Test factory creates HTTP transport."""
    transport = create_transport("http://localhost:8080/rpc")
    assert isinstance(transport, HttpTransport)
    assert transport.endpoint == "http://localhost:8080/rpc"


def test_create_transport_https():
    """Test factory creates HTTPS transport."""
    transport = create_transport("https://api.example.com/rpc")
    assert isinstance(transport, HttpTransport)
    assert transport.endpoint == "https://api.example.com/rpc"


def test_create_transport_stdio():
    """Test factory creates stdio transport."""
    transport = create_transport("stdio://python -m mcp_server")
    assert isinstance(transport, StdioTransport)
    assert transport.command == ["python", "-m", "mcp_server"]


def test_create_transport_invalid():
    """Test factory rejects invalid endpoint."""
    with pytest.raises(ValueError, match="Unsupported endpoint format"):
        create_transport("invalid://endpoint")
