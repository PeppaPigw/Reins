"""Load and save `.reins/config.yaml`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from reins.config.types import HooksConfig, PackageConfig, ReinsConfig, UpdateConfig

DEFAULT_CONFIG_TEMPLATE = """# Reins Configuration
# Project-level settings

# Session recording
session_commit_message: "chore: record journal"
max_journal_lines: 2000

# Packages (for monorepo)
packages:
  # example:
  #   path: packages/example
  #   type: package

default_package: null

# Task lifecycle hooks
hooks:
  after_create: []
  after_start: []
  after_archive: []

# Update skip paths
update:
  skip: []
"""


class ConfigLoaderError(ValueError):
    """Raised when `.reins/config.yaml` cannot be parsed."""


class ConfigLoader:
    """Load and validate Reins configuration."""

    def __init__(self, reins_root: Path):
        self.reins_root = Path(reins_root)
        self.config_path = self.reins_root / "config.yaml"

    def load(self) -> ReinsConfig:
        """Load config from YAML file or return defaults when absent."""
        if not self.config_path.exists():
            return ReinsConfig()

        try:
            data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigLoaderError(
                f"Invalid YAML in {self.config_path}: {exc}"
            ) from exc

        return self.parse_data(data)

    def save(self, config: ReinsConfig) -> None:
        """Save config to YAML file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = config.to_dict()
        self.config_path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def write_default_template(self, *, force: bool = False) -> Path:
        """Write the default commented config template."""
        if self.config_path.exists() and not force:
            return self.config_path
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
        return self.config_path

    def parse_data(self, data: object) -> ReinsConfig:
        """Parse YAML data into ReinsConfig."""
        if not isinstance(data, dict):
            raise ConfigLoaderError(
                f"Config root must be a mapping in {self.config_path}"
            )

        session_commit_message = self._expect_string(
            data,
            "session_commit_message",
            default=ReinsConfig.session_commit_message,
        )
        max_journal_lines = self._expect_int(
            data,
            "max_journal_lines",
            default=ReinsConfig.max_journal_lines,
        )
        packages = self._parse_packages(data.get("packages", {}))
        default_package = self._expect_optional_string(data, "default_package")
        hooks = self._parse_hooks(data.get("hooks", {}))
        update = self._parse_update(data.get("update", {}))

        return ReinsConfig(
            session_commit_message=session_commit_message,
            max_journal_lines=max_journal_lines,
            packages=packages,
            default_package=default_package,
            hooks=hooks,
            update=update,
        )

    def _parse_packages(self, value: object) -> dict[str, PackageConfig]:
        if value in ({}, None):
            return {}
        if not isinstance(value, dict):
            raise ConfigLoaderError(
                f"'packages' must be a mapping in {self.config_path}"
            )

        packages: dict[str, PackageConfig] = {}
        for name, package_data in value.items():
            if not isinstance(name, str):
                raise ConfigLoaderError(
                    f"Package names must be strings in {self.config_path}"
                )
            if not isinstance(package_data, dict):
                raise ConfigLoaderError(
                    f"Package '{name}' must be a mapping in {self.config_path}"
                )
            path = package_data.get("path")
            package_type = package_data.get("type", "package")
            if not isinstance(path, str) or not path.strip():
                raise ConfigLoaderError(
                    f"Package '{name}' must define a non-empty string path"
                )
            if not isinstance(package_type, str) or not package_type.strip():
                raise ConfigLoaderError(
                    f"Package '{name}' type must be a non-empty string"
                )
            packages[name] = PackageConfig(path=path, type=package_type)
        return packages

    def _parse_hooks(self, value: object) -> HooksConfig:
        if value in ({}, None):
            return HooksConfig()
        if not isinstance(value, dict):
            raise ConfigLoaderError(
                f"'hooks' must be a mapping in {self.config_path}"
            )
        return HooksConfig(
            after_create=self._string_list(
                value.get("after_create", []),
                field_name="hooks.after_create",
            ),
            after_start=self._string_list(
                value.get("after_start", []),
                field_name="hooks.after_start",
            ),
            after_archive=self._string_list(
                value.get("after_archive", []),
                field_name="hooks.after_archive",
            ),
        )

    def _parse_update(self, value: object) -> UpdateConfig:
        if value in ({}, None):
            return UpdateConfig()
        if not isinstance(value, dict):
            raise ConfigLoaderError(
                f"'update' must be a mapping in {self.config_path}"
            )
        return UpdateConfig(
            skip=self._string_list(value.get("skip", []), field_name="update.skip")
        )

    def _expect_string(
        self,
        data: dict[str, Any],
        key: str,
        *,
        default: str,
    ) -> str:
        value = data.get(key, default)
        if not isinstance(value, str):
            raise ConfigLoaderError(
                f"'{key}' must be a string in {self.config_path}"
            )
        return value

    def _expect_optional_string(
        self,
        data: dict[str, Any],
        key: str,
    ) -> str | None:
        value = data.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ConfigLoaderError(
                f"'{key}' must be a string or null in {self.config_path}"
            )
        return value

    def _expect_int(
        self,
        data: dict[str, Any],
        key: str,
        *,
        default: int,
    ) -> int:
        value = data.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigLoaderError(
                f"'{key}' must be an integer in {self.config_path}"
            )
        return value

    def _string_list(self, value: object, *, field_name: str) -> list[str]:
        if value in (None, []):
            return []
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ConfigLoaderError(
                f"'{field_name}' must be a list of strings in {self.config_path}"
            )
        return list(value)
