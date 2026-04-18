"""Decision and question management for workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class WorkflowDecision:
    """A decision point in a workflow."""

    decision_id: str
    node_id: str
    question: str
    options: list[str]
    selected: str | None = None
    decided_at: datetime | None = None


@dataclass
class WorkflowQuestion:
    """A question requiring user input."""

    question_id: str
    node_id: str
    question: str
    answer: str | None = None
    answered_at: datetime | None = None


class DecisionManager:
    """Manages decisions and questions in workflows."""

    def __init__(self) -> None:
        self.decisions: dict[str, WorkflowDecision] = {}
        self.questions: dict[str, WorkflowQuestion] = {}

    def create_decision(
        self, decision_id: str, node_id: str, question: str, options: list[str]
    ) -> WorkflowDecision:
        """Create a decision point."""
        decision = WorkflowDecision(
            decision_id=decision_id, node_id=node_id, question=question, options=options
        )
        self.decisions[decision_id] = decision
        return decision

    def make_decision(self, decision_id: str, selected: str) -> None:
        """Make a decision."""
        if decision_id in self.decisions:
            self.decisions[decision_id].selected = selected
            self.decisions[decision_id].decided_at = datetime.now(UTC)

    def create_question(
        self, question_id: str, node_id: str, question: str
    ) -> WorkflowQuestion:
        """Create a question."""
        q = WorkflowQuestion(
            question_id=question_id, node_id=node_id, question=question
        )
        self.questions[question_id] = q
        return q

    def answer_question(self, question_id: str, answer: str) -> None:
        """Answer a question."""
        if question_id in self.questions:
            self.questions[question_id].answer = answer
            self.questions[question_id].answered_at = datetime.now(UTC)

    def get_pending_decisions(self) -> list[WorkflowDecision]:
        """Get all pending decisions."""
        return [d for d in self.decisions.values() if d.selected is None]

    def get_pending_questions(self) -> list[WorkflowQuestion]:
        """Get all pending questions."""
        return [q for q in self.questions.values() if q.answer is None]
