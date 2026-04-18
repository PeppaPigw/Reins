from __future__ import annotations

import json
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import typer
import ulid
import yaml
from rich.console import Console
from tabulate import tabulate

from reins.context.spec_projection import ContextSpecProjection
from reins.isolation.agent_registry import AgentRegistry
from reins.isolation.types import WorktreeConfig, WorktreeState
from reins.isolation.worktree_manager import WorktreeManager
from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.envelope import EventEnvelope, event_from_dict
from reins.kernel.event.journal import EventJournal
from reins.kernel.event.worktree_events import WORKTREE_CREATED, WORKTREE_REMOVED
from reins.serde import parse_dt
from reins.task.projection import TaskContextProjection

console = Console()


class CLIError(RuntimeError):
    """Raised when CLI preconditions are not met."""


@dataclass(frozen=True)
class WorkspaceInfo:
    developer: str | None
    workspace_dir: Path | None
    journal_files: list[Path]
    active_journal: Path | None
    total_lines: int


def find_repo_root() -> Path:
    """Find .reins directory walking up from cwd."""
    current = Path.cwd().resolve()
    for path in [current, *current.parents]:
        if (path / ".reins").is_dir():
            return path
    raise CLIError("Could not find a .reins directory from the current working directory.")


def find_repo_root_for_init() -> Path:
    """Find a repository root for initialization commands.

    Prefers an existing `.reins` root, then the enclosing git root, then the
    current working directory.
    """
    try:
        return find_repo_root()
    except CLIError:
        pass

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return Path.cwd().resolve()

    return Path(result.stdout.strip()).resolve()


def load_config(repo_root: Path) -> dict:
    """Load .reins/config.yaml if exists."""
    config_path = repo_root / ".reins" / "config.yaml"
    if not config_path.exists():
        return {}
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise CLIError(f"Invalid config file: {config_path}")
    return raw


def format_timestamp(dt: datetime) -> str:
    """Human-readable timestamp."""
    normalized = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    return normalized.strftime("%Y-%m-%d %H:%M:%S UTC")


def format_table(data: list[dict], headers: list[str]) -> str:
    """Format data as table using tabulate."""
    rows = [[row.get(header, "") for header in headers] for row in data]
    return tabulate(rows, headers=headers, tablefmt="github")


def make_run_id(prefix: str = "cli") -> str:
    return f"{prefix}-{ulid.new()}"


def ensure_reins_layout(repo_root: Path) -> None:
    reins_dir = repo_root / ".reins"
    reins_dir.mkdir(parents=True, exist_ok=True)
    for dirname in ("tasks", "spec", "workspace"):
        (reins_dir / dirname).mkdir(exist_ok=True)


def journal_path(repo_root: Path) -> Path:
    return repo_root / ".reins" / "journal.jsonl"


def get_journal(repo_root: Path) -> EventJournal:
    ensure_reins_layout(repo_root)
    return EventJournal(journal_path(repo_root))


def task_pointer_for(task_id: str) -> str:
    return f"tasks/{task_id}"


def set_current_task_pointer(repo_root: Path, task_id: str | None) -> None:
    pointer_path = repo_root / ".reins" / ".current-task"
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    if task_id is None:
        if pointer_path.exists():
            pointer_path.unlink()
        return
    pointer_path.write_text(f"{task_pointer_for(task_id)}\n", encoding="utf-8")


def parse_task_pointer(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return None
    if value.startswith("tasks/"):
        return value.split("/", 1)[1]
    if value.startswith(".reins/tasks/"):
        return value.rsplit("/", 1)[-1]
    if value.startswith(".trellis/tasks/"):
        return value.rsplit("/", 1)[-1]
    return None


def get_current_task_id(repo_root: Path) -> str | None:
    pointer_path = repo_root / ".reins" / ".current-task"
    if not pointer_path.exists():
        return None
    return parse_task_pointer(pointer_path.read_text(encoding="utf-8"))


def task_dir(repo_root: Path, task_id: str) -> Path:
    return repo_root / ".reins" / "tasks" / task_id


def read_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_event_files(repo_root: Path) -> list[Path]:
    path = journal_path(repo_root)
    if path.is_dir():
        return sorted(path.glob("*.jsonl"))
    if path.exists():
        return [path]
    return []


def load_all_events(repo_root: Path) -> list[EventEnvelope]:
    events: list[EventEnvelope] = []
    for file_path in iter_event_files(repo_root):
        for line in file_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            events.append(event_from_dict(json.loads(line)))
    events.sort(key=lambda event: (event.ts, event.run_id, event.seq, event.event_id))
    return events


def rebuild_task_projection(repo_root: Path) -> TaskContextProjection:
    projection = TaskContextProjection()
    for event in load_all_events(repo_root):
        projection.apply_event(event)
    return projection


def rebuild_spec_projection(repo_root: Path) -> ContextSpecProjection:
    projection = ContextSpecProjection()
    for event in load_all_events(repo_root):
        projection.apply_event(event)
    return projection


def get_agent_registry(repo_root: Path, run_id: str) -> AgentRegistry:
    ensure_reins_layout(repo_root)
    return AgentRegistry(
        path=repo_root / ".reins" / "registry.json",
        journal=get_journal(repo_root),
        run_id=run_id,
    )


def hydrate_worktree_manager(repo_root: Path, run_id: str) -> WorktreeManager:
    manager = WorktreeManager(
        journal=get_journal(repo_root),
        run_id=run_id,
        repo_root=repo_root,
        agent_registry=get_agent_registry(repo_root, run_id),
    )

    active: dict[str, WorktreeState] = {}
    for event in load_all_events(repo_root):
        if event.type == WORKTREE_CREATED:
            payload = event.payload
            worktree_path = Path(payload["worktree_path"])
            config_payload = payload.get("config", {})
            config = WorktreeConfig(
                worktree_base_dir=worktree_path.parent,
                worktree_name=worktree_path.name,
                branch_name=payload["branch_name"],
                base_branch=payload["base_branch"],
                create_branch=True,
                copy_files=list(config_payload.get("copy_files", [])),
                post_create_commands=list(config_payload.get("post_create_commands", [])),
                verify_commands=list(config_payload.get("verify_commands", [])),
                cleanup_on_success=bool(config_payload.get("cleanup_on_success", True)),
                cleanup_on_failure=bool(config_payload.get("cleanup_on_failure", False)),
            )
            active[payload["worktree_id"]] = WorktreeState(
                worktree_id=payload["worktree_id"],
                worktree_path=worktree_path,
                branch_name=payload["branch_name"],
                base_branch=payload["base_branch"],
                agent_id=payload["agent_id"],
                task_id=payload.get("task_id"),
                created_at=parse_dt(payload["created_at"]),
                config=config,
                is_active=True,
                last_activity=parse_dt(payload["created_at"]),
            )
        elif event.type == WORKTREE_REMOVED:
            active.pop(event.payload["worktree_id"], None)

    manager._worktrees = active  # type: ignore[attr-defined]
    return manager


def discover_git_worktrees(repo_root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []

    paths: list[Path] = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line.split(" ", 1)[1]))
    return paths


def read_developer_identity(repo_root: Path) -> dict[str, str] | None:
    path = repo_root / ".reins" / ".developer"
    if not path.exists():
        return None

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return None

    identity: dict[str, str] = {}
    for line in content.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            identity[key.strip()] = value.strip()
        elif "name" not in identity:
            identity["name"] = line.strip()
    if "name" not in identity:
        return None
    return identity


def write_developer_identity(repo_root: Path, name: str) -> Path:
    path = repo_root / ".reins" / ".developer"
    path.parent.mkdir(parents=True, exist_ok=True)
    initialized_at = datetime.now(UTC).isoformat()
    path.write_text(
        f"name={name}\ninitialized_at={initialized_at}\n",
        encoding="utf-8",
    )
    return path


def workspace_dir(repo_root: Path, name: str) -> Path:
    return repo_root / ".reins" / "workspace" / name


def count_file_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def collect_workspace_info(repo_root: Path) -> WorkspaceInfo:
    identity = read_developer_identity(repo_root)
    developer = identity["name"] if identity else None
    if developer is None:
        return WorkspaceInfo(
            developer=None,
            workspace_dir=None,
            journal_files=[],
            active_journal=None,
            total_lines=0,
        )

    ws_dir = workspace_dir(repo_root, developer)
    journal_files = sorted(ws_dir.glob("journal-*.md"))
    active_journal = journal_files[-1] if journal_files else None
    total_lines = sum(count_file_lines(path) for path in journal_files)
    return WorkspaceInfo(
        developer=developer,
        workspace_dir=ws_dir,
        journal_files=journal_files,
        active_journal=active_journal,
        total_lines=total_lines,
    )


def git_status_summary(repo_root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def summarize_events(events: Iterable[EventEnvelope]) -> dict[str, Any]:
    type_counts = Counter(event.type for event in events)
    actor_counts = Counter(str(event.actor.value) for event in events)
    run_counts = Counter(event.run_id for event in events)
    return {
        "total": sum(type_counts.values()),
        "types": type_counts,
        "actors": actor_counts,
        "runs": run_counts,
    }


async def emit_cli_event(
    repo_root: Path,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> EventEnvelope:
    builder = EventBuilder(get_journal(repo_root))
    body = dict(payload)
    body.setdefault("source", "cli")
    return await builder.commit(run_id=run_id, event_type=event_type, payload=body)


async def emit_cli_error(
    repo_root: Path,
    run_id: str,
    command: str,
    error: Exception,
    payload: dict[str, Any] | None = None,
) -> EventEnvelope:
    body = {"command": command, "error": str(error), "source": "cli"}
    if payload:
        body.update(payload)
    return await emit_cli_event(repo_root, run_id, "cli.error", body)


def relpath(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path.resolve())


def load_task_context_messages(task_path: Path) -> dict[str, list[dict[str, Any]]]:
    messages: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for jsonl_file in sorted(task_path.glob("*.jsonl")):
        for line in jsonl_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            messages[jsonl_file.stem].append(json.loads(line))
    return dict(messages)


def print_error(message: str) -> None:
    console.print(f"[red]Error:[/red] {message}")


def exit_with_error(message: str, code: int = 1) -> None:
    print_error(message)
    raise typer.Exit(code=code)
