"""Subagent management — spawn, supervise, and coordinate child runs."""

from reins.isolation.types import IsolationLevel

__all__ = [
    "IsolationLevel",
    "SubagentManager",
    "SubagentSpec",
    "SubagentStatus",
]

try:
    from reins.subagent.manager import SubagentManager, SubagentSpec, SubagentStatus
except ImportError:
    SubagentManager = None  # type: ignore[misc,assignment]
    SubagentSpec = None  # type: ignore[misc,assignment]
    SubagentStatus = None  # type: ignore[misc,assignment]
