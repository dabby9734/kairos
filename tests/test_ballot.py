import pytest

from kairos.ballot import BallotOption, all_options, fill_to_cap, ranked_options, snake
from kairos.model import Session
from kairos.search import SearchResult

ALL_WEEKS = frozenset(range(1, 14))


def sess(day="Monday", start=600, end=660):
    return Session(day, start, end, ALL_WEEKS, "COM1")


def opt(module, ltype, class_no, letter):
    return BallotOption(module, ltype, class_no, letter, 0.0, (sess(),), [])


def fake_result(config):
    """ALPHA Tutorial: fp1 {01,02} score 10, fp2 {03} score 8, fp3 {04} never viable.
    BETA Laboratory: fpA {L1} score 9, fpB {L2} score 7."""
    from kairos.model import Choice

    def ch(module, ltype, no, day):
        return Choice(module, ltype, no, (sess(day),))

    a1, a2 = ch("ALPHA", "Tutorial", "01", "Monday"), ch("ALPHA", "Tutorial", "02", "Monday")
    a3 = ch("ALPHA", "Tutorial", "03", "Tuesday")
    a4 = ch("ALPHA", "Tutorial", "04", "Friday")
    b1, b2 = ch("BETA", "Laboratory", "L1", "Wednesday"), ch("BETA", "Laboratory", "L2", "Thursday")
    members = {
        ("ALPHA", "Tutorial"): {
            a1.footprint: [a1, a2],
            a3.footprint: [a3],
            a4.footprint: [a4],
        },
        ("BETA", "Laboratory"): {b1.footprint: [b1], b2.footprint: [b2]},
        ("ALPHA", "Lecture"): {ch("ALPHA", "Lecture", "1", "Monday").footprint: [ch("ALPHA", "Lecture", "1", "Monday")]},
    }
    best = {
        ("ALPHA", "Tutorial", a1.footprint): 10.0,
        ("ALPHA", "Tutorial", a3.footprint): 8.0,
        # a4 footprint absent: never part of a clash-free timetable
        ("BETA", "Laboratory", b1.footprint): 9.0,
        ("BETA", "Laboratory", b2.footprint): 7.0,
    }
    return SearchResult(top=[], best_by_footprint=best, members=members, evaluated=3)


def test_ranked_options(config):
    options = ranked_options(fake_result(config), config)
    assert set(options) == {("ALPHA", "Tutorial"), ("BETA", "Laboratory")}  # LEC not balloted
    tut = options[("ALPHA", "Tutorial")]
    assert [o.class_no for o in tut] == ["01", "02", "03"]  # 04 excluded (never viable)
    assert [o.letter for o in tut] == ["A", "B", "C"]
    assert tut[0].tied_with == ["02"] and tut[2].tied_with == []
    assert tut[0].best_score == pytest.approx(10.0)


def test_ranked_options_caps_alternatives(config):
    config.alternatives_per_module = 2
    tut = ranked_options(fake_result(config), config)[("ALPHA", "Tutorial")]
    assert [o.class_no for o in tut] == ["01", "02"]


def test_snake_order(config):
    options = {
        ("ALPHA", "Tutorial"): [opt("ALPHA", "Tutorial", n, l) for n, l in [("01", "A"), ("02", "B"), ("03", "C")]],
        ("ALPHA", "Laboratory"): [opt("ALPHA", "Laboratory", n, l) for n, l in [("L1", "A"), ("L2", "B")]],
        ("BETA", "Sectional Teaching"): [opt("BETA", "Sectional Teaching", n, l) for n, l in [("S1", "A")]],
    }
    entries = snake(options, config)  # priority ALPHA, BETA; TUT before LAB
    labels = [(e.module, e.class_no) for e in entries]
    assert labels == [
        ("ALPHA", "01"), ("ALPHA", "L1"), ("BETA", "S1"),  # round A forward
        ("ALPHA", "L2"), ("ALPHA", "02"),                   # round B reversed, BETA exhausted
        ("ALPHA", "03"),                                    # round C forward
    ]


def test_snake_cap(config):
    options = {
        ("ALPHA", "Tutorial"): [opt("ALPHA", "Tutorial", f"{i:02d}", "A") for i in range(30)],
    }
    assert len(snake(options, config)) == 20


def test_ranked_options_groups_week_twins(config):
    # REAL space: odd/even same-slot twins that are freely swappable (full Cartesian
    # with a non-clashing lecture) -> R(fp_odd) == R(fp_even), so they merge into one
    # ballot cluster and appear in each other's tied_with (Fix C, provably sound).
    from kairos.model import Choice, ChoiceGroup, Session
    from kairos.search import enumerate_clashfree, rank

    odd = frozenset({1, 3, 5})
    even = frozenset({2, 4, 6})
    lec = Choice("ALPHA", "Lecture", "1", (Session("Monday", 600, 720, ALL_WEEKS, "COM1"),))
    c_odd = Choice("ALPHA", "Tutorial", "01", (Session("Monday", 840, 900, odd, "COM1"),))
    c_even = Choice("ALPHA", "Tutorial", "02", (Session("Monday", 840, 900, even, "COM1"),))
    groups = [
        ChoiceGroup("ALPHA", "Lecture", [lec]),
        ChoiceGroup("ALPHA", "Tutorial", [c_odd, c_even]),
    ]
    result = rank(enumerate_clashfree(groups), config)
    options = ranked_options(result, config)[("ALPHA", "Tutorial")]
    assert {o.class_no for o in options} == {"01", "02"}
    by_no = {o.class_no: o for o in options}
    assert by_no["01"].tied_with == ["02"]
    assert by_no["02"].tied_with == ["01"]


def test_ranked_options_keeps_entangled_twins_separate(config):
    # ALPHA Tutorial and BETA Laboratory BOTH odd/even at the same slot: only the
    # opposite-week pairings are clash-free, so R(fp_odd) != R(fp_even) for the
    # tutorial twins -> they must NOT merge (Fix C soundness).
    from kairos.model import Choice, ChoiceGroup, Session
    from kairos.search import enumerate_clashfree, rank

    odd = frozenset({1, 3, 5})
    even = frozenset({2, 4, 6})
    a_odd = Choice("ALPHA", "Tutorial", "01", (Session("Monday", 840, 900, odd, "COM1"),))
    a_even = Choice("ALPHA", "Tutorial", "02", (Session("Monday", 840, 900, even, "COM1"),))
    b_odd = Choice("BETA", "Laboratory", "L1", (Session("Monday", 840, 900, odd, "COM2"),))
    b_even = Choice("BETA", "Laboratory", "L2", (Session("Monday", 840, 900, even, "COM2"),))
    groups = [
        ChoiceGroup("ALPHA", "Tutorial", [a_odd, a_even]),
        ChoiceGroup("BETA", "Laboratory", [b_odd, b_even]),
    ]
    result = rank(enumerate_clashfree(groups), config)
    tut = ranked_options(result, config)[("ALPHA", "Tutorial")]
    assert {o.class_no for o in tut} == {"01", "02"}
    assert all(o.tied_with == [] for o in tut)  # not interchangeable


def test_ranked_options_groups_venue_twins(config):
    # Same footprint, two class numbers (different venue) -> one member bucket, so
    # both class numbers land in one ballot cluster with each other in tied_with
    # (ballot side of I1 / Fix B).
    from kairos.model import Choice, ChoiceGroup, Session
    from kairos.search import enumerate_clashfree, rank

    lec = Choice("ALPHA", "Lecture", "1", (Session("Monday", 600, 720, ALL_WEEKS, "COM1"),))
    t_a = Choice("ALPHA", "Tutorial", "01", (Session("Tuesday", 540, 600, ALL_WEEKS, "COM1"),))
    t_b = Choice("ALPHA", "Tutorial", "02", (Session("Tuesday", 540, 600, ALL_WEEKS, "COM2"),))
    groups = [
        ChoiceGroup("ALPHA", "Lecture", [lec]),
        ChoiceGroup("ALPHA", "Tutorial", [t_a, t_b]),
    ]
    result = rank(enumerate_clashfree(groups), config)
    tut = ranked_options(result, config)[("ALPHA", "Tutorial")]
    assert {o.class_no for o in tut} == {"01", "02"}
    by_no = {o.class_no: o for o in tut}
    assert by_no["01"].tied_with == ["02"]
    assert by_no["02"].tied_with == ["01"]


def test_all_options_is_uncapped(config):
    config.alternatives_per_module = 2
    full = all_options(fake_result(config), config)
    # uncapped: all three viable ALPHA tutorials, despite the cap of 2
    assert [o.class_no for o in full[("ALPHA", "Tutorial")]] == ["01", "02", "03"]
    # letters are positional over the FULL list
    assert [o.letter for o in full[("ALPHA", "Tutorial")]] == ["A", "B", "C"]
    # 04 stays excluded: never part of a clash-free timetable
    assert "04" not in [o.class_no for o in full[("ALPHA", "Tutorial")]]


def test_ranked_options_is_a_prefix_of_all_options(config):
    config.alternatives_per_module = 2
    result = fake_result(config)
    full = all_options(result, config)
    capped = ranked_options(result, config)
    for key, opts in capped.items():
        assert opts == full[key][: len(opts)]


def test_ranked_options_cap_zero(config):
    """With cap of 0, no groups appear in result dict (keys excluded, not empty lists)."""
    config.alternatives_per_module = 0
    options = ranked_options(fake_result(config), config)
    assert options == {}


def test_ranked_options_cap_negative(config):
    """With negative cap, no groups appear in result dict (keys excluded, not empty lists)."""
    config.alternatives_per_module = -1
    options = ranked_options(fake_result(config), config)
    assert options == {}


def wide_result(config, groups=6, per_group=5):
    """`groups` balloted tutorial groups, each with `per_group` viable single-choice
    footprints. Scores descend within a group and across groups, so the
    best-remaining-score fill order is fully determined."""
    from kairos.model import Choice

    members, best = {}, {}
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    for g in range(groups):
        module = f"M{g}"
        fp_members = {}
        for i in range(per_group):
            c = Choice(module, "Tutorial", f"{i:02d}", (sess(days[i % len(days)], 600 + i * 60, 660 + i * 60),))
            fp_members[c.footprint] = [c]
            # group 0 scores highest; within a group, option 0 scores highest
            best[(module, "Tutorial", c.footprint)] = 100.0 - g * 10 - i
        members[(module, "Tutorial")] = fp_members
    return SearchResult(top=[], best_by_footprint=best, members=members, evaluated=0)


def test_fill_to_cap_reaches_20(config):
    config.alternatives_per_module = 2
    result = wide_result(config)  # 6 groups x 5 options = 30 available
    full = all_options(result, config)
    assert sum(len(v) for v in ranked_options(result, config).values()) == 12  # 6 x 2
    filled = fill_to_cap(full, config)
    assert sum(len(v) for v in filled.values()) == 20


def test_fill_to_cap_awards_slots_by_best_remaining_score(config):
    """The discriminating case: the extra slot must go to the group with the best
    NEXT option globally, not to the first group in iteration order."""
    config.alternatives_per_module = 1

    def o(module, no, letter, score):
        return BallotOption(module, "Tutorial", no, letter, score, (sess(),), [])

    # X's second option (70) is worse than Y's second (80), even though X's first
    # (100) beats Y's first (90). A round-robin or first-group-wins fill would pick
    # X["02"]; best-remaining-score must pick Y["02"].
    full = {
        ("X", "Tutorial"): [o("X", "01", "A", 100.0), o("X", "02", "B", 70.0)],
        ("Y", "Tutorial"): [o("Y", "01", "A", 90.0), o("Y", "02", "B", 80.0)],
    }
    filled = fill_to_cap(full, config, cap=3)
    assert [e.class_no for e in filled[("Y", "Tutorial")]] == ["01", "02"]
    assert [e.class_no for e in filled[("X", "Tutorial")]] == ["01"]


def test_fill_to_cap_concentrates_on_the_strongest_group(config):
    """Documents an accepted consequence of best-remaining-score: when one group's
    whole option list outscores another's, it takes every extra slot. Spreading depth
    by contest risk instead is the separate P2 item in plans/README.md."""
    config.alternatives_per_module = 1
    result = wide_result(config, groups=3, per_group=3)  # M0: 100,99,98  M1: 90,89,88
    filled = fill_to_cap(all_options(result, config), config, cap=5)
    assert [e.class_no for e in filled[("M0", "Tutorial")]] == ["00", "01", "02"]
    assert [e.class_no for e in filled[("M1", "Tutorial")]] == ["00"]
    assert [e.class_no for e in filled[("M2", "Tutorial")]] == ["00"]


def test_fill_to_cap_stops_when_options_exhausted(config):
    config.alternatives_per_module = 1
    result = fake_result(config)  # only 5 viable options exist in total
    filled = fill_to_cap(all_options(result, config), config)
    assert sum(len(v) for v in filled.values()) == 5
    # and the non-viable ALPHA tutorial 04 is still excluded
    assert "04" not in [o.class_no for o in filled[("ALPHA", "Tutorial")]]


def test_fill_to_cap_is_noop_when_already_at_cap(config):
    config.alternatives_per_module = 4
    result = wide_result(config, groups=5, per_group=4)  # 5 x 4 = 20 baseline
    full = all_options(result, config)
    filled = fill_to_cap(full, config)
    assert sum(len(v) for v in filled.values()) == 20
    assert filled == ranked_options(result, config)


def test_fill_to_cap_preserves_letters(config):
    config.alternatives_per_module = 1
    result = wide_result(config, groups=2, per_group=4)
    filled = fill_to_cap(all_options(result, config), config, cap=6)
    for opts in filled.values():
        assert [o.letter for o in opts] == [chr(ord("A") + i) for i in range(len(opts))]
