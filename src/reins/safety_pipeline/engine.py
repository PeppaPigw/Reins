from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from reins.safety_pipeline.types import (
    PipelineConfig,
    PipelineEvent,
    PipelineExecution,
    PipelineMode,
    PipelineStage,
    SafetyPipelineStats,
    StageResult,
    StageVerdict,
)

StageHandler = Callable[[dict[str, Any]], Awaitable[StageVerdict]]
SyncStageHandler = Callable[[dict[str, Any]], StageVerdict]
EventListener = Callable[[PipelineEvent], None]


class SafetyPipeline:
    """Async safety orchestration pipeline.

    Chains configurable safety stages into a unified evaluation flow.
    Each stage can PASS, FAIL, WARN, or SKIP. In STRICT mode, first FAIL
    short-circuits. In PERMISSIVE mode, all stages run and the worst verdict wins.
    In DRY_RUN mode, all stages run but FAIL is downgraded to WARN.
    """

    def __init__(self, config: PipelineConfig | None = None) -> None:
        self._config = config or PipelineConfig()
        self._handlers: dict[PipelineStage, StageHandler] = {}
        self._executions: list[PipelineExecution] = []
        self._listeners: list[EventListener] = []

    @property
    def config(self) -> PipelineConfig:
        return self._config

    def register_stage(self, stage: PipelineStage, handler: StageHandler | SyncStageHandler) -> None:
        if asyncio.iscoroutinefunction(handler):
            self._handlers[stage] = handler  # type: ignore[assignment]
        else:
            async def _wrap(ctx: dict[str, Any], fn: Any = handler) -> StageVerdict:
                return fn(ctx)
            self._handlers[stage] = _wrap

    def remove_stage(self, stage: PipelineStage) -> bool:
        return self._handlers.pop(stage, None) is not None

    def add_listener(self, listener: EventListener) -> None:
        self._listeners.append(listener)

    async def evaluate(self, agent_id: str, context: dict[str, Any]) -> PipelineExecution:
        start = time.perf_counter()
        stages: list[StageResult] = []
        events: list[PipelineEvent] = []
        failed_at = None
        final = StageVerdict.PASS

        self._emit(events, "pipeline.started", agent_id, payload={"mode": self._config.mode.value})

        for stage in self._config.stages:
            handler = self._handlers.get(stage)
            if not handler:
                result = StageResult(stage=stage, verdict=StageVerdict.SKIP, message="no handler")
                stages.append(result)
                continue

            gate_start = time.perf_counter()
            try:
                verdict = await asyncio.wait_for(
                    handler(context),
                    timeout=self._config.timeout_ms / 1000,
                )
            except asyncio.TimeoutError:
                verdict = StageVerdict.FAIL
                result = StageResult(
                    stage=stage, verdict=verdict, message="timeout",
                    duration_ms=(time.perf_counter() - gate_start) * 1000,
                )
                stages.append(result)
                self._emit(events, "stage.timeout", agent_id, stage=stage, verdict=verdict)
                if self._config.mode == PipelineMode.STRICT:
                    failed_at = stage
                    final = StageVerdict.FAIL
                    break
                continue
            except Exception as e:
                verdict = StageVerdict.FAIL
                result = StageResult(
                    stage=stage, verdict=verdict, message=str(e),
                    duration_ms=(time.perf_counter() - gate_start) * 1000,
                )
                stages.append(result)
                self._emit(events, "stage.error", agent_id, stage=stage, verdict=verdict)
                if self._config.mode == PipelineMode.STRICT:
                    failed_at = stage
                    final = StageVerdict.FAIL
                    break
                continue

            duration = (time.perf_counter() - gate_start) * 1000

            if self._config.mode == PipelineMode.DRY_RUN and verdict == StageVerdict.FAIL:
                verdict = StageVerdict.WARN

            stages.append(StageResult(stage=stage, verdict=verdict, duration_ms=duration))
            self._emit(events, "stage.completed", agent_id, stage=stage, verdict=verdict)

            if verdict == StageVerdict.FAIL:
                if self._config.mode == PipelineMode.STRICT:
                    failed_at = stage
                    final = StageVerdict.FAIL
                    break
                else:
                    final = StageVerdict.FAIL
                    failed_at = failed_at or stage
            elif verdict == StageVerdict.WARN and final == StageVerdict.PASS:
                final = StageVerdict.WARN

        total_ms = (time.perf_counter() - start) * 1000
        self._emit(events, "pipeline.completed", agent_id, verdict=final)

        execution = PipelineExecution(
            agent_id=agent_id,
            mode=self._config.mode,
            final_verdict=final,
            stages=stages,
            events=events,
            total_duration_ms=total_ms,
            failed_at=failed_at,
            completed_at=datetime.now(UTC),
        )
        self._executions.append(execution)
        return execution

    async def evaluate_batch(self, requests: list[tuple[str, dict[str, Any]]]) -> list[PipelineExecution]:
        return [await self.evaluate(agent_id, ctx) for agent_id, ctx in requests]

    def get_executions(self, agent_id: str | None = None,
                       verdict: StageVerdict | None = None) -> list[PipelineExecution]:
        results = self._executions
        if agent_id:
            results = [e for e in results if e.agent_id == agent_id]
        if verdict:
            results = [e for e in results if e.final_verdict == verdict]
        return results

    def get_stats(self) -> SafetyPipelineStats:
        if not self._executions:
            return SafetyPipelineStats()

        passed = sum(1 for e in self._executions if e.final_verdict == StageVerdict.PASS)
        failed = sum(1 for e in self._executions if e.final_verdict == StageVerdict.FAIL)
        warned = sum(1 for e in self._executions if e.final_verdict == StageVerdict.WARN)
        avg_dur = sum(e.total_duration_ms for e in self._executions) / len(self._executions)

        failure_by_stage: dict[str, int] = defaultdict(int)
        for e in self._executions:
            if e.failed_at:
                failure_by_stage[e.failed_at.value] += 1

        total_events = sum(len(e.events) for e in self._executions)

        return SafetyPipelineStats(
            total_executions=len(self._executions),
            passed=passed,
            failed=failed,
            warned=warned,
            avg_duration_ms=avg_dur,
            failure_by_stage=dict(failure_by_stage),
            events_emitted=total_events,
        )

    def _emit(self, events: list[PipelineEvent], event_type: str, agent_id: str,
              stage: PipelineStage | None = None, verdict: StageVerdict | None = None,
              payload: dict[str, Any] | None = None) -> None:
        if not self._config.emit_events:
            return
        event = PipelineEvent(
            event_type=event_type, agent_id=agent_id,
            stage=stage, verdict=verdict, payload=payload or {},
        )
        events.append(event)
        for listener in self._listeners:
            listener(event)
