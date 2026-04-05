from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime

import ulid

from reins.kernel.types import FailureClass


@dataclass(frozen=True)
class EvalResult:
    run_id: str
    command_id: str | None
    evaluator_kind: str
    passed: bool
    score: float
    details: dict
    failure_class: FailureClass | None = None
    repair_hints: list[str] = field(default_factory=list)
    eval_id: str = field(default_factory=lambda: str(ulid.new()))
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))


class Evaluator(ABC):
    @abstractmethod
    async def evaluate(self, context: dict) -> EvalResult: ...
