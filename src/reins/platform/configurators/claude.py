"""Claude Code platform configurator."""

from __future__ import annotations

import shutil
from typing import Mapping

from reins.platform.configurator import PlatformConfigurator
from reins.platform.template_fetcher import ConflictResolver, TemplateApplyResult


class ClaudeCodeConfigurator(PlatformConfigurator):
    """Install Claude Code hooks, settings, and agent scaffolding."""

    _MAPPING = {
        "hooks/session-start.py": ".claude/hooks/session-start.py",
        "hooks/inject-subagent-context.py": ".claude/hooks/inject-subagent-context.py",
        "agents/README.md": ".claude/agents/README.md",
        "settings.json": ".claude/settings.json",
    }

    def configure(
        self,
        *,
        variables: Mapping[str, str] | None = None,
        conflict_resolver: ConflictResolver | None = None,
    ) -> list[TemplateApplyResult]:
        self.ensure_config_dir()
        self.ensure_dir(self.config_path / "hooks")
        self.ensure_dir(self.config_path / "agents")
        self.ensure_dir(self.config_path / "commands")
        return self.apply_templates(
            self._MAPPING,
            variables=variables,
            conflict_resolver=conflict_resolver,
        )

    def validate(self) -> bool:
        required = [
            self.config_path,
            self.config_path / "hooks" / "session-start.py",
            self.config_path / "hooks" / "inject-subagent-context.py",
            self.config_path / "agents" / "README.md",
            self.config_path / "settings.json",
        ]
        return all(path.exists() for path in required)

    def cleanup(self) -> None:
        shutil.rmtree(self.config_path, ignore_errors=True)
        merge_files = [
            self.repo_root / ".claude" / "settings.json.reins-merge",
            self.repo_root / ".claude" / "hooks" / "session-start.py.reins-merge",
            self.repo_root / ".claude" / "hooks" / "inject-subagent-context.py.reins-merge",
        ]
        for merge_file in merge_files:
            if merge_file.exists():
                merge_file.unlink()
