"""Validation helpers for markdown-based spec trees."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from reins.context.checklist import ChecklistParser
from reins.context.types import SpecLayer

_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\((?P<target>[^)]+)\)")


@dataclass(frozen=True)
class SpecValidationIssue:
    """A single validation issue discovered in the spec tree."""

    path: Path
    message: str
    code: str
    line: int | None = None
    fixable: bool = False

    def display(self, repo_root: Path | None = None) -> str:
        location = self.path
        if repo_root is not None:
            try:
                location = self.path.resolve().relative_to(repo_root.resolve())
            except ValueError:
                location = self.path
        if self.line is not None:
            return f"{location}:{self.line}: {self.message}"
        return f"{location}: {self.message}"


@dataclass(frozen=True)
class SpecValidationReport:
    """Aggregate validation result for a spec tree."""

    issues: list[SpecValidationIssue]

    @property
    def is_valid(self) -> bool:
        return not self.issues


class SpecValidator:
    """Validate spec directory structure and markdown integrity."""

    def __init__(self, spec_root: Path) -> None:
        self.spec_root = spec_root

    def validate(self, *, project_type: str) -> SpecValidationReport:
        issues: list[SpecValidationIssue] = []
        if not self.spec_root.exists():
            issues.append(
                SpecValidationIssue(
                    path=self.spec_root,
                    message="Spec root does not exist.",
                    code="missing-spec-root",
                    fixable=True,
                )
            )
            return SpecValidationReport(issues=issues)

        issues.extend(self._validate_required_layers(project_type))
        issues.extend(self._validate_index_checklists())
        issues.extend(self._validate_markdown_links())
        issues.extend(self._validate_frontmatter())
        return SpecValidationReport(issues=issues)

    def _validate_required_layers(self, project_type: str) -> list[SpecValidationIssue]:
        required_layers = {
            layer.value for layer in SpecLayer.default_layers_for_project_type(project_type)
        }
        present_layers = {
            path.name
            for path in self.spec_root.iterdir()
            if path.is_dir() and SpecLayer.from_name(path.name) is not SpecLayer.CUSTOM
        }
        missing = sorted(required_layers - present_layers)
        return [
            SpecValidationIssue(
                path=self.spec_root / layer,
                message=f"Missing required layer '{layer}'.",
                code="missing-layer",
                fixable=True,
            )
            for layer in missing
        ]

    def _validate_index_checklists(self) -> list[SpecValidationIssue]:
        issues: list[SpecValidationIssue] = []
        for index_path in sorted(self.spec_root.rglob("index.md")):
            checklist = ChecklistParser.parse(index_path)
            if checklist is None:
                issues.append(
                    SpecValidationIssue(
                        path=index_path,
                        message="Missing 'Pre-Development Checklist' section.",
                        code="missing-checklist",
                        fixable=True,
                    )
                )
        return issues

    def _validate_markdown_links(self) -> list[SpecValidationIssue]:
        issues: list[SpecValidationIssue] = []
        for markdown_path in sorted(self.spec_root.rglob("*.md")):
            lines = markdown_path.read_text(encoding="utf-8").splitlines()
            for line_number, line in enumerate(lines, start=1):
                for match in _MARKDOWN_LINK.finditer(line):
                    target = match.group("target").strip()
                    if self._is_external_target(target):
                        continue
                    if "#" in target:
                        target = target.split("#", 1)[0]
                    resolved = (markdown_path.parent / target).resolve()
                    if resolved.exists():
                        continue
                    issues.append(
                        SpecValidationIssue(
                            path=markdown_path,
                            line=line_number,
                            message=f"Broken link target '{target}'.",
                            code="broken-link",
                        )
                    )
        return issues

    def _validate_frontmatter(self) -> list[SpecValidationIssue]:
        issues: list[SpecValidationIssue] = []
        for markdown_path in sorted(self.spec_root.rglob("*.md")):
            text = markdown_path.read_text(encoding="utf-8")
            if not text.startswith("---\n"):
                continue
            end = text.find("\n---\n", 4)
            if end == -1:
                issues.append(
                    SpecValidationIssue(
                        path=markdown_path,
                        line=1,
                        message="Frontmatter is missing a closing '---' delimiter.",
                        code="frontmatter-delimiter",
                    )
                )
                continue
            frontmatter = text[4:end]
            try:
                data = yaml.safe_load(frontmatter) or {}
            except yaml.YAMLError as exc:
                line = getattr(getattr(exc, "problem_mark", None), "line", None)
                issues.append(
                    SpecValidationIssue(
                        path=markdown_path,
                        line=(line + 1) if line is not None else 1,
                        message=f"Invalid YAML frontmatter: {exc}",
                        code="frontmatter-yaml",
                    )
                )
                continue
            if not isinstance(data, dict):
                issues.append(
                    SpecValidationIssue(
                        path=markdown_path,
                        line=1,
                        message="Frontmatter must decode to a mapping.",
                        code="frontmatter-mapping",
                    )
                )
        return issues

    def _is_external_target(self, target: str) -> bool:
        return (
            not target
            or target.startswith(("#", "http://", "https://", "mailto:", "data:"))
        )
