"""Token budget system for context compilation.

Manages token allocation across different spec types to ensure
the compiled context fits within the model's context window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TokenBudget:
    """Token budget allocation for context compilation.

    The budget is divided across three spec types:
    - standing_law: Always-on conventions (highest priority)
    - task_contract: Task-specific requirements (high priority)
    - spec_shards: On-demand guidance (lower priority)
    """

    total: int
    """Total token budget for all context"""

    standing_law: int
    """Tokens allocated for standing_law specs"""

    task_contract: int
    """Tokens allocated for task_contract specs"""

    spec_shards: int
    """Tokens allocated for spec_shard specs"""

    reserve: int
    """Reserve tokens for overflow/future use"""

    @classmethod
    def default(cls, total: int = 10_000) -> TokenBudget:
        """Create a default budget with standard allocation ratios.

        Default allocation:
        - 40% standing_law (always-on conventions)
        - 20% task_contract (task requirements)
        - 30% spec_shards (on-demand guidance)
        - 10% reserve (overflow buffer)

        Args:
            total: Total token budget

        Returns:
            TokenBudget with default allocation
        """
        return cls(
            total=total,
            standing_law=int(total * 0.40),
            task_contract=int(total * 0.20),
            spec_shards=int(total * 0.30),
            reserve=int(total * 0.10),
        )

    @classmethod
    def custom(
        cls,
        total: int,
        standing_law_ratio: float = 0.40,
        task_contract_ratio: float = 0.20,
        spec_shards_ratio: float = 0.30,
    ) -> TokenBudget:
        """Create a custom budget with specified allocation ratios.

        Args:
            total: Total token budget
            standing_law_ratio: Ratio for standing_law (0.0-1.0)
            task_contract_ratio: Ratio for task_contract (0.0-1.0)
            spec_shards_ratio: Ratio for spec_shards (0.0-1.0)

        Returns:
            TokenBudget with custom allocation

        Raises:
            ValueError: If ratios don't sum to <= 1.0
        """
        total_ratio = standing_law_ratio + task_contract_ratio + spec_shards_ratio
        if total_ratio > 1.0:
            raise ValueError(
                f"Ratios sum to {total_ratio}, must be <= 1.0 to leave room for reserve"
            )

        reserve_ratio = 1.0 - total_ratio

        return cls(
            total=total,
            standing_law=int(total * standing_law_ratio),
            task_contract=int(total * task_contract_ratio),
            spec_shards=int(total * spec_shards_ratio),
            reserve=int(total * reserve_ratio),
        )

    def get_allocation(
        self, spec_type: Literal["standing_law", "task_contract", "spec_shard"]
    ) -> int:
        """Get token allocation for a specific spec type.

        Args:
            spec_type: Type of spec

        Returns:
            Token allocation for that type
        """
        if spec_type == "standing_law":
            return self.standing_law
        elif spec_type == "task_contract":
            return self.task_contract
        elif spec_type == "spec_shard":
            return self.spec_shards
        else:
            return 0


def estimate_tokens(text: str) -> int:
    """Estimate token count using 4-chars-per-token heuristic.

    This is a rough estimate but good enough for budget allocation.
    More accurate counting (using tiktoken) can be added in v2.

    Args:
        text: Text to estimate

    Returns:
        Estimated token count
    """
    return max(1, len(text) // 4)


@dataclass
class TokenAllocation:
    """Result of token allocation for a set of specs.

    Tracks which specs were included, which were truncated,
    and which were dropped due to budget constraints.
    """

    included: list[tuple[str, int]]
    """List of (spec_id, token_count) for included specs"""

    truncated: list[tuple[str, int, int]]
    """List of (spec_id, original_tokens, truncated_tokens) for truncated specs"""

    dropped: list[tuple[str, int]]
    """List of (spec_id, token_count) for dropped specs"""

    total_tokens: int
    """Total tokens used after allocation"""

    budget: int
    """Budget that was allocated"""

    @property
    def utilization(self) -> float:
        """Calculate budget utilization as a ratio (0.0-1.0)."""
        if self.budget == 0:
            return 0.0
        return min(1.0, self.total_tokens / self.budget)


def allocate_tokens(
    specs: list[tuple[str, str, int]],
    budget: int,
    allow_truncation: bool = False,
) -> TokenAllocation:
    """Allocate tokens to specs within a budget.

    Specs are processed in order (caller should sort by precedence first).
    If a spec doesn't fit:
    - If allow_truncation=True, truncate it to fit
    - If allow_truncation=False, drop it

    Args:
        specs: List of (spec_id, content, token_count) tuples
        budget: Token budget to allocate
        allow_truncation: Whether to truncate specs that don't fit

    Returns:
        TokenAllocation with results
    """
    included: list[tuple[str, int]] = []
    truncated: list[tuple[str, int, int]] = []
    dropped: list[tuple[str, int]] = []
    total_tokens = 0

    for spec_id, content, token_count in specs:
        remaining = budget - total_tokens

        if token_count <= remaining:
            # Fits completely
            included.append((spec_id, token_count))
            total_tokens += token_count
        elif allow_truncation and remaining > 0:
            # Truncate to fit
            truncated_tokens = remaining
            truncated.append((spec_id, token_count, truncated_tokens))
            total_tokens += truncated_tokens
        else:
            # Drop
            dropped.append((spec_id, token_count))

    return TokenAllocation(
        included=included,
        truncated=truncated,
        dropped=dropped,
        total_tokens=total_tokens,
        budget=budget,
    )
