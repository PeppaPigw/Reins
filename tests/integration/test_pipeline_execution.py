from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from reins.kernel.event.journal import EventJournal
from reins.orchestration.coordinator import PipelineCoordinator, StageExecutionOutcome
from reins.orchestration.pipeline import Pipeline, PipelineStage, StageType
from reins.orchestration.types import PipelineStatus


@pytest.mark.asyncio
async def test_pipeline_execution_runs_independent_stages_in_parallel(tmp_path: Path) -> None:
    starts: dict[str, float] = {}
    finishes: dict[str, float] = {}

    async def runner(stage: PipelineStage, prompt: str, task_dir: Path) -> StageExecutionOutcome:
        starts[stage.name] = time.monotonic()
        await asyncio.sleep(0.2 if stage.name != "implement" else 0.01)
        finishes[stage.name] = time.monotonic()
        return StageExecutionOutcome(output=f"{stage.name}:{prompt}")

    pipeline = Pipeline(
        name="parallel",
        description="parallel execution",
        stages=[
            PipelineStage(
                name="research-a",
                type=StageType.RESEARCH,
                agent_type="research",
                prompt_template="A {task_goal}",
            ),
            PipelineStage(
                name="research-b",
                type=StageType.RESEARCH,
                agent_type="research",
                prompt_template="B {task_goal}",
            ),
            PipelineStage(
                name="implement",
                type=StageType.IMPLEMENT,
                agent_type="implement",
                prompt_template="I {task_goal}",
                depends_on=["research-a", "research-b"],
            ),
        ],
    )
    journal = EventJournal(tmp_path / "journal")
    coordinator = PipelineCoordinator(
        pipeline=pipeline,
        task_dir=tmp_path,
        event_journal=journal,
        variables={"task_goal": "phase3"},
        stage_runner=runner,
    )

    started_at = time.monotonic()
    result = await coordinator.execute()
    elapsed = time.monotonic() - started_at

    assert result.status is PipelineStatus.COMPLETED
    assert elapsed < 0.35
    assert abs(starts["research-a"] - starts["research-b"]) < 0.05
    assert starts["implement"] >= finishes["research-a"]
    assert starts["implement"] >= finishes["research-b"]

    event_types = [event.type async for event in journal.read_from(result.pipeline_id or "")]
    assert event_types[0] == "pipeline.started"
    assert "pipeline.stage.started" in event_types
    assert event_types[-1] == "pipeline.completed"
