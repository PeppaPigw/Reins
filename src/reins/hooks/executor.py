"""Hook executor with timeout and error handling.

Executes hooks with proper error handling, timeout management,
and fallback strategies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reins.hooks.registry import HookRegistry, get_registry
from reins.hooks.types import Hook, HookContext, HookResult, HookStatus
from reins.platform.types import HookType


@dataclass
class ExecutionConfig:
    """Configuration for hook execution."""

    timeout_ms: float = 5000.0
    """Timeout in milliseconds (default: 5 seconds)"""

    continue_on_failure: bool = True
    """Continue executing remaining hooks if one fails"""

    collect_all_results: bool = True
    """Collect results from all hooks (even if some fail)"""

    skip_validation: bool = False
    """Skip hook validation before execution"""


@dataclass
class ExecutionResult:
    """Result of executing multiple hooks."""

    hook_type: HookType
    """Type of hooks executed"""

    results: list[HookResult] = field(default_factory=list)
    """Individual hook results"""

    total_duration_ms: float = 0.0
    """Total execution duration in milliseconds"""

    hooks_executed: int = 0
    """Number of hooks executed"""

    hooks_succeeded: int = 0
    """Number of hooks that succeeded"""

    hooks_failed: int = 0
    """Number of hooks that failed"""

    hooks_timed_out: int = 0
    """Number of hooks that timed out"""

    hooks_skipped: int = 0
    """Number of hooks that were skipped"""

    @property
    def success(self) -> bool:
        """Check if all hooks succeeded."""
        return self.hooks_failed == 0 and self.hooks_timed_out == 0

    @property
    def partial_success(self) -> bool:
        """Check if at least one hook succeeded."""
        return self.hooks_succeeded > 0

    def get_combined_output(self) -> str:
        """Get combined output from all hooks.

        Returns:
            Combined output string
        """
        outputs = [r.output for r in self.results if r.output]
        return "\n".join(outputs)

    def get_combined_errors(self) -> str:
        """Get combined errors from all hooks.

        Returns:
            Combined error string
        """
        errors = [r.error for r in self.results if r.error]
        return "\n".join(errors)


class HookExecutor:
    """Executes hooks with timeout and error handling.

    Provides a robust execution pipeline for hooks with proper
    error handling, timeout management, and fallback strategies.
    """

    def __init__(self, registry: HookRegistry | None = None) -> None:
        """Initialize hook executor.

        Args:
            registry: Hook registry (uses global registry if None)
        """
        self._registry = registry or get_registry()

    def execute(
        self,
        hook_type: HookType,
        context: HookContext,
        config: ExecutionConfig | None = None,
    ) -> ExecutionResult:
        """Execute all hooks of a specific type.

        Args:
            hook_type: Type of hooks to execute
            context: Hook execution context
            config: Execution configuration

        Returns:
            Execution result
        """
        config = config or ExecutionConfig()

        result = ExecutionResult(hook_type=hook_type)

        # Get hooks
        hooks = self._registry.get_hooks(hook_type)
        if not hooks:
            return result

        import time
        start_time = time.time()

        # Execute each hook
        for hook in hooks:
            # Check if hook should execute
            if not config.skip_validation and not hook.should_execute(context):
                hook_result = HookResult(
                    status=HookStatus.SKIPPED,
                    output=f"Hook {hook.name} skipped (validation failed)",
                )
                result.results.append(hook_result)
                result.hooks_skipped += 1
                continue

            # Execute hook
            hook_result = self._execute_single_hook(hook, context, config)
            result.results.append(hook_result)
            result.hooks_executed += 1

            # Update counters
            if hook_result.success:
                result.hooks_succeeded += 1
            elif hook_result.failed:
                result.hooks_failed += 1
            elif hook_result.timed_out:
                result.hooks_timed_out += 1

            # Check if we should continue
            if not config.continue_on_failure and hook_result.failed:
                break

        result.total_duration_ms = (time.time() - start_time) * 1000

        return result

    def _execute_single_hook(
        self,
        hook: Hook,
        context: HookContext,
        config: ExecutionConfig,
    ) -> HookResult:
        """Execute a single hook with timeout.

        Args:
            hook: Hook to execute
            context: Hook execution context
            config: Execution configuration

        Returns:
            Hook execution result
        """
        try:
            # Execute hook
            result = hook.execute(context)

            # Check timeout
            if result.duration_ms > config.timeout_ms:
                return HookResult(
                    status=HookStatus.TIMEOUT,
                    output=result.output,
                    error=f"Hook exceeded timeout ({config.timeout_ms}ms)",
                    duration_ms=result.duration_ms,
                )

            return result

        except Exception as e:
            return HookResult(
                status=HookStatus.FAILURE,
                error=f"Hook execution failed: {e}",
            )

    def execute_with_fallback(
        self,
        hook_type: HookType,
        context: HookContext,
        fallback_output: str = "",
        config: ExecutionConfig | None = None,
    ) -> tuple[ExecutionResult, str]:
        """Execute hooks with fallback output if all fail.

        Args:
            hook_type: Type of hooks to execute
            context: Hook execution context
            fallback_output: Fallback output if all hooks fail
            config: Execution configuration

        Returns:
            Tuple of (execution result, output string)
        """
        result = self.execute(hook_type, context, config)

        # If no hooks executed or all failed, use fallback
        if result.hooks_executed == 0 or (not result.success and not result.partial_success):
            return result, fallback_output

        # Otherwise use combined output
        return result, result.get_combined_output()

    def validate_hooks(
        self,
        hook_type: HookType,
        context: HookContext,
    ) -> dict[str, bool]:
        """Validate all hooks of a specific type.

        Args:
            hook_type: Type of hooks to validate
            context: Hook execution context

        Returns:
            Dictionary mapping hook names to validation results
        """
        hooks = self._registry.get_hooks(hook_type)
        return {hook.name: hook.validate(context) for hook in hooks}

    def get_executable_hooks(
        self,
        hook_type: HookType,
        context: HookContext,
    ) -> list[Hook]:
        """Get hooks that can execute in the given context.

        Args:
            hook_type: Type of hooks to check
            context: Hook execution context

        Returns:
            List of executable hooks
        """
        hooks = self._registry.get_hooks(hook_type)
        return [hook for hook in hooks if hook.should_execute(context)]


# Global executor instance
_executor = HookExecutor()


def execute_hooks(
    hook_type: HookType,
    context: HookContext,
    config: ExecutionConfig | None = None,
) -> ExecutionResult:
    """Execute hooks using the global executor.

    Args:
        hook_type: Type of hooks to execute
        context: Hook execution context
        config: Execution configuration

    Returns:
        Execution result
    """
    return _executor.execute(hook_type, context, config)


def execute_hooks_with_fallback(
    hook_type: HookType,
    context: HookContext,
    fallback_output: str = "",
    config: ExecutionConfig | None = None,
) -> tuple[ExecutionResult, str]:
    """Execute hooks with fallback using the global executor.

    Args:
        hook_type: Type of hooks to execute
        context: Hook execution context
        fallback_output: Fallback output if all hooks fail
        config: Execution configuration

    Returns:
        Tuple of (execution result, output string)
    """
    return _executor.execute_with_fallback(hook_type, context, fallback_output, config)
