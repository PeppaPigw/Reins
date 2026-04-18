from __future__ import annotations

import asyncio
import json
import subprocess
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

from reins.cli import utils
from reins.cli.main import app
from reins.context.compiler import ContextCompiler
from reins.execution.dispatcher import ExecutionDispatcher
from reins.export.task_exporter import TaskExporter
from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal
from reins.kernel.orchestrator import RunOrchestrator
from reins.kernel.snapshot.store import SnapshotStore
from reins.memory.checkpoint import CheckpointStore
from reins.policy.approval.ledger import ApprovalLedger
from reins.policy.engine import PolicyEngine
from reins.task.context_jsonl import ContextJSONL, ContextMessage
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection
from typer.testing import CliRunner


@dataclass
class OrchestratorBundle:
    repo_root: Path
    journal: EventJournal
    snapshots: SnapshotStore
    checkpoints: CheckpointStore
    policy: PolicyEngine
    approvals: ApprovalLedger
    dispatcher: ExecutionDispatcher
    context: ContextCompiler
    task_projection: TaskContextProjection
    task_manager: TaskManager
    orchestrator: RunOrchestrator


@dataclass
class IntegrationHarness:
    repo_root: Path
    monkeypatch: MonkeyPatch

    def invoke(self, args: list[str]):
        self.monkeypatch.chdir(self.repo_root)
        runner = CliRunner()
        return runner.invoke(app, args)

    def load_events(
        self,
        *,
        event_type: str | None = None,
        run_id: str | None = None,
    ) -> list[EventEnvelope]:
        events = utils.load_all_events(self.repo_root)
        if event_type is not None:
            events = [event for event in events if event.type == event_type]
        if run_id is not None:
            events = [event for event in events if event.run_id == run_id]
        return events

    def task_dir(self, task_id: str) -> Path:
        return self.repo_root / ".reins" / "tasks" / task_id

    def task_ids(self) -> list[str]:
        tasks_dir = self.repo_root / ".reins" / "tasks"
        if not tasks_dir.exists():
            return []
        return sorted(path.name for path in tasks_dir.iterdir() if path.is_dir())

    def latest_task_id(self) -> str:
        task_ids = self.task_ids()
        assert task_ids
        return task_ids[-1]

    def current_task_id(self) -> str | None:
        return utils.get_current_task_id(self.repo_root)


def init_git_repo(repo_root: Path) -> str:
    subprocess.run(["git", "init"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_root, check=True)
    (repo_root / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_root, check=True)
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def build_repo(tmp_path: Path, *, git: bool = True) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    for path in (
        repo_root / ".reins",
        repo_root / ".reins" / "tasks",
        repo_root / ".reins" / "spec",
        repo_root / ".reins" / "workspace",
        repo_root / ".trellis",
    ):
        path.mkdir(parents=True, exist_ok=True)
    if git:
        init_git_repo(repo_root)
    return repo_root


def ensure_base_specs(
    repo_root: Path,
    *,
    package: str | None = None,
    layers: tuple[str, ...] = (),
) -> None:
    spec_root = repo_root / ".reins" / "spec"
    (spec_root / "backend").mkdir(parents=True, exist_ok=True)
    (spec_root / "guides").mkdir(parents=True, exist_ok=True)
    (spec_root / "backend" / "index.md").write_text(
        "# Backend Rules\n\n## Pre-Development Checklist\n\n- [ ] Read backend guidance.\n",
        encoding="utf-8",
    )
    (spec_root / "guides" / "index.md").write_text(
        "# Guides\n\n## Pre-Development Checklist\n\n- [ ] Read cross-cutting guidance.\n",
        encoding="utf-8",
    )
    if package is None:
        return
    package_dir = spec_root / package
    package_dir.mkdir(parents=True, exist_ok=True)
    if not (package_dir / "index.md").exists():
        checklist = "\n".join(
            f"- [ ] {layer}/index.md - Fill in the {layer} guidance." for layer in layers
        )
        (package_dir / "index.md").write_text(
            "\n".join(
                [
                    f"# {package.title()} Specifications",
                    "",
                    "## Pre-Development Checklist",
                    "",
                    checklist or "- [ ] Add package guidance.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    for layer in layers:
        layer_dir = package_dir / layer
        layer_dir.mkdir(parents=True, exist_ok=True)
        (layer_dir / "index.md").write_text(
            f"# {package.title()} / {layer.title()}\n\n## Pre-Development Checklist\n\n- [ ] Add rules.\n",
            encoding="utf-8",
        )


def write_worktree_config(
    repo_root: Path,
    *,
    worktree_dir: str = "../parallel-worktrees",
    copy_files: list[str] | None = None,
    post_create: list[str] | None = None,
    verify: list[str] | None = None,
) -> Path:
    copy_files = copy_files or [".reins/.developer"]
    post_create = post_create or ["test -f .reins/.developer"]
    verify = verify or ["test -f .reins/.developer"]
    config = textwrap.dedent(
        f"""
        worktree_dir: {worktree_dir}
        copy:
        """
    ).strip("\n")
    for item in copy_files:
        config += f"\n  - {item}"
    if post_create:
        config += "\npost_create:"
        for item in post_create:
            config += f"\n  - {item}"
    if verify:
        config += "\nverify:"
        for item in verify:
            config += f"\n  - {item}"
    path = repo_root / ".reins" / "worktree.yaml"
    path.write_text(config + "\n", encoding="utf-8")
    return path


async def load_run_events(journal: EventJournal, run_id: str) -> list[EventEnvelope]:
    return [event async for event in journal.read_from(run_id)]


async def wait_for_event(
    journal: EventJournal,
    run_id: str,
    event_type: str,
    timeout: float = 5.0,
) -> EventEnvelope:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = [event async for event in journal.read_from(run_id)]
        for event in events:
            if event.type == event_type:
                return event
        await asyncio.sleep(0.05)
    raise AssertionError(f"Timed out waiting for event {event_type!r} in run {run_id!r}")


def assert_event_types_in_order(
    events: list[EventEnvelope] | list[str],
    expected_types: list[str],
) -> None:
    actual_types = [event.type if isinstance(event, EventEnvelope) else event for event in events]
    cursor = 0
    for expected in expected_types:
        try:
            cursor = actual_types.index(expected, cursor) + 1
        except ValueError as exc:
            raise AssertionError(
                f"Expected event sequence {expected_types}, actual {actual_types}"
            ) from exc


def read_jsonl_messages(file_path: Path) -> list[ContextMessage]:
    return ContextJSONL.read_messages(file_path)


def assert_jsonl_valid(file_path: Path) -> list[ContextMessage]:
    valid, errors = ContextJSONL.validate_jsonl(file_path)
    assert valid, "\n".join(errors)
    return read_jsonl_messages(file_path)


async def create_test_task(
    repo_root: Path,
    title: str,
    *,
    journal: EventJournal | None = None,
    projection: TaskContextProjection | None = None,
    run_id: str = "test-task-run",
    task_type: str = "backend",
    prd_content: str | None = None,
    acceptance_criteria: list[str] | None = None,
    created_by: str = "test",
    assignee: str = "test",
    metadata: dict[str, Any] | None = None,
) -> str:
    journal = journal or utils.get_journal(repo_root)
    projection = projection or utils.rebuild_task_projection(repo_root)
    manager = TaskManager(journal, projection, run_id=run_id)
    task_id = await manager.create_task(
        title=title,
        task_type=task_type,
        prd_content=prd_content or title,
        acceptance_criteria=acceptance_criteria or [],
        created_by=created_by,
        assignee=assignee,
        metadata=metadata or {},
    )
    TaskExporter(projection, repo_root / ".reins" / "tasks").export_task(task_id)
    return task_id


async def simulate_agent_work(
    worktree_path: Path,
    *,
    file_name: str,
    content: str,
    duration: float = 0.01,
) -> Path:
    await asyncio.sleep(duration)
    target = worktree_path / file_name
    target.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(target.write_text, content, "utf-8")
    return target


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def make_harness(tmp_path: Path, monkeypatch: MonkeyPatch, *, git: bool = True) -> IntegrationHarness:
    repo_root = build_repo(tmp_path, git=git)
    return IntegrationHarness(repo_root=repo_root, monkeypatch=monkeypatch)


def build_orchestrator_bundle(
    tmp_path: Path,
    *,
    repo_root: Path | None = None,
    run_id: str = "test-run",
) -> OrchestratorBundle:
    repo_root = repo_root or build_repo(tmp_path, git=False)
    journal = EventJournal(repo_root / ".reins" / "journal.jsonl")
    snapshots = SnapshotStore(tmp_path / "snapshots")
    checkpoints = CheckpointStore(tmp_path / "checkpoints")
    policy = PolicyEngine()
    approvals = ApprovalLedger(tmp_path / "approvals")
    dispatcher = ExecutionDispatcher()
    context = ContextCompiler()
    task_projection = TaskContextProjection()
    task_manager = TaskManager(journal, task_projection, run_id=run_id)
    orchestrator = RunOrchestrator(
        journal=journal,
        snapshot_store=snapshots,
        checkpoint_store=checkpoints,
        policy_engine=policy,
        context_compiler=context,
        approval_ledger=approvals,
        dispatcher=dispatcher,
        task_manager=task_manager,
        task_projection=task_projection,
    )
    return OrchestratorBundle(
        repo_root=repo_root,
        journal=journal,
        snapshots=snapshots,
        checkpoints=checkpoints,
        policy=policy,
        approvals=approvals,
        dispatcher=dispatcher,
        context=context,
        task_projection=task_projection,
        task_manager=task_manager,
        orchestrator=orchestrator,
    )
