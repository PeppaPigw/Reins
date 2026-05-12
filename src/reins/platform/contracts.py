"""Contract validation schemas for platform-generated configurations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from reins.platform.registry import detect_platforms
from reins.platform.types import PlatformConfig, PlatformType


@dataclass(frozen=True)
class ContractViolation:
    """A single contract validation failure."""

    platform: PlatformType
    path: str
    rule: str
    detail: str


@dataclass(frozen=True)
class PlatformContract:
    """Validation contract for a platform's generated config."""

    platform_type: PlatformType
    required_paths: tuple[str, ...] = ()
    required_content: dict[str, list[str]] = field(default_factory=dict)
    forbidden_content: dict[str, list[str]] = field(default_factory=dict)


# --- Contract definitions for all 14 platforms + CUSTOM ---

PLATFORM_CONTRACTS: dict[PlatformType, PlatformContract] = {
    PlatformType.CLAUDE_CODE: PlatformContract(
        platform_type=PlatformType.CLAUDE_CODE,
        required_paths=("hooks", "agents", "commands", "settings.json"),
        required_content={"settings.json": ["hooks"]},
    ),
    PlatformType.CURSOR: PlatformContract(
        platform_type=PlatformType.CURSOR,
        required_paths=("settings.json",),
    ),
    PlatformType.CODEX: PlatformContract(
        platform_type=PlatformType.CODEX,
        required_paths=("config.yaml", "agents"),
        required_content={"config.yaml": ["platform"]},
    ),
    PlatformType.WINDSURF: PlatformContract(
        platform_type=PlatformType.WINDSURF,
        required_paths=(),
    ),
    PlatformType.AIDER: PlatformContract(
        platform_type=PlatformType.AIDER,
        required_paths=(),
    ),
    PlatformType.CONTINUE: PlatformContract(
        platform_type=PlatformType.CONTINUE,
        required_paths=(),
    ),
    PlatformType.CLINE: PlatformContract(
        platform_type=PlatformType.CLINE,
        required_paths=(),
    ),
    PlatformType.ZED_AI: PlatformContract(
        platform_type=PlatformType.ZED_AI,
        required_paths=(),
    ),
    PlatformType.GITHUB_COPILOT: PlatformContract(
        platform_type=PlatformType.GITHUB_COPILOT,
        required_paths=(),
    ),
    PlatformType.SUPERMAVEN: PlatformContract(
        platform_type=PlatformType.SUPERMAVEN,
        required_paths=(),
    ),
    PlatformType.CODY: PlatformContract(
        platform_type=PlatformType.CODY,
        required_paths=(),
    ),
    PlatformType.TABNINE: PlatformContract(
        platform_type=PlatformType.TABNINE,
        required_paths=(),
    ),
    PlatformType.AMAZON_Q: PlatformContract(
        platform_type=PlatformType.AMAZON_Q,
        required_paths=(),
    ),
    PlatformType.PIECES: PlatformContract(
        platform_type=PlatformType.PIECES,
        required_paths=(),
    ),
    PlatformType.CUSTOM: PlatformContract(
        platform_type=PlatformType.CUSTOM,
        required_paths=(),
    ),
}


def validate_platform(
    config: PlatformConfig, repo_root: Path
) -> list[ContractViolation]:
    """Validate a platform's generated config against its contract.

    Returns a list of violations (empty means the contract passes).
    """
    contract = PLATFORM_CONTRACTS.get(config.platform_type)
    if contract is None:
        return []

    violations: list[ContractViolation] = []
    config_path = repo_root / config.config_dir

    if not config_path.exists():
        violations.append(
            ContractViolation(
                platform=config.platform_type,
                path=config.config_dir,
                rule="config_dir_exists",
                detail=f"Config directory '{config.config_dir}' does not exist",
            )
        )
        return violations

    # Check required paths
    for required in contract.required_paths:
        target = config_path / required
        if not target.exists():
            violations.append(
                ContractViolation(
                    platform=config.platform_type,
                    path=required,
                    rule="required_path_exists",
                    detail=f"Required path '{required}' missing in "
                    f"'{config.config_dir}'",
                )
            )

    # Check required content
    for filename, required_strings in contract.required_content.items():
        filepath = config_path / filename
        if not filepath.exists():
            continue  # Already caught by required_paths check
        try:
            content = filepath.read_text(encoding="utf-8")
        except OSError:
            continue
        for expected in required_strings:
            if expected not in content:
                violations.append(
                    ContractViolation(
                        platform=config.platform_type,
                        path=filename,
                        rule="required_content",
                        detail=f"File '{filename}' missing required "
                        f"content: '{expected}'",
                    )
                )

    # Check forbidden content
    for filename, forbidden_strings in contract.forbidden_content.items():
        filepath = config_path / filename
        if not filepath.exists():
            continue
        try:
            content = filepath.read_text(encoding="utf-8")
        except OSError:
            continue
        for forbidden in forbidden_strings:
            if forbidden in content:
                violations.append(
                    ContractViolation(
                        platform=config.platform_type,
                        path=filename,
                        rule="forbidden_content",
                        detail=f"File '{filename}' contains forbidden "
                        f"content: '{forbidden}'",
                    )
                )

    return violations


def validate_all(
    repo_root: Path,
) -> dict[PlatformType, list[ContractViolation]]:
    """Validate all detected platforms in a repository.

    Returns a dict mapping each detected platform to its violations.
    """
    detected = detect_platforms(repo_root)
    results: dict[PlatformType, list[ContractViolation]] = {}
    for config in detected:
        results[config.platform_type] = validate_platform(config, repo_root)
    return results
