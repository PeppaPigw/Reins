"""Skill capability encapsulation system."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reins.skill.catalog import SkillDescriptor


@dataclass
class SkillCapabilityRequest:
    """Request for skill capability execution."""

    skill_id: str
    capability: str
    args: dict[str, Any]
    run_id: str
    requested_by: str = "skill"


@dataclass
class SkillCapabilityGrant:
    """Grant for skill capability execution."""

    request_id: str
    skill_id: str
    capability: str
    granted: bool
    grant_id: str | None = None
    reason: str = ""


class SkillCapabilityWrapper:
    """Wraps skill capabilities with policy enforcement."""

    def __init__(self, descriptor: SkillDescriptor) -> None:
        self.descriptor = descriptor

    def can_execute(self, capability: str) -> bool:
        """Check if skill is allowed to execute capability."""
        return capability in self.descriptor.allowed_capabilities

    def create_request(
        self, capability: str, args: dict[str, Any], run_id: str
    ) -> SkillCapabilityRequest:
        """Create a capability request."""
        return SkillCapabilityRequest(
            skill_id=self.descriptor.skill_id,
            capability=capability,
            args=args,
            run_id=run_id,
        )
