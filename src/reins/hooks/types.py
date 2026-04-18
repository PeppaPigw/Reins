"""Hook system types and interfaces.

Hooks are extension points that allow platform-specific code to inject
context, modify behavior, or react to events in the Reins system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from reins.platform.types import HookType


class HookStatus(str, Enum):
    """Status of hook execution."""

    SUCCESS = "success"
    """Hook executed successfully"""

    FAILURE = "failure"
    """Hook execution failed"""

    TIMEOUT = "timeout"
    """Hook execution timed out"""

    SKIPPED = "skipped"
    """Hook was skipped (not applicable or disabled)"""


@dataclass
class HookContext:
    """Context passed to hooks during execution.

    Contains all information a hook might need to execute.
    """

    hook_type: HookType
    """Type of hook being executed"""

    platform: str
    """Platform name (e.g., 'claude-code', 'codex')"""

    repo_root: Path
    """Root directory of the repository"""

    task_id: str | None = None
    """Current task ID (if applicable)"""

    agent_type: str | None = None
    """Agent type for subagent hooks (e.g., 'implement', 'check')"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional context metadata"""

    def get(self, key: str, default: Any = None) -> Any:
        """Get metadata value.

        Args:
            key: Metadata key
            default: Default value if key not found

        Returns:
            Metadata value or default
        """
        return self.metadata.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set metadata value.

        Args:
            key: Metadata key
            value: Metadata value
        """
        self.metadata[key] = value


@dataclass
class HookResult:
    """Result of hook execution."""

    status: HookStatus
    """Execution status"""

    output: str = ""
    """Hook output (stdout)"""

    error: str = ""
    """Error message (stderr)"""

    duration_ms: float = 0.0
    """Execution duration in milliseconds"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional result metadata"""

    @property
    def success(self) -> bool:
        """Check if hook executed successfully."""
        return self.status == HookStatus.SUCCESS

    @property
    def failed(self) -> bool:
        """Check if hook failed."""
        return self.status == HookStatus.FAILURE

    @property
    def timed_out(self) -> bool:
        """Check if hook timed out."""
        return self.status == HookStatus.TIMEOUT


class Hook(ABC):
    """Base class for hooks.

    Hooks are extension points that allow platform-specific code to inject
    context, modify behavior, or react to events.
    """

    def __init__(self, hook_type: HookType, name: str) -> None:
        """Initialize hook.

        Args:
            hook_type: Type of hook
            name: Hook name
        """
        self.hook_type = hook_type
        self.name = name

    @abstractmethod
    def execute(self, context: HookContext) -> HookResult:
        """Execute the hook.

        Args:
            context: Hook execution context

        Returns:
            Hook execution result
        """
        pass

    @abstractmethod
    def validate(self, context: HookContext) -> bool:
        """Validate that the hook can execute in the given context.

        Args:
            context: Hook execution context

        Returns:
            True if hook can execute, False otherwise
        """
        pass

    def should_execute(self, context: HookContext) -> bool:
        """Check if hook should execute.

        Default implementation checks if hook type matches and validates context.

        Args:
            context: Hook execution context

        Returns:
            True if hook should execute, False otherwise
        """
        if context.hook_type != self.hook_type:
            return False

        return self.validate(context)


class ScriptHook(Hook):
    """Hook that executes a script file.

    Supports Python, shell, and other executable scripts.
    """

    def __init__(
        self,
        hook_type: HookType,
        name: str,
        script_path: Path,
        interpreter: str | None = None,
    ) -> None:
        """Initialize script hook.

        Args:
            hook_type: Type of hook
            name: Hook name
            script_path: Path to script file
            interpreter: Optional interpreter (e.g., 'python3', 'bash')
        """
        super().__init__(hook_type, name)
        self.script_path = script_path
        self.interpreter = interpreter

    def execute(self, context: HookContext) -> HookResult:
        """Execute the script.

        Args:
            context: Hook execution context

        Returns:
            Hook execution result
        """
        import subprocess
        import time

        start_time = time.time()

        try:
            # Build command
            if self.interpreter:
                cmd = [self.interpreter, str(self.script_path)]
            else:
                cmd = [str(self.script_path)]

            # Set environment variables
            env = self._build_env(context)

            # Execute script
            result = subprocess.run(
                cmd,
                cwd=context.repo_root,
                capture_output=True,
                text=True,
                timeout=5.0,  # 5 second timeout
                env=env,
            )

            duration_ms = (time.time() - start_time) * 1000

            if result.returncode == 0:
                return HookResult(
                    status=HookStatus.SUCCESS,
                    output=result.stdout,
                    error=result.stderr,
                    duration_ms=duration_ms,
                )
            else:
                return HookResult(
                    status=HookStatus.FAILURE,
                    output=result.stdout,
                    error=result.stderr,
                    duration_ms=duration_ms,
                )

        except subprocess.TimeoutExpired:
            duration_ms = (time.time() - start_time) * 1000
            return HookResult(
                status=HookStatus.TIMEOUT,
                error="Hook execution timed out after 5 seconds",
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return HookResult(
                status=HookStatus.FAILURE,
                error=f"Hook execution failed: {e}",
                duration_ms=duration_ms,
            )

    def validate(self, context: HookContext) -> bool:
        """Validate that script exists and is executable.

        Args:
            context: Hook execution context

        Returns:
            True if script is valid, False otherwise
        """
        if not self.script_path.exists():
            return False

        if not self.script_path.is_file():
            return False

        # Check if file is executable (on Unix-like systems)
        import os
        if hasattr(os, 'access'):
            if not os.access(self.script_path, os.X_OK):
                # If not executable but has interpreter, that's OK
                if not self.interpreter:
                    return False

        return True

    def _build_env(self, context: HookContext) -> dict[str, str]:
        """Build environment variables for script execution.

        Args:
            context: Hook execution context

        Returns:
            Environment variables dictionary
        """
        import os

        env = os.environ.copy()

        # Add Reins-specific environment variables
        env["REINS_HOOK_TYPE"] = context.hook_type.value
        env["REINS_PLATFORM"] = context.platform
        env["REINS_REPO_ROOT"] = str(context.repo_root)

        if context.task_id:
            env["REINS_TASK_ID"] = context.task_id

        if context.agent_type:
            env["REINS_AGENT_TYPE"] = context.agent_type

        # Add metadata as environment variables
        for key, value in context.metadata.items():
            env_key = f"REINS_{key.upper()}"
            env[env_key] = str(value)

        return env


class PythonHook(Hook):
    """Hook that executes a Python callable.

    Useful for in-process hooks without subprocess overhead.
    """

    def __init__(
        self,
        hook_type: HookType,
        name: str,
        callable_func: Any,
    ) -> None:
        """Initialize Python hook.

        Args:
            hook_type: Type of hook
            name: Hook name
            callable_func: Python callable to execute
        """
        super().__init__(hook_type, name)
        self.callable_func = callable_func

    def execute(self, context: HookContext) -> HookResult:
        """Execute the Python callable.

        Args:
            context: Hook execution context

        Returns:
            Hook execution result
        """
        import time

        start_time = time.time()

        try:
            # Execute callable
            output = self.callable_func(context)

            duration_ms = (time.time() - start_time) * 1000

            return HookResult(
                status=HookStatus.SUCCESS,
                output=str(output) if output else "",
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return HookResult(
                status=HookStatus.FAILURE,
                error=f"Hook execution failed: {e}",
                duration_ms=duration_ms,
            )

    def validate(self, context: HookContext) -> bool:
        """Validate that callable is valid.

        Args:
            context: Hook execution context

        Returns:
            True if callable is valid, False otherwise
        """
        return callable(self.callable_func)
