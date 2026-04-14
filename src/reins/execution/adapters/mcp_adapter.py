"""MCP adapter — wraps McpSessionManager into the handle-based Adapter interface.

Allows the ExecutionDispatcher to route mcp.tool.invoke and mcp.resource.read
capacities through the same trusted pipeline as fs/git/shell adapters.

Handle spec:
  { "server_id": str, "name": str, "endpoint": str,
    "tools": [...], "resources": [...] }

Command ops:
  { "op": "invoke_tool", "tool_name": str, "args": dict, "run_id": str }
  { "op": "read_resource", "uri": str }
  { "op": "get_prompt", "name": str, "args": dict }
"""
from __future__ import annotations

import json

from reins.execution.adapter import Adapter, Handle, Observation
from reins.execution.mcp.session import McpSessionManager


class McpAdapter(Adapter):
    """Handle-based adapter backed by McpSessionManager."""

    def __init__(self, adapter_id: str = "mcp.local") -> None:
        self.adapter_id = adapter_id
        self._manager = McpSessionManager()

    # ------------------------------------------------------------------
    # Adapter lifecycle
    # ------------------------------------------------------------------
    async def open(self, spec: dict) -> Handle:
        """Register/connect an MCP server and return a handle."""
        server_id = spec["server_id"]
        session = await self._manager.connect(
            server_id=server_id,
            name=spec.get("name", server_id),
            endpoint=spec.get("endpoint", ""),
            tools=spec.get("tools", []),
            resources=spec.get("resources", []),
        )
        return Handle(
            adapter_kind="mcp",
            adapter_id=self.adapter_id,
            metadata={
                "server_id": server_id,
                "session_id": session.session_id,
                "tool_count": len(session.tools),
                "resource_count": len(session.resources),
            },
        )

    async def exec(self, handle: Handle, command: dict) -> Observation:
        server_id = handle.metadata["server_id"]
        op = command.get("op", "invoke_tool")

        if op == "invoke_tool":
            result = await self._manager.invoke_tool(
                server_id=server_id,
                tool_name=command["tool_name"],
                args=command.get("args", {}),
                run_id=command.get("run_id", ""),
            )
            return Observation(
                stdout=json.dumps(result),
                stderr="",
                exit_code=0 if result.get("status") != "error" else 1,
                effect_descriptor={
                    "op": "invoke_tool",
                    "server_id": server_id,
                    "tool_name": command["tool_name"],
                    "call_id": result.get("call_id"),
                },
            )

        if op == "read_resource":
            uri = command["uri"]
            # Resource reads are cheap/cached; audited but no heavy side effects.
            call_id = self._manager.audit_log  # reuse log as reference
            return Observation(
                stdout=json.dumps({"uri": uri, "status": "not_connected"}),
                stderr="",
                exit_code=0,
                effect_descriptor={"op": "read_resource", "server_id": server_id, "uri": uri},
            )

        if op == "get_prompt":
            name = command["name"]
            return Observation(
                stdout=json.dumps({"name": name, "status": "not_connected"}),
                stderr="",
                exit_code=0,
                effect_descriptor={"op": "get_prompt", "server_id": server_id, "name": name},
            )

        return Observation(
            stdout="",
            stderr=f"unknown op: {op}",
            exit_code=1,
            effect_descriptor={"op": op, "server_id": server_id},
        )

    async def snapshot(self, handle: Handle) -> str:
        server_id = handle.metadata["server_id"]
        session = self._manager.get_session(server_id)
        if session is None:
            return f"{{\"server_id\": \"{server_id}\", \"active\": false}}"
        return json.dumps({
            "server_id": server_id,
            "session_id": session.session_id,
            "active": session.active,
            "tool_count": len(session.tools),
        })

    async def freeze(self, handle: Handle) -> dict:
        return {
            "handle_id": handle.handle_id,
            "adapter_kind": "mcp",
            "adapter_id": self.adapter_id,
            "server_id": handle.metadata["server_id"],
            "session_id": handle.metadata.get("session_id", ""),
        }

    async def thaw(self, frozen: dict) -> Handle:
        return Handle(
            adapter_kind="mcp",
            adapter_id=frozen.get("adapter_id", self.adapter_id),
            handle_id=frozen["handle_id"],
            metadata={
                "server_id": frozen["server_id"],
                "session_id": frozen.get("session_id", ""),
                "restored": True,
            },
        )

    async def reset(self, handle: Handle) -> Handle:
        server_id = handle.metadata["server_id"]
        await self._manager.disconnect(server_id)
        return Handle(
            adapter_kind="mcp",
            adapter_id=self.adapter_id,
            metadata={"server_id": server_id},
        )

    async def close(self, handle: Handle) -> None:
        server_id = handle.metadata.get("server_id", "")
        if server_id:
            await self._manager.disconnect(server_id)

    @property
    def session_manager(self) -> McpSessionManager:
        return self._manager
