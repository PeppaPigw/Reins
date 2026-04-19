"""Command-based task lifecycle hooks from `.reins/config.yaml`."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from reins.config.types import ReinsConfig


@dataclass(frozen=True)
class HookCommandResult:
    """Outcome of a single hook command."""

    command: str
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class HookExecutor:
    """Execute configured task lifecycle hooks.

    Hook failures are collected and returned but never raised, so task
    operations can continue even when an integration hook is broken.
    """

    def __init__(
        self,
        repo_root: Path,
        config: ReinsConfig,
        *,
        timeout_seconds: int = 30,
    ) -> None:
        self.repo_root = repo_root
        self.reins_root = repo_root / ".reins"
        self.config = config
        self.timeout_seconds = timeout_seconds

    def execute_after_create(self, task_id: str) -> list[HookCommandResult]:
        """Execute hooks after a task is created."""
        return self._execute_hooks(self.config.hooks.after_create, task_id=task_id)

    def execute_after_start(self, task_id: str) -> list[HookCommandResult]:
        """Execute hooks after a task is started."""
        return self._execute_hooks(self.config.hooks.after_start, task_id=task_id)

    def execute_after_archive(self, task_id: str) -> list[HookCommandResult]:
        """Execute hooks after a task is archived."""
        return self._execute_hooks(self.config.hooks.after_archive, task_id=task_id)

    def _execute_hooks(
        self,
        commands: list[str],
        *,
        task_id: str,
    ) -> list[HookCommandResult]:
        if not commands:
            return []

        task_json_path = self.reins_root / "tasks" / task_id / "task.json"
        env = {
            **os.environ,
            "TASK_ID": task_id,
            "TASK_JSON_PATH": str(task_json_path),
        }

        results: list[HookCommandResult] = []
        for command in commands:
            try:
                completed = subprocess.run(
                    command,
                    shell=True,
                    cwd=self.repo_root,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
                results.append(
                    HookCommandResult(
                        command=command,
                        returncode=completed.returncode,
                        stdout=completed.stdout,
                        stderr=completed.stderr,
                    )
                )
            except subprocess.TimeoutExpired as exc:
                results.append(
                    HookCommandResult(
                        command=command,
                        returncode=-1,
                        stdout=_ensure_text(exc.stdout),
                        stderr=_ensure_text(exc.stderr),
                        timed_out=True,
                    )
                )
            except OSError as exc:
                results.append(
                    HookCommandResult(
                        command=command,
                        returncode=-1,
                        stderr=str(exc),
                    )
                )
        return results


def _ensure_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
