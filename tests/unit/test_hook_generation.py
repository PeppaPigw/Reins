"""Tests for shared hook generation."""

from __future__ import annotations

from reins.platform.hooks.templates import (
    HOOK_SHEBANG,
    HOOK_TEMPLATES,
    generate_all_hooks,
    generate_hook,
    get_hooks_for_platform,
)
from reins.platform.types import HookType, PlatformType


def test_generate_hook_session_start_valid_python() -> None:
    """Generated SESSION_START hook is valid Python."""
    script = generate_hook(
        HookType.SESSION_START, PlatformType.CLAUDE_CODE
    )
    # compile() will raise SyntaxError if invalid
    compile(script, "<session_start>", "exec")


def test_generate_hook_includes_shebang() -> None:
    """Generated hooks start with the Python shebang."""
    script = generate_hook(
        HookType.SESSION_START, PlatformType.CLAUDE_CODE
    )
    assert script.startswith(HOOK_SHEBANG)


def test_generate_hook_substitutes_variables() -> None:
    """Variable placeholders are replaced in generated hooks."""
    script = generate_hook(
        HookType.SESSION_START,
        PlatformType.CLAUDE_CODE,
        {"repo_root": "/tmp/test"},
    )
    assert "/tmp/test" in script
    assert "{{repo_root}}" not in script


def test_get_hooks_for_platform_claude_has_hooks() -> None:
    """Claude Code platform returns a non-empty hook list."""
    hooks = get_hooks_for_platform(PlatformType.CLAUDE_CODE)
    assert len(hooks) > 0
    assert HookType.SESSION_START in hooks


def test_get_hooks_for_platform_cursor_empty() -> None:
    """Cursor platform returns empty hook list (hooks=False)."""
    hooks = get_hooks_for_platform(PlatformType.CURSOR)
    assert hooks == []


def test_generate_all_hooks_claude() -> None:
    """Claude Code generates hooks with expected filenames."""
    result = generate_all_hooks(PlatformType.CLAUDE_CODE)
    assert len(result) > 0
    assert "session-start.py" in result
    # All values should be non-empty strings
    for filename, content in result.items():
        assert filename.endswith(".py")
        assert len(content) > 0


def test_generate_all_hooks_cursor_empty() -> None:
    """Cursor platform generates no hooks."""
    result = generate_all_hooks(PlatformType.CURSOR)
    assert result == {}


def test_all_hook_templates_compile() -> None:
    """Every hook template generates valid Python when rendered."""
    for hook_type in HOOK_TEMPLATES:
        script = generate_hook(hook_type, PlatformType.CLAUDE_CODE)
        compile(script, f"<{hook_type.value}>", "exec")
