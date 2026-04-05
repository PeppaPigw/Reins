"""MCP session manager — lifecycle management for MCP server connections.

MCP is Reins's default tool/resource bus.  This module handles:
- server lifecycle (init / teardown)
- capability negotiation
- tool invocation routing
- resource caching
- audit logging of every MCP call

Each MCP server is normalized into internal capability objects so the
policy engine can govern all tool access uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

import ulid


class McpCostClass(str, Enum):
    cheap = "cheap"
    moderate = "moderate"
    expensive = "expensive"


@dataclass(frozen=True)
class McpToolCapability:
    """An MCP tool normalized for Reins policy evaluation."""

    server_id: str
    name: str
    input_schema: dict
    cost_class: McpCostClass = McpCostClass.moderate
    risk_tier: int = 2
    auth_mode: str = "none"


@dataclass(frozen=True)
class McpResourceHandle:
    """An MCP resource endpoint for caching and freshness tracking."""

    server_id: str
    uri: str
    freshness_policy: str = "on_demand"  # on_demand | ttl | subscribe
    cache_policy: str = "none"  # none | read_through | write_through


@dataclass(frozen=True)
class McpPromptTemplate:
    """An MCP prompt template reference."""

    server_id: str
    name: str
    args_schema: dict
    trust_tier: str = "untrusted"


@dataclass
class McpServerSession:
    """Tracks a live MCP server connection."""

    server_id: str
    name: str
    endpoint: str
    tools: list[McpToolCapability] = field(default_factory=list)
    resources: list[McpResourceHandle] = field(default_factory=list)
    prompts: list[McpPromptTemplate] = field(default_factory=list)
    connected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    session_id: str = field(default_factory=lambda: str(ulid.new()))
    active: bool = True


class McpSessionManager:
    """Manages MCP server connections and provides unified access.

    Responsibilities:
      - lifecycle init / teardown
      - capability negotiation and normalization
      - tool throttling
      - resource caching
      - prompt retrieval policy
      - audit logging (every invocation gets a call_id)
    """

    def __init__(self) -> None:
        self._sessions: dict[str, McpServerSession] = {}
        self._call_log: list[dict] = []

    async def connect(
        self,
        server_id: str,
        name: str,
        endpoint: str,
        tools: list[dict] | None = None,
        resources: list[dict] | None = None,
    ) -> McpServerSession:
        """Register an MCP server and negotiate capabilities."""
        session = McpServerSession(
            server_id=server_id,
            name=name,
            endpoint=endpoint,
            tools=[
                McpToolCapability(
                    server_id=server_id,
                    name=t["name"],
                    input_schema=t.get("input_schema", {}),
                    cost_class=McpCostClass(t.get("cost_class", "moderate")),
                    risk_tier=t.get("risk_tier", 2),
                )
                for t in (tools or [])
            ],
            resources=[
                McpResourceHandle(
                    server_id=server_id,
                    uri=r["uri"],
                    freshness_policy=r.get("freshness_policy", "on_demand"),
                    cache_policy=r.get("cache_policy", "none"),
                )
                for r in (resources or [])
            ],
        )
        self._sessions[server_id] = session
        return session

    async def disconnect(self, server_id: str) -> None:
        session = self._sessions.pop(server_id, None)
        if session:
            session.active = False

    def get_session(self, server_id: str) -> McpServerSession | None:
        return self._sessions.get(server_id)

    def list_tools(self) -> list[McpToolCapability]:
        """List all tools across all connected MCP servers."""
        result: list[McpToolCapability] = []
        for session in self._sessions.values():
            if session.active:
                result.extend(session.tools)
        return result

    def find_tool(self, tool_name: str) -> McpToolCapability | None:
        for session in self._sessions.values():
            if session.active:
                for tool in session.tools:
                    if tool.name == tool_name:
                        return tool
        return None

    async def invoke_tool(
        self,
        server_id: str,
        tool_name: str,
        args: dict,
        run_id: str,
    ) -> dict:
        """Invoke an MCP tool. Returns the raw response dict.

        In a real implementation this would make a JSON-RPC call.
        For v1, we record the invocation for audit and return a
        placeholder observation.  The actual MCP protocol transport
        is an integration-plane concern.
        """
        call_id = str(ulid.new())
        self._call_log.append({
            "call_id": call_id,
            "server_id": server_id,
            "tool_name": tool_name,
            "args": args,
            "run_id": run_id,
            "ts": datetime.now(UTC).isoformat(),
        })
        # Real implementation: JSON-RPC call to endpoint
        # For now, structured placeholder — callers must handle this
        return {
            "call_id": call_id,
            "status": "not_connected",
            "message": f"MCP transport not implemented; tool={tool_name}@{server_id}",
        }

    @property
    def audit_log(self) -> list[dict]:
        return list(self._call_log)

    @property
    def active_servers(self) -> list[str]:
        return [sid for sid, s in self._sessions.items() if s.active]
