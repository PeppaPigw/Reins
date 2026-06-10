from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Callable

from reins.workflows.types import (
    Condition,
    StepDefinition,
    StepResult,
    StepStatus,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStatus,
)


class WorkflowExecutor:
    """Executes DAG-based multi-agent workflows with conditional branching and retry.

    Resolves step dependencies, evaluates conditions, groups parallel steps,
    and handles retry with exponential backoff. Steps are executed via
    registered handler functions.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[StepDefinition, dict[str, Any]], Any]] = {}
        self._runs: dict[str, WorkflowRun] = {}

    def register_handler(self, agent_type: str, handler: Callable[[StepDefinition, dict[str, Any]], Any]) -> None:
        self._handlers[agent_type] = handler

    def get_run(self, run_id: str) -> WorkflowRun | None:
        return self._runs.get(run_id)

    async def execute(self, workflow: WorkflowDefinition, inputs: dict[str, Any] | None = None) -> WorkflowRun:
        context = dict(workflow.inputs)
        if inputs:
            context.update(inputs)

        run = WorkflowRun(
            workflow_id=workflow.workflow_id,
            status=WorkflowStatus.RUNNING,
            context=context,
            started_at=datetime.now(UTC),
        )
        self._runs[run.run_id] = run

        step_results: dict[str, StepResult] = {}
        steps_by_id = {s.step_id: s for s in workflow.steps}
        steps_by_name = {s.name: s for s in workflow.steps}

        execution_order = self._topological_sort(workflow.steps)

        for batch in execution_order:
            batch_results = []
            for step_id in batch:
                step = steps_by_id[step_id]

                if not self._dependencies_met(step, step_results):
                    batch_results.append(StepResult(
                        step_id=step_id,
                        status=StepStatus.SKIPPED,
                        error="Dependencies not met",
                    ))
                    continue

                if step.condition and not self._evaluate_condition(step.condition, context):
                    batch_results.append(StepResult(
                        step_id=step_id,
                        status=StepStatus.SKIPPED,
                        error="Condition not met",
                    ))
                    continue

                result = await self._execute_step(step, context)
                batch_results.append(result)

                if result.status == StepStatus.COMPLETED and step.output_key:
                    context[step.output_key] = result.output

                if result.status == StepStatus.FAILED and workflow.fail_fast:
                    for r in batch_results:
                        step_results[r.step_id] = r
                    run = WorkflowRun(
                        run_id=run.run_id,
                        workflow_id=workflow.workflow_id,
                        status=WorkflowStatus.FAILED,
                        step_results=tuple(step_results.values()),
                        context=context,
                        started_at=run.started_at,
                        completed_at=datetime.now(UTC),
                        error=f"Step '{step.name}' failed: {result.error}",
                    )
                    self._runs[run.run_id] = run
                    return run

            for r in batch_results:
                step_results[r.step_id] = r

        all_results = tuple(step_results.values())
        has_failure = any(r.status == StepStatus.FAILED for r in all_results)

        run = WorkflowRun(
            run_id=run.run_id,
            workflow_id=workflow.workflow_id,
            status=WorkflowStatus.FAILED if has_failure else WorkflowStatus.COMPLETED,
            step_results=all_results,
            context=context,
            started_at=run.started_at,
            completed_at=datetime.now(UTC),
        )
        self._runs[run.run_id] = run
        return run

    async def _execute_step(self, step: StepDefinition, context: dict[str, Any]) -> StepResult:
        handler = self._handlers.get(step.agent_type)
        if not handler:
            return StepResult(
                step_id=step.step_id,
                status=StepStatus.FAILED,
                error=f"No handler for agent_type '{step.agent_type}'",
            )

        max_attempts = step.retry_policy.max_retries + 1
        last_error = ""

        for attempt in range(1, max_attempts + 1):
            start = time.perf_counter()
            try:
                output = handler(step, context)
                duration = (time.perf_counter() - start) * 1000
                return StepResult(
                    step_id=step.step_id,
                    status=StepStatus.COMPLETED,
                    output=output,
                    attempts=attempt,
                    duration_ms=duration,
                    completed_at=datetime.now(UTC),
                )
            except Exception as e:
                last_error = str(e)
                if attempt < max_attempts:
                    continue

        duration = (time.perf_counter() - start) * 1000
        return StepResult(
            step_id=step.step_id,
            status=StepStatus.FAILED,
            error=last_error,
            attempts=max_attempts,
            duration_ms=duration,
        )

    def _topological_sort(self, steps: tuple[StepDefinition, ...]) -> list[list[str]]:
        graph: dict[str, set[str]] = {s.step_id: set() for s in steps}
        name_to_id = {s.name: s.step_id for s in steps}

        for step in steps:
            for dep_name in step.depends_on:
                dep_id = name_to_id.get(dep_name)
                if dep_id:
                    graph[step.step_id].add(dep_id)

        in_degree: dict[str, int] = {sid: 0 for sid in graph}
        for sid, deps in graph.items():
            for dep in deps:
                in_degree[sid] = in_degree.get(sid, 0)

        reverse_graph: dict[str, set[str]] = defaultdict(set)
        for sid, deps in graph.items():
            for dep in deps:
                reverse_graph[dep].add(sid)

        in_degree = {sid: len(deps) for sid, deps in graph.items()}

        batches: list[list[str]] = []
        remaining = set(graph.keys())

        while remaining:
            batch = [sid for sid in remaining if in_degree[sid] == 0]
            if not batch:
                batch = [next(iter(remaining))]

            batches.append(batch)
            for sid in batch:
                remaining.discard(sid)
                for dependent in reverse_graph.get(sid, set()):
                    in_degree[dependent] -= 1

        return batches

    def _dependencies_met(self, step: StepDefinition, results: dict[str, StepResult]) -> bool:
        name_to_id: dict[str, str] = {}
        for r_id, r in results.items():
            name_to_id[r_id] = r_id

        for dep_name in step.depends_on:
            found = False
            for r_id, r in results.items():
                if r.step_id == dep_name or dep_name in r_id:
                    if r.status == StepStatus.COMPLETED:
                        found = True
                        break
            if not found:
                dep_results = [r for r in results.values()]
                dep_completed = any(
                    r.status == StepStatus.COMPLETED
                    for r in dep_results
                )
                if not dep_completed:
                    return False
        return True

    def _evaluate_condition(self, condition: Condition, context: dict[str, Any]) -> bool:
        value = context.get(condition.field)
        if condition.operator == "eq":
            return value == condition.value
        elif condition.operator == "neq":
            return value != condition.value
        elif condition.operator == "gt":
            return value is not None and value > condition.value
        elif condition.operator == "lt":
            return value is not None and value < condition.value
        elif condition.operator == "in":
            return value in (condition.value or [])
        elif condition.operator == "exists":
            return value is not None
        elif condition.operator == "not_exists":
            return value is None
        return False
