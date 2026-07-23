import pytest

from kairos.provenance import arrangement_provenance
from kairos.search import (
    build_arrangement_structure,
    enumerate_clashfree,
    rank_arrangements,
    score_combos,
)


@pytest.fixture
def prov(groups, config):
    space = enumerate_clashfree(groups)
    return arrangement_provenance(space, config), space


def test_total_matches_arrangement_count(prov, config):
    provenance, space = prov
    assert provenance.total == len(rank_arrangements(space, config))


def test_scores_are_descending(prov):
    provenance, _ = prov
    assert list(provenance.scores) == sorted(provenance.scores, reverse=True)


def test_distinct_scores_are_deduped_and_descending(prov):
    provenance, _ = prov
    assert list(provenance.distinct) == sorted(set(provenance.scores), reverse=True)
    assert provenance.tiers == len(set(provenance.scores))


def test_tier_of_observed_score_is_its_rank(prov):
    provenance, _ = prov
    for tier, score in enumerate(provenance.distinct, 1):
        assert provenance.tier_of(score) == tier


def test_tier_of_interpolated_score_takes_the_worse_tier(prov):
    # A median falling between two observed scores must never claim a better
    # tier than any arrangement actually achieved.
    provenance, _ = prov
    if len(provenance.distinct) < 2:
        pytest.skip("needs at least two distinct scores")
    high, low = provenance.distinct[0], provenance.distinct[1]
    between = (high + low) / 2
    assert provenance.tier_of(between) == 2


def test_cluster_stats_aggregates_over_all_members(prov):
    # ALPHA tutorials 02 and 03 are venue twins sharing a footprint, so the
    # union of their arrangements is the cluster's support.
    provenance, _ = prov
    keys = {("ALPHA", "Tutorial", "02"), ("ALPHA", "Tutorial", "03")}
    stats = provenance.cluster_stats(keys)
    union = set(provenance.by_class[("ALPHA", "Tutorial", "02")]) | set(
        provenance.by_class[("ALPHA", "Tutorial", "03")]
    )
    assert stats.support == len(union)
    assert stats.ceiling == max(provenance.scores[i] for i in union)


def test_cluster_stats_returns_none_for_unknown_class(prov):
    provenance, _ = prov
    assert provenance.cluster_stats({("ALPHA", "Tutorial", "99")}) is None


def test_ceiling_is_never_worse_than_median(prov):
    provenance, _ = prov
    for key in provenance.by_class:
        stats = provenance.cluster_stats({key})
        assert stats.ceiling >= stats.median
        assert stats.ceiling_tier <= stats.median_tier


def test_by_arrangement_and_by_class_agree(prov):
    provenance, _ = prov
    for index, keys in enumerate(provenance.by_arrangement):
        for key in keys:
            assert index in provenance.by_class[key]


def test_single_distinct_score_yields_one_tier(groups, config):
    # Every weight zero -> every arrangement scores the same -> exactly one tier.
    for name in list(config.preferences.weights):
        config.preferences.weights[name] = 0
    space = enumerate_clashfree(groups)
    provenance = arrangement_provenance(space, config)
    assert provenance.tiers == 1
    assert all(provenance.tier_of(score) == 1 for score in provenance.scores)


def test_provenance_is_independent_of_max_arrangements(groups, config):
    # AppState caps its arrangement list; provenance must not inherit that cap,
    # or the TUI would report "of 3" where the CLI reports the true total.
    space = enumerate_clashfree(groups)
    config.max_arrangements = 3
    capped = arrangement_provenance(space, config)
    config.max_arrangements = 500
    uncapped = arrangement_provenance(space, config)
    assert capped.total == uncapped.total
    assert capped.scores == uncapped.scores
    assert capped.by_class == uncapped.by_class


def test_indices_align_with_rank_arrangements(groups, config):
    # TUI highlighting indexes provenance.by_arrangement with a selection made
    # against rank_arrangements(limit=...). They agree only because nlargest is
    # equivalent to a stable descending sort. Pin it.
    space = enumerate_clashfree(groups)
    scored = score_combos(space, config)
    structure = build_arrangement_structure(space)
    provenance = arrangement_provenance(space, config, scored=scored, structure=structure)
    full = rank_arrangements(space, config, scored=scored, structure=structure)
    assert [a.score for a in full] == list(provenance.scores)
    for limit in (1, 2, len(full)):
        capped = rank_arrangements(
            space, config, limit=limit, scored=scored, structure=structure
        )
        assert [a.score for a in capped] == [a.score for a in full[:limit]]
        assert [a.assignment for a in capped] == [a.assignment for a in full[:limit]]
