import pytest

from optimiser.model import Choice, Session
from optimiser.scoring import score_assignment

ALL_WEEKS = frozenset(range(1, 14))


def choice(module, ltype, class_no, *sessions):
    return Choice(module, ltype, class_no, tuple(sessions))


def sess(day, start, end, venue="COM1"):
    return Session(day, start, end, ALL_WEEKS, venue)


def raw(choices, config, name):
    _, breakdown = score_assignment(choices, config)
    return breakdown[name][0]


def test_time_window_penalty(config):
    # 09:00-11:00 class with earliest 10:00 -> 60 min outside -> raw -1.0
    c = choice("ALPHA", "Tutorial", "01", sess("Monday", 540, 660))
    assert raw([c], config, "time_window") == pytest.approx(-1.0)


def test_time_window_ignores_online(config):
    c = choice("ALPHA", "Lecture", "1", sess("Monday", 480, 600, venue="E-Learn_C"))
    assert raw([c], config, "time_window") == 0


def test_tough_days_counts_online(config):
    # ALPHA LEC diff 2 (online) + ALPHA TUT diff 4 + BETA LAB diff 3 = 9 > 8 -> raw -1
    cs = [
        choice("ALPHA", "Lecture", "1", sess("Monday", 600, 720, venue="E-Learn_C")),
        choice("ALPHA", "Tutorial", "01", sess("Monday", 840, 900)),
        choice("BETA", "Laboratory", "L1", sess("Monday", 960, 1080)),
    ]
    assert raw(cs, config, "tough_days") == pytest.approx(-1)


def test_same_day_pairing_requires_oncampus_lecture(config):
    lec = choice("ALPHA", "Lecture", "1", sess("Monday", 600, 720))
    tut = choice("ALPHA", "Tutorial", "01", sess("Monday", 840, 900))
    assert raw([lec, tut], config, "same_day_pairing") == 1
    online_lec = choice("ALPHA", "Lecture", "1", sess("Monday", 600, 720, venue="E-Learn_C"))
    assert raw([online_lec, tut], config, "same_day_pairing") == 0


def test_free_days_ignores_online(config):
    # one on-campus Monday class + one online Friday lecture -> Tue/Wed/Thu/Fri free
    cs = [
        choice("ALPHA", "Tutorial", "01", sess("Monday", 600, 720)),
        choice("BETA", "Lecture", "1", sess("Friday", 480, 600, venue="E-Learn_C")),
    ]
    assert raw(cs, config, "free_days") == 4


def test_gaps(config):
    # 10:00-12:00 then 14:00-15:00 -> 120 min gap -> raw -2.0
    cs = [
        choice("ALPHA", "Lecture", "1", sess("Monday", 600, 720)),
        choice("ALPHA", "Tutorial", "01", sess("Monday", 840, 900)),
    ]
    assert raw(cs, config, "gaps") == pytest.approx(-2.0)


def test_lunch_penalty(config):
    # 11:00-14:00 solid class -> no lunch block -> raw -1
    blocked = [choice("ALPHA", "Lecture", "1", sess("Monday", 660, 840))]
    assert raw(blocked, config, "lunch") == -1
    # 11:00-12:00 class leaves 12:00-14:00 free -> ok
    fine = [choice("ALPHA", "Lecture", "1", sess("Monday", 660, 720))]
    assert raw(fine, config, "lunch") == 0


def test_total_is_weighted_sum(config):
    cs = [choice("ALPHA", "Tutorial", "01", sess("Monday", 540, 660))]
    total, breakdown = score_assignment(cs, config)
    assert total == pytest.approx(sum(w for _, w in breakdown.values()))
    assert breakdown["free_days"][1] == pytest.approx(4 * config.preferences.weights["free_days"])
