"""Tests for workflow composition engine."""

from __future__ import annotations

import pytest

from reins.workflows import (
    Condition,
    RetryPolicy,
    StepDefinition,
    StepStatus,
    WorkflowDefinition,
    WorkflowExecutor,
    WorkflowStatus,
)


@pytest.fixture
def executor() -> WorkflowExecutor:
    ex = WorkflowExecutor()
    ex.register_handler("default", lambda step, ctx: f"done:{step.name}")
    ex.register_handler("transform", lambda step, ctx: ctx.get("input", "").upper())
    return ex


@pytest.mark.asyncio
async def test_single_step_workflow(executor):
    wf = WorkflowDefinition(
        name="simple",
        steps=(StepDefinition(name="step1"),),
    )
    run = await executor.execute(wf)
    assert run.status == WorkflowStatus.COMPLETED
    assert len(run.step_results) == 1
    assert run.step_results[0].status == StepStatus.COMPLETED
    assert run.step_results[0].output == "done:step1"


@pytest.mark.asyncio
async def test_sequential_steps(executor):
    wf = WorkflowDefinition(
        name="sequential",
        steps=(
            StepDefinition(name="first"),
            StepDefinition(name="second", depends_on=("first",)),
            StepDefinition(name="third", depends_on=("second",)),
        ),
    )
    run = await executor.execute(wf)
    assert run.status == WorkflowStatus.COMPLETED
    assert len(run.step_results) == 3


@pytest.mark.asyncio
async def test_parallel_steps(executor):
    wf = WorkflowDefinition(
        name="parallel",
        steps=(
            StepDefinition(name="a"),
            StepDefinition(name="b"),
            StepDefinition(name="c"),
        ),
    )
    run = await executor.execute(wf)
    assert run.status == WorkflowStatus.COMPLETED
    assert len(run.step_results) == 3


@pytest.mark.asyncio
async def test_output_key_passes_data(executor):
    wf = WorkflowDefinition(
        name="data_pass",
        steps=(
            StepDefinition(name="produce", agent_type="transform", output_key="result"),
        ),
        inputs={"input": "hello"},
    )
    run = await executor.execute(wf)
    assert run.context["result"] == "HELLO"


@pytest.mark.asyncio
async def test_condition_true_executes(executor):
    wf = WorkflowDefinition(
        name="conditional",
        steps=(
            StepDefinition(
                name="guarded",
                condition=Condition(field="flag", operator="eq", value=True),
            ),
        ),
        inputs={"flag": True},
    )
    run = await executor.execute(wf)
    assert run.step_results[0].status == StepStatus.COMPLETED


@pytest.mark.asyncio
async def test_condition_false_skips(executor):
    wf = WorkflowDefinition(
        name="conditional",
        steps=(
            StepDefinition(
                name="guarded",
                condition=Condition(field="flag", operator="eq", value=True),
            ),
        ),
        inputs={"flag": False},
    )
    run = await executor.execute(wf)
    assert run.step_results[0].status == StepStatus.SKIPPED


@pytest.mark.asyncio
async def test_condition_exists(executor):
    wf = WorkflowDefinition(
        name="exists_check",
        steps=(
            StepDefinition(
                name="check",
                condition=Condition(field="data", operator="exists"),
            ),
        ),
        inputs={"data": "something"},
    )
    run = await executor.execute(wf)
    assert run.step_results[0].status == StepStatus.COMPLETED


@pytest.mark.asyncio
async def test_condition_not_exists(executor):
    wf = WorkflowDefinition(
        name="not_exists_check",
        steps=(
            StepDefinition(
                name="check",
                condition=Condition(field="missing", operator="not_exists"),
            ),
        ),
        inputs={},
    )
    run = await executor.execute(wf)
    assert run.step_results[0].status == StepStatus.COMPLETED


@pytest.mark.asyncio
async def test_failed_step_with_fail_fast(executor):
    executor.register_handler("failing", lambda s, c: (_ for _ in ()).throw(RuntimeError("boom")))
    wf = WorkflowDefinition(
        name="fail_fast",
        steps=(
            StepDefinition(name="bad", agent_type="failing", retry_policy=RetryPolicy(max_retries=0)),
            StepDefinition(name="never_runs", depends_on=("bad",)),
        ),
        fail_fast=True,
    )
    run = await executor.execute(wf)
    assert run.status == WorkflowStatus.FAILED
    assert "boom" in run.error


@pytest.mark.asyncio
async def test_retry_on_failure(executor):
    call_count = {"n": 0}

    def flaky(step, ctx):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise RuntimeError("transient")
        return "recovered"

    executor.register_handler("flaky", flaky)
    wf = WorkflowDefinition(
        name="retry",
        steps=(
            StepDefinition(name="flaky_step", agent_type="flaky", retry_policy=RetryPolicy(max_retries=3)),
        ),
    )
    run = await executor.execute(wf)
    assert run.status == WorkflowStatus.COMPLETED
    assert run.step_results[0].output == "recovered"
    assert run.step_results[0].attempts == 3


@pytest.mark.asyncio
async def test_retry_exhausted(executor):
    executor.register_handler("always_fail", lambda s, c: (_ for _ in ()).throw(RuntimeError("permanent")))
    wf = WorkflowDefinition(
        name="exhaust",
        steps=(
            StepDefinition(name="doomed", agent_type="always_fail", retry_policy=RetryPolicy(max_retries=2)),
        ),
    )
    run = await executor.execute(wf)
    assert run.status == WorkflowStatus.FAILED
    assert run.step_results[0].attempts == 3


@pytest.mark.asyncio
async def test_no_handler_fails_step(executor):
    wf = WorkflowDefinition(
        name="missing_handler",
        steps=(StepDefinition(name="orphan", agent_type="nonexistent"),),
    )
    run = await executor.execute(wf)
    assert run.status == WorkflowStatus.FAILED
    assert "No handler" in run.step_results[0].error


@pytest.mark.asyncio
async def test_inputs_override(executor):
    executor.register_handler("echo", lambda s, c: c.get("val"))
    wf = WorkflowDefinition(
        name="override",
        steps=(StepDefinition(name="echo", agent_type="echo", output_key="out"),),
        inputs={"val": "original"},
    )
    run = await executor.execute(wf, inputs={"val": "overridden"})
    assert run.context["out"] == "overridden"


@pytest.mark.asyncio
async def test_get_run(executor):
    wf = WorkflowDefinition(name="track", steps=(StepDefinition(name="s"),))
    run = await executor.execute(wf)
    retrieved = executor.get_run(run.run_id)
    assert retrieved is not None
    assert retrieved.run_id == run.run_id


@pytest.mark.asyncio
async def test_diamond_dependency(executor):
    wf = WorkflowDefinition(
        name="diamond",
        steps=(
            StepDefinition(name="root"),
            StepDefinition(name="left", depends_on=("root",)),
            StepDefinition(name="right", depends_on=("root",)),
            StepDefinition(name="join", depends_on=("left", "right")),
        ),
    )
    run = await executor.execute(wf)
    assert run.status == WorkflowStatus.COMPLETED
    assert len(run.step_results) == 4


@pytest.mark.asyncio
async def test_step_duration_tracked(executor):
    wf = WorkflowDefinition(name="timed", steps=(StepDefinition(name="s"),))
    run = await executor.execute(wf)
    assert run.step_results[0].duration_ms >= 0


@pytest.mark.asyncio
async def test_condition_gt(executor):
    wf = WorkflowDefinition(
        name="gt",
        steps=(
            StepDefinition(name="s", condition=Condition(field="x", operator="gt", value=5)),
        ),
        inputs={"x": 10},
    )
    run = await executor.execute(wf)
    assert run.step_results[0].status == StepStatus.COMPLETED


@pytest.mark.asyncio
async def test_condition_lt_skips(executor):
    wf = WorkflowDefinition(
        name="lt",
        steps=(
            StepDefinition(name="s", condition=Condition(field="x", operator="lt", value=5)),
        ),
        inputs={"x": 10},
    )
    run = await executor.execute(wf)
    assert run.step_results[0].status == StepStatus.SKIPPED
