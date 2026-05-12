"""Hook templates and generation utilities for platform configurators."""

from __future__ import annotations

import re

from reins.platform.registry import get_platform
from reins.platform.types import HookType, PlatformType

HOOK_SHEBANG = "#!/usr/bin/env python3"

# Hook templates — each is a Python script body with {{variable}} placeholders
HOOK_TEMPLATES: dict[HookType, str] = {
    HookType.SESSION_START: '''"""Session start hook — loads current task context."""

import json
import sys
from pathlib import Path


def main() -> None:
    repo_root = Path("{{repo_root}}") if "{{repo_root}}" != "." else Path.cwd()
    reins_dir = repo_root / ".reins"
    current_task_file = reins_dir / ".current-task"

    if not current_task_file.exists():
        return

    task_dir = current_task_file.read_text().strip()
    if not task_dir:
        return

    task_path = reins_dir / "tasks" / task_dir
    prd_file = task_path / "prd.md"

    output_parts = []
    if prd_file.exists():
        output_parts.append(
            f"<task-context>\\n{prd_file.read_text()}\\n</task-context>"
        )

    if output_parts:
        print("\\n".join(output_parts))


if __name__ == "__main__":
    main()
''',
    HookType.SESSION_END: '''"""Session end hook — logs session completion."""

from pathlib import Path


def main() -> None:
    pass


if __name__ == "__main__":
    main()
''',
    HookType.SUBAGENT_SPAWN: '''"""Subagent spawn hook — injects context for subagents."""

import sys
from pathlib import Path


def main() -> None:
    repo_root = Path("{{repo_root}}") if "{{repo_root}}" != "." else Path.cwd()
    reins_dir = repo_root / ".reins"
    current_task_file = reins_dir / ".current-task"

    if not current_task_file.exists():
        return

    task_dir = current_task_file.read_text().strip()
    if not task_dir:
        return

    task_path = reins_dir / "tasks" / task_dir
    prd_file = task_path / "prd.md"

    if prd_file.exists():
        print(
            f"<subagent-context>\\n{prd_file.read_text()}\\n"
            f"</subagent-context>"
        )


if __name__ == "__main__":
    main()
''',
    HookType.TASK_START: '''"""Task start hook — loads task PRD and checklist."""

from pathlib import Path


def main() -> None:
    pass


if __name__ == "__main__":
    main()
''',
    HookType.TASK_COMPLETE: '''"""Task complete hook — archives task artifacts."""

from pathlib import Path


def main() -> None:
    pass


if __name__ == "__main__":
    main()
''',
    HookType.CONTEXT_INJECT: '''"""Context injection hook — assembles context shards."""

from pathlib import Path


def main() -> None:
    pass


if __name__ == "__main__":
    main()
''',
    HookType.TOOL_CALL: '''"""Tool call hook — intercepts tool invocations."""

from pathlib import Path


def main() -> None:
    pass


if __name__ == "__main__":
    main()
''',
}


def _substitute_variables(
    template: str, variables: dict[str, str]
) -> str:
    """Replace {{variable}} placeholders in template."""

    def replacer(match: re.Match) -> str:  # type: ignore[type-arg]
        key = match.group(1).strip()
        return variables.get(key, match.group(0))

    return re.sub(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", replacer, template)


def generate_hook(
    hook_type: HookType,
    platform_type: PlatformType,
    variables: dict[str, str] | None = None,
) -> str:
    """Generate a hook script for the given type and platform."""
    template = HOOK_TEMPLATES.get(hook_type)
    if template is None:
        return ""
    vars_with_defaults = {"repo_root": ".", "platform": platform_type.value}
    if variables:
        vars_with_defaults.update(variables)
    body = _substitute_variables(template, vars_with_defaults)
    return f"{HOOK_SHEBANG}\n{body}"


def get_hooks_for_platform(platform_type: PlatformType) -> list[HookType]:
    """Return the list of supported hook types for a platform."""
    config = get_platform(platform_type)
    if config is None:
        return []
    if not config.capabilities.supports_hooks:
        return []
    return list(config.capabilities.supported_hooks)


def generate_all_hooks(
    platform_type: PlatformType,
    variables: dict[str, str] | None = None,
) -> dict[str, str]:
    """Generate all hook scripts for a platform.

    Returns a dict mapping filename to script content.
    """
    hooks = get_hooks_for_platform(platform_type)
    result: dict[str, str] = {}
    for hook_type in hooks:
        filename = f"{hook_type.value.replace('_', '-')}.py"
        content = generate_hook(hook_type, platform_type, variables)
        if content:
            result[filename] = content
    return result
