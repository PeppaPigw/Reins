from __future__ import annotations

from pathlib import Path

from reins.evaluation.classifier import FailureClassifier
from reins.intelligence.coordinator import IntelligenceCoordinator
from reins.intelligence.decomposer.planner import TaskDecomposer
from reins.intelligence.integration import IntelligenceAdvisor
from reins.intelligence.memory.engine import MemoryEngine
from reins.intelligence.recovery.planner import PatternRegistry, RecoveryPlanner
from reins.intelligence.strategy.selector import StrategySelector
from reins.intelligence.strategy.trust import TrustModel


def create_intelligence_advisor(
    store_path: Path,
    max_retries: int = 3,
    escalation_threshold: int = 3,
    rules: list[dict] | None = None,
) -> IntelligenceAdvisor:
    """Factory to create a fully-wired IntelligenceAdvisor.

    Args:
        store_path: Root directory for intelligence state (memory, trust, patterns).
        max_retries: Max recovery attempts before escalation.
        escalation_threshold: Failure count that triggers escalation.
        rules: Optional human-defined strategy rules.

    Returns:
        IntelligenceAdvisor ready to be passed as `advisor` to RunOrchestrator.
    """
    store_path.mkdir(parents=True, exist_ok=True)

    memory = MemoryEngine(store_path / "memory")
    trust = TrustModel(store_path / "trust")
    strategy = StrategySelector(trust, rules=rules)
    patterns = PatternRegistry(store_path / "patterns")
    recovery = RecoveryPlanner(
        classifier=FailureClassifier(),
        pattern_registry=patterns,
        max_retries=max_retries,
        escalation_threshold=escalation_threshold,
    )
    decomposer = TaskDecomposer()

    coordinator = IntelligenceCoordinator(
        decomposer=decomposer,
        memory=memory,
        strategy=strategy,
        recovery=recovery,
    )

    return IntelligenceAdvisor(coordinator)
