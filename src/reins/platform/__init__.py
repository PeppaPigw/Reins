"""Platform registry, detection, templates, and configuration helpers."""

from reins.platform.configurator import (
    GenericConfigurator,
    PlatformConfigurator,
    get_configurator,
)
from reins.platform.configurators.claude import ClaudeCodeConfigurator
from reins.platform.configurators.codex import CodexConfigurator
from reins.platform.configurators.cursor import CursorConfigurator
from reins.platform.project_detector import ProjectDetector, ProjectType
from reins.platform.registry import (
    PlatformRegistry,
    detect_platform,
    detect_platforms,
    get_platform,
    list_platforms,
    register_platform,
)
from reins.platform.template_fetcher import (
    ConflictAction,
    TemplateApplyResult,
    TemplateFetcher,
)
from reins.platform.template_hash import TemplateHashRecord, TemplateHashStore
from reins.platform.types import (
    ContextFormat,
    HookType,
    PlatformCapabilities,
    PlatformConfig,
    PlatformType,
)

__all__ = [
    "PlatformCapabilities",
    "PlatformConfig",
    "PlatformRegistry",
    "PlatformType",
    "HookType",
    "ContextFormat",
    "detect_platform",
    "detect_platforms",
    "get_platform",
    "list_platforms",
    "register_platform",
    "PlatformConfigurator",
    "ClaudeCodeConfigurator",
    "CursorConfigurator",
    "CodexConfigurator",
    "GenericConfigurator",
    "get_configurator",
    "ConflictAction",
    "TemplateApplyResult",
    "TemplateFetcher",
    "TemplateHashRecord",
    "TemplateHashStore",
    "ProjectDetector",
    "ProjectType",
]
