"""Context injection system for Reins."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "ContextAssemblyManifest",
    "ContextCompilerV2",
    "ContextRecompositionManager",
    "ContextSpecProjection",
    "ResolvedSpec",
    "SpecQuery",
    "SpecRegistrar",
    "SpecSection",
    "TokenAllocation",
    "TokenBudget",
]

_EXPORTS: dict[str, tuple[str, str]] = {
    "ContextAssemblyManifest": ("reins.context.compiler_v2", "ContextAssemblyManifest"),
    "ContextCompilerV2": ("reins.context.compiler_v2", "ContextCompilerV2"),
    "ContextRecompositionManager": (
        "reins.context.recomposition",
        "ContextRecompositionManager",
    ),
    "ContextSpecProjection": ("reins.context.spec_projection", "ContextSpecProjection"),
    "ResolvedSpec": ("reins.context.spec_projection", "ResolvedSpec"),
    "SpecQuery": ("reins.context.spec_projection", "SpecQuery"),
    "SpecRegistrar": ("reins.context.spec_registrar", "SpecRegistrar"),
    "SpecSection": ("reins.context.compiler_v2", "SpecSection"),
    "TokenAllocation": ("reins.context.token_budget", "TokenAllocation"),
    "TokenBudget": ("reins.context.token_budget", "TokenBudget"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attribute_name = _EXPORTS[name]
    module = import_module(module_name)
    return getattr(module, attribute_name)
