"""Platform registry and configuration for multi-tool support.

This module provides a single source of truth for platform metadata,
capabilities, and configuration across different AI coding tools.
"""

from reins.platform.configurator import (
    ClaudeCodeConfigurator,
    CodexConfigurator,
    GenericConfigurator,
    PlatformConfigurator,
    get_configurator,
)
from reins.platform.registry import (
    PlatformCapabilities,
    PlatformConfig,
    PlatformRegistry,
    get_platform,
    list_platforms,
    register_platform,
)
from reins.platform.types import ContextFormat, HookType, PlatformType

__all__ = [
    "PlatformCapabilities",
    "PlatformConfig",
    "PlatformRegistry",
    "PlatformType",
    "HookType",
    "ContextFormat",
    "get_platform",
    "list_platforms",
    "register_platform",
    "PlatformConfigurator",
    "ClaudeCodeConfigurator",
    "CodexConfigurator",
    "GenericConfigurator",
    "get_configurator",
]
