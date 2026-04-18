"""Hook system for extensible context injection and event handling.

The hook system provides extension points for platform-specific code
to inject context, modify behavior, or react to events.
"""

from reins.hooks.executor import (
    ExecutionConfig,
    ExecutionResult,
    HookExecutor,
    execute_hooks,
    execute_hooks_with_fallback,
)
from reins.hooks.registry import (
    HookRegistry,
    discover_hooks,
    get_hooks,
    get_registry,
    register_hook,
)
from reins.hooks.types import (
    Hook,
    HookContext,
    HookResult,
    HookStatus,
    PythonHook,
    ScriptHook,
)

__all__ = [
    # Types
    "Hook",
    "HookContext",
    "HookResult",
    "HookStatus",
    "ScriptHook",
    "PythonHook",
    # Registry
    "HookRegistry",
    "get_registry",
    "register_hook",
    "get_hooks",
    "discover_hooks",
    # Executor
    "HookExecutor",
    "ExecutionConfig",
    "ExecutionResult",
    "execute_hooks",
    "execute_hooks_with_fallback",
]
