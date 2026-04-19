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
except ImportError:
    AgentRegistry = None  # type: ignore[misc,assignment]
else:
    __all__.append("AgentRegistry")

try:
    from reins.orchestration.hooks import ContextInjectionHook
except ImportError:
    ContextInjectionHook = None  # type: ignore[misc,assignment]
else:
    __all__.append("ContextInjectionHook")

try:
    from reins.orchestration.subagent_manager import SubagentManager
except ImportError:
    SubagentManager = None  # type: ignore[misc,assignment]
else:
    __all__.append("SubagentManager")

try:
    from reins.orchestration.mcp_session import (
        OrchestrationMCPSession,
        OrchestrationMCPSessionManager,
    )
except ImportError:
    OrchestrationMCPSession = None  # type: ignore[misc,assignment]
    OrchestrationMCPSessionManager = None  # type: ignore[misc,assignment]
else:
    __all__.extend(["OrchestrationMCPSession", "OrchestrationMCPSessionManager"])

try:
    from reins.orchestration.pipeline import Pipeline, PipelineStage, StageType
    from reins.orchestration.types import PipelineResult, PipelineStatus, StageResult, StageStatus
    from reins.orchestration.coordinator import PipelineCoordinator
    from reins.orchestration.workflow import WorkflowExecutor
except ImportError:
    Pipeline = None  # type: ignore[misc,assignment]
    PipelineCoordinator = None  # type: ignore[misc,assignment]
    PipelineResult = None  # type: ignore[misc,assignment]
    PipelineStage = None  # type: ignore[misc,assignment]
    PipelineStatus = None  # type: ignore[misc,assignment]
    StageResult = None  # type: ignore[misc,assignment]
    StageStatus = None  # type: ignore[misc,assignment]
    StageType = None  # type: ignore[misc,assignment]
    WorkflowExecutor = None  # type: ignore[misc,assignment]
else:
    __all__.extend(
        [
            "Pipeline",
            "PipelineCoordinator",
            "PipelineResult",
            "PipelineStage",
            "PipelineStatus",
            "StageResult",
            "StageStatus",
            "StageType",
            "WorkflowExecutor",
        ]
    )
