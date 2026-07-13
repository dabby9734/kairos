from optimiser.model import (
    LESSON_ABBREV,
    LESSON_FULL,
    Choice,
    Session,
    fmt_time,
    parse_clock,
    parse_time,
)

ALL_WEEKS = frozenset(range(1, 14))


def sess(day="Monday", start=600, end=720, weeks=ALL_WEEKS, venue="COM1"):
    return Session(day, start, end, weeks, venue)


def test_time_parsing():
    assert parse_time("0930") == 570
    assert parse_clock("09:30") == 570
    assert fmt_time(570) == "0930"


def test_lesson_type_maps_roundtrip():
    assert LESSON_ABBREV["Tutorial"] == "TUT"
    assert LESSON_FULL["SEC"] == "Sectional Teaching"
    for full, ab in LESSON_ABBREV.items():
        assert LESSON_FULL[ab] == full


def test_online_detection():
    assert sess(venue="E-Learn_C").online
    assert not sess(venue="LT11").online


def test_clash_same_day_overlap():
    assert sess(start=600, end=720).clashes(sess(start=660, end=780))


def test_no_clash_different_day():
    assert not sess(day="Monday").clashes(sess(day="Tuesday"))


def test_no_clash_back_to_back():
    assert not sess(start=600, end=720).clashes(sess(start=720, end=840))


def test_no_clash_disjoint_weeks():
    odd = sess(weeks=frozenset({1, 3, 5}))
    even = sess(weeks=frozenset({2, 4, 6}))
    assert not odd.clashes(even)
    assert odd.clashes(sess(weeks=frozenset({5, 7})))


def test_choice_clash_and_footprint():
    a = Choice("ALPHA", "Tutorial", "01", (sess(),))
    b = Choice("BETA", "Laboratory", "L1", (sess(start=660, end=780),))
    assert a.clashes(b)
    # same schedule, different venue -> same footprint
    c = Choice("ALPHA", "Tutorial", "02", (sess(venue="COM2"),))
    assert a.footprint == c.footprint
    d = Choice("ALPHA", "Tutorial", "03", (sess(day="Friday"),))
    assert a.footprint != d.footprint


def test_footprint_distinguishes_online():
    online = Choice("ALPHA", "Lecture", "1", (sess(venue="E-Learn_C"),))
    physical = Choice("ALPHA", "Lecture", "2", (sess(venue="LT11"),))
    assert online.footprint != physical.footprint
