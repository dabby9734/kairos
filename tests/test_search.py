import itertools

import pytest

from kairos.api import build_groups, semester_timetable
from kairos.model import Choice, ChoiceGroup, Session
from kairos.scoring import score_assignment
from kairos.search import EnumeratedSpace, find_irreconcilable, prepare_groups, rank_arrangements, search


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
    # `locked` is now the key both writers produce, so the advice must name it too
    assert "no fixed/locked choice" in out


def test_prepare_groups_bad_locked_names_locked(alpha_json, config):
    config.fixed = {}
    config.locked = {"ALPHA": {"TUT": "99"}}
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    with pytest.raises(SystemExit, match="config 'locked'"):
        prepare_groups(gs, config)


def test_prepare_groups_bad_locked_names_fixed_when_migrated(alpha_json, config):
    """A migrated pin must blame 'fixed' — the key the on-disk config still has.

    migrate_fixed_to_locked rewrites in memory only; the user's file keeps saying
    `fixed` until they save, so naming 'locked' sends them hunting for a key that
    is not there (real case: the class vanished between semesters)."""
    config.fixed = {}
    config.locked = {"ALPHA": {"TUT": "99"}}
    config.migrated_from_fixed = {("ALPHA", "TUT")}
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    with pytest.raises(SystemExit, match="config 'fixed', migrated to 'locked'"):
        prepare_groups(gs, config)


def test_prepare_groups_bad_fixed(alpha_json, config):
    config.fixed = {"ALPHA": {"LEC": "99"}}
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    with pytest.raises(SystemExit):
        prepare_groups(gs, config)


def test_prepare_groups_locks_to_slot_twins(alpha_json, config):
    config.fixed = {}
    config.locked = {"ALPHA": {"TUT": "02"}}
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    prepared = prepare_groups(gs, config)
    tut = next(g for g in prepared if g.key == ("ALPHA", "Tutorial"))
    # 02 is the Tue 0900 slot; its venue-twin 03 stays, Mon 01 is dropped
    assert sorted(c.class_no for c in tut.choices) == ["02", "03"]


def test_prepare_groups_bad_locked(alpha_json, config):
    config.fixed = {}
    config.locked = {"ALPHA": {"TUT": "99"}}
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    with pytest.raises(SystemExit):
        prepare_groups(gs, config)


def test_prepare_groups_fixed_beats_locked(beta_json, config):
    config.fixed = {"BETA": {"LEC": "1"}}
    config.locked = {"BETA": {"LEC": "2"}}
    gs = build_groups("BETA", semester_timetable(beta_json, 1))
    prepared = prepare_groups(gs, config)
    lec = next(g for g in prepared if g.key == ("BETA", "Lecture"))
    assert [c.class_no for c in lec.choices] == ["1"]  # fixed wins


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
    from kairos.api import build_groups as bg

    a = bg("A", [lesson("1", "Tutorial", "Monday", "1000", "1200")])
    b = bg("B", [lesson("1", "Tutorial", "Monday", "1100", "1300")])
    pair = find_irreconcilable(a + b)
    assert pair is not None
    assert {pair[0].module, pair[1].module} == {"A", "B"}


from kairos.search import EnumeratedSpace, enumerate_clashfree, rank


def test_search_equals_enumerate_then_rank(groups, config):
    space = enumerate_clashfree(groups)
    assert isinstance(space, EnumeratedSpace)
    combined = search(groups, config)
    split = rank(space, config)
    assert [t for t, _, _ in split.top] == [t for t, _, _ in combined.top]
    assert split.best_by_footprint == combined.best_by_footprint
    assert split.evaluated == combined.evaluated


def test_rank_scored_param_is_behavior_preserving(groups, config):
    # rank must yield identical top/best_by_footprint whether or not a pre-scored
    # list is supplied (Fix D / M5: score every combo only once per retune).
    from kairos.search import score_combos
    space = enumerate_clashfree(groups)
    a = rank(space, config)
    b = rank(space, config, scored=score_combos(space, config))
    assert [t for t, _, _ in a.top] == [t for t, _, _ in b.top]
    assert a.best_by_footprint == b.best_by_footprint
    assert a.evaluated == b.evaluated


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
    # Derive a members map mirroring enumerate_clashfree: (module, lesson_type) ->
    # {footprint: sorted[Choice]}. Combos carry reps; this lets rank_arrangements
    # expand footprints to member class numbers (venue-twins) in tests.
    members: dict = {}
    for combo in combos:
        for c in combo:
            bucket = members.setdefault((c.module, c.lesson_type), {}).setdefault(c.footprint, [])
            if c not in bucket:
                bucket.append(c)
    for grp in members.values():
        for fp in grp:
            grp[fp] = sorted(grp[fp], key=lambda c: c.class_no)
    return EnumeratedSpace(combos=tuple(combos), members=members)


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


def test_rank_arrangements_lists_venue_twins(config):
    # Two class numbers at the SAME day/time/weeks but different venue share a
    # footprint, so only one rep reaches combos. The SlotBid must still list BOTH
    # class numbers (I1 / Fix B), while the Cartesian guard stays over footprints.
    lec = Choice("ALPHA", "Lecture", "1", (Session("Monday", 600, 720, ALL_WEEKS, "COM1"),))
    t_a = Choice("ALPHA", "Tutorial", "01", (Session("Tuesday", 540, 600, ALL_WEEKS, "COM1"),))
    t_b = Choice("ALPHA", "Tutorial", "02", (Session("Tuesday", 540, 600, ALL_WEEKS, "COM2"),))
    assert t_a.footprint == t_b.footprint  # venue not in footprint
    space = EnumeratedSpace(
        combos=((lec, t_a),),  # only the rep t_a is in combos
        members={
            ("ALPHA", "Lecture"): {lec.footprint: [lec]},
            ("ALPHA", "Tutorial"): {t_a.footprint: [t_a, t_b]},
        },
    )
    arrs = rank_arrangements(space, config)
    assert len(arrs) == 1
    tut_bid = next(b for b in arrs[0].bids if b.lesson_type == "Tutorial")
    assert [n for n, _ in tut_bid.options] == ["01", "02"]


def test_rank_arrangements_scored_param_is_behavior_preserving(config):
    # Passing a pre-scored list must produce identical arrangements (Fix D / M5).
    from kairos.search import score_combos
    odd = frozenset({1, 3, 5})
    even = frozenset({2, 4, 6})
    lec = Choice("ALPHA", "Lecture", "1", (Session("Monday", 600, 720, ALL_WEEKS, "COM1"),))
    tut_odd = Choice("ALPHA", "Tutorial", "01", (Session("Monday", 840, 900, odd, "COM1"),))
    tut_even = Choice("ALPHA", "Tutorial", "02", (Session("Monday", 840, 900, even, "COM1"),))
    space = _space((lec, tut_odd), (lec, tut_even))
    a = rank_arrangements(space, config)
    b = rank_arrangements(space, config, scored=score_combos(space, config))
    key = lambda arrs: [(x.score, [(bd.module, bd.lesson_type, bd.options) for bd in x.bids]) for x in arrs]
    assert key(a) == key(b)


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


def test_rank_arrangements_materializing_winners_matches_slice(config):
    # Building only the top `limit` arrangements must not change WHICH arrangements
    # appear or their -score order versus building all then slicing.
    lec = Choice("ALPHA", "Lecture", "1", (Session("Monday", 600, 720, ALL_WEEKS, "COM1"),))
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    combos = tuple(
        (lec, Choice("ALPHA", "Tutorial", f"{i:02d}", (Session(day, 780, 840, ALL_WEEKS, "COM1"),)))
        for i, day in enumerate(days, start=1)
    )
    space = _space(*combos)
    everything = rank_arrangements(space, config)
    assert len(everything) == 6

    def sig(arrs):
        return [(a.score, [(b.module, b.lesson_type, b.options) for b in a.bids]) for a in arrs]

    capped = rank_arrangements(space, config, limit=3)
    assert len(capped) == 3
    scores = [a.score for a in capped]
    assert scores == sorted(scores, reverse=True)          # -score order preserved
    assert sig(capped) == sig(everything[:3])              # same arrangements, same order
    # limit >= population returns everything unchanged
    assert sig(rank_arrangements(space, config, limit=50)) == sig(everything)


def test_weight_scored_matches_score_combos(groups, config):
    from kairos.search import (
        score_combos,
        enumerate_clashfree,
        score_raw,
        weight_scored,
    )

    space = enumerate_clashfree(groups)
    one_shot = score_combos(space, config)
    split = weight_scored(score_raw(space, config), config)
    # identical totals, breakdowns, assignments, combos in the same order
    assert [s[0] for s in split] == [s[0] for s in one_shot]
    assert [s[1] for s in split] == [s[1] for s in one_shot]
    assert [s[3] for s in split] == [s[3] for s in one_shot]


def test_score_raw_returns_weight_independent_entries(groups, config):
    import copy

    from kairos.search import enumerate_clashfree, score_raw

    space = enumerate_clashfree(groups)
    other = copy.deepcopy(config)
    other.preferences.weights = {k: v + 3 for k, v in config.preferences.weights.items()}
    # raw entries do not depend on weights; only the combo layout matters
    assert [e[0] for e in score_raw(space, config)] == [e[0] for e in score_raw(space, other)]


def test_build_structure_collapse_produces_correct_arrangement(config):
    # Week-twin collapse: 01 odd / 02 even at the same Mon slot -> one collapsed
    # template holding both members -> one arrangement with variant_count 2 and both
    # class numbers offered as a bid (mirrors test_rank_arrangements_collapses_week_twins).
    from kairos.search import build_arrangement_structure, rank_arrangements

    odd = frozenset({1, 3, 5})
    even = frozenset({2, 4, 6})
    lec = Choice("ALPHA", "Lecture", "1", (Session("Monday", 600, 720, ALL_WEEKS, "COM1"),))
    tut_odd = Choice("ALPHA", "Tutorial", "01", (Session("Monday", 840, 900, odd, "COM1"),))
    tut_even = Choice("ALPHA", "Tutorial", "02", (Session("Monday", 840, 900, even, "COM1"),))
    space = _space((lec, tut_odd), (lec, tut_even))
    structure = build_arrangement_structure(space)
    assert [len(t.member_indices) for t in structure] == [2]  # collapse branch: one 2-member template
    arrs = rank_arrangements(space, config, structure=structure)
    assert len(arrs) == 1 and arrs[0].variant_count == 2
    tut_bid = next(b for b in arrs[0].bids if b.lesson_type == "Tutorial")
    assert dict(tut_bid.options) == {"01": "odd wks", "02": "even wks"}


def test_build_structure_entangle_keeps_variants_separate(config):
    # Opposite-week ALPHA/BETA at the same slot: product (4) != member count (2), so
    # the group must NOT collapse -> two single-member templates, two arrangements.
    from kairos.search import build_arrangement_structure, rank_arrangements

    odd = frozenset({1, 3, 5})
    even = frozenset({2, 4, 6})
    a_odd = Choice("ALPHA", "Tutorial", "01", (Session("Monday", 840, 900, odd, "COM1"),))
    a_even = Choice("ALPHA", "Tutorial", "02", (Session("Monday", 840, 900, even, "COM1"),))
    b_odd = Choice("BETA", "Laboratory", "L1", (Session("Monday", 840, 900, odd, "COM2"),))
    b_even = Choice("BETA", "Laboratory", "L2", (Session("Monday", 840, 900, even, "COM2"),))
    space = _space((a_odd, b_even), (a_even, b_odd))
    structure = build_arrangement_structure(space)
    assert [len(t.member_indices) for t in structure] == [1, 1]  # entangle branch: two single templates
    arrs = rank_arrangements(space, config, structure=structure)
    assert len(arrs) == 2 and all(a.variant_count == 1 for a in arrs)


def test_score_raw_matches_direct_compute_raw(groups, config):
    # The per-choice fragment cache in score_raw must never diverge from calling
    # compute_raw directly per combo (batching is an optimisation, not a change).
    from kairos.scoring import compute_raw, pairing_impossibility
    from kairos.search import enumerate_clashfree, score_raw

    space = enumerate_clashfree(groups)
    entries = score_raw(space, config)
    assert len(entries) > 1  # guard: the space really exercises reuse across combos
    unpair, _ = pairing_impossibility(space.members)
    for raw, _assignment, combo in entries:
        assert raw == compute_raw(list(combo), config, unpair)
