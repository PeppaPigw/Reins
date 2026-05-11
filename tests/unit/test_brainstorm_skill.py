"""Tests for the brainstorm skill and PRD template."""

from __future__ import annotations

from reins.skill.brainstorm.prd_template import (
    GUIDED_QUESTIONS,
    PRDSection,
    PRDTemplate,
    render_prd,
)
from reins.skill.brainstorm.skill import (
    BrainstormPhase,
    BrainstormSkill,
)


class TestBrainstormSkill:
    def setup_method(self) -> None:
        self.skill = BrainstormSkill()

    def test_start_session_creates_gathering_phase(self) -> None:
        session = self.skill.start_session("Test Feature")
        assert session.phase == BrainstormPhase.gathering
        assert session.title == "Test Feature"
        assert session.session_id != ""
        assert session.current_section == PRDSection.overview

    def test_get_next_questions_returns_questions_for_first_section(self) -> None:
        session = self.skill.start_session("Test")
        questions = self.skill.get_next_questions(session)
        assert len(questions) > 0
        assert questions == GUIDED_QUESTIONS[PRDSection.overview]

    def test_submit_answer_records_content(self) -> None:
        session = self.skill.start_session("Test")
        session = self.skill.submit_answer(
            session, PRDSection.overview, "This is an overview."
        )
        assert PRDSection.overview in session.answers
        assert session.answers[PRDSection.overview] == "This is an overview."

    def test_submit_answer_advances_section(self) -> None:
        session = self.skill.start_session("Test")
        session = self.skill.submit_answer(
            session, PRDSection.overview, "Overview content"
        )
        assert session.current_section == PRDSection.problem_statement

    def test_generate_prd_produces_markdown(self) -> None:
        session = self.skill.start_session("My Feature")
        session = self.skill.submit_answer(
            session, PRDSection.overview, "Feature overview"
        )
        prd = self.skill.generate_prd(session)
        assert "# My Feature" in prd
        assert "## Overview" in prd
        assert "Feature overview" in prd

    def test_generate_prd_includes_all_sections(self) -> None:
        session = self.skill.start_session("Full PRD")
        for section in PRDSection:
            session = self.skill.submit_answer(
                session, section, f"Content for {section.value}"
            )
        prd = self.skill.generate_prd(session)
        for section in PRDSection:
            heading = section.value.replace("_", " ").title()
            assert f"## {heading}" in prd
            assert f"Content for {section.value}" in prd

    def test_is_complete_false_when_missing_required(self) -> None:
        session = self.skill.start_session("Test")
        session = self.skill.submit_answer(
            session, PRDSection.overview, "Overview"
        )
        assert not self.skill.is_complete(session)

    def test_is_complete_true_when_all_required_filled(self) -> None:
        session = self.skill.start_session("Test")
        required = [
            PRDSection.overview,
            PRDSection.problem_statement,
            PRDSection.goals,
            PRDSection.requirements,
            PRDSection.acceptance_criteria,
        ]
        for section in required:
            session = self.skill.submit_answer(
                session, section, f"Content for {section.value}"
            )
        assert self.skill.is_complete(session)

    def test_get_progress_shows_percentage(self) -> None:
        session = self.skill.start_session("Test")
        progress = self.skill.get_progress(session)
        assert progress["percent"] == 0.0
        assert len(progress["remaining"]) == len(PRDSection)

        session = self.skill.submit_answer(
            session, PRDSection.overview, "Overview"
        )
        progress = self.skill.get_progress(session)
        assert progress["percent"] > 0.0
        assert "overview" in progress["filled"]
        assert "overview" not in progress["remaining"]

    def test_prd_template_render_has_frontmatter(self) -> None:
        template = PRDTemplate(
            title="Test",
            sections={PRDSection.overview: "Content"},
            metadata={"author": "test", "version": "1.0"},
        )
        rendered = render_prd(template)
        assert "---" in rendered
        assert "author: test" in rendered
        assert "version: 1.0" in rendered

    def test_guided_questions_cover_all_sections(self) -> None:
        for section in PRDSection:
            assert section in GUIDED_QUESTIONS
            assert len(GUIDED_QUESTIONS[section]) >= 2

    def test_skill_descriptor_has_correct_metadata(self) -> None:
        descriptor = BrainstormSkill.SKILL_DESCRIPTOR
        assert descriptor.skill_id == "brainstorm"
        assert descriptor.name == "Brainstorm"
        assert "planning" in descriptor.tags
        assert "prd" in descriptor.tags
        assert descriptor.trust_tier == 0
        assert "prd" in descriptor.outputs
