from __future__ import annotations

import math
from collections import defaultdict

from reins.information.types import (
    CompressionStrategy,
    ContextItem,
    ContextSelection,
    InformationMetric,
    InformationProfile,
    InformationStats,
)


class InformationEngine:
    """Information-theoretic context optimization using entropy and mutual information.

    Selects optimal context subsets that maximize information density while
    minimizing redundancy, using principles from information theory.
    No other harness does this — they all just count tokens.
    """

    def __init__(self, token_budget: int = 8000) -> None:
        self._items: dict[str, ContextItem] = {}
        self._selections: list[ContextSelection] = []
        self._token_budget = token_budget

    def add_item(self, content: str, tokens: int, relevance: float = 0.5,
                 source: str = "", metadata: dict | None = None) -> ContextItem:
        entropy = self._compute_content_entropy(content)
        item = ContextItem(
            content=content,
            tokens=tokens,
            relevance=relevance,
            entropy=entropy,
            source=source,
            metadata=metadata or {},
        )
        self._items[item.item_id] = item
        return item

    def get_item(self, item_id: str) -> ContextItem | None:
        return self._items.get(item_id)

    def compute_entropy(self, item_id: str) -> float:
        item = self._items.get(item_id)
        if not item:
            return 0.0
        return item.entropy

    def compute_mutual_information(self, id_a: str, id_b: str) -> float:
        a = self._items.get(id_a)
        b = self._items.get(id_b)
        if not a or not b:
            return 0.0
        overlap = self._content_overlap(a.content, b.content)
        return overlap * min(a.entropy, b.entropy)

    def compute_kl_divergence(self, id_p: str, id_q: str) -> float:
        p = self._items.get(id_p)
        q = self._items.get(id_q)
        if not p or not q:
            return 0.0
        p_dist = self._char_distribution(p.content)
        q_dist = self._char_distribution(q.content)
        kl = 0.0
        for char, p_val in p_dist.items():
            q_val = q_dist.get(char, 1e-10)
            if p_val > 0:
                kl += p_val * math.log(p_val / q_val)
        return max(kl, 0.0)

    def compute_redundancy(self, item_ids: list[str]) -> float:
        if len(item_ids) < 2:
            return 0.0
        total_mi = 0.0
        pairs = 0
        for i in range(len(item_ids)):
            for j in range(i + 1, len(item_ids)):
                total_mi += self.compute_mutual_information(item_ids[i], item_ids[j])
                pairs += 1
        return total_mi / pairs if pairs > 0 else 0.0

    def get_profile(self, item_ids: list[str] | None = None) -> InformationProfile:
        if item_ids is None:
            items = list(self._items.values())
        else:
            items = [self._items[iid] for iid in item_ids if iid in self._items]

        if not items:
            return InformationProfile()

        total_entropy = sum(i.entropy for i in items)
        avg_relevance = sum(i.relevance for i in items) / len(items)
        total_tokens = sum(i.tokens for i in items)

        ids = [i.item_id for i in items]
        redundancy = self.compute_redundancy(ids)

        density = total_entropy / total_tokens if total_tokens > 0 else 0.0
        effective = int(total_tokens * (1 - redundancy))

        return InformationProfile(
            total_entropy=total_entropy,
            avg_relevance=avg_relevance,
            redundancy_ratio=redundancy,
            information_density=density,
            effective_tokens=effective,
            total_tokens=total_tokens,
        )

    def select_context(self, strategy: CompressionStrategy = CompressionStrategy.MRMR,
                       budget: int | None = None) -> ContextSelection:
        budget = budget or self._token_budget
        items = list(self._items.values())

        if not items:
            selection = ContextSelection(strategy=strategy)
            self._selections.append(selection)
            return selection

        if strategy == CompressionStrategy.MAX_ENTROPY:
            selected = self._select_max_entropy(items, budget)
        elif strategy == CompressionStrategy.MIN_REDUNDANCY:
            selected = self._select_min_redundancy(items, budget)
        elif strategy == CompressionStrategy.MAX_RELEVANCE:
            selected = self._select_max_relevance(items, budget)
        elif strategy == CompressionStrategy.MRMR:
            selected = self._select_mrmr(items, budget)
        else:
            selected = self._select_mrmr(items, budget)

        total_tokens = sum(self._items[sid].tokens for sid in selected)
        total_possible_entropy = sum(i.entropy for i in items)
        selected_entropy = sum(self._items[sid].entropy for sid in selected)
        info_retained = selected_entropy / total_possible_entropy if total_possible_entropy > 0 else 1.0
        all_tokens = sum(i.tokens for i in items)
        compression = total_tokens / all_tokens if all_tokens > 0 else 1.0

        selection = ContextSelection(
            selected_ids=tuple(selected),
            strategy=strategy,
            total_tokens=total_tokens,
            information_retained=info_retained,
            compression_ratio=compression,
        )
        self._selections.append(selection)
        return selection

    def get_stats(self) -> InformationStats:
        by_strategy: dict[str, int] = defaultdict(int)
        for s in self._selections:
            by_strategy[s.strategy.value] += 1

        avg_compression = (
            sum(s.compression_ratio for s in self._selections) / len(self._selections)
            if self._selections else 1.0
        )
        avg_retained = (
            sum(s.information_retained for s in self._selections) / len(self._selections)
            if self._selections else 1.0
        )

        return InformationStats(
            total_items=len(self._items),
            total_selections=len(self._selections),
            avg_compression_ratio=avg_compression,
            avg_information_retained=avg_retained,
            by_strategy=dict(by_strategy),
        )

    def _select_max_entropy(self, items: list[ContextItem], budget: int) -> list[str]:
        sorted_items = sorted(items, key=lambda i: -i.entropy)
        selected = []
        tokens_used = 0
        for item in sorted_items:
            if tokens_used + item.tokens <= budget:
                selected.append(item.item_id)
                tokens_used += item.tokens
        return selected

    def _select_max_relevance(self, items: list[ContextItem], budget: int) -> list[str]:
        sorted_items = sorted(items, key=lambda i: -i.relevance)
        selected = []
        tokens_used = 0
        for item in sorted_items:
            if tokens_used + item.tokens <= budget:
                selected.append(item.item_id)
                tokens_used += item.tokens
        return selected

    def _select_min_redundancy(self, items: list[ContextItem], budget: int) -> list[str]:
        sorted_items = sorted(items, key=lambda i: -i.entropy)
        selected = []
        tokens_used = 0
        for item in sorted_items:
            if tokens_used + item.tokens > budget:
                continue
            redundant = False
            for sid in selected:
                mi = self.compute_mutual_information(item.item_id, sid)
                if mi > 0.5 * item.entropy:
                    redundant = True
                    break
            if not redundant:
                selected.append(item.item_id)
                tokens_used += item.tokens
        return selected

    def _select_mrmr(self, items: list[ContextItem], budget: int) -> list[str]:
        """Maximum Relevance Minimum Redundancy selection."""
        selected: list[str] = []
        tokens_used = 0
        remaining = list(items)

        while remaining:
            best_score = float("-inf")
            best_item = None

            for item in remaining:
                if tokens_used + item.tokens > budget:
                    continue
                relevance_score = item.relevance * item.entropy
                redundancy_score = 0.0
                if selected:
                    for sid in selected:
                        redundancy_score += self.compute_mutual_information(item.item_id, sid)
                    redundancy_score /= len(selected)
                score = relevance_score - redundancy_score
                if score > best_score:
                    best_score = score
                    best_item = item

            if best_item is None:
                break
            selected.append(best_item.item_id)
            tokens_used += best_item.tokens
            remaining.remove(best_item)

        return selected

    def _compute_content_entropy(self, content: str) -> float:
        if not content:
            return 0.0
        dist = self._char_distribution(content)
        entropy = 0.0
        for p in dist.values():
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy

    def _char_distribution(self, content: str) -> dict[str, float]:
        if not content:
            return {}
        counts: dict[str, int] = defaultdict(int)
        for c in content:
            counts[c] += 1
        total = len(content)
        return {c: count / total for c, count in counts.items()}

    def _content_overlap(self, a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        set_a = set(a.split())
        set_b = set(b.split())
        if not set_a or not set_b:
            return 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union) if union else 0.0
