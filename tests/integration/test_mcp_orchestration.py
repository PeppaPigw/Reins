from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from reins.context.compiler import ContextCompiler
from reins.execution.mcp.session import McpSessionManager
from reins.execution.mcp.transport import JsonRpcRequest, JsonRpcResponse
from reins.export.task_exporter import TaskExporter
from reins.isolation.worktree_manager import WorktreeManager
from reins.kernel.event.journal import EventJournal
from reins.orchestration.agent_registry import AgentRegistry
from reins.orchestration.hooks import ContextInjectionHook
from reins.orchestration.mcp_session import OrchestrationMCPSessionManager
from reins.orchestration.subagent_manager import SubagentManager
from reins.task.context_jsonl import ContextJSONL, ContextMessage
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection
from tests.integration.helpers import assert_event_types_in_order, load_run_events


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


def _prepare_repo(repo_root: Path, task_id: str = "task-1") -> None:
    task_dir = repo_root / ".reins" / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (repo_root / ".reins" / "spec").mkdir(parents=True, exist_ok=True)
    (repo_root / ".reins" / "agents").mkdir(parents=True, exist_ok=True)
    (repo_root / ".trellis").mkdir(parents=True, exist_ok=True)
    (task_dir / "task.json").write_text(
        json.dumps(
            {
                "task_id": task_id,
                "title": "MCP orchestration task",
                "status": "pending",
                "task_type": "backend",
            }
        ),
        encoding="utf-8",
    )
    (task_dir / "prd.md").write_text("# PRD\n\nWire MCP orchestration.\n", encoding="utf-8")
    ContextJSONL.write_message(
        task_dir / "implement.jsonl",
        ContextMessage(role="user", content="Consult task context.", metadata={"source": "test"}),
    )


async def _build_subagent_fixture(
    tmp_path: Path,
) -> tuple[
    EventJournal,
    SubagentManager,
    OrchestrationMCPSessionManager,
    str,
]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _prepare_repo(repo_root)

    journal = EventJournal(repo_root / ".reins" / "journal.jsonl")
    projection = TaskContextProjection()
    task_manager = TaskManager(journal, projection, run_id="fixture-run")
    task_id = await task_manager.create_task(
        title="Fixture task",
        task_type="backend",
        prd_content="Exercise MCP orchestration fixture.",
        acceptance_criteria=["MCP session exists"],
        created_by="test",
        assignee="tester",
    )
    exporter = TaskExporter(projection, repo_root / ".reins" / "tasks")
    exporter.export_task(task_id)
    exporter.set_current_task(task_id)

    worktree_manager = WorktreeManager(
        journal=journal,
        run_id="fixture-run",
        repo_root=repo_root,
    )
    context_hook = ContextInjectionHook(
        repo_root=repo_root,
        journal=journal,
        context_compiler=ContextCompiler(token_budget=2_000),
    )
    agent_registry = AgentRegistry(repo_root=repo_root, journal=journal)
    mcp_manager = OrchestrationMCPSessionManager(repo_root, journal, McpSessionManager())
    subagent_manager = SubagentManager(
        repo_root=repo_root,
        journal=journal,
        worktree_manager=worktree_manager,
        context_hook=context_hook,
        agent_registry=agent_registry,
        mcp_session_manager=mcp_manager,
    )
    return journal, subagent_manager, mcp_manager, task_id


@pytest.mark.asyncio
async def test_end_to_end_session_lifecycle_with_real_base_manager(tmp_path: Path) -> None:
    _prepare_repo(tmp_path)
    journal = EventJournal(tmp_path / "journal.jsonl")
    base_manager = McpSessionManager()
    transport = FakeTransport("codex")

    with patch("reins.execution.mcp.session.create_transport", return_value=transport):
        manager = OrchestrationMCPSessionManager(tmp_path, journal, base_manager)
        session_id = await manager.create_session(
            "agent-1",
            "task-1",
            "run-life",
            [
                {
                    "server_id": "codex",
                    "endpoint": "http://codex",
                    "tools": [{"name": "plan", "input_schema": {}}],
                }
            ],
        )
        result = await manager.invoke_tool(session_id, "codex", "plan", {}, run_id="run-life")
        await manager.close_session(session_id, run_id="run-life")

    assert result["status"] == "success"
    assert len(base_manager.audit_log) == 1
    assert base_manager.active_servers == []
    events = await load_run_events(journal, "run-life")
    assert_event_types_in_order(
        events,
        ["mcp.session_created", "mcp.tool_invoked", "mcp.session_closed"],
    )


@pytest.mark.asyncio
async def test_multiple_concurrent_sessions_do_not_collide_on_logical_server_ids(
    tmp_path: Path,
) -> None:
    _prepare_repo(tmp_path, "task-1")
    _prepare_repo(tmp_path, "task-2")
    journal = EventJournal(tmp_path / "journal.jsonl")
    base_manager = McpSessionManager()
    transports = {
        "http://codex-a": FakeTransport("codex-a"),
        "http://codex-b": FakeTransport("codex-b"),
    }

    def factory(endpoint: str) -> FakeTransport:
        return transports[endpoint]

    with patch("reins.execution.mcp.session.create_transport", side_effect=factory):
        manager = OrchestrationMCPSessionManager(tmp_path, journal, base_manager)
        session_a = await manager.create_session(
            "agent-a",
            "task-1",
            "run-a",
            [{"server_id": "codex", "endpoint": "http://codex-a", "tools": []}],
        )
        session_b = await manager.create_session(
            "agent-b",
            "task-2",
            "run-b",
            [{"server_id": "codex", "endpoint": "http://codex-b", "tools": []}],
        )

        result_a = await manager.invoke_tool(session_a, "codex", "plan", {}, run_id="run-a")
        result_b = await manager.invoke_tool(session_b, "codex", "plan", {}, run_id="run-b")
        await manager.close_session(session_a, run_id="run-a")

    assert result_a["result"]["transport"] == "codex-a"
    assert result_b["result"]["transport"] == "codex-b"
    assert len(base_manager.active_servers) == 1
    session_b_info = manager.get_session_info(session_b)
    assert session_b_info is not None
    assert session_b_info["active"] is True


@pytest.mark.asyncio
async def test_convenience_methods_create_expected_sessions(tmp_path: Path) -> None:
    _prepare_repo(tmp_path)
    journal = EventJournal(tmp_path / "journal.jsonl")
    base_manager = McpSessionManager()
    transports = [FakeTransport("codex"), FakeTransport("gitnexus"), FakeTransport("abcoder")]

    with patch(
        "reins.execution.mcp.session.create_transport",
        side_effect=transports,
    ):
        manager = OrchestrationMCPSessionManager(tmp_path, journal, base_manager)
        codex_session = await manager.create_codex_session(
            "agent-codex",
            "task-1",
            "run-codex",
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

    assert manager.get_session_info(codex_session)["server_ids"] == ["codex"]
    assert (
        manager.get_session_info(git_session)["servers"][0]["endpoint"]
        == "stdio://gitnexus --repo /tmp/repo"
    )
    assert (
        manager.get_session_info(abc_session)["servers"][0]["endpoint"]
        == "stdio://abcoder --repo reins"
    )


@pytest.mark.asyncio
async def test_subagent_manager_creates_and_cleans_up_mcp_session(tmp_path: Path) -> None:
    journal, subagent_manager, mcp_manager, task_id = await _build_subagent_fixture(tmp_path)
    transport = FakeTransport("codex")

    with patch("reins.execution.mcp.session.create_transport", return_value=transport):
        handle = await subagent_manager.create_subagent(
            agent_type="implement",
            task_id=task_id,
            run_id="run-subagent",
            use_worktree=False,
            mcp_servers=[
                {
                    "server_id": "codex",
                    "endpoint": "http://codex",
                    "tools": [{"name": "plan", "input_schema": {}}],
                }
            ],
        )
        assert handle.mcp_session_id is not None
        assert len(mcp_manager.list_active_sessions()) == 1

        await subagent_manager.cleanup(handle, remove_worktree=False)

    session_info = mcp_manager.get_session_info(handle.mcp_session_id)
    assert session_info is not None
    assert session_info["active"] is False
    events = await load_run_events(journal, "run-subagent")
    assert_event_types_in_order(
        events,
        ["mcp.session_created", "orchestrator.subagent_spawned", "mcp.session_closed"],
    )


@pytest.mark.asyncio
async def test_subagent_failure_closes_mcp_session(tmp_path: Path) -> None:
    journal, subagent_manager, mcp_manager, task_id = await _build_subagent_fixture(tmp_path)
    transport = FakeTransport("codex")

    with patch("reins.execution.mcp.session.create_transport", return_value=transport):
        handle = await subagent_manager.create_subagent(
            agent_type="implement",
            task_id=task_id,
            run_id="run-failure",
            use_worktree=False,
            mcp_servers=[
                {
                    "server_id": "codex",
                    "endpoint": "http://codex",
                    "tools": [{"name": "plan", "input_schema": {}}],
                }
            ],
        )
        result = await subagent_manager.handle_failure(handle, RuntimeError("boom"))

    assert result is not None
    assert result.status == "failed"
    session_info = mcp_manager.get_session_info(handle.mcp_session_id)
    assert session_info is not None
    assert session_info["active"] is False
    events = await load_run_events(journal, "run-failure")
    assert_event_types_in_order(
        events,
        ["mcp.session_created", "orchestrator.subagent_spawned", "mcp.session_closed"],
    )
