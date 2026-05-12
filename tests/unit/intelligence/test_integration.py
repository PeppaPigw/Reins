from __future__ import annotations

from pathlib import Path

import pytest

from reins.intelligence.factory import create_intelligence_advisor


@pytest.fixture
def advisor(tmp_path: Path):
    return create_intelligence_advisor(tmp_path / "intel")


async def test_advisor_on_intake(advisor) -> None:
    result = await advisor.on_intake(
        "add new endpoint for user profiles",
        {"domain": "backend"},
    )
    assert "dag_proposal" in result
    assert result["dag_proposal"]["node_count"] >= 1
    assert result["dag_proposal"]["objective"] == "add new endpoint for user profiles"


async def test_advisor_on_before_route(advisor) -> None:
    result = await advisor.on_before_route({"domain": "testing", "risk_tier": "T1"})
    assert "strategy" in result
    assert "trust_level" in result
    assert result["trust_level"] == "supervised"


async def test_advisor_on_repair_required(advisor) -> None:
    result = await advisor.on_repair_required(
        failure={"error": "timeout"},
        context={"task_id": "task-1", "domain": "testing"},
    )
    assert "failure_class" in result
    assert "action" in result
    assert result["action"] != ""


async def test_advisor_full_lifecycle(advisor) -> None:
    await advisor.on_intake("add test for auth", {"domain": "testing"})

    route_advice = await advisor.on_before_route({"domain": "testing", "risk_tier": "T1"})
    assert route_advice["requires_approval"] is True

    await advisor.on_after_execution("task-1", "testing", success=True, context={})
    await advisor.on_complete("task-1", "testing")

    route_advice2 = await advisor.on_before_route({"domain": "testing", "risk_tier": "T1"})
    assert "strategy" in route_advice2


async def test_advisor_trust_builds_over_time(advisor) -> None:
    for i in range(6):
        await advisor.on_after_execution(f"task-{i}", "testing", success=True, context={})

    route_advice = await advisor.on_before_route({"domain": "testing", "risk_tier": "T1"})
    assert route_advice["trust_level"] == "semi_auto"
    assert route_advice["requires_approval"] is False
