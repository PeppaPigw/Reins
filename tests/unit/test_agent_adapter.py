from __future__ import annotations

from pathlib import Path

import pytest

from reins.execution.agent_adapter import (
    AgentExecutionAdapter,
    AgentExecutionRequest,
    AgentExecutionResult,
)


class StubAgentExecutionAdapter(AgentExecutionAdapter):
    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        return AgentExecutionResult(
            success=True,
            output=f"executed:{request.agent_type}",
            artifacts=[request.task_dir / "artifact.txt"],
            exit_code=0,
        )

    def supports_agent_type(self, agent_type: str) -> bool:
        return agent_type == "stub"


def test_agent_execution_request_preserves_fields(tmp_path: Path) -> None:
    request = AgentExecutionRequest(
        agent_type="stub",
        prompt="run checks",
        context={"stage": "research", "attempt": 1},
        task_dir=tmp_path,
        model="gpt-test",
    )

    assert request.agent_type == "stub"
    assert request.prompt == "run checks"
    assert request.context == {"stage": "research", "attempt": 1}
    assert request.task_dir == tmp_path
    assert request.model == "gpt-test"


def test_agent_execution_result_defaults_are_optional(tmp_path: Path) -> None:
    result = AgentExecutionResult(
        success=False,
        output="",
        artifacts=[tmp_path / "artifact.txt"],
        error="execution failed",
    )

    assert result.success is False
    assert result.output == ""
    assert result.artifacts == [tmp_path / "artifact.txt"]
    assert result.error == "execution failed"
    assert result.exit_code is None


@pytest.mark.asyncio
async def test_agent_execution_adapter_contract(tmp_path: Path) -> None:
    adapter = StubAgentExecutionAdapter()
    request = AgentExecutionRequest(
        agent_type="stub",
        prompt="compile plan",
        context={"pipeline_stage": "implement"},
        task_dir=tmp_path,
    )

    result = await adapter.execute(request)

    assert adapter.supports_agent_type("stub") is True
    assert adapter.supports_agent_type("other") is False
    assert result.success is True
    assert result.output == "executed:stub"
    assert result.artifacts == [tmp_path / "artifact.txt"]
    assert result.error is None
    assert result.exit_code == 0
