"""PRD template and structured output for brainstorm skill."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PRDSection(str, Enum):
    """Sections of a Product Requirements Document."""

    overview = "overview"
    problem_statement = "problem_statement"
    goals = "goals"
    non_goals = "non_goals"
    requirements = "requirements"
    acceptance_criteria = "acceptance_criteria"
    technical_approach = "technical_approach"
    risks = "risks"
    open_questions = "open_questions"


@dataclass(frozen=True)
class PRDTemplate:
    """Structured PRD with sections and metadata."""

    title: str
    sections: dict[PRDSection, str] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)


def render_prd(template: PRDTemplate) -> str:
    """Render a PRDTemplate to markdown format.

    Metadata is rendered as YAML frontmatter, each section as a ## heading.
    """
    lines: list[str] = []

    # YAML frontmatter
    if template.metadata:
        lines.append("---")
        for key, value in template.metadata.items():
            lines.append(f"{key}: {value}")
        lines.append("---")
        lines.append("")

    # Title
    lines.append(f"# {template.title}")
    lines.append("")

    # Sections
    for section in PRDSection:
        if section in template.sections:
            heading = section.value.replace("_", " ").title()
            lines.append(f"## {heading}")
            lines.append("")
            lines.append(template.sections[section])
            lines.append("")

    return "\n".join(lines)


GUIDED_QUESTIONS: dict[PRDSection, list[str]] = {
    PRDSection.overview: [
        "What is this feature/change?",
        "Who is it for?",
    ],
    PRDSection.problem_statement: [
        "What problem does this solve?",
        "What happens if we don't solve it?",
    ],
    PRDSection.goals: [
        "What does success look like?",
        "How will we measure it?",
    ],
    PRDSection.non_goals: [
        "What are we explicitly NOT doing?",
        "What's out of scope?",
    ],
    PRDSection.requirements: [
        "What must be true when this is done?",
        "What are the constraints?",
    ],
    PRDSection.acceptance_criteria: [
        "How do we verify this works?",
        "What are the edge cases?",
    ],
    PRDSection.technical_approach: [
        "What's the high-level approach?",
        "What alternatives were considered?",
    ],
    PRDSection.risks: [
        "What could go wrong?",
        "What are the dependencies?",
    ],
    PRDSection.open_questions: [
        "What don't we know yet?",
        "What needs clarification?",
    ],
}
