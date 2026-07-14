import itertools

import pytest

from optimiser.api import build_groups, semester_timetable
from optimiser.model import Choice, ChoiceGroup, Session
from optimiser.scoring import score_assignment
from optimiser.search import EnumeratedSpace, find_irreconcilable, prepare_groups, rank_arrangements, search


@pytest.fixture
def groups(alpha_json, beta_json, config):
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1)) + build_groups(
        "BETA", semester_timetable(beta_json, 1)
    )
    return prepare_groups(gs, config)


def test_prepare_groups_applies_fixed(groups):
    beta_lec = next(g for g in groups if g.key == ("BETA", "Lecture"))
    assert [c.class_no for c in beta_lec.choices] == ["1"]  # config.fixed pins it


def test_prepare_groups_warns_for_free_nonballoted_group(capsys, beta_json, config):
    config.fixed = {}
    gs = build_groups("BETA", semester_timetable(beta_json, 1))
    prepared = prepare_groups(gs, config)
    beta_lec = next(g for g in prepared if g.key == ("BETA", "Lecture"))
    assert [c.class_no for c in beta_lec.choices] == ["1", "2"]
    out = capsys.readouterr().out
    assert "warning:" in out
    assert "BETA" in out


def test_prepare_groups_bad_fixed(alpha_json, config):
    config.fixed = {"ALPHA": {"LEC": "99"}}
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    with pytest.raises(SystemExit):
        prepare_groups(gs, config)


def test_search_footprint_dedup_and_clash(groups, config):
    result = search(groups, config)
    # ALPHA TUT footprints: {Mon}, {Tue} (02+03 collapse). BETA LAB: L1, L2.
    # L1 clashes ALPHA TUT 01 -> clash-free footprint combos = 2*2 - 1 = 3
    assert result.evaluated == 3
    tut_members = result.members[("ALPHA", "Tutorial")]
    assert sorted(len(v) for v in tut_members.values()) == [1, 2]


def test_search_top_sorted_and_assignment_shape(groups, config):
    result = search(groups, config)
    totals = [t for t, _, _ in result.top]
    assert totals == sorted(totals, reverse=True)
    _, _, assignment = result.top[0]
    assert set(assignment) == {
        ("ALPHA", "Lecture"),
        ("ALPHA", "Tutorial"),
        ("BETA", "Lecture"),
        ("BETA", "Laboratory"),
    }


def test_best_by_footprint_matches_bruteforce(groups, config):
    result = search(groups, config)
    best = {}
    for combo in itertools.product(*(g.choices for g in groups)):
        if any(a.clashes(b) for a, b in itertools.combinations(combo, 2)):
            continue
        total, _ = score_assignment(list(combo), config)
        for c in combo:
            key = (c.module, c.lesson_type, c.footprint)
            best[key] = max(best.get(key, float("-inf")), total)
    assert result.best_by_footprint == pytest.approx(best)


def test_find_irreconcilable(config):
    from tests.conftest import lesson
    from optimiser.api import build_groups as bg

    a = bg("A", [lesson("1", "Tutorial", "Monday", "1000", "1200")])
    b = bg("B", [lesson("1", "Tutorial", "Monday", "1100", "1300")])
    pair = find_irreconcilable(a + b)
    assert pair is not None
    assert {pair[0].module, pair[1].module} == {"A", "B"}


from optimiser.search import EnumeratedSpace, enumerate_clashfree, rank


def test_search_equals_enumerate_then_rank(groups, config):
    space = enumerate_clashfree(groups)
    assert isinstance(space, EnumeratedSpace)
    combined = search(groups, config)
    split = rank(space, config)
    assert [t for t, _, _ in split.top] == [t for t, _, _ in combined.top]
    assert split.best_by_footprint == combined.best_by_footprint
    assert split.evaluated == combined.evaluated


def test_enumerate_is_config_independent(groups, config):
    # Enumerated set does not depend on config; only ranking does.
    space = enumerate_clashfree(groups)
    assert space.evaluated_count() == len(space.combos)
    # Re-ranking the same space with a different weight reorders results.
    import copy

    cfg_a = copy.deepcopy(config)
    cfg_a.preferences.weights["free_days"] = 0
    cfg_b = copy.deepcopy(config)
    cfg_b.preferences.weights["free_days"] = 100
    top_a = [t for t, _, _ in rank(space, cfg_a).top]
    top_b = [t for t, _, _ in rank(space, cfg_b).top]
    assert top_a != top_b  # weighting change changes ordering


ALL_WEEKS = frozenset(range(1, 14))


def _space(*combos):
    return EnumeratedSpace(combos=tuple(combos), members={})


def test_rank_arrangements_collapses_week_twins(config):
    # ALPHA Tutorial twin at Mon 1400-1500: 01 odd weeks, 02 even weeks -> one
    # arrangement offering both class numbers with week labels.
    odd = frozenset({1, 3, 5})
    even = frozenset({2, 4, 6})
    lec = Choice("ALPHA", "Lecture", "1", (Session("Monday", 600, 720, ALL_WEEKS, "COM1"),))
    tut_odd = Choice("ALPHA", "Tutorial", "01", (Session("Monday", 840, 900, odd, "COM1"),))
    tut_even = Choice("ALPHA", "Tutorial", "02", (Session("Monday", 840, 900, even, "COM1"),))
    arrs = rank_arrangements(_space((lec, tut_odd), (lec, tut_even)), config)
    assert len(arrs) == 1
    a = arrs[0]
    assert a.variant_count == 2
    tut_bid = next(b for b in a.bids if b.lesson_type == "Tutorial")
    assert dict(tut_bid.options) == {"01": "odd wks", "02": "even wks"}
    # Lecture is not a balloted type -> not in the bids block
    assert all(b.lesson_type != "Lecture" for b in a.bids)


def test_rank_arrangements_keeps_entangled_variants_separate(config):
    # ALPHA Tutorial and BETA Laboratory BOTH at Mon 1400-1500 with odd/even
    # splits: only the opposite-week pairings are clash-free, so picking one twin
    # forces the other -> must NOT collapse into free per-slot bids.
    odd = frozenset({1, 3, 5})
    even = frozenset({2, 4, 6})
    a_odd = Choice("ALPHA", "Tutorial", "01", (Session("Monday", 840, 900, odd, "COM1"),))
    a_even = Choice("ALPHA", "Tutorial", "02", (Session("Monday", 840, 900, even, "COM1"),))
    b_odd = Choice("BETA", "Laboratory", "L1", (Session("Monday", 840, 900, odd, "COM2"),))
    b_even = Choice("BETA", "Laboratory", "L2", (Session("Monday", 840, 900, even, "COM2"),))
    arrs = rank_arrangements(_space((a_odd, b_even), (a_even, b_odd)), config)
    assert len(arrs) == 2  # entangled -> not collapsed
    assert all(a.variant_count == 1 for a in arrs)


def test_rank_arrangements_ranks_by_best_and_limits(config):
    # Two genuinely different arrangements (different tutorial days); the higher
    # scorer comes first; limit truncates.
    lec = Choice("ALPHA", "Lecture", "1", (Session("Monday", 600, 720, ALL_WEEKS, "COM1"),))
    tut_mon = Choice("ALPHA", "Tutorial", "01", (Session("Monday", 780, 840, ALL_WEEKS, "COM1"),))
    tut_fri = Choice("ALPHA", "Tutorial", "05", (Session("Friday", 780, 840, ALL_WEEKS, "COM1"),))
    arrs = rank_arrangements(_space((lec, tut_mon), (lec, tut_fri)), config)
    assert len(arrs) == 2
    assert arrs[0].score >= arrs[1].score          # best-first
    assert len(rank_arrangements(_space((lec, tut_mon), (lec, tut_fri)), config, limit=1)) == 1
