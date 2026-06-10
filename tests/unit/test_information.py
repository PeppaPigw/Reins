"""Tests for information-theoretic context optimization."""

from __future__ import annotations

import pytest

from reins.information import (
    CompressionStrategy,
    ContextItem,
    ContextSelection,
    InformationEngine,
    InformationMetric,
    InformationProfile,
    InformationStats,
)


@pytest.fixture
def engine() -> InformationEngine:
    return InformationEngine(token_budget=500)


@pytest.fixture
def items(engine) -> list[ContextItem]:
    i1 = engine.add_item("the quick brown fox jumps over the lazy dog", tokens=100, relevance=0.9)
    i2 = engine.add_item("a completely different topic about quantum physics", tokens=100, relevance=0.7)
    i3 = engine.add_item("the quick brown fox runs fast in the park", tokens=100, relevance=0.5)
    i4 = engine.add_item("machine learning algorithms optimize parameters", tokens=150, relevance=0.8)
    i5 = engine.add_item("deep neural networks learn representations", tokens=150, relevance=0.6)
    return [i1, i2, i3, i4, i5]


def test_add_item(engine):
    item = engine.add_item("hello world", tokens=10)
    assert engine.get_item(item.item_id) is not None


def test_get_item_not_found(engine):
    assert engine.get_item("nonexistent") is None


def test_entropy_computed(engine):
    item = engine.add_item("aaabbbccc", tokens=10)
    assert item.entropy > 0


def test_entropy_uniform_higher(engine):
    uniform = engine.add_item("abcdefghij", tokens=10)
    skewed = engine.add_item("aaaaaaaaab", tokens=10)
    assert uniform.entropy > skewed.entropy


def test_entropy_empty(engine):
    item = engine.add_item("", tokens=0)
    assert item.entropy == 0.0


def test_mutual_information_similar(engine, items):
    mi = engine.compute_mutual_information(items[0].item_id, items[2].item_id)
    assert mi > 0


def test_mutual_information_different(engine, items):
    mi_similar = engine.compute_mutual_information(items[0].item_id, items[2].item_id)
    mi_different = engine.compute_mutual_information(items[0].item_id, items[1].item_id)
    assert mi_similar > mi_different


def test_mutual_information_nonexistent(engine):
    assert engine.compute_mutual_information("a", "b") == 0.0


def test_kl_divergence_same(engine):
    a = engine.add_item("hello world", tokens=10)
    assert engine.compute_kl_divergence(a.item_id, a.item_id) == pytest.approx(0.0, abs=0.01)


def test_kl_divergence_different(engine, items):
    kl = engine.compute_kl_divergence(items[0].item_id, items[1].item_id)
    assert kl > 0


def test_redundancy_no_overlap(engine, items):
    redundancy = engine.compute_redundancy([items[0].item_id, items[1].item_id])
    assert redundancy >= 0


def test_redundancy_high_overlap(engine, items):
    r_similar = engine.compute_redundancy([items[0].item_id, items[2].item_id])
    r_different = engine.compute_redundancy([items[0].item_id, items[1].item_id])
    assert r_similar >= r_different


def test_redundancy_single_item(engine, items):
    assert engine.compute_redundancy([items[0].item_id]) == 0.0


def test_profile(engine, items):
    profile = engine.get_profile()
    assert profile.total_entropy > 0
    assert profile.total_tokens == 600
    assert profile.avg_relevance > 0


def test_profile_subset(engine, items):
    profile = engine.get_profile([items[0].item_id, items[1].item_id])
    assert profile.total_tokens == 200


def test_profile_empty(engine):
    profile = engine.get_profile([])
    assert profile.total_entropy == 0.0


def test_select_max_entropy(engine, items):
    selection = engine.select_context(CompressionStrategy.MAX_ENTROPY, budget=300)
    assert len(selection.selected_ids) > 0
    assert selection.total_tokens <= 300


def test_select_max_relevance(engine, items):
    selection = engine.select_context(CompressionStrategy.MAX_RELEVANCE, budget=300)
    assert len(selection.selected_ids) > 0
    selected_items = [engine.get_item(sid) for sid in selection.selected_ids]
    assert selected_items[0].relevance >= 0.8


def test_select_min_redundancy(engine, items):
    selection = engine.select_context(CompressionStrategy.MIN_REDUNDANCY, budget=300)
    assert len(selection.selected_ids) > 0


def test_select_mrmr(engine, items):
    selection = engine.select_context(CompressionStrategy.MRMR, budget=400)
    assert len(selection.selected_ids) > 0
    assert selection.information_retained > 0


def test_select_respects_budget(engine, items):
    selection = engine.select_context(budget=200)
    assert selection.total_tokens <= 200


def test_compression_ratio(engine, items):
    selection = engine.select_context(budget=300)
    assert 0 < selection.compression_ratio <= 1.0


def test_information_retained(engine, items):
    selection = engine.select_context(budget=500)
    assert selection.information_retained > 0


def test_select_empty(engine):
    selection = engine.select_context()
    assert len(selection.selected_ids) == 0


def test_mrmr_reduces_redundancy(engine):
    engine.add_item("the cat sat on the mat", tokens=50, relevance=0.9)
    engine.add_item("the cat sat on the hat", tokens=50, relevance=0.9)
    engine.add_item("quantum physics is fascinating", tokens=50, relevance=0.8)
    selection = engine.select_context(CompressionStrategy.MRMR, budget=100)
    assert len(selection.selected_ids) == 2


def test_stats_empty():
    eng = InformationEngine()
    stats = eng.get_stats()
    assert stats.total_items == 0
    assert stats.total_selections == 0


def test_stats_with_data(engine, items):
    engine.select_context(CompressionStrategy.MRMR, budget=300)
    engine.select_context(CompressionStrategy.MAX_ENTROPY, budget=200)
    stats = engine.get_stats()
    assert stats.total_items == 5
    assert stats.total_selections == 2
    assert CompressionStrategy.MRMR.value in stats.by_strategy
