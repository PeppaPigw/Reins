from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from reins.cli import utils
from reins.orchestration.orchestrator import Orchestrator
from reins.orchestration.workflow import WorkflowExecutor
from reins.policy.engine import PolicyEngine

app = typer.Typer(
    help=(
        "Pipeline orchestration commands.\n\n"
        "Examples:\n"
        "  reins pipeline list\n"
        "  reins pipeline run standard --task .reins/tasks/04-19-example-task\n"
        "  reins pipeline status pipeline-abc123\n"
    )
)


def _executor(repo_root: Path) -> WorkflowExecutor:
    journal = utils.get_journal(repo_root)
    orchestrator = Orchestrator(
        journal=journal,
        policy_engine=PolicyEngine(),
    )
    return WorkflowExecutor(
        orchestrator=orchestrator,
        event_journal=journal,
        repo_root=repo_root,
    )


@app.command("run")
def run_command(
    pipeline_name: str = typer.Argument(..., help="Pipeline name."),
    task: str = typer.Option(..., "--task", help="Task directory path."),
) -> None:
    """Run a pipeline for a task."""
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("pipeline")
    try:
        task_dir = Path(task).resolve()
        executor = _executor(repo_root)
        result = asyncio.run(executor.run_pipeline(pipeline_name, task_dir))
        utils.console.print(
            f"[green]Pipeline completed[/green] [bold]{result.pipeline_name}[/bold] "
            f"({result.pipeline_id}) -> {result.status.value}"
        )
    except Exception as exc:  # pragma: no cover - exercised via CLI tests
        asyncio.run(
            utils.emit_cli_error(
                repo_root,
                run_id,
                "pipeline.run",
                exc,
                {"pipeline_name": pipeline_name, "task": task},
            )
        )
        utils.exit_with_error(str(exc))


@app.command("list")
def list_command() -> None:
    """List available pipelines."""
    repo_root = utils.find_repo_root()
    executor = _executor(repo_root)
    pipelines = executor.list_pipelines()
    if not pipelines:
        utils.console.print("[yellow]No pipelines found.[/yellow]")
        return
    rows = [
        {
            "name": pipeline.name,
            "description": pipeline.description,
            "stages": len(pipeline.stages),
        }
        for pipeline in pipelines
    ]
    utils.console.print(utils.format_table(rows, ["name", "description", "stages"]))


@app.command("status")
def status_command(
    pipeline_id: str = typer.Argument(..., help="Pipeline ID."),
) -> None:
    """Check pipeline status."""
    repo_root = utils.find_repo_root()
    executor = _executor(repo_root)
    try:
        status = executor.get_pipeline_status(pipeline_id)
        utils.console.print(f"{pipeline_id}: {status.value}")
    except FileNotFoundError as exc:
        utils.exit_with_error(str(exc))


@app.command("cancel")
def cancel_command(
    pipeline_id: str = typer.Argument(..., help="Pipeline ID."),
) -> None:
    """Cancel a running pipeline."""
    repo_root = utils.find_repo_root()
    run_id = utils.make_run_id("pipeline")
    executor = _executor(repo_root)
    try:
        cancelled = asyncio.run(executor.cancel_pipeline(pipeline_id))
        if not cancelled:
            raise utils.CLIError(f"Pipeline is not active: {pipeline_id}")
        utils.console.print(f"[yellow]Cancelled pipeline[/yellow] {pipeline_id}")
    except Exception as exc:  # pragma: no cover - exercised via CLI tests
        asyncio.run(
            utils.emit_cli_error(
                repo_root,
                run_id,
                "pipeline.cancel",
                exc,
                {"pipeline_id": pipeline_id},
            )
        )
        utils.exit_with_error(str(exc))
