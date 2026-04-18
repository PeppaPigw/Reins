from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from reins.execution.mcp.session import McpSessionManager
from reins.execution.mcp.transport import JsonRpcRequest, JsonRpcResponse
from reins.kernel.event.journal import EventJournal
from reins.orchestration.mcp_session import OrchestrationMCPSessionManager
from reins.task.context_jsonl import ContextJSONL, ContextMessage


class FakeTransport:
    def __init__(self, name: str) -> None:
        self.name = name
        self.requests: list[JsonRpcRequest] = []
        self.closed = False

    async def send(self, request: JsonRpcRequest) -> JsonRpcResponse:
        self.requests.append(request)
        if request.method == "tools/list":
            return JsonRpcResponse(jsonrpc="2.0", id=request.id, result={"tools": []})
        if request.method == "tools/call":
            params = request.params if isinstance(request.params, dict) else {}
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                result={
                    "transport": self.name,
                    "tool_name": params.get("name"),
                    "arguments": params.get("arguments", {}),
                },
            )
        return JsonRpcResponse(jsonrpc="2.0", id=request.id, result={})

    async def close(self) -> None:
        self.closed = True


def _prepare_task(repo_root: Path, task_id: str = "task-1") -> Path:
    task_dir = repo_root / ".reins" / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.json").write_text(
        json.dumps(
            {
                "task_id": task_id,
                "title": "Investigate MCP task",
                "status": "pending",
            }
        ),
        encoding="utf-8",
    )
    (task_dir / "prd.md").write_text("# Task PRD\n\nImplement MCP orchestration.\n", encoding="utf-8")
    ContextJSONL.write_message(
        task_dir / "implement.jsonl",
        ContextMessage(
            role="user",
            content="Use the task context when invoking the tool.",
            metadata={"source": "test"},
        ),
    )
    return task_dir


async def _load_events(journal: EventJournal, run_id: str) -> list:
    return [event async for event in journal.read_from(run_id)]


@pytest.mark.asyncio
async def test_create_session_tracks_session_and_emits_event(tmp_path: Path) -> None:
    _prepare_task(tmp_path)
    journal = EventJournal(tmp_path / "journal.jsonl")
    base_manager = McpSessionManager()
    transport = FakeTransport("codex")

    with patch("reins.execution.mcp.session.create_transport", return_value=transport):
        manager = OrchestrationMCPSessionManager(tmp_path, journal, base_manager)
        session_id = await manager.create_session(
            agent_id="agent-1",
            task_id="task-1",
            run_id="run-create",
            servers=[
                {
                    "server_id": "codex",
                    "endpoint": "http://codex.test/rpc",
                    "tools": [{"name": "plan", "input_schema": {}}],
                }
            ],
        )

    info = manager.get_session_info(session_id)
    assert info is not None
    assert info["agent_id"] == "agent-1"
    assert info["task_id"] == "task-1"
    assert info["server_ids"] == ["codex"]
    assert info["servers"][0]["tool_count"] == 1
    assert info["active"] is True

    events = await _load_events(journal, "run-create")
    assert [event.type for event in events] == ["mcp.session_created"]
    assert events[0].payload["session_id"] == session_id
    assert events[0].payload["server_ids"] == ["codex"]


@pytest.mark.asyncio
async def test_invoke_tool_injects_task_context_when_schema_requests_it(tmp_path: Path) -> None:
    _prepare_task(tmp_path)
    journal = EventJournal(tmp_path / "journal.jsonl")
    base_manager = McpSessionManager()
    transport = FakeTransport("codex")

    with patch("reins.execution.mcp.session.create_transport", return_value=transport):
        manager = OrchestrationMCPSessionManager(tmp_path, journal, base_manager)
        session_id = await manager.create_session(
            agent_id="agent-ctx",
            task_id="task-1",
            run_id="run-session",
            servers=[
                {
                    "server_id": "codex",
                    "endpoint": "http://codex.test/rpc",
                    "tools": [
                        {
                            "name": "plan",
                            "input_schema": {
                                "type": "object",
                                "properties": {
                                    "prompt": {"type": "string"},
                                    "task_context": {"type": "object"},
                                    "repo_root": {"type": "string"},
                                    "task_id": {"type": "string"},
                                    "agent_id": {"type": "string"},
                                    "run_id": {"type": "string"},
                                },
                            },
                        }
                    ],
                }
            ],
        )

        result = await manager.invoke_tool(
            session_id=session_id,
            server_id="codex",
            tool_name="plan",
            args={"prompt": "summarize"},
            run_id="run-invoke",
        )

    assert result["status"] == "success"
    injected_args = transport.requests[-1].params["arguments"]
    assert injected_args["prompt"] == "summarize"
    assert injected_args["repo_root"] == str(tmp_path)
    assert injected_args["task_id"] == "task-1"
    assert injected_args["agent_id"] == "agent-ctx"
    assert injected_args["run_id"] == "run-invoke"
    assert injected_args["task_context"]["task_metadata"]["task_id"] == "task-1"
    assert injected_args["task_context"]["agent_contexts"]["implement"][0]["content"] == (
        "Use the task context when invoking the tool."
    )

    events = await _load_events(journal, "run-invoke")
    assert [event.type for event in events] == ["mcp.tool_invoked"]
    assert events[0].payload["status"] == "success"


@pytest.mark.asyncio
async def test_close_session_disconnects_servers_and_emits_event(tmp_path: Path) -> None:
    _prepare_task(tmp_path)
    journal = EventJournal(tmp_path / "journal.jsonl")
    base_manager = McpSessionManager()
    transport_one = FakeTransport("one")
    transport_two = FakeTransport("two")

    with patch(
        "reins.execution.mcp.session.create_transport",
        side_effect=[transport_one, transport_two],
    ):
        manager = OrchestrationMCPSessionManager(tmp_path, journal, base_manager)
        session_id = await manager.create_session(
            agent_id="agent-close",
            task_id="task-1",
            run_id="run-open",
            servers=[
                {"server_id": "codex", "endpoint": "http://one", "tools": []},
                {"server_id": "gitnexus", "endpoint": "http://two", "tools": []},
            ],
        )
        await manager.close_session(session_id, run_id="run-close")

    info = manager.get_session_info(session_id)
    assert info is not None
    assert info["active"] is False
    assert transport_one.closed is True
    assert transport_two.closed is True

    events = await _load_events(journal, "run-close")
    assert [event.type for event in events] == ["mcp.session_closed"]
    assert events[0].payload["session_id"] == session_id


@pytest.mark.asyncio
async def test_get_resource_usage_tracks_per_server_call_counts(tmp_path: Path) -> None:
    _prepare_task(tmp_path)
    journal = EventJournal(tmp_path / "journal.jsonl")
    base_manager = McpSessionManager()
    transport_one = FakeTransport("one")
    transport_two = FakeTransport("two")

    with patch(
        "reins.execution.mcp.session.create_transport",
        side_effect=[transport_one, transport_two],
    ):
        manager = OrchestrationMCPSessionManager(tmp_path, journal, base_manager)
        session_id = await manager.create_session(
            agent_id="agent-usage",
            task_id="task-1",
            run_id="run-usage-open",
            servers=[
                {
                    "server_id": "codex",
                    "endpoint": "http://one",
                    "tools": [{"name": "plan", "input_schema": {}}],
                },
                {
                    "server_id": "gitnexus",
                    "endpoint": "http://two",
                    "tools": [{"name": "status", "input_schema": {}}],
                },
            ],
        )

        await manager.invoke_tool(session_id, "codex", "plan", {}, run_id="run-usage")
        await manager.invoke_tool(session_id, "codex", "plan", {}, run_id="run-usage")
        await manager.invoke_tool(session_id, "gitnexus", "status", {}, run_id="run-usage")

    usage = manager.get_resource_usage(session_id)
    assert usage["tool_call_count"] == 3
    assert usage["total_duration_ms"] >= 0
    counts = {item["server_id"]: item["call_count"] for item in usage["servers"]}
    assert counts == {"codex": 2, "gitnexus": 1}


@pytest.mark.asyncio
async def test_list_and_filter_sessions_by_agent_and_task(tmp_path: Path) -> None:
    _prepare_task(tmp_path, "task-1")
    _prepare_task(tmp_path, "task-2")
    journal = EventJournal(tmp_path / "journal.jsonl")
    base_manager = McpSessionManager()
    transports = [FakeTransport(f"transport-{idx}") for idx in range(3)]

    with patch(
        "reins.execution.mcp.session.create_transport",
        side_effect=transports,
    ):
        manager = OrchestrationMCPSessionManager(tmp_path, journal, base_manager)
        session_one = await manager.create_session(
            "agent-a",
            "task-1",
            "run-a",
            [{"server_id": "codex", "endpoint": "http://one", "tools": []}],
        )
        await manager.create_session(
            "agent-a",
            "task-2",
            "run-b",
            [{"server_id": "gitnexus", "endpoint": "http://two", "tools": []}],
        )
        await manager.create_session(
            "agent-b",
            "task-2",
            "run-c",
            [{"server_id": "abcoder", "endpoint": "http://three", "tools": []}],
        )
        await manager.close_session(session_one, run_id="run-close-one")

    active_sessions = manager.list_active_sessions()
    assert len(active_sessions) == 2
    assert {item["agent_id"] for item in active_sessions} == {"agent-a", "agent-b"}
    assert len(manager.get_sessions_by_agent("agent-a")) == 2
    assert len(manager.get_sessions_by_task("task-2")) == 2


@pytest.mark.asyncio
async def test_invoke_tool_missing_server_emits_error_event(tmp_path: Path) -> None:
    _prepare_task(tmp_path)
    journal = EventJournal(tmp_path / "journal.jsonl")
    base_manager = McpSessionManager()
    transport = FakeTransport("codex")

    with patch("reins.execution.mcp.session.create_transport", return_value=transport):
        manager = OrchestrationMCPSessionManager(tmp_path, journal, base_manager)
        session_id = await manager.create_session(
            "agent-missing",
            "task-1",
            "run-open",
            [{"server_id": "codex", "endpoint": "http://codex", "tools": []}],
        )
        result = await manager.invoke_tool(
            session_id=session_id,
            server_id="gitnexus",
            tool_name="status",
            args={},
            run_id="run-missing",
        )

    assert result["status"] == "error"
    assert "not registered" in result["error"]
    events = await _load_events(journal, "run-missing")
    assert [event.type for event in events] == ["mcp.tool_invoked"]
    assert events[0].payload["status"] == "error"


@pytest.mark.asyncio
async def test_create_session_cleans_up_partial_connections_on_failure(tmp_path: Path) -> None:
    _prepare_task(tmp_path)
    journal = EventJournal(tmp_path / "journal.jsonl")
    base_manager = McpSessionManager()
    transport = FakeTransport("first")

    with patch(
        "reins.execution.mcp.session.create_transport",
        side_effect=[transport, RuntimeError("transport boom")],
    ):
        manager = OrchestrationMCPSessionManager(tmp_path, journal, base_manager)
        with pytest.raises(RuntimeError, match="transport boom"):
            await manager.create_session(
                "agent-partial",
                "task-1",
                "run-fail",
                [
                    {"server_id": "codex", "endpoint": "http://one", "tools": []},
                    {"server_id": "gitnexus", "endpoint": "http://two", "tools": []},
                ],
            )

    assert transport.closed is True
    assert manager.list_active_sessions() == []


@pytest.mark.asyncio
async def test_convenience_methods_build_expected_endpoints(tmp_path: Path) -> None:
    _prepare_task(tmp_path)
    journal = EventJournal(tmp_path / "journal.jsonl")
    base_manager = McpSessionManager()
    transports = [FakeTransport("codex"), FakeTransport("git"), FakeTransport("abc")]

    with patch(
        "reins.execution.mcp.session.create_transport",
        side_effect=transports,
    ):
        manager = OrchestrationMCPSessionManager(tmp_path, journal, base_manager)
        codex_session = await manager.create_codex_session(
            "agent-codex",
            "task-1",
            "run-codex",
            {"endpoint": "http://codex"},
        )
        git_session = await manager.create_gitnexus_session(
            "agent-git",
            "task-1",
            "run-git",
            repo_path="/tmp/repo",
        )
        abc_session = await manager.create_abcoder_session(
            "agent-abc",
            "task-1",
            "run-abc",
            repo_name="reins",
        )

    assert manager.get_session_info(codex_session)["servers"][0]["endpoint"] == "http://codex"
    assert (
        manager.get_session_info(git_session)["servers"][0]["endpoint"]
        == "stdio://gitnexus --repo /tmp/repo"
    )
    assert (
        manager.get_session_info(abc_session)["servers"][0]["endpoint"]
        == "stdio://abcoder --repo reins"
    )
