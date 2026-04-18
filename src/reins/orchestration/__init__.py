"""Orchestration layer for multi-agent coordination."""

from reins.orchestration.orchestrator import (
    AgentHandle,
    AgentResult,
    ExecutionResult,
    Orchestrator,
)

__all__ = [
    "AgentHandle",
    "AgentResult",
    "ExecutionResult",
    "Orchestrator",
]

try:
    from reins.orchestration.agent_registry import AgentRegistry
except ModuleNotFoundError:
    AgentRegistry = None  # type: ignore[misc,assignment]
else:
    __all__.append("AgentRegistry")

try:
    from reins.orchestration.hooks import ContextInjectionHook
except ModuleNotFoundError:
    ContextInjectionHook = None  # type: ignore[misc,assignment]
else:
    __all__.append("ContextInjectionHook")

try:
    from reins.orchestration.subagent_manager import SubagentManager
except ModuleNotFoundError:
    SubagentManager = None  # type: ignore[misc,assignment]
else:
    __all__.append("SubagentManager")

try:
    from reins.orchestration.mcp_session import (
        OrchestrationMCPSession,
        OrchestrationMCPSessionManager,
    )
except ModuleNotFoundError:
    OrchestrationMCPSession = None  # type: ignore[misc,assignment]
    OrchestrationMCPSessionManager = None  # type: ignore[misc,assignment]
else:
    __all__.extend(["OrchestrationMCPSession", "OrchestrationMCPSessionManager"])
