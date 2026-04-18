"""Hook registry for discovery and management.

The registry discovers hooks from platform directories and manages
hook execution.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reins.hooks.types import Hook, HookContext, HookResult, HookStatus, ScriptHook
from reins.platform.types import HookType, PlatformConfig


class HookRegistry:
    """Registry for discovering and managing hooks.

    Discovers hooks from platform directories and provides methods
    for executing hooks by type.
    """

    def __init__(self) -> None:
        """Initialize hook registry."""
        self._hooks: dict[HookType, list[Hook]] = {}

    def register(self, hook: Hook) -> None:
        """Register a hook.

        Args:
            hook: Hook to register
        """
        if hook.hook_type not in self._hooks:
            self._hooks[hook.hook_type] = []

        self._hooks[hook.hook_type].append(hook)

    def unregister(self, hook: Hook) -> None:
        """Unregister a hook.

        Args:
            hook: Hook to unregister
        """
        if hook.hook_type in self._hooks:
            self._hooks[hook.hook_type] = [
                h for h in self._hooks[hook.hook_type] if h != hook
            ]

    def get_hooks(self, hook_type: HookType) -> list[Hook]:
        """Get all hooks of a specific type.

        Args:
            hook_type: Type of hooks to get

        Returns:
            List of hooks
        """
        return self._hooks.get(hook_type, [])

    def has_hooks(self, hook_type: HookType) -> bool:
        """Check if any hooks are registered for a type.

        Args:
            hook_type: Type of hooks to check

        Returns:
            True if hooks exist, False otherwise
        """
        return hook_type in self._hooks and len(self._hooks[hook_type]) > 0

    def discover_platform_hooks(
        self, platform_config: PlatformConfig, repo_root: Path
    ) -> int:
        """Discover hooks from platform directory.

        Args:
            platform_config: Platform configuration
            repo_root: Repository root directory

        Returns:
            Number of hooks discovered
        """
        if not platform_config.capabilities.supports_hooks:
            return 0

        if not platform_config.hook_path:
            return 0

        hook_dir = repo_root / platform_config.hook_path
        if not hook_dir.exists():
            return 0

        discovered = 0

        # Discover Python hooks
        for hook_file in hook_dir.glob("*.py"):
            hook = self._create_script_hook(hook_file, platform_config)
            if hook:
                self.register(hook)
                discovered += 1

        # Discover shell hooks
        for hook_file in hook_dir.glob("*.sh"):
            hook = self._create_script_hook(hook_file, platform_config)
            if hook:
                self.register(hook)
                discovered += 1

        return discovered

    def _create_script_hook(
        self, script_path: Path, platform_config: PlatformConfig
    ) -> Hook | None:
        """Create a script hook from a file.

        Args:
            script_path: Path to script file
            platform_config: Platform configuration

        Returns:
            Hook instance or None if hook type cannot be determined
        """
        # Determine hook type from filename
        hook_type = self._determine_hook_type(script_path.stem)
        if not hook_type:
            return None

        # Determine interpreter
        interpreter = None
        if script_path.suffix == ".py":
            interpreter = "python3"
        elif script_path.suffix == ".sh":
            interpreter = "bash"

        return ScriptHook(
            hook_type=hook_type,
            name=script_path.stem,
            script_path=script_path,
            interpreter=interpreter,
        )

    def _determine_hook_type(self, filename: str) -> HookType | None:
        """Determine hook type from filename.

        Args:
            filename: Hook filename (without extension)

        Returns:
            Hook type or None if cannot be determined
        """
        # Map common filenames to hook types
        mapping = {
            "session-start": HookType.SESSION_START,
            "session_start": HookType.SESSION_START,
            "session-end": HookType.SESSION_END,
            "session_end": HookType.SESSION_END,
            "subagent-spawn": HookType.SUBAGENT_SPAWN,
            "subagent_spawn": HookType.SUBAGENT_SPAWN,
            "inject-subagent-context": HookType.SUBAGENT_SPAWN,
            "inject_subagent_context": HookType.SUBAGENT_SPAWN,
            "subagent-complete": HookType.SUBAGENT_COMPLETE,
            "subagent_complete": HookType.SUBAGENT_COMPLETE,
            "task-start": HookType.TASK_START,
            "task_start": HookType.TASK_START,
            "task-complete": HookType.TASK_COMPLETE,
            "task_complete": HookType.TASK_COMPLETE,
            "context-inject": HookType.CONTEXT_INJECT,
            "context_inject": HookType.CONTEXT_INJECT,
            "tool-call": HookType.TOOL_CALL,
            "tool_call": HookType.TOOL_CALL,
        }

        return mapping.get(filename)

    def clear(self) -> None:
        """Clear all registered hooks."""
        self._hooks.clear()

    def count(self) -> int:
        """Count total number of registered hooks.

        Returns:
            Total number of hooks
        """
        return sum(len(hooks) for hooks in self._hooks.values())

    def list_hook_types(self) -> list[HookType]:
        """List all hook types that have registered hooks.

        Returns:
            List of hook types
        """
        return list(self._hooks.keys())


# Global registry instance
_registry = HookRegistry()


def get_registry() -> HookRegistry:
    """Get the global hook registry.

    Returns:
        Global hook registry instance
    """
    return _registry


def register_hook(hook: Hook) -> None:
    """Register a hook in the global registry.

    Args:
        hook: Hook to register
    """
    _registry.register(hook)


def get_hooks(hook_type: HookType) -> list[Hook]:
    """Get hooks of a specific type from the global registry.

    Args:
        hook_type: Type of hooks to get

    Returns:
        List of hooks
    """
    return _registry.get_hooks(hook_type)


def discover_hooks(platform_config: PlatformConfig, repo_root: Path) -> int:
    """Discover hooks from platform directory.

    Args:
        platform_config: Platform configuration
        repo_root: Repository root directory

    Returns:
        Number of hooks discovered
    """
    return _registry.discover_platform_hooks(platform_config, repo_root)
