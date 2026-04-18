from __future__ import annotations

from pathlib import Path
from typing import Iterable

import typer

from reins.cli import utils
from reins.context.compiler import ContextCompiler
from reins.kernel.event.builder import EventBuilder
from reins.task.context_jsonl import ContextJSONL, ContextMessage


def register(app: typer.Typer) -> None:
    @app.command("add-context")
    def add_context_command(
        task_id: str = typer.Argument(..., help="Task ID."),
        agent: str = typer.Argument(..., help="Context file stem: implement, check, debug."),
        file_path: Path = typer.Argument(..., exists=True, readable=True, resolve_path=True),
        reason: str = typer.Option("Added via CLI", "--reason", help="Reason for adding this context."),
    ) -> None:
        """
        Append a file's content to a task context JSONL file.

        Example:
          reins task add-context 04-18-auth implement docs/spec.md --reason "Auth rules"
        """
        repo_root = utils.find_repo_root()
        run_id = utils.make_run_id("task-context")
        try:
            _add_context(repo_root, run_id, task_id, agent, file_path, reason)
        except Exception as exc:  # pragma: no cover - exercised via CLI tests
            _emit_error(repo_root, run_id, "task.add-context", exc, task_id=task_id, agent=agent)
            utils.exit_with_error(str(exc))

    @app.command("init-context")
    def init_context_command(
        task_id: str = typer.Argument(..., help="Task ID."),
        context_type: str = typer.Argument(..., help="backend | frontend | fullstack"),
    ) -> None:
        """
        Initialize implement/check/debug context files for a task.

        Example:
          reins task init-context 04-18-auth backend
        """
        repo_root = utils.find_repo_root()
        run_id = utils.make_run_id("task-context")
        try:
            _init_context(repo_root, run_id, task_id, context_type)
        except Exception as exc:  # pragma: no cover - exercised via CLI tests
            _emit_error(repo_root, run_id, "task.init-context", exc, task_id=task_id)
            utils.exit_with_error(str(exc))


def _task_dir(repo_root: Path, task_id: str) -> Path:
    path = utils.task_dir(repo_root, task_id)
    if not path.is_dir():
        raise utils.CLIError(f"Task directory not found: {path}")
    return path


def _load_task_metadata(repo_root: Path, task_id: str) -> dict:
    task_json = utils.task_dir(repo_root, task_id) / "task.json"
    if not task_json.exists():
        raise utils.CLIError(f"Task metadata not found: {task_json}")
    return utils.read_json_file(task_json)


def _relevant_spec_files(repo_root: Path, context_type: str, package: str | None) -> list[Path]:
    compiler = ContextCompiler()
    spec_root = repo_root / ".reins" / "spec"
    sources = compiler.resolve_spec_sources(spec_root, task_type=context_type, package=package)
    files: list[Path] = []
    seen: set[Path] = set()
    for source in sources:
        if not source.path:
            continue
        source_path = Path(source.path)
        index_path = source_path / "index.md" if source_path.is_dir() else source_path
        if not index_path.exists() or index_path in seen:
            continue
        seen.add(index_path)
        files.append(index_path)
    return files


def _append_messages(path: Path, messages: Iterable[ContextMessage]) -> None:
    ContextJSONL.clear_messages(path)
    for message in messages:
        ContextJSONL.write_message(path, message)


def _build_seed_messages(
    repo_root: Path,
    task_id: str,
    agent: str,
    context_type: str,
    package: str | None,
) -> list[ContextMessage]:
    task_path = utils.task_dir(repo_root, task_id)
    prd_path = task_path / "prd.md"
    prd_content = prd_path.read_text(encoding="utf-8") if prd_path.exists() else ""

    role_prompts = {
        "implement": "Implement the task carefully and keep changes scoped.",
        "check": "Review the task output against its acceptance criteria.",
        "debug": "Use the task context to debug regressions and failed checks.",
    }

    messages = [
        ContextMessage(
            role="system",
            content=role_prompts[agent],
            metadata={
                "task_id": task_id,
                "context_type": context_type,
                "source": "reins.task.init-context",
            },
        )
    ]

    if prd_content:
        messages.append(
            ContextMessage(
                role="system",
                content=prd_content,
                metadata={
                    "task_id": task_id,
                    "source": utils.relpath(prd_path, repo_root),
                    "kind": "prd",
                },
            )
        )

    for spec_path in _relevant_spec_files(repo_root, context_type, package):
        messages.append(
            ContextMessage(
                role="system",
                content=spec_path.read_text(encoding="utf-8"),
                metadata={
                    "task_id": task_id,
                    "source": utils.relpath(spec_path, repo_root),
                    "kind": "spec",
                },
            )
        )

    return messages


def _init_context(repo_root: Path, run_id: str, task_id: str, context_type: str) -> None:
    if context_type not in {"backend", "frontend", "fullstack"}:
        raise utils.CLIError("Context type must be one of: backend, frontend, fullstack")

    task_path = _task_dir(repo_root, task_id)
    metadata = _load_task_metadata(repo_root, task_id)
    package = metadata.get("metadata", {}).get("package")

    for agent in ("implement", "check", "debug"):
        messages = _build_seed_messages(repo_root, task_id, agent, context_type, package)
        _append_messages(task_path / f"{agent}.jsonl", messages)

    builder = EventBuilder(utils.get_journal(repo_root))
    import asyncio

    asyncio.run(
        builder.commit(
            run_id=run_id,
            event_type="task.context_initialized",
            payload={
                "task_id": task_id,
                "context_type": context_type,
                "files": ["implement.jsonl", "check.jsonl", "debug.jsonl"],
                "source": "cli",
            },
        )
    )

    utils.console.print(
        f"[green]Initialized context files[/green] for [bold]{task_id}[/bold] ({context_type})."
    )


def _add_context(
    repo_root: Path,
    run_id: str,
    task_id: str,
    agent: str,
    file_path: Path,
    reason: str,
) -> None:
    if agent not in {"implement", "check", "debug"}:
        raise utils.CLIError("Agent must be one of: implement, check, debug")

    task_path = _task_dir(repo_root, task_id)
    if file_path.is_dir():
        raise utils.CLIError("add-context expects a file path, not a directory")

    content = file_path.read_text(encoding="utf-8")
    message = ContextMessage(
        role="system",
        content=content,
        metadata={
            "task_id": task_id,
            "source": utils.relpath(file_path, repo_root),
            "reason": reason,
            "added_via": "reins task add-context",
        },
    )
    ContextJSONL.write_message(task_path / f"{agent}.jsonl", message)

    builder = EventBuilder(utils.get_journal(repo_root))
    import asyncio

    asyncio.run(
        builder.commit(
            run_id=run_id,
            event_type="task.context_added",
            payload={
                "task_id": task_id,
                "agent": agent,
                "source_path": utils.relpath(file_path, repo_root),
                "reason": reason,
                "source": "cli",
            },
        )
    )

    utils.console.print(
        f"[green]Added context[/green] to [bold]{agent}.jsonl[/bold] from "
        f"[cyan]{utils.relpath(file_path, repo_root)}[/cyan]."
    )


def _emit_error(
    repo_root: Path,
    run_id: str,
    command: str,
    error: Exception,
    **payload: str,
) -> None:
    import asyncio

    asyncio.run(utils.emit_cli_error(repo_root, run_id, command, error, payload))
