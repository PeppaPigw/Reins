"""Tests for hook system."""

import pytest
from pathlib import Path

from reins.hooks import (
    ExecutionConfig,
    Hook,
    HookContext,
    HookExecutor,
    HookRegistry,
    HookResult,
    HookStatus,
    PythonHook,
    ScriptHook,
    discover_hooks,
    execute_hooks,
    get_registry,
)
from reins.platform import PlatformType, get_platform
from reins.platform.types import HookType


def test_hook_context_creation():
    """Test creating hook context."""
    context = HookContext(
        hook_type=HookType.SESSION_START,
        platform="claude-code",
        repo_root=Path("/test"),
        task_id="task-1",
        agent_type="implement",
        metadata={"key": "value"},
    )

    assert context.hook_type == HookType.SESSION_START
    assert context.platform == "claude-code"
    assert context.repo_root == Path("/test")
    assert context.task_id == "task-1"
    assert context.agent_type == "implement"
    assert context.get("key") == "value"


def test_hook_context_metadata():
    """Test hook context metadata operations."""
    context = HookContext(
        hook_type=HookType.SESSION_START,
        platform="claude-code",
        repo_root=Path("/test"),
    )

    # Set metadata
    context.set("test_key", "test_value")
    assert context.get("test_key") == "test_value"

    # Get with default
    assert context.get("nonexistent", "default") == "default"


def test_hook_result_properties():
    """Test hook result properties."""
    success_result = HookResult(status=HookStatus.SUCCESS, output="Success")
    assert success_result.success
    assert not success_result.failed
    assert not success_result.timed_out

    failure_result = HookResult(status=HookStatus.FAILURE, error="Failed")
    assert not failure_result.success
    assert failure_result.failed
    assert not failure_result.timed_out

    timeout_result = HookResult(status=HookStatus.TIMEOUT, error="Timeout")
    assert not timeout_result.success
    assert not timeout_result.failed
    assert timeout_result.timed_out


def test_python_hook_execution():
    """Test Python hook execution."""
    def test_func(context: HookContext) -> str:
        return f"Hello from {context.platform}"

    hook = PythonHook(
        hook_type=HookType.SESSION_START,
        name="test-hook",
        callable_func=test_func,
    )

    context = HookContext(
        hook_type=HookType.SESSION_START,
        platform="claude-code",
        repo_root=Path("/test"),
    )

    result = hook.execute(context)
    assert result.success
    assert "Hello from claude-code" in result.output


def test_python_hook_validation():
    """Test Python hook validation."""
    def test_func(context: HookContext) -> str:
        return "test"

    hook = PythonHook(
        hook_type=HookType.SESSION_START,
        name="test-hook",
        callable_func=test_func,
    )

    context = HookContext(
        hook_type=HookType.SESSION_START,
        platform="claude-code",
        repo_root=Path("/test"),
    )

    assert hook.validate(context)


def test_python_hook_error_handling():
    """Test Python hook error handling."""
    def failing_func(context: HookContext) -> str:
        raise ValueError("Test error")

    hook = PythonHook(
        hook_type=HookType.SESSION_START,
        name="failing-hook",
        callable_func=failing_func,
    )

    context = HookContext(
        hook_type=HookType.SESSION_START,
        platform="claude-code",
        repo_root=Path("/test"),
    )

    result = hook.execute(context)
    assert result.failed
    assert "Test error" in result.error


def test_script_hook_validation(tmp_path):
    """Test script hook validation."""
    # Create a test script
    script_path = tmp_path / "test-hook.py"
    script_path.write_text("#!/usr/bin/env python3\nprint('test')")
    script_path.chmod(0o755)

    hook = ScriptHook(
        hook_type=HookType.SESSION_START,
        name="test-hook",
        script_path=script_path,
        interpreter="python3",
    )

    context = HookContext(
        hook_type=HookType.SESSION_START,
        platform="claude-code",
        repo_root=tmp_path,
    )

    assert hook.validate(context)


def test_script_hook_validation_nonexistent():
    """Test script hook validation with nonexistent file."""
    hook = ScriptHook(
        hook_type=HookType.SESSION_START,
        name="test-hook",
        script_path=Path("/nonexistent/hook.py"),
        interpreter="python3",
    )

    context = HookContext(
        hook_type=HookType.SESSION_START,
        platform="claude-code",
        repo_root=Path("/test"),
    )

    assert not hook.validate(context)


def test_script_hook_execution(tmp_path):
    """Test script hook execution."""
    # Create a test script
    script_path = tmp_path / "test-hook.py"
    script_path.write_text("#!/usr/bin/env python3\nprint('Hello from script')")
    script_path.chmod(0o755)

    hook = ScriptHook(
        hook_type=HookType.SESSION_START,
        name="test-hook",
        script_path=script_path,
        interpreter="python3",
    )

    context = HookContext(
        hook_type=HookType.SESSION_START,
        platform="claude-code",
        repo_root=tmp_path,
    )

    result = hook.execute(context)
    assert result.success
    assert "Hello from script" in result.output


def test_script_hook_environment_variables(tmp_path):
    """Test script hook environment variables."""
    # Create a script that prints environment variables
    script_path = tmp_path / "test-hook.py"
    script_path.write_text("""#!/usr/bin/env python3
import os
print(f"HOOK_TYPE={os.environ.get('REINS_HOOK_TYPE')}")
print(f"PLATFORM={os.environ.get('REINS_PLATFORM')}")
print(f"TASK_ID={os.environ.get('REINS_TASK_ID')}")
""")
    script_path.chmod(0o755)

    hook = ScriptHook(
        hook_type=HookType.SESSION_START,
        name="test-hook",
        script_path=script_path,
        interpreter="python3",
    )

    context = HookContext(
        hook_type=HookType.SESSION_START,
        platform="claude-code",
        repo_root=tmp_path,
        task_id="task-123",
    )

    result = hook.execute(context)
    assert result.success
    assert "HOOK_TYPE=session_start" in result.output
    assert "PLATFORM=claude-code" in result.output
    assert "TASK_ID=task-123" in result.output


def test_hook_registry_register():
    """Test registering hooks."""
    registry = HookRegistry()

    def test_func(context: HookContext) -> str:
        return "test"

    hook = PythonHook(
        hook_type=HookType.SESSION_START,
        name="test-hook",
        callable_func=test_func,
    )

    registry.register(hook)

    hooks = registry.get_hooks(HookType.SESSION_START)
    assert len(hooks) == 1
    assert hooks[0] == hook


def test_hook_registry_unregister():
    """Test unregistering hooks."""
    registry = HookRegistry()

    def test_func(context: HookContext) -> str:
        return "test"

    hook = PythonHook(
        hook_type=HookType.SESSION_START,
        name="test-hook",
        callable_func=test_func,
    )

    registry.register(hook)
    assert registry.has_hooks(HookType.SESSION_START)

    registry.unregister(hook)
    assert not registry.has_hooks(HookType.SESSION_START)


def test_hook_registry_discover(tmp_path):
    """Test discovering hooks from platform directory."""
    # Create platform hook directory
    hook_dir = tmp_path / ".claude" / "hooks"
    hook_dir.mkdir(parents=True)

    # Create test hooks
    (hook_dir / "session-start.py").write_text("#!/usr/bin/env python3\nprint('test')")
    (hook_dir / "session-start.py").chmod(0o755)

    (hook_dir / "task-start.sh").write_text("#!/bin/bash\necho 'test'")
    (hook_dir / "task-start.sh").chmod(0o755)

    # Get platform config
    platform_config = get_platform(PlatformType.CLAUDE_CODE)
    assert platform_config is not None

    # Discover hooks
    registry = HookRegistry()
    count = registry.discover_platform_hooks(platform_config, tmp_path)

    assert count == 2
    assert registry.has_hooks(HookType.SESSION_START)
    assert registry.has_hooks(HookType.TASK_START)


def test_hook_executor_execute():
    """Test executing hooks."""
    registry = HookRegistry()
    executor = HookExecutor(registry)

    def test_func(context: HookContext) -> str:
        return "Success"

    hook = PythonHook(
        hook_type=HookType.SESSION_START,
        name="test-hook",
        callable_func=test_func,
    )

    registry.register(hook)

    context = HookContext(
        hook_type=HookType.SESSION_START,
        platform="claude-code",
        repo_root=Path("/test"),
    )

    result = executor.execute(HookType.SESSION_START, context)

    assert result.success
    assert result.hooks_executed == 1
    assert result.hooks_succeeded == 1
    assert result.hooks_failed == 0


def test_hook_executor_multiple_hooks():
    """Test executing multiple hooks."""
    registry = HookRegistry()
    executor = HookExecutor(registry)

    def hook1_func(context: HookContext) -> str:
        return "Hook 1"

    def hook2_func(context: HookContext) -> str:
        return "Hook 2"

    hook1 = PythonHook(
        hook_type=HookType.SESSION_START,
        name="hook-1",
        callable_func=hook1_func,
    )

    hook2 = PythonHook(
        hook_type=HookType.SESSION_START,
        name="hook-2",
        callable_func=hook2_func,
    )

    registry.register(hook1)
    registry.register(hook2)

    context = HookContext(
        hook_type=HookType.SESSION_START,
        platform="claude-code",
        repo_root=Path("/test"),
    )

    result = executor.execute(HookType.SESSION_START, context)

    assert result.success
    assert result.hooks_executed == 2
    assert result.hooks_succeeded == 2
    assert "Hook 1" in result.get_combined_output()
    assert "Hook 2" in result.get_combined_output()


def test_hook_executor_continue_on_failure():
    """Test continuing execution after failure."""
    registry = HookRegistry()
    executor = HookExecutor(registry)

    def failing_func(context: HookContext) -> str:
        raise ValueError("Fail")

    def success_func(context: HookContext) -> str:
        return "Success"

    hook1 = PythonHook(
        hook_type=HookType.SESSION_START,
        name="failing-hook",
        callable_func=failing_func,
    )

    hook2 = PythonHook(
        hook_type=HookType.SESSION_START,
        name="success-hook",
        callable_func=success_func,
    )

    registry.register(hook1)
    registry.register(hook2)

    context = HookContext(
        hook_type=HookType.SESSION_START,
        platform="claude-code",
        repo_root=Path("/test"),
    )

    # Continue on failure (default)
    config = ExecutionConfig(continue_on_failure=True)
    result = executor.execute(HookType.SESSION_START, context, config)

    assert result.hooks_executed == 2
    assert result.hooks_failed == 1
    assert result.hooks_succeeded == 1


def test_hook_executor_stop_on_failure():
    """Test stopping execution on failure."""
    registry = HookRegistry()
    executor = HookExecutor(registry)

    def failing_func(context: HookContext) -> str:
        raise ValueError("Fail")

    def success_func(context: HookContext) -> str:
        return "Success"

    hook1 = PythonHook(
        hook_type=HookType.SESSION_START,
        name="failing-hook",
        callable_func=failing_func,
    )

    hook2 = PythonHook(
        hook_type=HookType.SESSION_START,
        name="success-hook",
        callable_func=success_func,
    )

    registry.register(hook1)
    registry.register(hook2)

    context = HookContext(
        hook_type=HookType.SESSION_START,
        platform="claude-code",
        repo_root=Path("/test"),
    )

    # Stop on failure
    config = ExecutionConfig(continue_on_failure=False)
    result = executor.execute(HookType.SESSION_START, context, config)

    assert result.hooks_executed == 1
    assert result.hooks_failed == 1
    assert result.hooks_succeeded == 0


def test_hook_executor_with_fallback():
    """Test executing hooks with fallback."""
    registry = HookRegistry()
    executor = HookExecutor(registry)

    context = HookContext(
        hook_type=HookType.SESSION_START,
        platform="claude-code",
        repo_root=Path("/test"),
    )

    # No hooks registered, should use fallback
    result, output = executor.execute_with_fallback(
        HookType.SESSION_START,
        context,
        fallback_output="Fallback output",
    )

    assert output == "Fallback output"


def test_hook_executor_validate_hooks():
    """Test validating hooks."""
    registry = HookRegistry()
    executor = HookExecutor(registry)

    def test_func(context: HookContext) -> str:
        return "test"

    hook = PythonHook(
        hook_type=HookType.SESSION_START,
        name="test-hook",
        callable_func=test_func,
    )

    registry.register(hook)

    context = HookContext(
        hook_type=HookType.SESSION_START,
        platform="claude-code",
        repo_root=Path("/test"),
    )

    validation_results = executor.validate_hooks(HookType.SESSION_START, context)

    assert "test-hook" in validation_results
    assert validation_results["test-hook"] is True


def test_hook_executor_get_executable_hooks():
    """Test getting executable hooks."""
    registry = HookRegistry()
    executor = HookExecutor(registry)

    def test_func(context: HookContext) -> str:
        return "test"

    hook = PythonHook(
        hook_type=HookType.SESSION_START,
        name="test-hook",
        callable_func=test_func,
    )

    registry.register(hook)

    context = HookContext(
        hook_type=HookType.SESSION_START,
        platform="claude-code",
        repo_root=Path("/test"),
    )

    executable = executor.get_executable_hooks(HookType.SESSION_START, context)

    assert len(executable) == 1
    assert executable[0] == hook


def test_global_functions():
    """Test global hook functions."""
    # Clear global registry first
    registry = get_registry()
    registry.clear()

    def test_func(context: HookContext) -> str:
        return "test"

    hook = PythonHook(
        hook_type=HookType.SESSION_START,
        name="test-hook",
        callable_func=test_func,
    )

    # Register using global function
    from reins.hooks import register_hook
    register_hook(hook)

    # Get using global function
    from reins.hooks import get_hooks
    hooks = get_hooks(HookType.SESSION_START)

    assert len(hooks) == 1
    assert hooks[0] == hook

    # Execute using global function
    context = HookContext(
        hook_type=HookType.SESSION_START,
        platform="claude-code",
        repo_root=Path("/test"),
    )

    result = execute_hooks(HookType.SESSION_START, context)
    assert result.success
