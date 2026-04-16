"""Tests for the approval ledger and MCP session manager."""

import pytest

from reins.execution.mcp.session import McpSessionManager
from reins.policy.approval.ledger import ApprovalLedger, EffectDescriptor


# ---- Approval Ledger ----

@pytest.mark.asyncio
async def test_request_and_approve(tmp_path):
    ledger = ApprovalLedger(tmp_path / "approvals")
    effect = EffectDescriptor(
        capability="git.push",
        resource="origin/main",
        intent_ref="intent-1",
        command_id="cmd-1",
        rollback_strategy="none",
    )
    req = await ledger.request("run-1", effect, "model")
    assert req.request_id
    assert len(ledger.pending) == 1

    grant = await ledger.approve(req.request_id, "human")
    assert grant is not None
    assert grant.descriptor_hash == effect.descriptor_hash
    assert len(ledger.pending) == 0


@pytest.mark.asyncio
async def test_request_and_reject(tmp_path):
    ledger = ApprovalLedger(tmp_path / "approvals")
    effect = EffectDescriptor(
        capability="deploy.prod",
        resource="prod-cluster",
        intent_ref="intent-2",
        command_id="cmd-2",
    )
    req = await ledger.request("run-2", effect, "subagent")
    rej = await ledger.reject(req.request_id, "too risky")
    assert rej is not None
    assert rej.reason == "too risky"
    assert len(ledger.pending) == 0


@pytest.mark.asyncio
async def test_approve_nonexistent_returns_none(tmp_path):
    ledger = ApprovalLedger(tmp_path / "approvals")
    result = await ledger.approve("nonexistent-id")
    assert result is None


@pytest.mark.asyncio
async def test_effect_descriptor_hash_deterministic():
    e1 = EffectDescriptor(capability="a", resource="b", intent_ref="i", command_id="c")
    e2 = EffectDescriptor(capability="a", resource="b", intent_ref="i", command_id="c")
    assert e1.descriptor_hash == e2.descriptor_hash
    e3 = EffectDescriptor(capability="x", resource="b", intent_ref="i", command_id="c")
    assert e1.descriptor_hash != e3.descriptor_hash
    e4 = EffectDescriptor(capability="a", resource="b", intent_ref="other", command_id="other")
    assert e1.descriptor_hash == e4.descriptor_hash


@pytest.mark.asyncio
async def test_pending_requests_survive_restart(tmp_path):
    base = tmp_path / "approvals"
    req = await ApprovalLedger(base).request(
        "run-3",
        EffectDescriptor(
            capability="git.push",
            resource="origin/main",
            intent_ref="intent-3",
            command_id="cmd-3",
        ),
        "model",
    )

    reloaded = ApprovalLedger(base)
    assert len(reloaded.pending) == 1
    grant = await reloaded.approve(req.request_id, "human")
    assert grant is not None


# ---- MCP Session Manager ----

@pytest.mark.asyncio
async def test_mcp_connect_and_list_tools():
    mgr = McpSessionManager()
    session = await mgr.connect(
        server_id="codex",
        name="Codex MCP",
        endpoint="stdio://codex",
        tools=[
            {"name": "codex.run", "input_schema": {"prompt": "str"}},
            {"name": "codex.reply", "input_schema": {"prompt": "str", "threadId": "str"}},
        ],
    )
    assert session.active
    assert len(mgr.list_tools()) == 2
    assert mgr.find_tool("codex.run") is not None
    assert mgr.find_tool("nonexistent") is None


@pytest.mark.asyncio
async def test_mcp_disconnect():
    mgr = McpSessionManager()
    await mgr.connect("s1", "Server1", "stdio://s1")
    assert "s1" in mgr.active_servers
    await mgr.disconnect("s1")
    assert "s1" not in mgr.active_servers


@pytest.mark.asyncio
async def test_mcp_invoke_records_audit():
    from unittest.mock import AsyncMock, MagicMock, patch
    from reins.execution.mcp.transport import JsonRpcResponse

    mgr = McpSessionManager()

    # Mock the transport
    mock_transport = MagicMock()
    mock_transport.send = AsyncMock(
        return_value=JsonRpcResponse(
            jsonrpc="2.0",
            id="test-id",
            result={"output": "success"},
        )
    )

    with patch("reins.execution.mcp.session.create_transport") as mock_create:
        mock_create.return_value = mock_transport

        await mgr.connect("s1", "Server1", "stdio://s1",
                          tools=[{"name": "do_thing", "input_schema": {}}])
        result = await mgr.invoke_tool("s1", "do_thing", {"x": 1}, "run-1")

        assert result["call_id"]
        assert result["status"] == "success"
        assert len(mgr.audit_log) == 1
        assert mgr.audit_log[0]["tool_name"] == "do_thing"
