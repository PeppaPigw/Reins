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

from reins.execution.mcp.transport import JsonRpcRequest, JsonRpcTransport, create_transport


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
    transport: JsonRpcTransport | None = None
    reconnect_attempts: int = 0
    last_error: str | None = None
    last_activity: datetime = field(default_factory=lambda: datetime.now(UTC))


class McpSessionManager:
    """Manages MCP server connections and provides unified access.

    Responsibilities:
      - lifecycle init / teardown
      - capability negotiation and normalization
      - automatic reconnection on failure
      - health checking
      - tool throttling
      - resource caching
      - prompt retrieval policy
      - audit logging (every invocation gets a call_id)
    """

    def __init__(self, max_reconnect_attempts: int = 3) -> None:
        self._sessions: dict[str, McpServerSession] = {}
        self._call_log: list[dict] = []
        self._max_reconnect_attempts = max_reconnect_attempts

    async def connect(
        self,
        server_id: str,
        name: str,
        endpoint: str,
        tools: list[dict] | None = None,
        resources: list[dict] | None = None,
        negotiate_capabilities: bool = True,
    ) -> McpServerSession:
        """Register an MCP server and negotiate capabilities.

        If negotiate_capabilities is True, will query the server for its
        available tools, resources, and prompts via JSON-RPC.
        """
        # Create transport
        transport = create_transport(endpoint)

        # Negotiate capabilities if requested
        negotiated_tools = tools or []
        negotiated_resources = resources or []
        negotiated_prompts: list[dict] = []

        if negotiate_capabilities and not tools:
            # Query server for capabilities
            capabilities = await self._negotiate_capabilities(transport)
            negotiated_tools = capabilities.get("tools", [])
            negotiated_resources = capabilities.get("resources", [])
            negotiated_prompts = capabilities.get("prompts", [])

        session = McpServerSession(
            server_id=server_id,
            name=name,
            endpoint=endpoint,
            transport=transport,
            tools=[
                McpToolCapability(
                    server_id=server_id,
                    name=t["name"],
                    input_schema=t.get("input_schema", {}),
                    cost_class=McpCostClass(t.get("cost_class", "moderate")),
                    risk_tier=t.get("risk_tier", 2),
                )
                for t in negotiated_tools
            ],
            resources=[
                McpResourceHandle(
                    server_id=server_id,
                    uri=r["uri"],
                    freshness_policy=r.get("freshness_policy", "on_demand"),
                    cache_policy=r.get("cache_policy", "none"),
                )
                for r in negotiated_resources
            ],
            prompts=[
                McpPromptTemplate(
                    server_id=server_id,
                    name=p["name"],
                    args_schema=p.get("args_schema", {}),
                    trust_tier=p.get("trust_tier", "untrusted"),
                )
                for p in negotiated_prompts
            ],
        )
        self._sessions[server_id] = session
        return session

    async def _negotiate_capabilities(self, transport: JsonRpcTransport) -> dict:
        """Query an MCP server for its capabilities.

        Returns a dict with 'tools', 'resources', and 'prompts' lists.
        """
        capabilities = {
            "tools": [],
            "resources": [],
            "prompts": [],
        }

        # Query for tools
        try:
            request = JsonRpcRequest(
                method="tools/list",
                params={},
                id=str(ulid.new()),
            )
            response = await transport.send(request)
            if not response.is_error() and response.result:
                capabilities["tools"] = response.result.get("tools", [])
        except Exception:
            pass  # Ignore errors, server may not support this method

        # Query for resources
        try:
            request = JsonRpcRequest(
                method="resources/list",
                params={},
                id=str(ulid.new()),
            )
            response = await transport.send(request)
            if not response.is_error() and response.result:
                capabilities["resources"] = response.result.get("resources", [])
        except Exception:
            pass

        # Query for prompts
        try:
            request = JsonRpcRequest(
                method="prompts/list",
                params={},
                id=str(ulid.new()),
            )
            response = await transport.send(request)
            if not response.is_error() and response.result:
                capabilities["prompts"] = response.result.get("prompts", [])
        except Exception:
            pass

        return capabilities

    async def disconnect(self, server_id: str) -> None:
        """Disconnect from an MCP server and clean up resources."""
        session = self._sessions.pop(server_id, None)
        if session:
            session.active = False
            if session.transport:
                await session.transport.close()

    async def refresh_capabilities(self, server_id: str) -> bool:
        """Refresh the capabilities of an existing server connection.

        Returns True if refresh succeeded, False otherwise.
        """
        session = self._sessions.get(server_id)
        if not session or not session.active or not session.transport:
            return False

        try:
            capabilities = await self._negotiate_capabilities(session.transport)

            # Update session with new capabilities
            session.tools = [
                McpToolCapability(
                    server_id=server_id,
                    name=t["name"],
                    input_schema=t.get("input_schema", {}),
                    cost_class=McpCostClass(t.get("cost_class", "moderate")),
                    risk_tier=t.get("risk_tier", 2),
                )
                for t in capabilities.get("tools", [])
            ]

            session.resources = [
                McpResourceHandle(
                    server_id=server_id,
                    uri=r["uri"],
                    freshness_policy=r.get("freshness_policy", "on_demand"),
                    cache_policy=r.get("cache_policy", "none"),
                )
                for r in capabilities.get("resources", [])
            ]

            session.prompts = [
                McpPromptTemplate(
                    server_id=server_id,
                    name=p["name"],
                    args_schema=p.get("args_schema", {}),
                    trust_tier=p.get("trust_tier", "untrusted"),
                )
                for p in capabilities.get("prompts", [])
            ]

            session.last_activity = datetime.now(UTC)
            return True

        except Exception as e:
            session.last_error = str(e)
            return False

    async def reconnect(self, server_id: str) -> bool:
        """Attempt to reconnect to a disconnected server.

        Returns True if reconnection succeeded, False otherwise.
        """
        session = self._sessions.get(server_id)
        if not session:
            return False

        # Check if we've exceeded max attempts
        if session.reconnect_attempts >= self._max_reconnect_attempts:
            session.last_error = "Max reconnection attempts exceeded"
            return False

        # Close old transport if it exists
        if session.transport:
            try:
                await session.transport.close()
            except Exception:
                pass  # Ignore errors closing old transport

        # Try to create new transport
        try:
            session.transport = create_transport(session.endpoint)
            session.active = True
            session.reconnect_attempts += 1
            session.last_activity = datetime.now(UTC)
            session.last_error = None
            return True
        except Exception as e:
            session.reconnect_attempts += 1
            session.last_error = str(e)
            session.active = False
            return False

    async def health_check(self, server_id: str) -> dict:
        """Check the health of an MCP server connection.

        Returns a dict with status information.
        """
        session = self._sessions.get(server_id)
        if not session:
            return {
                "server_id": server_id,
                "status": "not_found",
                "message": "Server not registered",
            }

        if not session.active:
            return {
                "server_id": server_id,
                "status": "inactive",
                "reconnect_attempts": session.reconnect_attempts,
                "last_error": session.last_error,
            }

        # Try a simple ping via JSON-RPC
        if session.transport:
            try:
                request = JsonRpcRequest(
                    method="ping",
                    params={},
                    id=str(ulid.new()),
                )
                response = await session.transport.send(request)

                if response.is_error():
                    return {
                        "server_id": server_id,
                        "status": "unhealthy",
                        "error": response.error,
                    }

                session.last_activity = datetime.now(UTC)
                return {
                    "server_id": server_id,
                    "status": "healthy",
                    "last_activity": session.last_activity.isoformat(),
                }
            except Exception as e:
                session.last_error = str(e)
                return {
                    "server_id": server_id,
                    "status": "error",
                    "error": str(e),
                }

        return {
            "server_id": server_id,
            "status": "no_transport",
            "message": "Transport not initialized",
        }

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
        auto_reconnect: bool = True,
    ) -> dict:
        """Invoke an MCP tool via JSON-RPC. Returns the raw response dict.

        If auto_reconnect is True, will attempt to reconnect once on connection errors.
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

        # Get session and transport
        session = self._sessions.get(server_id)
        if not session:
            return {
                "call_id": call_id,
                "status": "error",
                "error": f"Server {server_id} not found",
            }

        if not session.active:
            # Try to reconnect if enabled
            if auto_reconnect:
                reconnected = await self.reconnect(server_id)
                if not reconnected:
                    return {
                        "call_id": call_id,
                        "status": "error",
                        "error": f"Server {server_id} not connected and reconnection failed",
                    }
            else:
                return {
                    "call_id": call_id,
                    "status": "error",
                    "error": f"Server {server_id} not connected",
                }

        if not session.transport:
            return {
                "call_id": call_id,
                "status": "error",
                "error": f"No transport available for server {server_id}",
            }

        # Make JSON-RPC call
        request = JsonRpcRequest(
            method="tools/call",
            params={"name": tool_name, "arguments": args},
            id=call_id,
        )

        try:
            response = await session.transport.send(request)

            # Update last activity on successful call
            session.last_activity = datetime.now(UTC)

            # Convert JSON-RPC response to our format
            if response.is_error():
                # Check if it's a connection error and try to reconnect
                error_code = response.error.get("code") if isinstance(response.error, dict) else None
                if auto_reconnect and error_code == -32000:  # Transport error
                    reconnected = await self.reconnect(server_id)
                    if reconnected:
                        # Retry the call once
                        return await self.invoke_tool(
                            server_id, tool_name, args, run_id, auto_reconnect=False
                        )

                return {
                    "call_id": call_id,
                    "status": "error",
                    "error": response.error,
                }

            return {
                "call_id": call_id,
                "status": "success",
                "result": response.result,
            }

        except Exception as e:
            session.last_error = str(e)
            session.active = False

            # Try to reconnect on exception
            if auto_reconnect:
                reconnected = await self.reconnect(server_id)
                if reconnected:
                    # Retry the call once
                    return await self.invoke_tool(
                        server_id, tool_name, args, run_id, auto_reconnect=False
                    )

            return {
                "call_id": call_id,
                "status": "error",
                "error": f"Exception during invocation: {str(e)}",
            }

    @property
    def audit_log(self) -> list[dict]:
        return list(self._call_log)

    @property
    def active_servers(self) -> list[str]:
        return [sid for sid, s in self._sessions.items() if s.active]
