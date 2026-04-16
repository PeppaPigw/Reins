"""Tests for the MCP adapter and extended capabilities taxonomy."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from reins.execution.adapters.mcp_adapter import McpAdapter
from reins.execution.dispatcher import ExecutionDispatcher
from reins.execution.mcp.transport import JsonRpcResponse
from reins.policy.capabilities import CAPABILITY_RISK_TIERS


# ---------------------------------------------------------------------------
# Capability taxonomy
# ---------------------------------------------------------------------------
class TestCapabilityTaxonomy:
    def test_mcp_tool_invoke_is_t2(self):
        assert CAPABILITY_RISK_TIERS["mcp.tool.invoke"] == 2

    def test_mcp_resource_read_is_t0(self):
        assert CAPABILITY_RISK_TIERS["mcp.resource.read"] == 0

    def test_mcp_prompt_get_is_t0(self):
        assert CAPABILITY_RISK_TIERS["mcp.prompt.get"] == 0

    def test_browser_navigate_is_t2(self):
        assert CAPABILITY_RISK_TIERS["browser.navigate"] == 2

    def test_browser_click_is_t3(self):
        assert CAPABILITY_RISK_TIERS["browser.click"] == 3

    def test_db_read_is_t0(self):
        assert CAPABILITY_RISK_TIERS["db.read"] == 0

    def test_ticket_write_is_t3(self):
        assert CAPABILITY_RISK_TIERS["ticket.write"] == 3


# ---------------------------------------------------------------------------
# ExecutionDispatcher — MCP capability support
# ---------------------------------------------------------------------------
class TestDispatcherMcpSupport:
    def test_supports_mcp_tool_invoke(self):
        d = ExecutionDispatcher()
        assert d.supports("mcp.tool.invoke")

    def test_supports_mcp_resource_read(self):
        d = ExecutionDispatcher()
        assert d.supports("mcp.resource.read")

    def test_supports_mcp_prompt_get(self):
        d = ExecutionDispatcher()
        assert d.supports("mcp.prompt.get")

    def test_does_not_support_unknown(self):
        d = ExecutionDispatcher()
        assert not d.supports("made.up.capability")

    def test_resolve_mcp_tool_invoke(self):
        d = ExecutionDispatcher()
        from reins.kernel.intent.envelope import CommandEnvelope
        cmd = CommandEnvelope(
            run_id="r1",
            normalized_kind="mcp.tool.invoke",
            args={"server_id": "s1", "name": "s1", "endpoint": "", "tool_name": "search", "args": {}},
        )
        adapter_kind, open_spec, adapter_cmd = d._resolve(cmd)
        assert adapter_kind == "mcp"
        assert open_spec["server_id"] == "s1"
        assert adapter_cmd["op"] == "invoke_tool"
        assert adapter_cmd["tool_name"] == "search"

    def test_resolve_mcp_resource_read(self):
        d = ExecutionDispatcher()
        from reins.kernel.intent.envelope import CommandEnvelope
        cmd = CommandEnvelope(
            run_id="r1",
            normalized_kind="mcp.resource.read",
            args={"server_id": "s1", "uri": "file:///README.md"},
        )
        _, _, adapter_cmd = d._resolve(cmd)
        assert adapter_cmd["op"] == "read_resource"
        assert adapter_cmd["uri"] == "file:///README.md"

    def test_resolve_mcp_prompt_get(self):
        d = ExecutionDispatcher()
        from reins.kernel.intent.envelope import CommandEnvelope
        cmd = CommandEnvelope(
            run_id="r1",
            normalized_kind="mcp.prompt.get",
            args={"server_id": "s1", "prompt_name": "code_review"},
        )
        _, _, adapter_cmd = d._resolve(cmd)
        assert adapter_cmd["op"] == "get_prompt"
        assert adapter_cmd["name"] == "code_review"


# ---------------------------------------------------------------------------
# McpAdapter — handle lifecycle
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
class TestMcpAdapter:
    async def test_open_returns_mcp_handle(self):
        adapter = McpAdapter()

        # Mock the transport
        mock_transport = MagicMock()
        mock_transport.send = AsyncMock(
            return_value=JsonRpcResponse(jsonrpc="2.0", id="1", result={})
        )

        with patch("reins.execution.mcp.session.create_transport") as mock_create:
            mock_create.return_value = mock_transport

            handle = await adapter.open({
                "server_id": "test_server",
                "name": "Test Server",
                "endpoint": "http://localhost:8080/rpc",
                "tools": [{"name": "search", "input_schema": {}}],
                "resources": [],
            })
            assert handle.adapter_kind == "mcp"
            assert handle.metadata["server_id"] == "test_server"
            assert handle.metadata["tool_count"] == 1

    async def test_exec_invoke_tool(self):
        adapter = McpAdapter()

        mock_transport = MagicMock()
        mock_transport.send = AsyncMock(
            return_value=JsonRpcResponse(jsonrpc="2.0", id="1", result={"output": "pong"})
        )

        with patch("reins.execution.mcp.session.create_transport") as mock_create:
            mock_create.return_value = mock_transport

            handle = await adapter.open({
                "server_id": "srv",
                "name": "srv",
                "endpoint": "http://localhost:8080/rpc"
            })
            obs = await adapter.exec(handle, {"op": "invoke_tool", "tool_name": "ping", "args": {}})
            assert obs.exit_code == 0
            assert "call_id" in obs.stdout

    async def test_exec_read_resource(self):
        adapter = McpAdapter()

        mock_transport = MagicMock()
        mock_transport.send = AsyncMock(
            return_value=JsonRpcResponse(jsonrpc="2.0", id="1", result={"content": "data"})
        )

        with patch("reins.execution.mcp.session.create_transport") as mock_create:
            mock_create.return_value = mock_transport

            handle = await adapter.open({
                "server_id": "srv",
                "name": "srv",
                "endpoint": "http://localhost:8080/rpc"
            })
            obs = await adapter.exec(handle, {"op": "read_resource", "uri": "mem://x"})
            assert obs.exit_code == 0

    async def test_exec_get_prompt(self):
        adapter = McpAdapter()

        mock_transport = MagicMock()
        mock_transport.send = AsyncMock(
            return_value=JsonRpcResponse(jsonrpc="2.0", id="1", result={"prompt": "text"})
        )

        with patch("reins.execution.mcp.session.create_transport") as mock_create:
            mock_create.return_value = mock_transport

            handle = await adapter.open({
                "server_id": "srv",
                "name": "srv",
                "endpoint": "http://localhost:8080/rpc"
            })
            obs = await adapter.exec(handle, {"op": "get_prompt", "name": "review"})
            assert obs.exit_code == 0

    async def test_snapshot(self):
        adapter = McpAdapter()

        mock_transport = MagicMock()
        mock_transport.send = AsyncMock(
            return_value=JsonRpcResponse(jsonrpc="2.0", id="1", result={})
        )

        with patch("reins.execution.mcp.session.create_transport") as mock_create:
            mock_create.return_value = mock_transport

            handle = await adapter.open({
                "server_id": "srv",
                "name": "srv",
                "endpoint": "http://localhost:8080/rpc"
            })
            snap = await adapter.snapshot(handle)
            assert "srv" in snap

    async def test_freeze_thaw_roundtrip(self):
        adapter = McpAdapter()

        mock_transport = MagicMock()
        mock_transport.send = AsyncMock(
            return_value=JsonRpcResponse(jsonrpc="2.0", id="1", result={})
        )

        with patch("reins.execution.mcp.session.create_transport") as mock_create:
            mock_create.return_value = mock_transport

            handle = await adapter.open({
                "server_id": "srv",
                "name": "srv",
                "endpoint": "http://localhost:8080/rpc"
            })
            frozen = await adapter.freeze(handle)
            assert frozen["server_id"] == "srv"
            restored = await adapter.thaw(frozen)
        assert restored.handle_id == handle.handle_id
        assert restored.metadata["server_id"] == "srv"

    async def test_close_disconnects(self):
        adapter = McpAdapter()

        mock_transport = MagicMock()
        mock_transport.send = AsyncMock(
            return_value=JsonRpcResponse(jsonrpc="2.0", id="1", result={})
        )
        mock_transport.close = AsyncMock()

        with patch("reins.execution.mcp.session.create_transport") as mock_create:
            mock_create.return_value = mock_transport

            handle = await adapter.open({
                "server_id": "srv2",
                "name": "srv2",
                "endpoint": "http://localhost:8080/rpc"
            })
            await adapter.close(handle)
            session = adapter.session_manager.get_session("srv2")
        assert session is None or not session.active
