"""Kernel Runtime: unified assembly of all safety and coordination components."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from reins.event_bus import EventBus
from reins.kernel.health import KernelHealthMonitor
from reins.reactive_mesh import ReactiveMesh
from reins.safety_pipeline import (
    PipelineConfig,
    PipelineMode,
    PipelineStage,
    SafetyPipeline,
    StageVerdict,
)


@dataclass
class RuntimeConfig:
    state_dir: Path | None = None
    pipeline_mode: PipelineMode = PipelineMode.STRICT
    pipeline_stages: list[PipelineStage] = field(default_factory=lambda: [
        PipelineStage.IDENTITY,
        PipelineStage.RESOURCE_CHECK,
        PipelineStage.POLICY,
        PipelineStage.BEHAVIOR_CHECK,
    ])
    max_retries: int = 3
    bus_replay_enabled: bool = True


class KernelRuntime:
    """Assembles and wires all kernel components into a unified runtime.

    Single entry point for agent action evaluation with full safety,
    event propagation, and reactive response.
    """

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self._config = config or RuntimeConfig()
        self._bus = EventBus(max_retries=self._config.max_retries)
        self._pipeline = SafetyPipeline(PipelineConfig(
            stages=self._config.pipeline_stages,
            mode=self._config.pipeline_mode,
        ))
        self._mesh = ReactiveMesh(self._bus)
        self._health = KernelHealthMonitor(self._bus)
        self._boot_hooks: list[Callable[[], None]] = []
        self._shutdown_hooks: list[Callable[[], None]] = []
        self._booted = False

        self._pipeline.add_listener(self._on_pipeline_event)

    @property
    def bus(self) -> EventBus:
        return self._bus

    @property
    def pipeline(self) -> SafetyPipeline:
        return self._pipeline

    @property
    def mesh(self) -> ReactiveMesh:
        return self._mesh

    @property
    def health(self) -> KernelHealthMonitor:
        return self._health

    @property
    def is_booted(self) -> bool:
        return self._booted

    def on_boot(self, hook: Callable[[], None]) -> None:
        self._boot_hooks.append(hook)

    def on_shutdown(self, hook: Callable[[], None]) -> None:
        self._shutdown_hooks.append(hook)

    def boot(self) -> None:
        for hook in self._boot_hooks:
            hook()
        self._booted = True
        self._bus.publish_sync("kernel.booted", "kernel")

    def shutdown(self) -> None:
        self._bus.publish_sync("kernel.shutdown", "kernel")
        for hook in self._shutdown_hooks:
            hook()
        self._booted = False

    async def evaluate(self, agent_id: str, context: dict[str, Any]) -> Any:
        if self._mesh.is_quarantined(agent_id):
            self._bus.publish_sync("safety.blocked", agent_id,
                                   {"agent_id": agent_id, "reason": "quarantined"})
            from reins.safety_pipeline.types import PipelineExecution
            return PipelineExecution(
                agent_id=agent_id,
                final_verdict=StageVerdict.FAIL,
                failed_at=PipelineStage.IDENTITY,
            )
        return await self._pipeline.evaluate(agent_id, context)

    def _on_pipeline_event(self, event: Any) -> None:
        if event.event_type != "pipeline.completed":
            return
        if event.verdict == StageVerdict.FAIL:
            self._bus.publish_sync("safety.denied", event.agent_id,
                                   {"agent_id": event.agent_id,
                                    "stage": event.stage.value if event.stage else ""})
        elif event.verdict == StageVerdict.PASS:
            self._bus.publish_sync("safety.passed", event.agent_id,
                                   {"agent_id": event.agent_id})
