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


def test_same_day_pairing_caps_at_one_per_module(config):
    # BETA has a lecture Monday plus TWO non-lecture classes on Monday.
    # The bonus is per module, so this scores 1, not 2.
    lec = choice("BETA", "Lecture", "1", sess("Monday", 600, 720))
    rec = choice("BETA", "Recitation", "01", sess("Monday", 840, 900))
    lab = choice("BETA", "Laboratory", "L1", sess("Monday", 960, 1020))
    assert raw([lec, rec, lab], config, "same_day_pairing") == 1


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


def test_compute_raw_is_weight_independent(config):
    import copy

    from optimiser.scoring import compute_raw

    cs = [choice("ALPHA", "Tutorial", "01", sess("Monday", 540, 660))]
    other = copy.deepcopy(config)
    other.preferences.weights = {k: v + 5 for k, v in config.preferences.weights.items()}
    # raw depends only on the timetable, never on the weights
    assert compute_raw(cs, config) == compute_raw(cs, other)


def test_weight_raw_applies_weights(config):
    from optimiser.scoring import weight_raw

    raw = {name: 0.0 for name in config.preferences.weights}
    raw["free_days"] = 3.0
    total, breakdown = weight_raw(raw, config)
    w = config.preferences.weights["free_days"]
    assert breakdown["free_days"] == (3.0, 3.0 * w)
    assert total == pytest.approx(3.0 * w)


def test_score_assignment_equals_split(config):
    from optimiser.scoring import compute_raw, weight_raw

    cs = [choice("ALPHA", "Tutorial", "01", sess("Monday", 540, 660))]
    assert score_assignment(cs, config) == weight_raw(compute_raw(cs, config), config)


def test_tough_day_peaks_reports_peak_week(config):
    from optimiser.scoring import tough_day_peaks

    w13 = frozenset({1, 3})
    cs = [
        Choice("ALPHA", "Tutorial", "01", (Session("Monday", 600, 660, w13, "COM1"),)),
        Choice("BETA", "Laboratory", "L1", (Session("Monday", 720, 780, w13, "COM1"),)),
        Choice("BETA", "Recitation", "R1", (Session("Monday", 840, 900, w13, "COM1"),)),
    ]
    # cap is 8; all three share weeks 1&3, so week 1 load = 4+3+3 = 10.
    assert tough_day_peaks(cs, config) == {"Monday": 10}


def test_tough_days_week_aware_ignores_disjoint_weeks(config):
    # Naive Monday difficulty 4+3+3 = 10 > cap 8, but the diff-3 recitation runs on
    # weeks disjoint from the other two, so no single week exceeds 8 (peak = 7).
    w13 = frozenset({1, 3})
    w24 = frozenset({2, 4})
    cs = [
        choice("ALPHA", "Tutorial", "01", Session("Monday", 600, 660, w13, "COM1")),
        choice("BETA", "Laboratory", "L1", Session("Monday", 720, 780, w13, "COM1")),
        choice("BETA", "Recitation", "R1", Session("Monday", 840, 900, w24, "COM1")),
    ]
    assert raw(cs, config, "tough_days") == 0


def test_tough_days_week_aware_penalises_overlapping_weeks(config):
    # Same three classes, but the recitation now shares weeks 1&3 -> week 1 load is
    # 4+3+3 = 10 > cap 8 -> penalty of (10 - 8) = 2.
    w13 = frozenset({1, 3})
    cs = [
        choice("ALPHA", "Tutorial", "01", Session("Monday", 600, 660, w13, "COM1")),
        choice("BETA", "Laboratory", "L1", Session("Monday", 720, 780, w13, "COM1")),
        choice("BETA", "Recitation", "R1", Session("Monday", 840, 900, w13, "COM1")),
    ]
    assert raw(cs, config, "tough_days") == pytest.approx(-2)
