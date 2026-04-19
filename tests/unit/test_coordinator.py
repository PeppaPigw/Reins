from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from reins.kernel.event.journal import EventJournal
from reins.orchestration.coordinator import PipelineCoordinator, StageExecutionOutcome
from reins.orchestration.pipeline import Pipeline, PipelineStage, StageType
from reins.orchestration.types import PipelineStatus, StageStatus


def test_build_dependency_graph(tmp_path: Path) -> None:
    pipeline = Pipeline(
        name="graph",
        description="graph test",
        stages=[
            PipelineStage(
                name="research",
                type=StageType.RESEARCH,
                agent_type="research",
                prompt_template="research",
            ),
            PipelineStage(
                name="implement",
                type=StageType.IMPLEMENT,
                agent_type="implement",
                prompt_template="implement",
                depends_on=["research"],
            ),
        ],
    )
    coordinator = PipelineCoordinator(
        pipeline=pipeline,
        task_dir=tmp_path,
        event_journal=EventJournal(tmp_path / "journal.jsonl"),
    )

    graph = coordinator._build_dependency_graph()

    assert set(graph.nodes) == {"research", "implement"}
    assert graph.nodes["implement"].dependencies == ["research"]
    assert ("research", "implement") in graph.edges


@pytest.mark.asyncio
async def test_execute_retries_failed_stage_then_succeeds(tmp_path: Path) -> None:
    attempts: dict[str, int] = {"research": 0}
    sleeps: list[float] = []

    async def runner(stage: PipelineStage, prompt: str, task_dir: Path) -> StageExecutionOutcome:
        assert prompt
        assert task_dir == tmp_path
        attempts[stage.name] += 1
        if attempts[stage.name] == 1:
            raise RuntimeError("temporary failure")
        return StageExecutionOutcome(output=f"{stage.name} ok")

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    pipeline = Pipeline(
        name="retry",
        description="retry test",
        stages=[
            PipelineStage(
                name="research",
                type=StageType.RESEARCH,
                agent_type="research",
                prompt_template="Research {task_goal}",
                max_retries=1,
            )
        ],
    )
    coordinator = PipelineCoordinator(
        pipeline=pipeline,
        task_dir=tmp_path,
        event_journal=EventJournal(tmp_path / "journal.jsonl"),
        variables={"task_goal": "auth"},
        stage_runner=runner,
        sleep_fn=fake_sleep,
        retry_backoff_seconds=0.5,
    )

    result = await coordinator.execute()

    assert result.status is PipelineStatus.COMPLETED
    assert result.success is True
    assert result.stage_results[0].attempts == 2
    assert attempts["research"] == 2
    assert sleeps == [0.5]


@pytest.mark.asyncio
async def test_execute_skips_dependents_after_failure(tmp_path: Path) -> None:
    async def runner(stage: PipelineStage, prompt: str, task_dir: Path) -> StageExecutionOutcome:
        if stage.name == "research":
            raise RuntimeError("boom")
        return StageExecutionOutcome(output=stage.name)

    pipeline = Pipeline(
        name="failure",
        description="failure test",
        stages=[
            PipelineStage(
                name="research",
                type=StageType.RESEARCH,
                agent_type="research",
                prompt_template="research",
                retry_on_failure=False,
                max_retries=0,
            ),
            PipelineStage(
                name="implement",
                type=StageType.IMPLEMENT,
                agent_type="implement",
                prompt_template="implement",
                depends_on=["research"],
            ),
        ],
    )
    coordinator = PipelineCoordinator(
        pipeline=pipeline,
        task_dir=tmp_path,
        event_journal=EventJournal(tmp_path / "journal.jsonl"),
        stage_runner=runner,
    )

    result = await coordinator.execute()

    assert result.status is PipelineStatus.FAILED
    assert {stage.stage_name: stage.status for stage in result.stage_results} == {
        "research": StageStatus.FAILED,
        "implement": StageStatus.SKIPPED,
    }


@pytest.mark.asyncio
async def test_execute_cancels_active_stages(tmp_path: Path) -> None:
    started = asyncio.Event()

    async def runner(stage: PipelineStage, prompt: str, task_dir: Path) -> StageExecutionOutcome:
        started.set()
        await asyncio.sleep(5)
        return StageExecutionOutcome(output=stage.name)

    pipeline = Pipeline(
        name="cancel",
        description="cancel test",
        stages=[
            PipelineStage(
                name="research",
                type=StageType.RESEARCH,
                agent_type="research",
                prompt_template="research",
            )
        ],
    )
    coordinator = PipelineCoordinator(
        pipeline=pipeline,
        task_dir=tmp_path,
        event_journal=EventJournal(tmp_path / "journal.jsonl"),
        stage_runner=runner,
    )

    execution_task = asyncio.create_task(coordinator.execute())
    await started.wait()
    await coordinator.cancel()
    result = await execution_task

    assert result.status is PipelineStatus.CANCELLED
    assert result.stage_results[0].status is StageStatus.CANCELLED
