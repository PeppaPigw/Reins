from __future__ import annotations

import asyncio

import typer

from reins.cli import utils


def status_command(
    verbose: bool = typer.Option(False, "--verbose", help="Show expanded status details."),
) -> None:
    """
    Show current task, agent, git, workspace, and recent journal state.
    """
    repo_root = utils.find_repo_root()
    projection = utils.rebuild_task_projection(repo_root)
    current_task_id = utils.get_current_task_id(repo_root)
    current_task = projection.get_task(current_task_id) if current_task_id else None
    workspace = utils.collect_workspace_info(repo_root)
    registry = utils.get_agent_registry(repo_root, utils.make_run_id("status"))
    agents = asyncio.run(registry.list_all())
    git_status = utils.git_status_summary(repo_root)
    recent_events = utils.load_all_events(repo_root)[-10:]

    rows = [
        {"field": "current_task", "value": current_task.task_id if current_task else "-"},
        {"field": "task_status", "value": current_task.status.value if current_task else "-"},
        {"field": "active_agents", "value": str(len(agents))},
        {"field": "developer", "value": workspace.developer or "-"},
        {"field": "workspace_journals", "value": str(len(workspace.journal_files))},
        {"field": "git_changes", "value": str(len(git_status))},
        {"field": "recent_events", "value": str(len(recent_events))},
    ]
    utils.console.print(utils.format_table(rows, ["field", "value"]))

    if not verbose:
        return

    if agents:
        utils.console.print("")
        agent_rows = [
            {
                "agent_id": agent.agent_id,
                "task_id": agent.task_id or "",
                "status": agent.status,
                "worktree_id": agent.worktree_id,
            }
            for agent in agents
        ]
        utils.console.print(utils.format_table(agent_rows, ["agent_id", "task_id", "status", "worktree_id"]))

    if git_status:
        utils.console.print("")
        utils.console.print("[bold]Git status[/bold]")
        for line in git_status:
            utils.console.print(line)

    if recent_events:
        utils.console.print("")
        event_rows = [
            {
                "ts": utils.format_timestamp(event.ts),
                "type": event.type,
                "run_id": event.run_id,
            }
            for event in recent_events
        ]
        utils.console.print(utils.format_table(event_rows, ["ts", "type", "run_id"]))
