from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reins.evaluation.classifier import FailureClassifier
from reins.evaluation.evaluators.base import EvalResult, Evaluator
from reins.kernel.intent.envelope import CommandEnvelope
from reins.kernel.types import FailureClass
from reins.serde import to_primitive


@dataclass(frozen=True)
class EvaluationOutcome:
    passed: bool
    results: list[EvalResult] = field(default_factory=list)
    failure_class: FailureClass | None = None
    repair_route: str | None = None
    retry_allowed: bool | None = None


class EvaluationRunner:
    """Runs trusted evaluator bundles for a command."""

    def __init__(
        self,
        evaluators: dict[str, Evaluator],
        capability_map: dict[str, list[str]] | None = None,
        classifier: FailureClassifier | None = None,
    ) -> None:
        self._evaluators = evaluators
        self._capability_map = capability_map or {}
        self._classifier = classifier or FailureClassifier()

    def resolve_evaluators(
        self,
        command: CommandEnvelope,
        eval_context: dict[str, Any] | None = None,
    ) -> list[str]:
        eval_context = eval_context or {}
        explicit = eval_context.get("evaluators")
        if explicit is not None:
            return [name for name in explicit if name in self._evaluators]
        return [
            name
            for name in self._capability_map.get(command.normalized_kind, [])
            if name in self._evaluators
        ]

    async def evaluate(
        self,
        command: CommandEnvelope,
        observation: dict[str, Any],
        eval_context: dict[str, Any] | None = None,
    ) -> EvaluationOutcome:
        requested = self.resolve_evaluators(command, eval_context)
        if not requested:
            return EvaluationOutcome(passed=True)

        results: list[EvalResult] = []
        context = self._build_context(command, observation, eval_context or {})
        for evaluator_name in requested:
            result = await self._evaluators[evaluator_name].evaluate(context)
            results.append(result)

        failing = next((result for result in results if not result.passed), None)
        if failing is None:
            return EvaluationOutcome(passed=True, results=results)

        failure_class = failing.failure_class or self._classifier.classify(
            to_primitive(failing),
            context,
        )
        repair_route = self._classifier.repair_route(failure_class)
        retry_allowed = self._classifier.retry_allowed(
            failure_class,
            (
                eval_context.get("prior_hypotheses", [])
                if eval_context is not None
                else []
            ),
        )
        return EvaluationOutcome(
            passed=False,
            results=results,
            failure_class=failure_class,
            repair_route=repair_route,
            retry_allowed=retry_allowed,
        )

    @staticmethod
    def _build_context(
        command: CommandEnvelope,
        observation: dict[str, Any],
        eval_context: dict[str, Any],
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "run_id": command.run_id,
            "command_id": command.command_id,
            "capability": command.normalized_kind,
            "command_args": command.args,
            "observation": observation,
        }
        context.update(command.args)
        context.update(eval_context)
        if "cwd" not in context:
            context["cwd"] = (
                command.args.get("cwd")
                or command.args.get("repo")
                or command.args.get("root")
                or "."
            )
        if "target" not in context and "path" in command.args:
            context["target"] = command.args["path"]
        return context
