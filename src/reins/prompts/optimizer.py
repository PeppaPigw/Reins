from __future__ import annotations

from collections import defaultdict
from typing import Any

from reins.prompts.types import (
    FewShotExample,
    OptimizationResult,
    OptimizationStrategy,
    OutcomeSignal,
    PromptOutcome,
    PromptTemplate,
    PromptVariant,
)


_SIGNAL_SCORES = {
    OutcomeSignal.SUCCESS: 1.0,
    OutcomeSignal.PARTIAL: 0.5,
    OutcomeSignal.FAILURE: 0.0,
    OutcomeSignal.TIMEOUT: 0.1,
    OutcomeSignal.REJECTED: 0.0,
}


class PromptOptimizer:
    """Learns from agent outcomes to refine prompts, select few-shot examples, and tune parameters.

    Tracks prompt performance over time and generates optimized variants
    using strategies like few-shot selection, template refinement, and
    parameter tuning.
    """

    def __init__(self, exploration_rate: float = 0.2) -> None:
        self._templates: dict[str, PromptTemplate] = {}
        self._outcomes: list[PromptOutcome] = []
        self._variants: dict[str, list[PromptVariant]] = defaultdict(list)
        self._example_pool: list[FewShotExample] = []
        self._exploration_rate = exploration_rate

    @property
    def template_count(self) -> int:
        return len(self._templates)

    @property
    def outcome_count(self) -> int:
        return len(self._outcomes)

    def register_template(self, template: PromptTemplate) -> None:
        self._templates[template.template_id] = template

    def get_template(self, template_id: str) -> PromptTemplate | None:
        return self._templates.get(template_id)

    def add_example(self, example: FewShotExample) -> None:
        self._example_pool.append(example)

    def record_outcome(self, outcome: PromptOutcome) -> None:
        self._outcomes.append(outcome)

    def get_success_rate(self, template_id: str) -> float:
        relevant = [o for o in self._outcomes if o.template_id == template_id]
        if not relevant:
            return 0.0
        successes = sum(1 for o in relevant if o.signal == OutcomeSignal.SUCCESS)
        return successes / len(relevant)

    def get_avg_score(self, template_id: str) -> float:
        relevant = [o for o in self._outcomes if o.template_id == template_id]
        if not relevant:
            return 0.0
        return sum(_SIGNAL_SCORES[o.signal] for o in relevant) / len(relevant)

    def select_few_shots(self, template_id: str, task_tags: tuple[str, ...] = (), max_examples: int = 3) -> tuple[FewShotExample, ...]:
        if not self._example_pool:
            return ()

        scored: list[tuple[FewShotExample, float]] = []
        for ex in self._example_pool:
            score = ex.quality_score
            if task_tags:
                overlap = len(set(ex.tags) & set(task_tags))
                score += overlap * 0.3
            scored.append((ex, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return tuple(ex for ex, _ in scored[:max_examples])

    def create_variant(self, template_id: str, strategy: OptimizationStrategy, content: str, parameters: dict[str, Any] | None = None) -> PromptVariant:
        variant = PromptVariant(
            template_id=template_id,
            strategy=strategy,
            content=content,
            parameters=parameters or {},
        )
        self._variants[template_id].append(variant)
        return variant

    def record_variant_outcome(self, variant_id: str, signal: OutcomeSignal) -> PromptVariant | None:
        for variants in self._variants.values():
            for i, v in enumerate(variants):
                if v.variant_id == variant_id:
                    score = _SIGNAL_SCORES[signal]
                    new_trial_count = v.trial_count + 1
                    new_success_count = v.success_count + (1 if signal == OutcomeSignal.SUCCESS else 0)
                    new_score = (v.score * v.trial_count + score) / new_trial_count

                    updated = PromptVariant(
                        variant_id=v.variant_id,
                        template_id=v.template_id,
                        strategy=v.strategy,
                        content=v.content,
                        parameters=v.parameters,
                        score=new_score,
                        trial_count=new_trial_count,
                        success_count=new_success_count,
                        created_at=v.created_at,
                    )
                    variants[i] = updated
                    return updated
        return None

    def get_best_variant(self, template_id: str, min_trials: int = 3) -> PromptVariant | None:
        variants = self._variants.get(template_id, [])
        eligible = [v for v in variants if v.trial_count >= min_trials]
        if not eligible:
            return None
        return max(eligible, key=lambda v: v.score)

    def optimize(self, template_id: str) -> OptimizationResult:
        template = self._templates.get(template_id)
        if not template:
            return OptimizationResult(template_id=template_id, variants_tested=0)

        variants = self._variants.get(template_id, [])
        best = self.get_best_variant(template_id, min_trials=1)

        baseline_score = self.get_avg_score(template_id)
        improvement = 0.0
        strategy = OptimizationStrategy.TEMPLATE_REFINEMENT

        if best:
            improvement = ((best.score - baseline_score) / max(baseline_score, 0.01)) * 100
            strategy = best.strategy

        return OptimizationResult(
            template_id=template_id,
            best_variant=best,
            variants_tested=len(variants),
            improvement_pct=improvement,
            strategy_used=strategy,
        )

    def suggest_parameters(self, template_id: str) -> dict[str, Any]:
        outcomes = [o for o in self._outcomes if o.template_id == template_id]
        if not outcomes:
            return {}

        successful = [o for o in outcomes if o.signal == OutcomeSignal.SUCCESS]
        if not successful:
            return {}

        avg_tokens = sum(o.token_count for o in successful) / len(successful)
        avg_latency = sum(o.latency_ms for o in successful) / len(successful)

        return {
            "recommended_max_tokens": int(avg_tokens * 1.2),
            "expected_latency_ms": avg_latency,
            "success_rate": len(successful) / len(outcomes),
        }

    def prune_examples(self, min_quality: float = 0.5) -> int:
        before = len(self._example_pool)
        self._example_pool = [ex for ex in self._example_pool if ex.quality_score >= min_quality]
        return before - len(self._example_pool)

    def get_template_stats(self, template_id: str) -> dict[str, Any]:
        outcomes = [o for o in self._outcomes if o.template_id == template_id]
        variants = self._variants.get(template_id, [])

        if not outcomes:
            return {"total_uses": 0, "success_rate": 0.0, "variants": len(variants)}

        by_signal: dict[str, int] = defaultdict(int)
        for o in outcomes:
            by_signal[o.signal.value] += 1

        return {
            "total_uses": len(outcomes),
            "success_rate": self.get_success_rate(template_id),
            "avg_score": self.get_avg_score(template_id),
            "avg_latency_ms": sum(o.latency_ms for o in outcomes) / len(outcomes),
            "avg_tokens": sum(o.token_count for o in outcomes) / len(outcomes),
            "total_cost": sum(o.cost for o in outcomes),
            "by_signal": dict(by_signal),
            "variants": len(variants),
        }
