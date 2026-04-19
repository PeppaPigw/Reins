"""Shared helpers for standalone orchestration scripts."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from reins.cli import utils  # noqa: E402
from reins.export.task_exporter import TaskExporter  # noqa: E402
from reins.kernel.event.journal import EventJournal  # noqa: E402
from reins.orchestration.orchestrator import Orchestrator  # noqa: E402
from reins.orchestration.pipeline import Pipeline, load_pipeline_from_yaml  # noqa: E402
from reins.orchestration.types import PipelineResult  # noqa: E402
from reins.orchestration.workflow import WorkflowExecutor, generate_pipeline_timeline  # noqa: E402
from reins.policy.engine import PolicyEngine  # noqa: E402
from reins.task.manager import TaskManager  # noqa: E402


def get_repo_root() -> Path:
    """Return the repository root that owns these scripts."""
    return REPO_ROOT


def resolve_path(path_str: str, *, repo_root: Path | None = None) -> Path:
    """Resolve a user-supplied path against cwd first, then repo root."""
    raw = Path(path_str)
    if raw.is_absolute():
        return raw.resolve()

    cwd_candidate = (Path.cwd() / raw).resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    root = (repo_root or get_repo_root()).resolve()
    return (root / raw).resolve()


def safe_slug(value: str, *, prefix: str | None = None, max_length: int = 40) -> str:
    """Create a filesystem-friendly slug."""
    base = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if prefix:
        base = f"{prefix}-{base}" if base else prefix
    base = re.sub(r"-{2,}", "-", base)
    trimmed = base[:max_length].strip("-")
    return trimmed or (prefix or "task")


def create_executor(
    repo_root: Path,
    *,
    max_parallel_stages: int | None = None,
    journal: EventJournal | None = None,
) -> WorkflowExecutor:
    """Create a workflow executor without going through the CLI layer."""
    resolved_root = repo_root.resolve()
    active_journal = journal or utils.get_journal(resolved_root)
    orchestrator = Orchestrator(
        journal=active_journal,
        policy_engine=PolicyEngine(),
    )
    return WorkflowExecutor(
        orchestrator=orchestrator,
        event_journal=active_journal,
        repo_root=resolved_root,
        max_parallel_stages=max_parallel_stages,
    )


def load_pipeline(
    pipeline_path: Path,
    *,
    model_override: str | None = None,
) -> Pipeline:
    """Load a pipeline definition and optionally override stage model hints."""
    pipeline = load_pipeline_from_yaml(pipeline_path)
    if model_override:
        for stage in pipeline.stages:
            stage.model = model_override
    return pipeline


def result_error(result: PipelineResult) -> str | None:
    """Return the first stage error for a failed result."""
    for stage in result.stage_results:
        if stage.error:
            return stage.error
    return None


def write_pipeline_output(
    output_dir: Path,
    *,
    pipeline_path: Path,
    task_dir: Path,
    result: PipelineResult,
) -> Path:
    """Persist a machine-readable and human-readable pipeline summary."""
    output_dir.mkdir(parents=True, exist_ok=True)

    timeline = generate_pipeline_timeline(result)
    payload: dict[str, Any] = {
        "pipeline_path": str(pipeline_path),
        "task_dir": str(task_dir),
        "pipeline_name": result.pipeline_name,
        "pipeline_id": result.pipeline_id,
        "status": result.status.value,
        "success": result.success,
        "total_duration_seconds": result.total_duration_seconds,
        "timeline": asdict(timeline),
        "stages": [
            {
                "stage_name": stage.stage_name,
                "status": stage.status.value,
                "attempts": stage.attempts,
                "duration_seconds": stage.duration_seconds,
                "error": stage.error,
                "artifacts": [str(path) for path in stage.artifacts],
                "output_file": f"{stage.stage_name}.txt",
            }
            for stage in result.stage_results
        ],
    }
    result_path = output_dir / "result.json"
    result_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        f"# {result.pipeline_name}",
        "",
        f"- Pipeline ID: `{result.pipeline_id}`",
        f"- Status: `{result.status.value}`",
        f"- Success: `{result.success}`",
        f"- Duration: `{result.total_duration_seconds:.3f}s`",
        f"- Task directory: `{task_dir}`",
        f"- Pipeline file: `{pipeline_path}`",
        "",
        "## Stages",
        "",
    ]
    for stage in result.stage_results:
        lines.append(
            f"- `{stage.stage_name}`: `{stage.status.value}` in {stage.duration_seconds:.3f}s"
        )
        if stage.error:
            lines.append(f"  error: {stage.error}")
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    for stage in result.stage_results:
        (output_dir / f"{stage.stage_name}.txt").write_text(stage.output, encoding="utf-8")

    state_path = task_dir / "pipeline-state.json"
    if state_path.exists():
        shutil.copy2(state_path, output_dir / "pipeline-state.json")

    return result_path


def create_task(
    repo_root: Path,
    *,
    title: str,
    task_type: str,
    prd_content: str,
    acceptance_criteria: list[str],
    slug: str | None = None,
    priority: str = "P1",
    assignee: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Create and export a task directory using the native task APIs."""
    utils.ensure_reins_layout(repo_root)
    run_id = utils.make_run_id("bootstrap")
    projection = utils.rebuild_task_projection(repo_root)
    manager = TaskManager(
        utils.get_journal(repo_root),
        projection,
        run_id=run_id,
        repo_root=repo_root,
    )
    exporter = TaskExporter(projection, repo_root / ".reins" / "tasks")
    identity = utils.read_developer_identity(repo_root)
    created_by = identity["name"] if identity else "script"
    final_assignee = assignee or created_by or "unassigned"

    task_id = asyncio.run(
        manager.create_task(
            title=title,
            task_type=task_type,
            prd_content=prd_content,
            acceptance_criteria=acceptance_criteria,
            created_by=created_by,
            slug=slug,
            priority=priority,
            assignee=final_assignee,
            metadata=metadata or {},
        )
    )
    task_dir = exporter.export_task(task_id)
    if task_dir is None:
        raise RuntimeError(f"Failed to export task {task_id}")
    manager.execute_after_create(task_id)
    return task_dir
