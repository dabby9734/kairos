import pytest

from optimiser.ballot import BallotOption, ranked_options, snake
from optimiser.model import Session
from optimiser.search import SearchResult

ALL_WEEKS = frozenset(range(1, 14))


def sess(day="Monday", start=600, end=660):
    return Session(day, start, end, ALL_WEEKS, "COM1")


def opt(module, ltype, class_no, letter):
    return BallotOption(module, ltype, class_no, letter, 0.0, (sess(),), [])


def fake_result(config):
    """ALPHA Tutorial: fp1 {01,02} score 10, fp2 {03} score 8, fp3 {04} never viable.
    BETA Laboratory: fpA {L1} score 9, fpB {L2} score 7."""
    from optimiser.model import Choice

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
    from optimiser.model import Choice, Session
    from optimiser.search import SearchResult
    from optimiser.ballot import ranked_options

    odd = frozenset({1, 3, 5})
    even = frozenset({2, 4, 6})
    c_odd = Choice("ALPHA", "Tutorial", "01", (Session("Monday", 840, 900, odd, "COM1"),))
    c_even = Choice("ALPHA", "Tutorial", "02", (Session("Monday", 840, 900, even, "COM1"),))
    members = {
        ("ALPHA", "Tutorial"): {c_odd.footprint: [c_odd], c_even.footprint: [c_even]}
    }
    best = {
        ("ALPHA", "Tutorial", c_odd.footprint): 5.0,
        ("ALPHA", "Tutorial", c_even.footprint): 5.0,
    }
    result = SearchResult(top=[], best_by_footprint=best, members=members, evaluated=2)
    options = ranked_options(result, config)[("ALPHA", "Tutorial")]
    # 01 and 02 are the same slot (Mon 1400-1500), different weeks -> interchangeable
    first = options[0]
    assert "02" in first.tied_with or "01" in first.tied_with
