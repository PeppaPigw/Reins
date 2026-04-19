"""High-level workflow execution and state persistence for pipelines."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ulid

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal
from reins.orchestration.coordinator import (
    PipelineCoordinator,
    StageExecutionOutcome,
)
from reins.orchestration.orchestrator import Orchestrator
from reins.orchestration.pipeline import Pipeline, load_pipeline_from_yaml
from reins.orchestration.types import PipelineResult, PipelineStatus, StageStatus


@dataclass(frozen=True)
class PipelineTimelineEntry:
    """Stage-level timeline entry derived from a pipeline result."""

    stage_name: str
    status: StageStatus
    duration_seconds: float
    summary: str
    error: str | None = None


@dataclass
class PipelineTimeline:
    """Lightweight timeline representation for pipeline execution."""

    pipeline_id: str | None
    pipeline_name: str
    status: PipelineStatus
    total_duration_seconds: float
    entries: list[PipelineTimelineEntry] = field(default_factory=list)


class WorkflowExecutor:
    """High-level workflow automation."""

    def __init__(
        self,
        orchestrator: Orchestrator,
        event_journal: EventJournal,
        *,
        repo_root: Path | None = None,
        max_parallel_stages: int | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.journal = event_journal
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self.max_parallel_stages = max_parallel_stages
        self._active_coordinators: dict[str, PipelineCoordinator] = {}

    async def run_pipeline(
        self,
        pipeline_name: str,
        task_dir: Path,
        variables: dict[str, str] | None = None,
    ) -> PipelineResult:
        """Run a named pipeline for a task."""
        pipeline = self._load_pipeline(pipeline_name)
        return await self.run_pipeline_definition(pipeline, task_dir, variables)

    async def run_pipeline_file(
        self,
        pipeline_path: Path,
        task_dir: Path,
        variables: dict[str, str] | None = None,
    ) -> PipelineResult:
        """Run a pipeline loaded from an explicit YAML file path."""
        pipeline = load_pipeline_from_yaml(pipeline_path)
        return await self.run_pipeline_definition(pipeline, task_dir, variables)

    async def run_pipeline_definition(
        self,
        pipeline: Pipeline,
        task_dir: Path,
        variables: dict[str, str] | None = None,
    ) -> PipelineResult:
        """Run an in-memory pipeline definition for a task."""
        task_dir = task_dir.resolve()
        task_dir.mkdir(parents=True, exist_ok=True)

        pipeline_id = f"pipeline-{ulid.new()}"
        state_path = task_dir / "pipeline-state.json"
        merged_variables = self._pipeline_variables(task_dir, variables)
        await self._write_state(
            state_path,
            self._initial_state_payload(
                pipeline_id=pipeline_id,
                pipeline=pipeline,
                task_dir=task_dir,
                variables=merged_variables,
            ),
        )

        stop_monitor = asyncio.Event()
        monitor_task = asyncio.create_task(
            self._monitor_pipeline_state(
                pipeline=pipeline,
                pipeline_id=pipeline_id,
                state_path=state_path,
                stop_event=stop_monitor,
            )
        )

        coordinator = PipelineCoordinator(
            pipeline=pipeline,
            task_dir=task_dir,
            event_journal=self.journal,
            pipeline_id=pipeline_id,
            variables=merged_variables,
            stage_runner=self._run_stage,
            max_parallel_stages=self.max_parallel_stages,
        )
        self._active_coordinators[pipeline_id] = coordinator

        try:
            result = await coordinator.execute()
        except Exception:
            stop_monitor.set()
            await monitor_task
            raise
        finally:
            self._active_coordinators.pop(pipeline_id, None)

        stop_monitor.set()
        await monitor_task
        current_state = self._load_state(state_path)
        await self._write_state(
            state_path,
            self._result_state_payload(
                result,
                task_dir,
                merged_variables,
                existing_state=current_state,
            ),
        )
        self._update_task_metadata(task_dir, result)
        return result

    def get_pipeline_status(self, pipeline_id: str) -> PipelineStatus:
        """Get current status of a running or persisted pipeline."""
        if pipeline_id in self._active_coordinators:
            coordinator = self._active_coordinators[pipeline_id]
            statuses = set(coordinator.stage_status.values())
            if any(status is StageStatus.FAILED for status in statuses):
                return PipelineStatus.FAILED
            if any(status is StageStatus.RUNNING for status in statuses):
                return PipelineStatus.RUNNING
            if any(status is StageStatus.CANCELLED for status in statuses):
                return PipelineStatus.CANCELLED
            return PipelineStatus.PENDING

        state_path = self._find_pipeline_state(pipeline_id)
        if state_path is None:
            raise FileNotFoundError(f"Pipeline state not found for {pipeline_id}")

        payload = json.loads(state_path.read_text(encoding="utf-8"))
        return PipelineStatus(payload["status"])

    async def cancel_pipeline(self, pipeline_id: str) -> bool:
        """Cancel a running pipeline."""
        coordinator = self._active_coordinators.get(pipeline_id)
        if coordinator is None:
            return False
        await coordinator.cancel()
        return True

    def list_pipelines(self) -> list[Pipeline]:
        """List all available pipeline definitions."""
        pipeline_dir = self.repo_root / ".reins" / "pipelines"
        if not pipeline_dir.exists():
            return []
        return [
            load_pipeline_from_yaml(path)
            for path in sorted(pipeline_dir.glob("*.yaml"))
        ]

    async def _run_stage(
        self,
        stage,
        prompt: str,
        task_dir: Path,
    ) -> StageExecutionOutcome:
        handle = await self.orchestrator.spawn_subagent(
            agent_type=stage.agent_type,
            context={
                "pipeline_stage": stage.name,
                "pipeline_stage_type": stage.type.value,
                "prompt": prompt,
                "task_dir": str(task_dir),
                "context_files": stage.context_files,
            },
        )
        if stage.model:
            handle.context["model"] = stage.model
        artifacts = [
            task_dir / relative_path
            for relative_path in stage.context_files
            if (task_dir / relative_path).exists()
        ]
        output = json.dumps(
            {
                "agent_id": handle.agent_id,
                "agent_type": handle.agent_type,
                "stage_name": stage.name,
                "model": stage.model,
                "prompt": prompt,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return StageExecutionOutcome(output=output, artifacts=artifacts)

    async def _monitor_pipeline_state(
        self,
        *,
        pipeline: Pipeline,
        pipeline_id: str,
        state_path: Path,
        stop_event: asyncio.Event,
    ) -> None:
        from_seq = 0
        while True:
            saw_event = False
            async for event in self.journal.read_from(pipeline_id, from_seq=from_seq):
                saw_event = True
                from_seq = max(from_seq, event.seq + 1)
                if not event.type.startswith("pipeline."):
                    continue
                state = self._load_state(state_path)
                self._apply_pipeline_event(state, pipeline, event)
                await self._write_state(state_path, state)
                if event.type in {"pipeline.completed", "pipeline.failed", "pipeline.cancelled"}:
                    stop_event.set()

            if stop_event.is_set():
                return
            if not saw_event:
                await asyncio.sleep(0.01)

    def _apply_pipeline_event(
        self,
        state: dict[str, Any],
        pipeline: Pipeline,
        event: EventEnvelope,
    ) -> None:
        state["updated_at"] = event.ts.isoformat()
        stages = state.setdefault("stages", {})

        if event.type == "pipeline.started":
            state["status"] = PipelineStatus.RUNNING.value
            state["started_at"] = event.ts.isoformat()
            return

        if event.type == "pipeline.stage.started":
            stage_name = str(event.payload["stage_name"])
            stage_state = stages.setdefault(stage_name, self._default_stage_state(pipeline, stage_name))
            stage_state["status"] = StageStatus.RUNNING.value
            stage_state["attempts"] = int(event.payload.get("attempt", 1))
            return

        if event.type == "pipeline.stage.retrying":
            stage_name = str(event.payload["stage_name"])
            stage_state = stages.setdefault(stage_name, self._default_stage_state(pipeline, stage_name))
            stage_state["attempts"] = int(event.payload.get("attempt", stage_state["attempts"]))
            stage_state["last_error"] = event.payload.get("error")
            return

        if event.type in {
            "pipeline.stage.completed",
            "pipeline.stage.failed",
            "pipeline.stage.skipped",
            "pipeline.stage.cancelled",
        }:
            stage_name = str(event.payload["stage_name"])
            stage_state = stages.setdefault(stage_name, self._default_stage_state(pipeline, stage_name))
            status_map = {
                "pipeline.stage.completed": StageStatus.COMPLETED.value,
                "pipeline.stage.failed": StageStatus.FAILED.value,
                "pipeline.stage.skipped": StageStatus.SKIPPED.value,
                "pipeline.stage.cancelled": StageStatus.CANCELLED.value,
            }
            stage_state["status"] = status_map[event.type]
            stage_state["attempts"] = int(event.payload.get("attempts", stage_state["attempts"]))
            stage_state["duration_seconds"] = float(event.payload.get("duration_seconds", 0.0))
            if "artifacts" in event.payload:
                stage_state["artifacts"] = list(event.payload["artifacts"])
            if "error" in event.payload:
                stage_state["last_error"] = event.payload["error"]
            if "reason" in event.payload:
                stage_state["last_error"] = event.payload["reason"]
            return

        if event.type in {"pipeline.completed", "pipeline.failed", "pipeline.cancelled"}:
            state["status"] = str(event.payload["status"])
            state["completed_at"] = event.ts.isoformat()
            state["total_duration_seconds"] = float(event.payload.get("total_duration_seconds", 0.0))
            state["success"] = bool(event.payload.get("success", False))

    def _load_pipeline(self, pipeline_name: str) -> Pipeline:
        pipeline_path = self.repo_root / ".reins" / "pipelines" / f"{pipeline_name}.yaml"
        if not pipeline_path.exists():
            raise FileNotFoundError(f"Pipeline definition not found: {pipeline_path}")
        return load_pipeline_from_yaml(pipeline_path)

    def _pipeline_variables(
        self,
        task_dir: Path,
        variables: dict[str, str] | None,
    ) -> dict[str, str]:
        merged = {
            "task_dir": str(task_dir),
            "task_goal": task_dir.name,
            "task_type": "custom",
        }
        task_json = task_dir / "task.json"
        if task_json.exists():
            raw = json.loads(task_json.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                title = raw.get("title")
                task_type = raw.get("task_type")
                if isinstance(title, str) and title:
                    merged["task_goal"] = title
                if isinstance(task_type, str) and task_type:
                    merged["task_type"] = task_type
        if variables:
            merged.update(variables)
        return merged

    def _initial_state_payload(
        self,
        *,
        pipeline_id: str,
        pipeline: Pipeline,
        task_dir: Path,
        variables: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "pipeline_id": pipeline_id,
            "pipeline_name": pipeline.name,
            "task_dir": str(task_dir),
            "status": PipelineStatus.PENDING.value,
            "success": False,
            "started_at": None,
            "completed_at": None,
            "updated_at": datetime.now(UTC).isoformat(),
            "total_duration_seconds": 0.0,
            "variables": variables,
            "stages": {
                stage.name: {
                    "name": stage.name,
                    "type": stage.type.value,
                    "agent_type": stage.agent_type,
                    "depends_on": list(stage.depends_on),
                    "status": StageStatus.PENDING.value,
                    "attempts": 0,
                    "duration_seconds": 0.0,
                    "artifacts": [],
                    "last_error": None,
                }
                for stage in pipeline.stages
            },
        }

    def _result_state_payload(
        self,
        result: PipelineResult,
        task_dir: Path,
        variables: dict[str, str],
        *,
        existing_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing_state = dict(existing_state or {})
        stages = dict(existing_state.get("stages", {}))
        for stage in result.stage_results:
            current_stage = dict(stages.get(stage.stage_name, {}))
            current_stage.update(
                {
                    "name": stage.stage_name,
                    "status": stage.status.value,
                    "attempts": stage.attempts,
                    "duration_seconds": stage.duration_seconds,
                    "artifacts": [str(path) for path in stage.artifacts],
                    "last_error": stage.error,
                }
            )
            stages[stage.stage_name] = current_stage

        return {
            "pipeline_id": result.pipeline_id,
            "pipeline_name": result.pipeline_name,
            "task_dir": str(task_dir),
            "status": result.status.value,
            "success": result.success,
            "started_at": existing_state.get("started_at"),
            "completed_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "total_duration_seconds": result.total_duration_seconds,
            "variables": variables,
            "stages": stages,
            "timeline": asdict(generate_pipeline_timeline(result)),
        }

    async def _write_state(self, state_path: Path, payload: dict[str, Any]) -> None:
        state_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_state(self, state_path: Path) -> dict[str, Any]:
        return json.loads(state_path.read_text(encoding="utf-8"))

    def _find_pipeline_state(self, pipeline_id: str) -> Path | None:
        tasks_root = self.repo_root / ".reins" / "tasks"
        if not tasks_root.exists():
            return None
        for state_path in tasks_root.glob("*/pipeline-state.json"):
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            if payload.get("pipeline_id") == pipeline_id:
                return state_path
        return None

    def _default_stage_state(self, pipeline: Pipeline, stage_name: str) -> dict[str, Any]:
        stage = pipeline.get_stage(stage_name)
        return {
            "name": stage.name,
            "type": stage.type.value,
            "agent_type": stage.agent_type,
            "depends_on": list(stage.depends_on),
            "status": StageStatus.PENDING.value,
            "attempts": 0,
            "duration_seconds": 0.0,
            "artifacts": [],
            "last_error": None,
        }

    def _update_task_metadata(self, task_dir: Path, result: PipelineResult) -> None:
        task_json = task_dir / "task.json"
        if not task_json.exists():
            return
        raw = json.loads(task_json.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        metadata = raw.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
            raw["metadata"] = metadata
        metadata["pipeline"] = {
            "pipeline_id": result.pipeline_id,
            "pipeline_name": result.pipeline_name,
            "status": result.status.value,
            "success": result.success,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        task_json.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")


def generate_pipeline_timeline(pipeline_result: PipelineResult) -> PipelineTimeline:
    """Generate a compact stage timeline from a pipeline result."""
    entries = [
        PipelineTimelineEntry(
            stage_name=stage.stage_name,
            status=stage.status,
            duration_seconds=stage.duration_seconds,
            summary=(
                f"{stage.stage_name} {stage.status.value}"
                + (f" in {stage.duration_seconds:.3f}s" if stage.duration_seconds else "")
            ),
            error=stage.error,
        )
        for stage in pipeline_result.stage_results
    ]
    return PipelineTimeline(
        pipeline_id=pipeline_result.pipeline_id,
        pipeline_name=pipeline_result.pipeline_name,
        status=pipeline_result.status,
        total_duration_seconds=pipeline_result.total_duration_seconds,
        entries=entries,
    )
