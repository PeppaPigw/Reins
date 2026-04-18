"""Orchestration-layer MCP session management.

This wrapper keeps agent/task-scoped MCP sessions on top of the lower-level
``McpSessionManager``. The low-level manager tracks live connections per
transport-facing ``server_id``; this orchestration layer adds:

- per-agent / per-task session tracking
- session-scoped server namespacing so concurrent logical sessions do not clash
- journaled lifecycle events
- lightweight task context injection for MCP tools
- resource usage accounting for observability
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ulid

from reins.execution.mcp.session import McpServerSession, McpSessionManager
from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.journal import EventJournal
from reins.task.context_jsonl import ContextJSONL


@dataclass
class OrchestrationMCPServerBinding:
    """Tracks a logical server inside an orchestration MCP session."""

    server_id: str
    transport_server_id: str
    endpoint: str
    call_count: int = 0
    total_duration_ms: float = 0.0
    last_activity: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class OrchestrationMCPSession:
    """Tracks an orchestration-layer MCP session."""

    session_id: str
    agent_id: str
    task_id: str
    run_id: str
    server_ids: list[str]
    created_at: datetime
    closed_at: datetime | None = None
    active: bool = True
    tool_call_count: int = 0
    last_activity: datetime = field(default_factory=lambda: datetime.now(UTC))
    servers: dict[str, OrchestrationMCPServerBinding] = field(default_factory=dict)


class OrchestrationMCPSessionManager:
    """High-level MCP session orchestration for agents and tasks."""

    def __init__(
        self,
        repo_root: Path,
        journal: EventJournal,
        base_session_manager: McpSessionManager | None = None,
    ):
        """Initialize orchestration MCP session manager.

        Args:
            repo_root: Repository root directory
            journal: EventJournal for event emission
            base_session_manager: Optional existing McpSessionManager to wrap
        """
        self.repo_root = repo_root
        self.journal = journal
        self.base_session_manager = base_session_manager or McpSessionManager()
        self._builder = EventBuilder(journal)
        self._sessions: dict[str, OrchestrationMCPSession] = {}
        self._sessions_by_agent: dict[str, set[str]] = {}
        self._sessions_by_task: dict[str, set[str]] = {}

    async def create_session(
        self,
        agent_id: str,
        task_id: str,
        run_id: str,
        servers: list[dict],
    ) -> str:
        """Create MCP session for an agent.

        Returns session_id for tracking.
        Emits: mcp.session_created event
        """
        session_id = f"mcp-session-{ulid.new()}"
        created_at = datetime.now(UTC)
        session = OrchestrationMCPSession(
            session_id=session_id,
            agent_id=agent_id,
            task_id=task_id,
            run_id=run_id,
            server_ids=[],
            created_at=created_at,
            last_activity=created_at,
        )

        connected_transport_ids: list[str] = []
        try:
            for server in servers:
                logical_server_id = self._coerce_required_str(server, "server_id")
                endpoint = self._coerce_required_str(server, "endpoint")
                if logical_server_id in session.servers:
                    raise ValueError(
                        f"Duplicate server_id {logical_server_id!r} in session {session_id}"
                    )

                transport_server_id = self._transport_server_id(session_id, logical_server_id)
                await self.base_session_manager.connect(
                    server_id=transport_server_id,
                    name=str(server.get("name") or logical_server_id),
                    endpoint=endpoint,
                    tools=self._coerce_optional_list(server.get("tools")),
                    resources=self._coerce_optional_list(server.get("resources")),
                    negotiate_capabilities=bool(server.get("negotiate_capabilities", True)),
                )
                connected_transport_ids.append(transport_server_id)
                session.server_ids.append(logical_server_id)
                session.servers[logical_server_id] = OrchestrationMCPServerBinding(
                    server_id=logical_server_id,
                    transport_server_id=transport_server_id,
                    endpoint=endpoint,
                    last_activity=created_at,
                )
        except Exception:
            for transport_server_id in connected_transport_ids:
                try:
                    await self.base_session_manager.disconnect(transport_server_id)
                except Exception:
                    pass
            raise

        self._sessions[session_id] = session
        self._sessions_by_agent.setdefault(agent_id, set()).add(session_id)
        self._sessions_by_task.setdefault(task_id, set()).add(session_id)

        await self._builder.commit(
            run_id,
            "mcp.session_created",
            {
                "session_id": session_id,
                "agent_id": agent_id,
                "task_id": task_id,
                "server_ids": list(session.server_ids),
            },
            correlation_id=session_id,
        )
        return session_id

    async def invoke_tool(
        self,
        session_id: str,
        server_id: str,
        tool_name: str,
        args: dict,
        run_id: str,
    ) -> dict:
        """Invoke MCP tool with context injection.

        Automatically injects task context into tool args if needed.
        Emits: mcp.tool_invoked event
        Returns: Tool result dict
        """
        session = self._sessions.get(session_id)
        if session is None:
            return await self._emit_failed_tool_invocation(
                run_id=run_id,
                session_id=session_id,
                server_id=server_id,
                tool_name=tool_name,
                error=f"Session {session_id} not found",
            )

        if not session.active:
            return await self._emit_failed_tool_invocation(
                run_id=run_id,
                session_id=session_id,
                server_id=server_id,
                tool_name=tool_name,
                error=f"Session {session_id} is closed",
            )

        binding = session.servers.get(server_id)
        if binding is None:
            return await self._emit_failed_tool_invocation(
                run_id=run_id,
                session_id=session_id,
                server_id=server_id,
                tool_name=tool_name,
                error=f"Server {server_id} not registered in session {session_id}",
            )

        start = time.perf_counter()
        injected_args = self._inject_tool_context(
            session=session,
            server_id=server_id,
            tool_name=tool_name,
            args=args,
            run_id=run_id,
        )

        try:
            result = await self.base_session_manager.invoke_tool(
                server_id=binding.transport_server_id,
                tool_name=tool_name,
                args=injected_args,
                run_id=run_id,
            )
        except Exception as exc:
            result = {
                "call_id": str(ulid.new()),
                "status": "error",
                "error": f"Exception during invocation: {exc}",
            }

        duration_ms = (time.perf_counter() - start) * 1000
        status = "success" if result.get("status") == "success" else "error"
        call_id = str(result.get("call_id") or ulid.new())
        if "call_id" not in result:
            result = {**result, "call_id": call_id}

        session.tool_call_count += 1
        session.last_activity = datetime.now(UTC)
        binding.call_count += 1
        binding.total_duration_ms += duration_ms
        binding.last_activity = session.last_activity

        await self._builder.commit(
            run_id,
            "mcp.tool_invoked",
            {
                "session_id": session_id,
                "server_id": server_id,
                "tool_name": tool_name,
                "call_id": call_id,
                "status": status,
            },
            correlation_id=session_id,
        )
        return result

    async def close_session(
        self,
        session_id: str,
        run_id: str,
    ) -> None:
        """Close MCP session and cleanup resources.

        Disconnects all servers in the session.
        Emits: mcp.session_closed event
        """
        session = self._sessions.get(session_id)
        if session is None or not session.active:
            return

        for server_id in session.server_ids:
            binding = session.servers.get(server_id)
            if binding is None:
                continue
            try:
                await self.base_session_manager.disconnect(binding.transport_server_id)
            except Exception:
                pass

        closed_at = datetime.now(UTC)
        session.active = False
        session.closed_at = closed_at
        session.last_activity = closed_at

        await self._builder.commit(
            run_id,
            "mcp.session_closed",
            {
                "session_id": session_id,
                "agent_id": session.agent_id,
                "tool_call_count": session.tool_call_count,
                "duration_seconds": (closed_at - session.created_at).total_seconds(),
            },
            correlation_id=session_id,
        )

    def get_session_info(self, session_id: str) -> dict | None:
        """Get session information including active servers and tool counts."""
        session = self._sessions.get(session_id)
        if session is None:
            return None

        return {
            "session_id": session.session_id,
            "agent_id": session.agent_id,
            "task_id": session.task_id,
            "run_id": session.run_id,
            "server_ids": list(session.server_ids),
            "created_at": session.created_at.isoformat(),
            "closed_at": session.closed_at.isoformat() if session.closed_at else None,
            "active": session.active,
            "tool_call_count": session.tool_call_count,
            "last_activity": session.last_activity.isoformat(),
            "servers": [self._server_info(session, server_id) for server_id in session.server_ids],
        }

    def list_active_sessions(self) -> list[dict]:
        """List all active MCP sessions."""
        return [
            info
            for session_id in self._ordered_session_ids()
            if (info := self.get_session_info(session_id)) is not None and info["active"]
        ]

    def get_sessions_by_agent(self, agent_id: str) -> list[dict]:
        """Get all sessions for a specific agent."""
        session_ids = sorted(
            self._sessions_by_agent.get(agent_id, set()),
            key=self._session_sort_key,
        )
        return [
            info
            for session_id in session_ids
            if (info := self.get_session_info(session_id)) is not None
        ]

    def get_sessions_by_task(self, task_id: str) -> list[dict]:
        """Get all sessions for a specific task."""
        session_ids = sorted(
            self._sessions_by_task.get(task_id, set()),
            key=self._session_sort_key,
        )
        return [
            info
            for session_id in session_ids
            if (info := self.get_session_info(session_id)) is not None
        ]

    def get_resource_usage(self, session_id: str) -> dict:
        """Get resource usage stats for a session."""
        session = self._sessions.get(session_id)
        if session is None:
            return {
                "tool_call_count": 0,
                "total_duration_ms": 0.0,
                "servers": [],
            }

        return {
            "tool_call_count": session.tool_call_count,
            "total_duration_ms": sum(
                binding.total_duration_ms for binding in session.servers.values()
            ),
            "servers": [
                {
                    "server_id": server_id,
                    "call_count": session.servers[server_id].call_count,
                }
                for server_id in session.server_ids
            ],
        }

    async def create_codex_session(
        self,
        agent_id: str,
        task_id: str,
        run_id: str,
        codex_config: dict | None = None,
    ) -> str:
        """Create session with Codex MCP server."""
        config = dict(codex_config or {})
        endpoint = str(config.pop("endpoint", "stdio://codex"))
        tools = self._coerce_optional_list(config.pop("tools", []))
        server = {
            "server_id": "codex",
            "endpoint": endpoint,
            "tools": tools,
            **config,
        }
        return await self.create_session(agent_id, task_id, run_id, [server])

    async def create_gitnexus_session(
        self,
        agent_id: str,
        task_id: str,
        run_id: str,
        repo_path: str,
    ) -> str:
        """Create session with GitNexus MCP server."""
        return await self.create_session(
            agent_id,
            task_id,
            run_id,
            [
                {
                    "server_id": "gitnexus",
                    "endpoint": f"stdio://gitnexus --repo {repo_path}",
                    "tools": [],
                }
            ],
        )

    async def create_abcoder_session(
        self,
        agent_id: str,
        task_id: str,
        run_id: str,
        repo_name: str,
    ) -> str:
        """Create session with ABCoder MCP server."""
        return await self.create_session(
            agent_id,
            task_id,
            run_id,
            [
                {
                    "server_id": "abcoder",
                    "endpoint": f"stdio://abcoder --repo {repo_name}",
                    "tools": [],
                }
            ],
        )

    async def _emit_failed_tool_invocation(
        self,
        *,
        run_id: str,
        session_id: str,
        server_id: str,
        tool_name: str,
        error: str,
    ) -> dict:
        call_id = str(ulid.new())
        result = {
            "call_id": call_id,
            "status": "error",
            "error": error,
        }
        await self._builder.commit(
            run_id,
            "mcp.tool_invoked",
            {
                "session_id": session_id,
                "server_id": server_id,
                "tool_name": tool_name,
                "call_id": call_id,
                "status": "error",
            },
            correlation_id=session_id,
        )
        return result

    def _inject_tool_context(
        self,
        *,
        session: OrchestrationMCPSession,
        server_id: str,
        tool_name: str,
        args: dict,
        run_id: str,
    ) -> dict:
        injected_args = dict(args)
        task_context = self._build_task_context(session, run_id)
        schema = self._tool_input_schema(session, server_id, tool_name)

        candidate_values: dict[str, Any] = {
            "agent_id": session.agent_id,
            "task_id": session.task_id,
            "run_id": run_id,
            "session_id": session.session_id,
            "repo_root": str(self.repo_root),
            "repo_path": str(self.repo_root),
            "cwd": str(self.repo_root),
            "working_directory": str(self.repo_root),
            "task_dir": task_context.get("task_dir"),
            "task_context": task_context,
            "context": task_context,
        }

        for key, value in candidate_values.items():
            if value is None or key in injected_args:
                continue
            if self._schema_accepts_property(schema, key):
                injected_args[key] = value

        return injected_args

    def _build_task_context(
        self,
        session: OrchestrationMCPSession,
        run_id: str,
    ) -> dict[str, Any]:
        task_dir = self.repo_root / ".reins" / "tasks" / session.task_id
        task_metadata = self._read_json_file(task_dir / "task.json")
        prd_content = None
        prd_path = task_dir / "prd.md"
        if prd_path.exists():
            prd_content = prd_path.read_text(encoding="utf-8")

        agent_contexts: dict[str, list[dict[str, Any]]] = {}
        if task_dir.exists():
            for context_path in sorted(task_dir.glob("*.jsonl")):
                agent_contexts[context_path.stem] = [
                    message.to_dict() for message in ContextJSONL.read_messages(context_path)
                ]

        return {
            "repo_root": str(self.repo_root),
            "session_id": session.session_id,
            "run_id": run_id,
            "agent_id": session.agent_id,
            "task_id": session.task_id,
            "task_dir": str(task_dir) if task_dir.exists() else None,
            "task_metadata": task_metadata,
            "prd": prd_content,
            "agent_contexts": agent_contexts,
        }

    def _tool_input_schema(
        self,
        session: OrchestrationMCPSession,
        server_id: str,
        tool_name: str,
    ) -> dict[str, Any]:
        server_session = self._resolve_server_session(session, server_id)
        if server_session is None:
            return {}

        for tool in server_session.tools:
            if tool.name == tool_name:
                return dict(tool.input_schema)
        return {}

    def _resolve_server_session(
        self,
        session: OrchestrationMCPSession,
        server_id: str,
    ) -> McpServerSession | None:
        binding = session.servers.get(server_id)
        if binding is None:
            return None
        return self.base_session_manager.get_session(binding.transport_server_id)

    def _server_info(
        self,
        session: OrchestrationMCPSession,
        server_id: str,
    ) -> dict[str, Any]:
        binding = session.servers[server_id]
        server_session = self._resolve_server_session(session, server_id)
        tool_count = len(server_session.tools) if server_session else 0
        active = bool(session.active and server_session and server_session.active)
        return {
            "server_id": server_id,
            "active": active,
            "tool_count": tool_count,
            "call_count": binding.call_count,
            "endpoint": binding.endpoint,
        }

    def _ordered_session_ids(self) -> list[str]:
        return sorted(self._sessions, key=self._session_sort_key)

    def _session_sort_key(self, session_id: str) -> tuple[datetime, str]:
        session = self._sessions[session_id]
        return (session.created_at, session_id)

    @staticmethod
    def _transport_server_id(session_id: str, server_id: str) -> str:
        return f"{session_id}:{server_id}"

    @staticmethod
    def _coerce_required_str(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Expected non-empty string for {key!r}")
        return value

    @staticmethod
    def _coerce_optional_list(value: Any) -> list[dict] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return value
        raise TypeError(f"Expected list or None, got {type(value).__name__}")

    @staticmethod
    def _read_json_file(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    @classmethod
    def _schema_accepts_property(cls, schema: dict[str, Any], property_name: str) -> bool:
        properties = schema.get("properties")
        if isinstance(properties, dict) and property_name in properties:
            return True

        for key in ("allOf", "anyOf", "oneOf"):
            nested = schema.get(key)
            if not isinstance(nested, list):
                continue
            for item in nested:
                if isinstance(item, dict) and cls._schema_accepts_property(item, property_name):
                    return True
        return False
