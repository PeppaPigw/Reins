"""Codex platform configurator."""

from __future__ import annotations

import shutil
from typing import Mapping

from reins.platform.configurator import PlatformConfigurator
from reins.platform.template_fetcher import ConflictResolver, TemplateApplyResult


class CodexConfigurator(PlatformConfigurator):
    """Install Codex configuration and MCP scaffolding."""

    _MAPPING = {
        "config.yaml": ".codex/config.yaml",
        "mcp.json": ".codex/mcp.json",
        "agents/README.md": ".codex/agents/README.md",
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
        return self.apply_templates(
            self._MAPPING,
            variables=variables,
            conflict_resolver=conflict_resolver,
        )

    def validate(self) -> bool:
        return all(
            path.exists()
            for path in (
                self.config_path,
                self.config_path / "config.yaml",
                self.config_path / "mcp.json",
                self.config_path / "agents" / "README.md",
            )
        )

    def cleanup(self) -> None:
        shutil.rmtree(self.config_path, ignore_errors=True)
        for path in (
            self.repo_root / ".codex" / "config.yaml.reins-merge",
            self.repo_root / ".codex" / "mcp.json.reins-merge",
        ):
            if path.exists():
                path.unlink()
