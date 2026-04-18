"""Cursor platform configurator."""

from __future__ import annotations

import shutil
from typing import Mapping

from reins.platform.configurator import PlatformConfigurator
from reins.platform.template_fetcher import ConflictResolver, TemplateApplyResult


class CursorConfigurator(PlatformConfigurator):
    """Install Cursor rules and project-local settings."""

    _MAPPING = {
        ".cursorrules": ".cursorrules",
        "settings.json": ".cursor/settings.json",
    }

    def configure(
        self,
        *,
        variables: Mapping[str, str] | None = None,
        conflict_resolver: ConflictResolver | None = None,
    ) -> list[TemplateApplyResult]:
        self.ensure_config_dir()
        return self.apply_templates(
            self._MAPPING,
            variables=variables,
            conflict_resolver=conflict_resolver,
        )

    def validate(self) -> bool:
        return all(
            path.exists()
            for path in (
                self.repo_root / ".cursorrules",
                self.config_path,
                self.config_path / "settings.json",
            )
        )

    def cleanup(self) -> None:
        shutil.rmtree(self.config_path, ignore_errors=True)
        for path in (
            self.repo_root / ".cursorrules",
            self.repo_root / ".cursorrules.reins-merge",
            self.repo_root / ".cursor" / "settings.json.reins-merge",
        ):
            if path.exists():
                path.unlink()
