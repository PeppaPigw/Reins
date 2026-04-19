"""Typed YAML configuration support for Reins."""

from reins.config.hooks import HookCommandResult, HookExecutor
from reins.config.loader import ConfigLoader, ConfigLoaderError
from reins.config.types import (
    HooksConfig,
    PackageConfig,
    ReinsConfig,
    UpdateConfig,
    WorktreeConfig,
)
from reins.config.validator import validate_config

__all__ = [
    "ConfigLoader",
    "ConfigLoaderError",
    "HookCommandResult",
    "HookExecutor",
    "HooksConfig",
    "PackageConfig",
    "ReinsConfig",
    "UpdateConfig",
    "WorktreeConfig",
    "validate_config",
]
