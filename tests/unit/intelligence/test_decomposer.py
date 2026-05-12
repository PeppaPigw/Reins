from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from reins.intelligence.decomposer.planner import TaskDecomposer
from reins.intelligence.types import AssumptionStatus, DAGProposal, SubtaskNode


@pytest.fixture
def decomposer() -> TaskDecomposer:
    return TaskDecomposer()


async def test_trivial_task_single_node(decomposer: TaskDecomposer) -> None:
    dag = await decomposer.decompose("rename variable foo to bar", {})
    assert len(dag.nodes) == 1
    assert dag.nodes[0].estimated_complexity == "trivial"
    assert len(dag.edges) == 0


async def test_medium_task_produces_dag(decomposer: TaskDecomposer) -> None:
    dag = await decomposer.decompose("add new endpoint for user profiles", {})
    assert len(dag.nodes) == 3
    assert len(dag.edges) == 2
    assert dag.nodes[0].description.startswith("Research")
    assert dag.nodes[1].description.startswith("Implement")
    assert dag.nodes[2].description.startswith("Verify")


async def test_high_complexity_without_memory_triggers_checkpoint(
    decomposer: TaskDecomposer,
) -> None:
    dag = await decomposer.decompose(
        "redesign architecture for distributed processing",
        {"relevant_memories": []},
    )
    assert any(n.requires_checkpoint for n in dag.nodes)
    assert len(dag.assumptions) > 0
    assert dag.assumptions[0].status == AssumptionStatus.recorded


async def test_high_complexity_with_memory_no_checkpoint(
    decomposer: TaskDecomposer,
) -> None:
    dag = await decomposer.decompose(
        "redesign architecture for distributed processing",
        {"relevant_memories": ["past pattern: use event sourcing"]},
    )
    assert not any(n.requires_checkpoint for n in dag.nodes)


async def test_restructure_replaces_failed_node(decomposer: TaskDecomposer) -> None:
    dag = await decomposer.decompose("refactor auth module", {})
    failed_id = dag.nodes[1].task_id

    new_dag = await decomposer.restructure(dag, failed_id, {"error": "type error"})

    assert failed_id not in [n.task_id for n in new_dag.nodes]
    assert any("Investigate" in n.description for n in new_dag.nodes)
    assert any("Retry" in n.description for n in new_dag.nodes)


async def test_risk_estimation(decomposer: TaskDecomposer) -> None:
    dag = await decomposer.decompose("update security policy", {})
    assert any(n.risk_tier == "T3" for n in dag.nodes)

    dag2 = await decomposer.decompose("add test for utils", {})
    assert all(n.risk_tier == "T1" for n in dag2.nodes)
