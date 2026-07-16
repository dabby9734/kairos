import pytest

from kairos.ballot import BallotOption, ranked_options, snake
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
