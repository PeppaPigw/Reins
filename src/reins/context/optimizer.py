"""Context optimization helpers for Phase 6A compilation.

The optimizer works on compiled context sections and is intentionally policy-free:
it deduplicates repeated content, applies source-type priority ordering, and trims
the result to a target token budget.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from reins.context.compiler import ContextSection


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _truncate_content(text: str, max_tokens: int) -> tuple[str, int]:
    if max_tokens <= 0:
        return "", 0
    if _estimate_tokens(text) <= max_tokens:
        return text, _estimate_tokens(text)

    suffix = "\n...[truncated]"
    max_chars = max(1, (max_tokens * 4) - len(suffix))
    truncated = text[:max_chars].rstrip() + suffix
    return truncated, min(max_tokens, _estimate_tokens(truncated))


@dataclass(frozen=True)
class OptimizationResult:
    """Result of optimizing compiled context sections."""

    sections: list["ContextSection"]
    total_tokens: int
    max_tokens: int
    dropped: list[str]
    deduplicated: list[str]


class ContextOptimizer:
    """Deduplicate and budget compiled context sections."""

    def optimize(
        self,
        sections: Sequence["ContextSection"],
        max_tokens: int,
        priority: list[str] | None = None,
    ) -> OptimizationResult:
        priority_order = {name: index for index, name in enumerate(priority or [])}
        deduplicated_sections: list["ContextSection"] = []
        deduplicated_ids: list[str] = []
        seen_hashes: set[str] = set()

        for section in sections:
            fingerprint = sha256(section.content.encode("utf-8")).hexdigest()
            if fingerprint in seen_hashes:
                deduplicated_ids.append(section.identifier)
                continue
            seen_hashes.add(fingerprint)
            deduplicated_sections.append(section)

        sorted_sections = sorted(
            enumerate(deduplicated_sections),
            key=lambda item: (
                priority_order.get(item[1].source_type, len(priority_order)),
                -item[1].priority,
                item[0],
            ),
        )

        optimized: list["ContextSection"] = []
        dropped: list[str] = []
        total_tokens = 0

        for _, section in sorted_sections:
            remaining = max_tokens - total_tokens
            if remaining <= 0:
                dropped.append(section.identifier)
                continue

            if section.token_count <= remaining:
                optimized.append(section)
                total_tokens += section.token_count
                continue

            truncated_content, truncated_tokens = _truncate_content(
                section.content, remaining
            )
            if truncated_tokens <= 0 or not truncated_content:
                dropped.append(section.identifier)
                continue

            optimized.append(
                replace(
                    section,
                    content=truncated_content,
                    token_count=truncated_tokens,
                    truncated=True,
                )
            )
            total_tokens += truncated_tokens

        return OptimizationResult(
            sections=optimized,
            total_tokens=total_tokens,
            max_tokens=max_tokens,
            dropped=dropped,
            deduplicated=deduplicated_ids,
        )
