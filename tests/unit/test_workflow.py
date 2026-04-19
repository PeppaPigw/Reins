from __future__ import annotations

import json
from pathlib import Path

import pytest

from reins.kernel.event.journal import EventJournal
from reins.orchestration.orchestrator import Orchestrator
from reins.orchestration.workflow import WorkflowExecutor, generate_pipeline_timeline
from reins.policy.engine import PolicyEngine


def _write_pipeline(repo_root: Path, name: str, content: str) -> None:
    pipeline_dir = repo_root / ".reins" / "pipelines"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / f"{name}.yaml").write_text(content, encoding="utf-8")


def _write_task(task_dir: Path) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.json").write_text(
        json.dumps(
            {
                "task_id": task_dir.name,
                "title": "Implement pipeline workflow",
                "task_type": "backend",
                "metadata": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (task_dir / "prd.md").write_text("# PRD\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_run_pipeline_persists_state_and_updates_task_metadata(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    task_dir = repo_root / ".reins" / "tasks" / "task-1"
    _write_task(task_dir)
    _write_pipeline(
        repo_root,
        "sample",
        """
name: sample
description: Sample pipeline
stages:
  - name: research
    type: research
    agent_type: research
    prompt_template: "Research {task_goal}"
    context_files: ["prd.md"]
""".strip()
        + "\n",
    )

    journal = EventJournal(repo_root / ".reins" / "journal")
    executor = WorkflowExecutor(
        orchestrator=Orchestrator(journal=journal, policy_engine=PolicyEngine()),
        event_journal=journal,
        repo_root=repo_root,
    )

    result = await executor.run_pipeline("sample", task_dir)

    state = json.loads((task_dir / "pipeline-state.json").read_text(encoding="utf-8"))
    task_json = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))

    assert result.success is True
    assert state["status"] == "completed"
    assert state["pipeline_id"] == result.pipeline_id
    assert state["stages"]["research"]["status"] == "completed"
    assert state["timeline"]["status"] == "completed"
    assert task_json["metadata"]["pipeline"]["pipeline_id"] == result.pipeline_id


@pytest.mark.asyncio
async def test_get_pipeline_status_and_list_pipelines(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    task_dir = repo_root / ".reins" / "tasks" / "task-2"
    _write_task(task_dir)
    _write_pipeline(
        repo_root,
        "first",
        """
name: first
description: First pipeline
stages:
  - name: verify
    type: verify
    agent_type: verify
    prompt_template: "Verify {task_goal}"
""".strip()
        + "\n",
    )

    journal = EventJournal(repo_root / ".reins" / "journal")
    executor = WorkflowExecutor(
        orchestrator=Orchestrator(journal=journal, policy_engine=PolicyEngine()),
        event_journal=journal,
        repo_root=repo_root,
    )

    result = await executor.run_pipeline("first", task_dir)

    assert [pipeline.name for pipeline in executor.list_pipelines()] == ["first"]
    assert executor.get_pipeline_status(result.pipeline_id or "") is result.status


def test_generate_pipeline_timeline() -> None:
    from reins.orchestration.types import PipelineResult, PipelineStatus, StageResult, StageStatus

    result = PipelineResult(
        pipeline_name="sample",
        status=PipelineStatus.COMPLETED,
        stage_results=[
            StageResult(
                stage_name="research",
                status=StageStatus.COMPLETED,
                output="ok",
                artifacts=[],
                duration_seconds=0.25,
            )
        ],
        total_duration_seconds=0.25,
        success=True,
        pipeline_id="pipeline-1",
    )

    timeline = generate_pipeline_timeline(result)

    assert timeline.pipeline_id == "pipeline-1"
    assert timeline.status is PipelineStatus.COMPLETED
    assert timeline.entries[0].summary.startswith("research completed")
