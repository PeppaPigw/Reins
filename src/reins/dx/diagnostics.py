"""Diagnostic checks for common setup issues."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class CheckStatus(str, Enum):
    passed = "passed"
    warning = "warning"
    failed = "failed"


@dataclass
class DiagnosticResult:
    """Result of a single diagnostic check."""

    name: str
    status: CheckStatus
    message: str
    suggestion: str | None = None
    doc_url: str | None = None


class DiagnosticSuite:
    """Runs diagnostic checks for common Reins setup issues."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = repo_root

    def check_python_version(self) -> DiagnosticResult:
        """Check that Python >= 3.11 is available."""
        major, minor = sys.version_info[:2]
        if major >= 3 and minor >= 11:
            return DiagnosticResult(
                name="python_version",
                status=CheckStatus.passed,
                message=f"Python {major}.{minor} detected",
            )
        return DiagnosticResult(
            name="python_version",
            status=CheckStatus.failed,
            message=f"Python {major}.{minor} detected, but >= 3.11 is required",
            suggestion="Install Python 3.11 or later from https://python.org/downloads/",
            doc_url="https://reins.dev/docs/setup#python-version",
        )

    def check_git_available(self) -> DiagnosticResult:
        """Check that git is installed and functional."""
        git_path = shutil.which("git")
        if git_path is None:
            return DiagnosticResult(
                name="git_available",
                status=CheckStatus.failed,
                message="git not found in PATH",
                suggestion="Install git: https://git-scm.com/downloads",
                doc_url="https://reins.dev/docs/setup#git",
            )
        try:
            result = subprocess.run(
                ["git", "--version"],
                capture_output=True,
                text=True,
                check=True,
            )
            version = result.stdout.strip()
            return DiagnosticResult(
                name="git_available",
                status=CheckStatus.passed,
                message=f"git available: {version}",
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            return DiagnosticResult(
                name="git_available",
                status=CheckStatus.failed,
                message=f"git found but not functional: {exc}",
                suggestion="Reinstall git or check your PATH configuration",
            )

    def check_reins_initialized(self) -> DiagnosticResult:
        """Check that .reins/ directory exists."""
        if self.repo_root is None:
            return DiagnosticResult(
                name="reins_initialized",
                status=CheckStatus.failed,
                message="No .reins directory found",
                suggestion="Run 'reins init' to initialize the project",
                doc_url="https://reins.dev/docs/getting-started#init",
            )
        reins_dir = self.repo_root / ".reins"
        if reins_dir.is_dir():
            return DiagnosticResult(
                name="reins_initialized",
                status=CheckStatus.passed,
                message=f".reins directory found at {reins_dir}",
            )
        return DiagnosticResult(
            name="reins_initialized",
            status=CheckStatus.failed,
            message="No .reins directory found at project root",
            suggestion="Run 'reins init' to initialize the project",
            doc_url="https://reins.dev/docs/getting-started#init",
        )

    def check_dependencies(self) -> DiagnosticResult:
        """Check that key dependencies are importable."""
        required = ["pydantic", "aiohttp", "typer", "yaml", "structlog", "aiofiles"]
        missing: list[str] = []
        for pkg in required:
            try:
                __import__(pkg)
            except ImportError:
                missing.append(pkg)

        if not missing:
            return DiagnosticResult(
                name="dependencies",
                status=CheckStatus.passed,
                message="All key dependencies are importable",
            )
        return DiagnosticResult(
            name="dependencies",
            status=CheckStatus.failed,
            message=f"Missing dependencies: {', '.join(missing)}",
            suggestion="Run 'pip install reins' or 'pip install -e .[dev]' to install dependencies",
            doc_url="https://reins.dev/docs/setup#dependencies",
        )

    def check_config_valid(self) -> DiagnosticResult:
        """Check that .reins/config.yaml is valid YAML if it exists."""
        if self.repo_root is None:
            return DiagnosticResult(
                name="config_valid",
                status=CheckStatus.warning,
                message="Cannot check config: no repo root",
                suggestion="Run 'reins init' first",
            )
        config_path = self.repo_root / ".reins" / "config.yaml"
        if not config_path.exists():
            return DiagnosticResult(
                name="config_valid",
                status=CheckStatus.warning,
                message="No config.yaml found (using defaults)",
                suggestion="Run 'reins init' to create a configuration file",
            )
        try:
            import yaml

            content = config_path.read_text(encoding="utf-8")
            yaml.safe_load(content)
            return DiagnosticResult(
                name="config_valid",
                status=CheckStatus.passed,
                message="config.yaml is valid YAML",
            )
        except Exception as exc:
            return DiagnosticResult(
                name="config_valid",
                status=CheckStatus.failed,
                message=f"config.yaml is invalid: {exc}",
                suggestion="Fix the YAML syntax in .reins/config.yaml",
                doc_url="https://reins.dev/docs/configuration",
            )

    def check_journal_accessible(self) -> DiagnosticResult:
        """Check that the journal file is readable/writable."""
        if self.repo_root is None:
            return DiagnosticResult(
                name="journal_accessible",
                status=CheckStatus.warning,
                message="Cannot check journal: no repo root",
                suggestion="Run 'reins init' first",
            )
        journal_path = self.repo_root / ".reins" / "journal.jsonl"
        if not journal_path.exists():
            parent = journal_path.parent
            if parent.exists() and parent.is_dir():
                return DiagnosticResult(
                    name="journal_accessible",
                    status=CheckStatus.passed,
                    message="Journal directory is writable (journal will be created on first event)",
                )
            return DiagnosticResult(
                name="journal_accessible",
                status=CheckStatus.failed,
                message="Journal parent directory does not exist",
                suggestion="Run 'reins init' to create the directory structure",
            )
        try:
            with open(journal_path, "a"):
                pass
            return DiagnosticResult(
                name="journal_accessible",
                status=CheckStatus.passed,
                message="Journal file is readable and writable",
            )
        except OSError as exc:
            return DiagnosticResult(
                name="journal_accessible",
                status=CheckStatus.failed,
                message=f"Journal file not accessible: {exc}",
                suggestion="Check file permissions on .reins/journal.jsonl",
            )

    def check_platform_configs(self) -> DiagnosticResult:
        """Check that platform config files exist and are valid."""
        if self.repo_root is None:
            return DiagnosticResult(
                name="platform_configs",
                status=CheckStatus.warning,
                message="Cannot check platform configs: no repo root",
                suggestion="Run 'reins init' first",
            )
        reins_dir = self.repo_root / ".reins"
        platform_indicators = [
            reins_dir / "platform.yaml",
            self.repo_root / ".claude" / "settings.json",
            self.repo_root / ".cursor" / "rules",
            self.repo_root / ".codex" / "config.yaml",
        ]
        found = [p for p in platform_indicators if p.exists()]
        if found:
            names = [str(p.relative_to(self.repo_root)) for p in found]
            return DiagnosticResult(
                name="platform_configs",
                status=CheckStatus.passed,
                message=f"Platform configs found: {', '.join(names)}",
            )
        return DiagnosticResult(
            name="platform_configs",
            status=CheckStatus.warning,
            message="No platform configuration files detected",
            suggestion="Run 'reins init --platform <name>' to configure a platform",
            doc_url="https://reins.dev/docs/platforms",
        )

    def run_all(self) -> list[DiagnosticResult]:
        """Run all diagnostic checks and return results."""
        return [
            self.check_python_version(),
            self.check_git_available(),
            self.check_reins_initialized(),
            self.check_dependencies(),
            self.check_config_valid(),
            self.check_journal_accessible(),
            self.check_platform_configs(),
        ]

    def format_results(self, results: list[DiagnosticResult]) -> str:
        """Format results as terminal-friendly output with status indicators."""
        lines: list[str] = []
        status_icons = {
            CheckStatus.passed: "[green]PASS[/green]",
            CheckStatus.warning: "[yellow]WARN[/yellow]",
            CheckStatus.failed: "[red]FAIL[/red]",
        }
        for result in results:
            icon = status_icons[result.status]
            lines.append(f"  {icon}  {result.name}: {result.message}")
            if result.suggestion:
                lines.append(f"         -> {result.suggestion}")
            if result.doc_url:
                lines.append(f"         Docs: {result.doc_url}")
        return "\n".join(lines)
