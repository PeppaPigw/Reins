"""Pipeline coordination with dependency-aware parallel execution."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

import ulid

from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.journal import EventJournal
from reins.orchestration.pipeline import Pipeline, PipelineStage, validate_pipeline
from reins.orchestration.types import PipelineResult, PipelineStatus, StageResult, StageStatus
from reins.workflow.graph import NodeType, WorkflowGraph, WorkflowNode


@dataclass(frozen=True)
class StageExecutionOutcome:
    """Raw execution payload returned by a stage runner."""

    output: str
    artifacts: list[Path] = field(default_factory=list)


StageRunner = Callable[[PipelineStage, str, Path], Awaitable[StageExecutionOutcome]]
SleepFn = Callable[[float], Awaitable[None]]


class PipelineCoordinator:
    """Coordinates parallel stage execution with dependency tracking."""

    def __init__(
        self,
        pipeline: Pipeline,
        task_dir: Path,
        event_journal: EventJournal,
        *,
        pipeline_id: str | None = None,
        variables: Mapping[str, Any] | None = None,
        stage_runner: StageRunner | None = None,
        sleep_fn: SleepFn | None = None,
        retry_backoff_seconds: float = 0.1,
        max_parallel_stages: int | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.task_dir = task_dir
        self.journal = event_journal
        self.pipeline_id = pipeline_id or f"pipeline-{ulid.new()}"
        self.variables = dict(variables or {})
        self.stage_runner = stage_runner or self._default_stage_runner
        self.sleep_fn = sleep_fn or asyncio.sleep
        self.retry_backoff_seconds = retry_backoff_seconds
        self.max_parallel_stages = max_parallel_stages

        self.stage_results: dict[str, StageResult] = {}
        self.stage_status: dict[str, StageStatus] = {
            stage.name: StageStatus.PENDING for stage in pipeline.stages
        }
        self._event_builder = EventBuilder(event_journal)
        self._active_tasks: dict[str, asyncio.Task[StageResult]] = {}
        self._pipeline_started_at: float | None = None
        self._cancel_requested = False
        self._graph: WorkflowGraph | None = None

    async def execute(self) -> PipelineResult:
        """Execute the pipeline, running independent stages in parallel."""
        errors = validate_pipeline(self.pipeline)
        if errors:
            raise ValueError("; ".join(errors))
        if self.max_parallel_stages is not None and self.max_parallel_stages <= 0:
            raise ValueError("max_parallel_stages must be greater than zero when provided.")

        self._pipeline_started_at = time.monotonic()
        self._graph = self._build_dependency_graph()
        await self._event_builder.commit(
            run_id=self.pipeline_id,
            event_type="pipeline.started",
            payload={
                "pipeline_id": self.pipeline_id,
                "pipeline_name": self.pipeline.name,
                "task_dir": str(self.task_dir),
                "stage_count": len(self.pipeline.stages),
            },
        )

        try:
            while True:
                await self._skip_unrunnable_stages()
                self._launch_ready_stages()

                if not self._active_tasks:
                    break

                done, _ = await asyncio.wait(
                    list(self._active_tasks.values()),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for finished_task in done:
                    stage_name = self._stage_name_for_task(finished_task)
                    del self._active_tasks[stage_name]
                    result = await finished_task
                    self.stage_results[stage_name] = result
                    self.stage_status[stage_name] = result.status

            pipeline_result = self._aggregate_results()
            event_type = {
                PipelineStatus.COMPLETED: "pipeline.completed",
                PipelineStatus.FAILED: "pipeline.failed",
                PipelineStatus.CANCELLED: "pipeline.cancelled",
                PipelineStatus.PENDING: "pipeline.completed",
                PipelineStatus.RUNNING: "pipeline.completed",
            }[pipeline_result.status]
            await self._event_builder.commit(
                run_id=self.pipeline_id,
                event_type=event_type,
                payload={
                    "pipeline_id": self.pipeline_id,
                    "pipeline_name": self.pipeline.name,
                    "status": pipeline_result.status.value,
                    "total_duration_seconds": pipeline_result.total_duration_seconds,
                    "success": pipeline_result.success,
                },
            )
            return pipeline_result
        except asyncio.CancelledError:
            self._cancel_requested = True
            await self.cancel()
            raise

    async def cancel(self) -> None:
        """Cancel any active stage execution."""
        self._cancel_requested = True
        for task in list(self._active_tasks.values()):
            task.cancel()

    def _build_dependency_graph(self) -> WorkflowGraph:
        """Build a workflow graph from the pipeline definition."""
        graph = WorkflowGraph(graph_id=self.pipeline_id)
        for stage in self.pipeline.stages:
            graph.nodes[stage.name] = WorkflowNode(
                node_id=stage.name,
                node_type=NodeType.TASK,
                name=stage.name,
                dependencies=list(stage.depends_on),
                metadata={
                    "stage_type": stage.type.value,
                    "agent_type": stage.agent_type,
                },
            )
            for dependency in stage.depends_on:
                graph.edges.append((dependency, stage.name))
        return graph

    async def _execute_stage(self, stage: PipelineStage) -> StageResult:
        """Execute a single stage with retry handling."""
        attempts = 0
        started_at = time.monotonic()

        while True:
            attempts += 1
            self.stage_status[stage.name] = StageStatus.RUNNING
            await self._event_builder.commit(
                run_id=self.pipeline_id,
                event_type="pipeline.stage.started",
                payload={
                    "pipeline_id": self.pipeline_id,
                    "pipeline_name": self.pipeline.name,
                    "stage_name": stage.name,
                    "stage_type": stage.type.value,
                    "agent_type": stage.agent_type,
                    "attempt": attempts,
                    "depends_on": list(stage.depends_on),
                },
            )
            try:
                prompt = stage.render_prompt(self._stage_variables())
                outcome = await self.stage_runner(stage, prompt, self.task_dir)
                result = StageResult(
                    stage_name=stage.name,
                    status=StageStatus.COMPLETED,
                    output=outcome.output,
                    artifacts=list(outcome.artifacts),
                    duration_seconds=time.monotonic() - started_at,
                    attempts=attempts,
                )
                await self._event_builder.commit(
                    run_id=self.pipeline_id,
                    event_type="pipeline.stage.completed",
                    payload={
                        "pipeline_id": self.pipeline_id,
                        "pipeline_name": self.pipeline.name,
                        "stage_name": stage.name,
                        "attempts": attempts,
                        "duration_seconds": result.duration_seconds,
                        "artifacts": [str(path) for path in outcome.artifacts],
                    },
                )
                return result
            except asyncio.CancelledError:
                duration = time.monotonic() - started_at
                result = StageResult(
                    stage_name=stage.name,
                    status=StageStatus.CANCELLED,
                    output="",
                    artifacts=[],
                    duration_seconds=duration,
                    error="Cancelled",
                    attempts=attempts,
                )
                await self._event_builder.commit(
                    run_id=self.pipeline_id,
                    event_type="pipeline.stage.cancelled",
                    payload={
                        "pipeline_id": self.pipeline_id,
                        "pipeline_name": self.pipeline.name,
                        "stage_name": stage.name,
                        "attempts": attempts,
                        "duration_seconds": duration,
                    },
                )
                return result
            except Exception as error:
                failure_result = await self._handle_stage_failure(
                    stage=stage,
                    error=error,
                    attempts=attempts,
                    started_at=started_at,
                )
                if failure_result is not None:
                    return failure_result

    def _aggregate_results(self) -> PipelineResult:
        """Aggregate all stage results into a pipeline result."""
        total_duration = 0.0
        if self._pipeline_started_at is not None:
            total_duration = time.monotonic() - self._pipeline_started_at

        ordered_results = [
            self.stage_results.get(stage.name)
            for stage in self.pipeline.stages
            if stage.name in self.stage_results
        ]
        results = [result for result in ordered_results if result is not None]

        if self._cancel_requested or any(
            result.status is StageStatus.CANCELLED for result in results
        ):
            status = PipelineStatus.CANCELLED
        elif any(result.status is StageStatus.FAILED for result in results):
            status = PipelineStatus.FAILED
        elif any(result.status is StageStatus.SKIPPED for result in results):
            status = PipelineStatus.FAILED
        else:
            status = PipelineStatus.COMPLETED

        pipeline_result = PipelineResult(
            pipeline_name=self.pipeline.name,
            status=status,
            stage_results=results,
            total_duration_seconds=total_duration,
            success=status is PipelineStatus.COMPLETED,
            pipeline_id=self.pipeline_id,
        )

        return pipeline_result

    async def _handle_stage_failure(
        self,
        stage: PipelineStage,
        error: Exception,
        *,
        attempts: int,
        started_at: float,
    ) -> StageResult | None:
        """Handle stage failure with retry/backoff logic."""
        if stage.retry_on_failure and attempts <= stage.max_retries:
            backoff = self.retry_backoff_seconds * (2 ** (attempts - 1))
            await self._event_builder.commit(
                run_id=self.pipeline_id,
                event_type="pipeline.stage.retrying",
                payload={
                    "pipeline_id": self.pipeline_id,
                    "pipeline_name": self.pipeline.name,
                    "stage_name": stage.name,
                    "attempt": attempts,
                    "max_retries": stage.max_retries,
                    "backoff_seconds": backoff,
                    "error": str(error),
                },
            )
            await self.sleep_fn(backoff)
            return None

        duration = time.monotonic() - started_at
        result = StageResult(
            stage_name=stage.name,
            status=StageStatus.FAILED,
            output="",
            artifacts=[],
            duration_seconds=duration,
            error=str(error),
            attempts=attempts,
        )
        await self._event_builder.commit(
            run_id=self.pipeline_id,
            event_type="pipeline.stage.failed",
            payload={
                "pipeline_id": self.pipeline_id,
                "pipeline_name": self.pipeline.name,
                "stage_name": stage.name,
                "attempts": attempts,
                "duration_seconds": duration,
                "error": str(error),
            },
        )
        return result

    def _launch_ready_stages(self) -> None:
        remaining_slots = None
        if self.max_parallel_stages is not None:
            remaining_slots = self.max_parallel_stages - len(self._active_tasks)
            if remaining_slots <= 0:
                return

        for stage in self.pipeline.stages:
            if stage.name in self._active_tasks:
                continue
            if self.stage_status[stage.name] is not StageStatus.PENDING:
                continue
            if not self._dependencies_completed(stage):
                continue
            self._active_tasks[stage.name] = asyncio.create_task(self._execute_stage(stage))
            if remaining_slots is not None:
                remaining_slots -= 1
                if remaining_slots <= 0:
                    return

    async def _skip_unrunnable_stages(self) -> None:
        for stage in self.pipeline.stages:
            if self.stage_status[stage.name] is not StageStatus.PENDING:
                continue
            failed_dependencies = [
                dependency
                for dependency in stage.depends_on
                if self.stage_status.get(dependency)
                in {StageStatus.FAILED, StageStatus.SKIPPED, StageStatus.CANCELLED}
            ]
            if not failed_dependencies:
                continue

            reason = (
                "Blocked by failed dependency: " + ", ".join(sorted(failed_dependencies))
            )
            result = StageResult(
                stage_name=stage.name,
                status=StageStatus.SKIPPED,
                output="",
                artifacts=[],
                duration_seconds=0.0,
                error=reason,
                attempts=0,
            )
            self.stage_results[stage.name] = result
            self.stage_status[stage.name] = StageStatus.SKIPPED
            await self._event_builder.commit(
                run_id=self.pipeline_id,
                event_type="pipeline.stage.skipped",
                payload={
                    "pipeline_id": self.pipeline_id,
                    "pipeline_name": self.pipeline.name,
                    "stage_name": stage.name,
                    "reason": reason,
                },
            )

    def _dependencies_completed(self, stage: PipelineStage) -> bool:
        return all(
            self.stage_status.get(dependency) is StageStatus.COMPLETED
            for dependency in stage.depends_on
        )

    def _stage_name_for_task(self, task: asyncio.Task[StageResult]) -> str:
        for stage_name, active_task in self._active_tasks.items():
            if active_task is task:
                return stage_name
        raise KeyError("Active stage task not found")

    def _stage_variables(self) -> dict[str, Any]:
        variables = dict(self.variables)
        variables.setdefault("pipeline_name", self.pipeline.name)
        variables.setdefault("pipeline_id", self.pipeline_id)
        variables.setdefault("task_dir", str(self.task_dir))
        return variables

    async def _default_stage_runner(
        self,
        stage: PipelineStage,
        prompt: str,
        task_dir: Path,
    ) -> StageExecutionOutcome:
        """Fallback runner used when no orchestration runtime is injected."""
        output = "\n".join(
            [
                f"stage={stage.name}",
                f"agent_type={stage.agent_type}",
                f"task_dir={task_dir}",
                "",
                prompt,
            ]
        )
        return StageExecutionOutcome(output=output, artifacts=[])
