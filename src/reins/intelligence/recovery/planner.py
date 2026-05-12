from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reins.evaluation.classifier import FailureClassifier
from reins.intelligence.types import (
    EscalationDecision,
    EscalationReason,
    HealingPattern,
    RecoveryProposal,
)


class PatternRegistry:
    def __init__(self, store_path: Path) -> None:
        self._store_path = store_path
        self._store_path.mkdir(parents=True, exist_ok=True)
        self._registry_path = self._store_path / "patterns.json"
        self._patterns: dict[str, HealingPattern] = {}
        self._outcomes: dict[str, list[bool]] = {}
        self._load()

    def _load(self) -> None:
        if not self._registry_path.exists():
            return
        data: dict[str, Any] = json.loads(self._registry_path.read_text(encoding="utf-8"))
        for entry in data.get("patterns", []):
            pattern = HealingPattern(
                pattern_id=entry["pattern_id"],
                failure_signature=entry["failure_signature"],
                recovery_action=entry["recovery_action"],
                success_rate=entry.get("success_rate", 0.5),
                applicable_domains=tuple(entry.get("applicable_domains", ())),
                max_auto_applications=entry.get("max_auto_applications", 3),
            )
            self._patterns[pattern.pattern_id] = pattern
            self._outcomes[pattern.pattern_id] = entry.get("outcomes", [])

    def _save(self) -> None:
        data: dict[str, list[Any]] = {"patterns": []}
        for pid, pattern in self._patterns.items():
            data["patterns"].append({
                "pattern_id": pattern.pattern_id,
                "failure_signature": pattern.failure_signature,
                "recovery_action": pattern.recovery_action,
                "success_rate": pattern.success_rate,
                "applicable_domains": list(pattern.applicable_domains),
                "max_auto_applications": pattern.max_auto_applications,
                "outcomes": self._outcomes.get(pid, []),
            })
        self._registry_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def match(self, failure_class: str, context: dict[str, Any]) -> list[HealingPattern]:
        domain = context.get("domain", "general")
        matches: list[HealingPattern] = []
        for pattern in self._patterns.values():
            if pattern.failure_signature in failure_class or failure_class in pattern.failure_signature:
                if not pattern.applicable_domains or domain in pattern.applicable_domains:
                    matches.append(pattern)
        matches.sort(key=lambda p: p.success_rate, reverse=True)
        return matches

    def record_outcome(self, pattern_id: str, success: bool) -> None:
        if pattern_id not in self._outcomes:
            self._outcomes[pattern_id] = []
        self._outcomes[pattern_id].append(success)

        outcomes = self._outcomes[pattern_id]
        new_rate = sum(outcomes) / len(outcomes) if outcomes else 0.5

        if pattern_id in self._patterns:
            old = self._patterns[pattern_id]
            self._patterns[pattern_id] = HealingPattern(
                pattern_id=old.pattern_id,
                failure_signature=old.failure_signature,
                recovery_action=old.recovery_action,
                success_rate=new_rate,
                applicable_domains=old.applicable_domains,
                max_auto_applications=old.max_auto_applications,
            )
        self._save()

    def register_pattern(self, pattern: HealingPattern) -> None:
        self._patterns[pattern.pattern_id] = pattern
        self._outcomes[pattern.pattern_id] = []
        self._save()

    def retire_pattern(self, pattern_id: str) -> None:
        self._patterns.pop(pattern_id, None)
        self._outcomes.pop(pattern_id, None)
        self._save()


class RecoveryPlanner:
    def __init__(
        self,
        classifier: FailureClassifier,
        pattern_registry: PatternRegistry,
        max_retries: int = 3,
        escalation_threshold: int = 3,
    ) -> None:
        self._classifier = classifier
        self._patterns = pattern_registry
        self._max_retries = max_retries
        self._escalation_threshold = escalation_threshold
        self._attempt_counts: dict[str, int] = {}

    async def plan_recovery(
        self, failure: dict[str, Any], context: dict[str, Any]
    ) -> RecoveryProposal:
        failure_class = self._classifier.classify(failure, context)
        repair_route = self._classifier.repair_route(failure_class)

        task_id = context.get("task_id", "unknown")
        self._attempt_counts[task_id] = self._attempt_counts.get(task_id, 0) + 1
        prior_attempts = self._attempt_counts[task_id]

        patterns = self._patterns.match(failure_class.value, context)

        if patterns and patterns[0].success_rate > 0.7:
            best = patterns[0]
            return RecoveryProposal(
                failure_class=failure_class.value,
                assumed_failure_class=failure_class.value,
                action=best.recovery_action,
                rationale=f"Pattern '{best.pattern_id}' matched (rate={best.success_rate:.0%})",
                requires_approval=prior_attempts > best.max_auto_applications,
                risk_tier=context.get("risk_tier", "T1"),
                pattern_id=best.pattern_id,
                prior_attempts=prior_attempts,
            )

        past_failures = context.get("past_failures", [])
        action = self._generate_action(failure_class.value, repair_route, past_failures)

        return RecoveryProposal(
            failure_class=failure_class.value,
            assumed_failure_class=failure_class.value,
            fallback_classes=self._compute_fallbacks(failure_class.value),
            action=action,
            rationale=f"No high-confidence pattern. Using repair route '{repair_route}'.",
            requires_approval=prior_attempts > 1 or failure_class.value == "policy_block",
            risk_tier=context.get("risk_tier", "T1"),
            prior_attempts=prior_attempts,
        )

    async def record_recovery_outcome(
        self, proposal: RecoveryProposal, success: bool
    ) -> None:
        if proposal.pattern_id:
            self._patterns.record_outcome(proposal.pattern_id, success)

    def should_escalate(self, context: dict[str, Any]) -> EscalationDecision:
        task_id = context.get("task_id", "unknown")
        attempts = self._attempt_counts.get(task_id, 0)

        if attempts >= self._escalation_threshold:
            return EscalationDecision(
                should_escalate=True,
                reason=EscalationReason.max_retries_exceeded,
                context={"task_id": task_id, "attempts": attempts},
                suggested_human_action="Review failure pattern and provide guidance",
            )

        if context.get("all_hypotheses_exhausted"):
            return EscalationDecision(
                should_escalate=True,
                reason=EscalationReason.all_hypotheses_exhausted,
                context=context,
                suggested_human_action="Provide new hypothesis or change approach",
            )

        if context.get("trust_insufficient"):
            return EscalationDecision(
                should_escalate=True,
                reason=EscalationReason.trust_insufficient,
                context=context,
                suggested_human_action="Approve action or grant higher trust",
            )

        return EscalationDecision(should_escalate=False)

    def reset_attempts(self, task_id: str) -> None:
        self._attempt_counts.pop(task_id, None)

    def _generate_action(
        self, failure_class: str, repair_route: str, past_failures: list[Any]
    ) -> str:
        action_map = {
            "change_hypothesis": "generate_alternative_approach",
            "recompile_context": "rebuild_context_with_expanded_budget",
            "reacquire_environment": "check_and_fix_environment",
            "escalate_or_request_human": "escalate_to_human",
            "isolate_and_retry": "retry_in_isolation",
            "rerun_local_fix": "attempt_auto_merge_resolution",
        }
        return action_map.get(repair_route, "escalate_to_human")

    def _compute_fallbacks(self, primary_class: str) -> tuple[str, ...]:
        fallback_map: dict[str, tuple[str, ...]] = {
            "logic_failure": ("context_failure", "environment_failure"),
            "context_failure": ("logic_failure",),
            "environment_failure": ("logic_failure", "external_effect_failure"),
            "flaky_eval": ("environment_failure", "logic_failure"),
        }
        return fallback_map.get(primary_class, ())
