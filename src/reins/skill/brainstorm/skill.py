"""Brainstorm skill — guided PRD generation through structured questioning."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar

import ulid

from reins.skill.catalog import SkillDescriptor
from reins.skill.brainstorm.prd_template import (
    GUIDED_QUESTIONS,
    PRDSection,
    PRDTemplate,
    render_prd,
)


class BrainstormPhase(str, Enum):
    """Phases of a brainstorm session."""

    gathering = "gathering"
    structuring = "structuring"
    refining = "refining"
    complete = "complete"


REQUIRED_SECTIONS: tuple[PRDSection, ...] = (
    PRDSection.overview,
    PRDSection.problem_statement,
    PRDSection.goals,
    PRDSection.requirements,
    PRDSection.acceptance_criteria,
)


@dataclass
class BrainstormSession:
    """State of an active brainstorm session."""

    session_id: str
    title: str
    phase: BrainstormPhase = BrainstormPhase.gathering
    answers: dict[PRDSection, str] = field(default_factory=dict)
    current_section: PRDSection | None = None
    iteration_count: int = 0


class BrainstormSkill:
    """Guided PRD generation through structured questioning.

    Walks users through each PRD section with guiding questions,
    collects answers, and produces a structured markdown PRD.
    """

    SKILL_DESCRIPTOR: ClassVar[SkillDescriptor] = SkillDescriptor(
        skill_id="brainstorm",
        source="builtin",
        version="1.0.0",
        manifest_hash="",
        name="Brainstorm",
        description="Guided PRD generation through structured questioning",
        tags=["planning", "prd", "brainstorm"],
        trust_tier=0,
        outputs=["prd"],
    )

    def start_session(self, title: str) -> BrainstormSession:
        """Start a new brainstorm session."""
        session = BrainstormSession(
            session_id=str(ulid.new()),
            title=title,
            phase=BrainstormPhase.gathering,
            current_section=PRDSection.overview,
        )
        return session

    def get_next_questions(self, session: BrainstormSession) -> list[str]:
        """Return questions for the next unfilled section."""
        for section in PRDSection:
            if section not in session.answers:
                return GUIDED_QUESTIONS.get(section, [])
        return []

    def submit_answer(
        self, session: BrainstormSession, section: PRDSection, content: str
    ) -> BrainstormSession:
        """Record an answer and advance to the next section."""
        session.answers[section] = content
        session.iteration_count += 1

        # Advance current_section to next unfilled
        next_section: PRDSection | None = None
        found_current = False
        for s in PRDSection:
            if s == section:
                found_current = True
                continue
            if found_current and s not in session.answers:
                next_section = s
                break

        session.current_section = next_section

        # Update phase based on progress
        if self.is_complete(session):
            if next_section is None:
                session.phase = BrainstormPhase.complete
            else:
                session.phase = BrainstormPhase.refining
        elif len(session.answers) >= len(REQUIRED_SECTIONS):
            session.phase = BrainstormPhase.structuring
        else:
            session.phase = BrainstormPhase.gathering

        return session

    def generate_prd(self, session: BrainstormSession) -> str:
        """Build PRDTemplate from session answers and render to markdown."""
        template = PRDTemplate(
            title=session.title,
            sections=dict(session.answers),
            metadata={
                "session_id": session.session_id,
                "status": session.phase.value,
            },
        )
        return render_prd(template)

    def is_complete(self, session: BrainstormSession) -> bool:
        """True when all required sections have answers."""
        return all(section in session.answers for section in REQUIRED_SECTIONS)

    def get_progress(self, session: BrainstormSession) -> dict[str, Any]:
        """Return progress information for the session."""
        all_sections = list(PRDSection)
        filled = [s.value for s in all_sections if s in session.answers]
        remaining = [s.value for s in all_sections if s not in session.answers]
        total = len(all_sections)
        percent = (len(filled) / total) * 100.0 if total > 0 else 0.0
        return {
            "filled": filled,
            "remaining": remaining,
            "percent": round(percent, 1),
        }
