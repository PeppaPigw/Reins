"""Isolation types and configuration for worktree parallelism.

Defines IsolationLevel enum, WorktreeConfig, and WorktreeState.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class IsolationLevel(str, Enum):
    """Isolation level for subagent execution.

    Determines how agents are isolated from each other and the main repo.
    """

    NONE = "none"
    """No isolation - agent works in main repo (not recommended for parallel work)"""

    PROCESS = "process"
    """Process isolation only - separate process, same git state"""

    WORKTREE = "worktree"
    """Git worktree isolation - separate git state, independent work"""

    CONTAINER = "container"
    """Container isolation - full environment isolation (future)"""

    REMOTE = "remote"
    """Remote execution - agent runs on different machine (future)"""


@dataclass(frozen=True)
class WorktreeConfig:
    """Configuration for creating a worktree.

    Specifies how the worktree should be set up and what files to copy.
    """

    worktree_base_dir: Path
    """Base directory for worktrees (e.g., ../reins-worktrees/)"""

    worktree_name: str
    """Name for this worktree (used in path)"""

    branch_name: str
    """Git branch to create in the worktree"""

    base_branch: str
    """Base branch to create worktree from"""

    create_branch: bool = True
    """Whether to create a new branch (True) or use existing (False)"""

    copy_files: list[str] = field(default_factory=list)
    """Files to copy from main repo to worktree (e.g., ['.reins/.developer'])"""

    post_create_commands: list[str] = field(default_factory=list)
    """Shell commands to run after worktree creation (e.g., ['pnpm install'])"""

    verify_commands: list[str] = field(default_factory=list)
    """Shell commands to verify a worktree after creation (e.g., ['ruff check'])"""

    cleanup_on_success: bool = True
    """Whether to remove worktree after successful completion"""

    cleanup_on_failure: bool = False
    """Whether to remove worktree after failure"""

    @classmethod
    def default(
        cls,
        worktree_name: str,
        branch_name: str,
        base_dir: Path | None = None,
    ) -> WorktreeConfig:
        """Create a default worktree config.

        Args:
            worktree_name: Name for the worktree
            branch_name: Git branch name
            base_dir: Base directory (defaults to ../reins-worktrees/)

        Returns:
            WorktreeConfig with default settings
        """
        if base_dir is None:
            # Default to ../reins-worktrees/ relative to current repo
            base_dir = Path.cwd().parent / "reins-worktrees"

        return cls(
            worktree_base_dir=base_dir,
            worktree_name=worktree_name,
            branch_name=branch_name,
            base_branch="main",
            create_branch=True,
            copy_files=[".reins/.developer", ".trellis/.developer"],
            post_create_commands=[],
            verify_commands=[],
            cleanup_on_success=True,
            cleanup_on_failure=False,
        )


@dataclass
class WorktreeState:
    """Runtime state of a worktree.

    Tracks the current state of a worktree during its lifecycle.
    """

    worktree_id: str
    """Unique identifier for this worktree"""

    worktree_path: Path
    """Absolute path to the worktree directory"""

    branch_name: str
    """Git branch in the worktree"""

    base_branch: str
    """Base branch the worktree was created from"""

    agent_id: str
    """ID of the agent using this worktree"""

    task_id: str | None
    """Task ID if this worktree is for a specific task"""

    created_at: datetime
    """When the worktree was created"""

    config: WorktreeConfig
    """Configuration used to create this worktree"""

    is_active: bool = True
    """Whether the worktree is still active"""

    last_activity: datetime | None = None
    """Last time the worktree was accessed"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata"""

    def get_path(self) -> Path:
        """Get the worktree path."""
        return self.worktree_path

    def is_idle(self, idle_threshold_seconds: int = 3600) -> bool:
        """Check if worktree has been idle for too long.

        Args:
            idle_threshold_seconds: Seconds of inactivity to consider idle

        Returns:
            True if worktree is idle, False otherwise
        """
        if not self.last_activity:
            return False

        now = datetime.now(self.last_activity.tzinfo)
        idle_time = (now - self.last_activity).total_seconds()
        return idle_time > idle_threshold_seconds


@dataclass
class MergeStrategy:
    """Strategy for merging worktree changes back to main repo."""

    strategy: str
    """Merge strategy: 'merge', 'rebase', 'squash'"""

    target_branch: str
    """Branch to merge into (usually 'main')"""

    auto_merge: bool = False
    """Whether to merge automatically or require manual approval"""

    delete_branch_after_merge: bool = True
    """Whether to delete the worktree branch after merge"""
