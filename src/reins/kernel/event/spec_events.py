"""Spec-related event types for context injection system.

Events emitted when specs are registered, superseded, or deactivated.
These events are the source of truth for the ContextSpecProjection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SpecRegisteredEvent:
    """Event emitted when a spec is registered in the system.

    This is the primary event for adding new specs to the context injection
    system. The spec content and metadata are stored in the event payload.
    """

    spec_id: str
    """Unique identifier for this spec (e.g., 'backend.error-handling')"""

    spec_type: str
    """Type of spec: 'standing_law', 'task_contract', or 'spec_shard'"""

    scope: str
    """Scope of the spec: 'workspace' or 'task:{task_id}'"""

    content: str
    """The actual spec content (markdown or YAML)"""

    applicability: dict[str, Any]
    """Applicability criteria for when this spec should be included.

    Fields:
    - task_type: str | None - Apply to specific task types (e.g., 'backend', 'frontend')
    - run_phase: str | None - Apply to specific run phases (e.g., 'implement', 'check')
    - actor_type: str | None - Apply to specific actor types (e.g., 'implement-agent')
    - path_pattern: str | None - Apply when working on files matching pattern
    """

    required_capabilities: list[str]
    """Capabilities required to see this spec (visibility filtering).

    Example: ['fs:write', 'git:commit']
    If agent doesn't have these capabilities, spec won't be shown.
    """

    visibility_tier: int
    """Visibility tier (0=always visible, 1=standard, 2=advanced, 3=expert).

    Higher tiers require explicit opt-in. Used to prevent context overload.
    """

    precedence: int
    """Precedence for conflict resolution (higher = more important).

    When multiple specs cover the same topic, higher precedence wins.
    Default: 100 (standard), 200 (high priority), 50 (low priority).
    """

    source_path: str | None = None
    """Original file path if imported from filesystem"""

    registered_by: str = "system"
    """Who registered this spec: 'system', 'admin', or 'user:{user_id}'"""

    token_count: int = 0
    """Approximate token count for budget allocation"""


@dataclass(frozen=True)
class SpecSupersededEvent:
    """Event emitted when a spec is superseded by a newer version.

    The old spec is marked as superseded and will be excluded from
    context resolution. The new spec should be registered separately.
    """

    spec_id: str
    """ID of the spec being superseded"""

    superseded_by: str
    """ID of the new spec that replaces this one"""

    reason: str | None = None
    """Optional reason for superseding"""


@dataclass(frozen=True)
class SpecDeactivatedEvent:
    """Event emitted when a spec is deactivated (soft delete).

    Deactivated specs are excluded from context resolution but remain
    in the journal for audit purposes.
    """

    spec_id: str
    """ID of the spec being deactivated"""

    reason: str | None = None
    """Optional reason for deactivation"""

    deactivated_by: str = "system"
    """Who deactivated this spec"""


# Event type constants for registration
SPEC_REGISTERED = "spec.registered"
SPEC_SUPERSEDED = "spec.superseded"
SPEC_DEACTIVATED = "spec.deactivated"
