"""Worktree manager — creates, removes, and merges git worktrees.

The WorktreeManager handles all git worktree operations and emits
events to track worktree lifecycle.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reins.isolation.agent_registry import AgentRegistry
from reins.isolation.types import MergeStrategy, WorktreeConfig, WorktreeState
from reins.isolation.worktree_config import load_worktree_config
from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal
from reins.kernel.event.worktree_events import (
    WORKTREE_VERIFIED,
    WORKTREE_CREATED,
    WORKTREE_MERGED,
    WORKTREE_REMOVED,
)
from reins.kernel.types import Actor


class WorktreeError(Exception):
    """Raised when worktree operations fail."""

    pass


class WorktreeManager:
    """Manages git worktree lifecycle: create, remove, merge.

    This is the command side for worktree operations.
    It emits events to the journal for audit trail.
    """

    def __init__(
        self,
        journal: EventJournal,
        run_id: str,
        repo_root: Path | None = None,
        worktree_config_path: Path | None = None,
        agent_registry: AgentRegistry | None = None,
    ) -> None:
        self._journal = journal
        self._run_id = run_id
        self._repo_root = repo_root or Path.cwd()
        self._worktree_config_path = worktree_config_path
        self._agent_registry = agent_registry

        # Active worktrees: worktree_id -> WorktreeState
        self._worktrees: dict[str, WorktreeState] = {}

    async def create_worktree(
        self,
        agent_id: str,
        task_id: str | None,
        config: WorktreeConfig,
    ) -> WorktreeState:
        """Create a new git worktree.

        Args:
            agent_id: ID of the agent that will use this worktree
            task_id: Task ID if this worktree is for a specific task
            config: Worktree configuration

        Returns:
            WorktreeState for the created worktree

        Raises:
            WorktreeError: If worktree creation fails
        """
        # Generate worktree ID
        worktree_id = f"{agent_id}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"

        # Determine worktree path
        worktree_path = config.worktree_base_dir / config.worktree_name

        # Ensure base directory exists
        config.worktree_base_dir.mkdir(parents=True, exist_ok=True)
        worktree_created = False

        try:
            # Create git worktree
            await self._git_worktree_add(
                worktree_path,
                config.branch_name,
                config.base_branch,
                config.create_branch,
            )
            worktree_created = True

            # Copy files
            for file_path in config.copy_files:
                await self._copy_file(
                    self._repo_root / file_path,
                    worktree_path / file_path,
                )

            # Run post-create commands
            for command in config.post_create_commands:
                await self._run_command(command, cwd=worktree_path)

            # Create worktree state
            now = datetime.now(UTC)
            state = WorktreeState(
                worktree_id=worktree_id,
                worktree_path=worktree_path,
                branch_name=config.branch_name,
                base_branch=config.base_branch,
                agent_id=agent_id,
                task_id=task_id,
                created_at=now,
                config=config,
                is_active=True,
                last_activity=now,
            )

            # Store state
            self._worktrees[worktree_id] = state

            # Emit event
            payload = {
                "worktree_id": worktree_id,
                "worktree_path": str(worktree_path),
                "branch_name": config.branch_name,
                "base_branch": config.base_branch,
                "agent_id": agent_id,
                "task_id": task_id,
                "created_at": now.isoformat(),
                "config": {
                    "copy_files": config.copy_files,
                    "post_create_commands": config.post_create_commands,
                    "verify_commands": config.verify_commands,
                    "cleanup_on_success": config.cleanup_on_success,
                },
            }

            event = EventEnvelope(
                run_id=self._run_id,
                actor=Actor.runtime,
                type=WORKTREE_CREATED,
                payload=payload,
            )

            await self._journal.append(event)

            return state

        except Exception as e:
            if worktree_created or worktree_path.exists():
                try:
                    await self._git_worktree_remove(worktree_path, force=True)
                except Exception:
                    pass
            raise WorktreeError(f"Failed to create worktree: {e}") from e

    async def create_worktree_for_agent(
        self,
        agent_id: str,
        task_id: str | None,
        *,
        branch_name: str,
        base_branch: str,
        create_branch: bool = True,
        worktree_name: str | None = None,
        cleanup_on_success: bool = True,
        cleanup_on_failure: bool = False,
        config_path: Path | None = None,
        extra_copy_files: list[str] | None = None,
    ) -> WorktreeState:
        """Create an agent worktree using repo-level YAML defaults."""
        template = load_worktree_config(
            self._repo_root,
            path=config_path or self._worktree_config_path,
        )
        runtime_config = template.build_runtime_config(
            worktree_name=worktree_name or self._default_worktree_name(agent_id, task_id),
            branch_name=branch_name,
            base_branch=base_branch,
            create_branch=create_branch,
            cleanup_on_success=cleanup_on_success,
            cleanup_on_failure=cleanup_on_failure,
            extra_copy_files=self._default_identity_files() + list(extra_copy_files or []),
        )

        state = await self.create_worktree(
            agent_id=agent_id,
            task_id=task_id,
            config=runtime_config,
        )

        try:
            if task_id is not None:
                await self._write_current_task_files(state.worktree_path, task_id)

            registry = self._get_agent_registry(create_default=True)
            if registry is not None:
                await registry.register(
                    agent_id=agent_id,
                    worktree_id=state.worktree_id,
                    task_id=task_id,
                    status="running",
                )

            return state
        except Exception as exc:
            try:
                await self.remove_worktree(
                    state.worktree_id,
                    force=True,
                    removed_by="system",
                    reason=f"agent worktree setup failed: {exc}",
                )
            except Exception:
                pass
            raise WorktreeError(f"Failed to create agent worktree: {exc}") from exc

    async def verify_worktree(self, worktree_id: str) -> list[dict[str, Any]]:
        """Run configured verification commands for a worktree."""
        state = self._worktrees.get(worktree_id)
        if not state:
            raise WorktreeError(f"Worktree not found: {worktree_id}")

        registry = self._get_agent_registry(create_default=False)
        if registry is not None:
            await registry.heartbeat(state.agent_id, status="verifying")

        results: list[dict[str, Any]] = []
        success = True
        for command in state.config.verify_commands:
            result = await self._run_command_capture(command, cwd=state.worktree_path)
            results.append(result)
            if result["returncode"] != 0:
                success = False
                break

        payload = {
            "worktree_id": worktree_id,
            "verified_at": datetime.now(UTC).isoformat(),
            "success": success,
            "results": results,
        }
        await self._journal.append(
            EventEnvelope(
                run_id=self._run_id,
                actor=Actor.runtime,
                type=WORKTREE_VERIFIED,
                payload=payload,
            )
        )

        if registry is not None:
            await registry.heartbeat(
                state.agent_id,
                status="verified" if success else "verify_failed",
            )

        if not success:
            failed = results[-1]
            raise WorktreeError(
                f"Verification failed for {worktree_id}: {failed['command']}\n"
                f"Stderr: {failed['stderr']}"
            )

        return results

    async def cleanup_agent_worktree(
        self,
        worktree_id: str,
        *,
        force: bool = False,
        removed_by: str = "system",
        reason: str | None = None,
    ) -> None:
        """Remove a worktree and unregister its agent if tracked."""
        await self.remove_worktree(
            worktree_id,
            force=force,
            removed_by=removed_by,
            reason=reason,
        )

    async def remove_worktree(
        self,
        worktree_id: str,
        force: bool = False,
        removed_by: str = "system",
        reason: str | None = None,
    ) -> None:
        """Remove a git worktree.

        Args:
            worktree_id: ID of the worktree to remove
            force: Whether to force removal (discard changes)
            removed_by: Who is removing the worktree
            reason: Optional reason for removal

        Raises:
            WorktreeError: If worktree removal fails
        """
        state = self._worktrees.get(worktree_id)
        if not state:
            raise WorktreeError(f"Worktree not found: {worktree_id}")

        try:
            # Remove git worktree
            await self._git_worktree_remove(state.worktree_path, force=force)

            # Mark as inactive
            state.is_active = False

            # Emit event
            payload = {
                "worktree_id": worktree_id,
                "removed_at": datetime.now(UTC).isoformat(),
                "removed_by": removed_by,
                "reason": reason,
                "force": force,
            }

            event = EventEnvelope(
                run_id=self._run_id,
                actor=Actor.runtime,
                type=WORKTREE_REMOVED,
                payload=payload,
            )

            await self._journal.append(event)

            registry = self._get_agent_registry(create_default=False)
            if registry is not None:
                try:
                    await registry.unregister(state.agent_id, final_status="removed")
                except Exception:
                    pass

            # Remove from active worktrees
            del self._worktrees[worktree_id]

        except Exception as e:
            raise WorktreeError(f"Failed to remove worktree: {e}") from e

    async def merge_worktree(
        self,
        worktree_id: str,
        strategy: MergeStrategy,
        merged_by: str = "system",
    ) -> str | None:
        """Merge worktree changes back to main repo.

        Args:
            worktree_id: ID of the worktree to merge
            strategy: Merge strategy to use
            merged_by: Who is performing the merge

        Returns:
            Commit SHA of the merge (if available)

        Raises:
            WorktreeError: If merge fails
        """
        state = self._worktrees.get(worktree_id)
        if not state:
            raise WorktreeError(f"Worktree not found: {worktree_id}")

        try:
            # Switch to target branch in main repo
            await self._git_checkout(strategy.target_branch, cwd=self._repo_root)

            # Perform merge based on strategy
            if strategy.strategy == "merge":
                commit_sha = await self._git_merge(
                    state.branch_name, cwd=self._repo_root
                )
            elif strategy.strategy == "rebase":
                commit_sha = await self._git_rebase(
                    state.branch_name, cwd=self._repo_root
                )
            elif strategy.strategy == "squash":
                commit_sha = await self._git_merge_squash(
                    state.branch_name, cwd=self._repo_root
                )
            else:
                raise WorktreeError(f"Unknown merge strategy: {strategy.strategy}")

            # Emit event
            payload = {
                "worktree_id": worktree_id,
                "target_branch": strategy.target_branch,
                "merge_strategy": strategy.strategy,
                "merged_at": datetime.now(UTC).isoformat(),
                "merged_by": merged_by,
                "commit_sha": commit_sha,
            }

            event = EventEnvelope(
                run_id=self._run_id,
                actor=Actor.runtime,
                type=WORKTREE_MERGED,
                payload=payload,
            )

            await self._journal.append(event)

            return commit_sha

        except Exception as e:
            raise WorktreeError(f"Failed to merge worktree: {e}") from e

    def list_worktrees(self) -> list[WorktreeState]:
        """List all active worktrees."""
        return [w for w in self._worktrees.values() if w.is_active]

    def get_worktree(self, worktree_id: str) -> WorktreeState | None:
        """Get worktree state by ID."""
        return self._worktrees.get(worktree_id)

    def detect_orphans(self) -> list[Path]:
        """Detect orphaned worktrees (exist on disk but not tracked).

        Returns:
            List of paths to orphaned worktree directories
        """
        orphans: list[Path] = []

        # Get all worktrees from git
        try:
            result = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=self._repo_root,
                capture_output=True,
                text=True,
                check=True,
            )

            # Parse git worktree list output
            git_worktrees: set[Path] = set()
            for line in result.stdout.split("\n"):
                if line.startswith("worktree "):
                    path = Path(line.split(" ", 1)[1])
                    git_worktrees.add(path)

            # Check tracked worktrees
            tracked_paths = {w.worktree_path for w in self._worktrees.values()}

            # Find orphans: in git but not tracked
            for git_path in git_worktrees:
                if git_path != self._repo_root and git_path not in tracked_paths:
                    orphans.append(git_path)

        except subprocess.CalledProcessError:
            # Git command failed, return empty list
            pass

        return orphans

    async def cleanup_idle(self, idle_threshold_seconds: int = 3600) -> list[str]:
        """Clean up idle worktrees.

        Args:
            idle_threshold_seconds: Seconds of inactivity before cleanup

        Returns:
            List of worktree IDs that were cleaned up
        """
        cleaned_up: list[str] = []

        for worktree_id, state in list(self._worktrees.items()):
            if state.is_idle(idle_threshold_seconds):
                try:
                    await self.remove_worktree(
                        worktree_id,
                        force=False,
                        removed_by="system",
                        reason="Idle timeout",
                    )
                    cleaned_up.append(worktree_id)
                except WorktreeError:
                    # Skip if removal fails (might have uncommitted changes)
                    pass

        return cleaned_up

    async def cleanup_orphans(self, force: bool = False) -> list[Path]:
        """Clean up orphaned worktrees.

        Args:
            force: Whether to force removal (discard changes)

        Returns:
            List of paths that were cleaned up
        """
        orphans = self.detect_orphans()
        cleaned_up: list[Path] = []

        for orphan_path in orphans:
            try:
                await self._git_worktree_remove(orphan_path, force=force)
                cleaned_up.append(orphan_path)
            except WorktreeError:
                # Skip if removal fails
                pass

        return cleaned_up

    # Git operations

    async def _git_worktree_add(
        self,
        path: Path,
        branch: str,
        base_branch: str,
        create_branch: bool,
    ) -> None:
        """Add a git worktree."""
        cmd = ["git", "worktree", "add"]

        if create_branch:
            cmd.extend(["-b", branch])

        cmd.extend([str(path), base_branch if create_branch else branch])

        await self._run_command(" ".join(cmd), cwd=self._repo_root)

    async def _git_worktree_remove(self, path: Path, force: bool = False) -> None:
        """Remove a git worktree."""
        cmd = ["git", "worktree", "remove", str(path)]

        if force:
            cmd.append("--force")

        await self._run_command(" ".join(cmd), cwd=self._repo_root)

    async def _git_checkout(self, branch: str, cwd: Path) -> None:
        """Checkout a git branch."""
        await self._run_command(f"git checkout {branch}", cwd=cwd)

    async def _git_merge(self, branch: str, cwd: Path) -> str | None:
        """Merge a branch."""
        await self._run_command(f"git merge {branch}", cwd=cwd)
        return await self._get_current_commit(cwd)

    async def _git_rebase(self, branch: str, cwd: Path) -> str | None:
        """Rebase onto a branch."""
        await self._run_command(f"git rebase {branch}", cwd=cwd)
        return await self._get_current_commit(cwd)

    async def _git_merge_squash(self, branch: str, cwd: Path) -> str | None:
        """Squash merge a branch."""
        await self._run_command(f"git merge --squash {branch}", cwd=cwd)
        await self._run_command('git commit -m "Squash merge"', cwd=cwd)
        return await self._get_current_commit(cwd)

    async def _get_current_commit(self, cwd: Path) -> str | None:
        """Get current commit SHA."""
        try:
            result = await self._run_command("git rev-parse HEAD", cwd=cwd)
            return result.strip() if result else None
        except Exception:
            return None

    # Utility methods

    async def _copy_file(self, src: Path, dest: Path) -> None:
        """Copy a file from src to dest."""
        if not src.exists():
            return

        dest.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy2, src, dest)

    async def _write_current_task_files(self, worktree_path: Path, task_id: str) -> None:
        """Write current-task markers in the worktree for Reins and Trellis hooks."""
        task_pointer = self._resolve_task_pointer(task_id)
        for marker in (".reins/.current-task", ".trellis/.current-task"):
            target = worktree_path / marker
            target.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                target.write_text,
                f"{task_pointer}\n",
                "utf-8",
            )

    async def _run_command(self, command: str, cwd: Path) -> str:
        """Run a shell command."""
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise WorktreeError(
                f"Command failed: {command}\n"
                f"Exit code: {proc.returncode}\n"
                f"Stderr: {stderr.decode()}"
            )

        return stdout.decode()

    async def _run_command_capture(self, command: str, cwd: Path) -> dict[str, Any]:
        """Run a shell command and capture output without raising."""
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return {
            "command": command,
            "returncode": proc.returncode,
            "stdout": stdout.decode(),
            "stderr": stderr.decode(),
        }

    def _get_agent_registry(self, create_default: bool) -> AgentRegistry | None:
        if self._agent_registry is not None:
            return self._agent_registry

        default_path = self._repo_root / ".reins" / "registry.json"
        if create_default or default_path.exists():
            self._agent_registry = AgentRegistry(
                path=default_path,
                journal=self._journal,
                run_id=self._run_id,
            )
        return self._agent_registry

    def _default_identity_files(self) -> list[str]:
        return [".reins/.developer", ".trellis/.developer"]

    def _default_worktree_name(self, agent_id: str, task_id: str | None) -> str:
        base = task_id or agent_id
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-")
        normalized = normalized or "agent-worktree"
        suffix = re.sub(r"[^A-Za-z0-9._-]+", "-", agent_id[:8]).strip("-")
        suffix = suffix or "agent"
        return f"{normalized}-{suffix}"

    def _resolve_task_pointer(self, task_id: str) -> str:
        candidates = (
            Path(".reins/tasks") / task_id,
            Path(".trellis/tasks") / task_id,
        )
        for candidate in candidates:
            if (self._repo_root / candidate).exists():
                return str(candidate)
        return str(candidates[0])
