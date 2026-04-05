from __future__ import annotations

from reins.kernel.types import PathKind

FAST_CAPABILITIES = frozenset(
    {
        "fs.read",
        "search.read",
        "git.status",
        "mcp.resource.read",
        "skill.catalog.lookup",
        "a2a.agent.discover",
    }
)

DELIBERATIVE_CAPABILITIES = frozenset(
    {
        "fs.write.workspace",
        "git.commit",
        "git.push",
        "browser.submit.external",
        "deploy.staging",
        "deploy.prod",
        "exec.shell.network",
        "db.write",
    }
)


def route(
    requested_capabilities: list[str],
    ambiguity_score: float = 0.0,
    retry_count: int = 0,
    pending_approval: bool = False,
) -> PathKind:
    """Rules-first router. Returns PathKind.fast or PathKind.deliberative."""
    capabilities = set(requested_capabilities)
    if pending_approval or ambiguity_score >= 0.35:
        return PathKind.deliberative
    if capabilities & DELIBERATIVE_CAPABILITIES:
        return PathKind.deliberative
    if not capabilities:
        return PathKind.fast if retry_count == 0 else PathKind.deliberative
    if not capabilities.issubset(FAST_CAPABILITIES):
        return PathKind.deliberative
    return PathKind.fast if retry_count == 0 else PathKind.deliberative
