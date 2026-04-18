"""Worktree-related event types for worktree parallelism system.

Events emitted when worktrees are created, removed, or merged.
These events are the source of truth for worktree state tracking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class WorktreeCreatedEvent:
    """Event emitted when a worktree is created.

    This is the primary event for tracking worktree lifecycle.
    """

    worktree_id: str
    """Unique identifier for this worktree"""

    worktree_path: str
    """Absolute path to the worktree directory"""

    branch_name: str
    """Git branch created in the worktree"""

    base_branch: str
    """Base branch the worktree was created from"""

    agent_id: str
    """ID of the agent using this worktree"""

    task_id: str | None
    """Task ID if this worktree is for a specific task"""

    created_at: datetime
    """When the worktree was created"""

    config: dict[str, Any]
    """Worktree configuration (copied files, post-create commands, etc.)"""


@dataclass(frozen=True)
class WorktreeRemovedEvent:
    """Event emitted when a worktree is removed.

    Marks the worktree as cleaned up and no longer available.
    """

    worktree_id: str
    """ID of the worktree being removed"""

    removed_at: datetime
    """When the worktree was removed"""

    removed_by: str
    """Who removed the worktree ('system', 'agent', 'user')"""

    reason: str | None = None
    """Optional reason for removal"""

    force: bool = False
    """Whether removal was forced (discarding changes)"""


@dataclass(frozen=True)
class WorktreeMergedEvent:
    """Event emitted when a worktree's changes are merged.

    Records the merge operation before worktree removal.
    """

    worktree_id: str
    """ID of the worktree being merged"""

    target_branch: str
    """Branch that changes were merged into"""

    merge_strategy: str
    """Merge strategy used ('merge', 'rebase', 'squash')"""

    merged_at: datetime
    """When the merge occurred"""

    merged_by: str
    """Who performed the merge"""

    commit_sha: str | None = None
    """Commit SHA of the merge (if available)"""


# Event type constants for registration
WORKTREE_CREATED = "worktree.created"
WORKTREE_REMOVED = "worktree.removed"
WORKTREE_MERGED = "worktree.merged"
