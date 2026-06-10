from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from reins.coordination import (
    AgentNode,
    ConflictResolution,
    CoordinationMessage,
    CoordinationProtocol,
    MessageType,
    NodeRegistry,
    NodeStatus,
    ResolutionStrategy,
    RoutingStrategy,
    TaskRouter,
    TaskAssignment,
)


def test_coordination_message_checksum_is_stable_and_verifiable() -> None:
    sent_at = datetime(2026, 5, 15, tzinfo=UTC)
    first = CoordinationMessage(
        message_id="message-1",
        source_node_id="source",
        target_node_id="target",
        message_type=MessageType.TASK_ASSIGN,
        payload={"b": 2, "a": 1},
        timestamp=sent_at,
    )
    second = CoordinationMessage(
        message_id="message-1",
        source_node_id="source",
        target_node_id="target",
        message_type=MessageType.TASK_ASSIGN,
        payload={"a": 1, "b": 2},
        timestamp=sent_at,
    )

    assert first.checksum == second.checksum
    assert first.verify_checksum() is True
    assert first.checksum == first.compute_checksum()


@pytest.mark.asyncio
async def test_node_registry_replays_jsonl_events(tmp_path: Path) -> None:
    journal_path = tmp_path / "nodes.jsonl"
    registry = NodeRegistry(journal_path)

    await registry.register_node(
        AgentNode(
            node_id="node-1",
            endpoint="https://node-1.example.test",
            capabilities=("python", "tests"),
            trust_score=0.8,
            max_concurrent_tasks=2,
        )
    )
    await registry.heartbeat(
        "node-1",
        status=NodeStatus.BUSY,
        current_load=1,
        current_task_id="task-1",
    )
    await registry.update_status("node-1", NodeStatus.BUSY)

    reopened = NodeRegistry(journal_path)
    replayed = await reopened.get_node("node-1")

    assert replayed is not None
    assert replayed.status is NodeStatus.BUSY
    assert replayed.current_load == 1
    assert replayed.current_task_id == "task-1"

    event_types = [
        json.loads(line)["type"]
        for line in journal_path.read_text(encoding="utf-8").splitlines()
    ]
    assert event_types == [
        "node.registered",
        "node.heartbeat",
        "node.status_changed",
    ]


@pytest.mark.asyncio
async def test_task_router_scores_capabilities_trust_load_and_success() -> None:
    router = TaskRouter()
    task = TaskAssignment(
        task_id="task-1",
        objective="run Python tests",
        required_capabilities=("python", "tests"),
    )
    selected = await router.route_task(
        [
            AgentNode(
                node_id="node-low",
                endpoint="https://node-low.example.test",
                capabilities=("python",),
                trust_score=0.9,
                max_concurrent_tasks=2,
                completed_tasks=1,
                failed_tasks=3,
            ),
            AgentNode(
                node_id="node-high",
                endpoint="https://node-high.example.test",
                capabilities=("python", "tests"),
                trust_score=0.8,
                max_concurrent_tasks=4,
                current_load=0,
                completed_tasks=9,
                failed_tasks=1,
            ),
        ],
        task=task,
        strategy=RoutingStrategy.CAPABILITY_MATCH,
    )

    assert selected is not None
    assert selected.node_id == "node-high"


@pytest.mark.asyncio
async def test_protocol_assigns_task_and_falls_back_after_failure(tmp_path: Path) -> None:
    protocol = CoordinationProtocol(NodeRegistry(tmp_path / "nodes.jsonl"))
    await protocol.register_node(
        AgentNode(
            node_id="primary",
            endpoint="https://primary.example.test",
            capabilities=("python",),
            trust_score=0.9,
            max_concurrent_tasks=2,
        )
    )
    await protocol.register_node(
        AgentNode(
            node_id="fallback",
            endpoint="https://fallback.example.test",
            capabilities=("python",),
            trust_score=0.7,
            max_concurrent_tasks=2,
        )
    )

    assigned_node_id = await protocol.assign_task(
        TaskAssignment(
            task_id="task-1",
            objective="implement feature",
            required_capabilities=("python",),
            fallback_nodes=("fallback",),
        )
    )
    assert assigned_node_id == "primary"

    await protocol.report_failure("task-1", {"error": "lost connection"})

    reassigned = await protocol.get_task("task-1")
    assert reassigned is not None
    assert reassigned.assigned_node_id == "fallback"
    assert reassigned.attempts == 2

    primary = await protocol.registry.get_node("primary")
    assert primary is not None
    assert primary.failed_tasks == 1


@pytest.mark.asyncio
async def test_protocol_marks_stale_nodes_offline(tmp_path: Path) -> None:
    registry = NodeRegistry(tmp_path / "nodes.jsonl")
    protocol = CoordinationProtocol(registry, heartbeat_timeout=timedelta(seconds=30))
    stale_at = datetime.now(UTC) - timedelta(minutes=10)

    await registry.register_node(
        AgentNode(
            node_id="stale",
            endpoint="https://stale.example.test",
            capabilities=("python",),
            last_heartbeat=stale_at,
        )
    )

    stale_nodes = await protocol.detect_stale_nodes()

    assert [node.node_id for node in stale_nodes] == ["stale"]
    node = await registry.get_node("stale")
    assert node is not None
    assert node.status is NodeStatus.OFFLINE


@pytest.mark.asyncio
async def test_query_capabilities_and_consensus(tmp_path: Path) -> None:
    protocol = CoordinationProtocol(NodeRegistry(tmp_path / "nodes.jsonl"))
    await protocol.register_node(
        AgentNode(
            node_id="node-1",
            endpoint="https://node-1.example.test",
            capabilities=("python", "tests"),
        )
    )
    await protocol.register_node(
        AgentNode(
            node_id="node-2",
            endpoint="https://node-2.example.test",
            capabilities=("docs",),
        )
    )

    python_nodes = await protocol.query_capabilities(["python"])
    consensus = await protocol.request_consensus(
        {"change": "rebalance"},
        ["node-1", "node-2"],
    )

    assert [node.node_id for node in python_nodes] == ["node-1"]
    assert consensus is True


@pytest.mark.asyncio
async def test_conflict_resolution_uses_last_writer(tmp_path: Path) -> None:
    protocol = CoordinationProtocol(NodeRegistry(tmp_path / "nodes.jsonl"))
    older = datetime(2026, 5, 15, 1, tzinfo=UTC)
    newer = datetime(2026, 5, 15, 2, tzinfo=UTC)
    await protocol.register_node(
        AgentNode(
            node_id="node-old",
            endpoint="https://node-old.example.test",
            last_heartbeat=older,
        )
    )
    await protocol.register_node(
        AgentNode(
            node_id="node-new",
            endpoint="https://node-new.example.test",
            last_heartbeat=newer,
        )
    )

    result = await protocol.resolve_conflict(
        ConflictResolution(
            conflicting_nodes=("node-old", "node-new"),
            resource_path="src/reins/example.py",
            resolution_strategy=ResolutionStrategy.LAST_WRITER_WINS,
        )
    )

    assert result["status"] == "resolved"
    assert result["resolved_by"] == "node-new"
