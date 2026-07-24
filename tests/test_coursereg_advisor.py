import math

from kairos.coursereg.model import UNLIMITED, DemandRecord, Profile


def rec(course, year, sem, rnd, demand, vacancy):
    return DemandRecord(course, year, sem, rnd, demand, vacancy)


def profile(**kw):
    base = dict(seniority=2, semester=1, round=2,
                tiers={"AAA1000": "major"}, order=["AAA1000"], ranked=False)
    base.update(kw)
    return Profile(**base)


def history(course, ratios_by_year, sem=1, rnd=2):
    """ratios expressed as (demand, vacancy) pairs keyed by year."""
    return [rec(course, year, sem, rnd, d, v) for year, (d, v) in ratios_by_year.items()]


def test_ratio_edge_cases():
    from kairos.coursereg.advisor import ratio

    assert ratio(50, 100) == 0.5
    assert ratio(None, 100) is None and ratio(50, None) is None
    assert ratio(108, UNLIMITED) == 0.0
    assert ratio(5, 0) == math.inf
    assert ratio(0, 0) is None


def test_base_verdict_bands():
    from kairos.coursereg.advisor import (
        CONTESTED, LONG_SHOT, NO_DATA, SAFE, base_verdict, same_sem_ratios,
    )

    safe = history("AAA1000", {"2324": (40, 100), "2425": (50, 100), "2526": (60, 100)})
    contested = history("AAA1000", {"2324": (90, 100), "2425": (110, 100), "2526": (95, 100)})
    long_shot = history("AAA1000", {"2324": (200, 100), "2425": (180, 100), "2526": (210, 100)})

    assert base_verdict(same_sem_ratios(safe, "AAA1000", 1, 2)) == SAFE
    assert base_verdict(same_sem_ratios(contested, "AAA1000", 1, 2)) == CONTESTED
    assert base_verdict(same_sem_ratios(long_shot, "AAA1000", 1, 2)) == LONG_SHOT
    assert base_verdict([]) == NO_DATA


def test_base_verdict_uses_only_recent_years():
    from kairos.coursereg.advisor import SAFE, base_verdict, same_sem_ratios

    # Ancient oversubscription beyond RECENT_YEARS=3 must not spoil SAFE.
    records = history("AAA1000", {
        "2122": (300, 100),
        "2324": (40, 100), "2425": (50, 100), "2526": (60, 100),
    })
    assert base_verdict(same_sem_ratios(records, "AAA1000", 1, 2)) == SAFE


def test_same_sem_ratios_filters_semester_and_round():
    from kairos.coursereg.advisor import same_sem_ratios

    records = [
        rec("AAA1000", "2526", 1, 2, 50, 100),
        rec("AAA1000", "2526", 2, 2, 999, 100),  # other semester
        rec("AAA1000", "2526", 1, 3, 999, 100),  # other round
        rec("BBB1000", "2526", 1, 2, 999, 100),  # other course
    ]
    assert same_sem_ratios(records, "AAA1000", 1, 2) == [("2526", 0.5)]


def test_nudge_steps_table():
    from kairos.coursereg.advisor import nudge_steps

    assert nudge_steps("core", 2) == -1   # toward safe
    assert nudge_steps("major", 2) == 0
    assert nudge_steps("ue", 2) == 1      # toward long-shot
    assert nudge_steps("ue", 4) == 0      # Y3/Y4 seniority cancels the UE hit
    assert nudge_steps("ue", 1) == 1      # Y1 + ue clamped at +1, never +2
    assert nudge_steps("core", 1) == -1   # seniority only applies to ue tier


def test_verdict_five_bands_and_reasoning():
    from kairos.coursereg.advisor import CONTESTED, LIKELY, TOUGH, verdict

    contested = history("AAA1000", {"2324": (90, 100), "2425": (110, 100), "2526": (95, 100)})
    v_major = verdict(contested, "AAA1000", profile(tiers={"AAA1000": "major"}))
    v_core = verdict(contested, "AAA1000", profile(tiers={"AAA1000": "core"}))
    v_ue = verdict(contested, "AAA1000", profile(tiers={"AAA1000": "ue"}))
    assert v_major.standing == CONTESTED
    assert v_core.standing == LIKELY
    assert v_ue.standing == TOUGH
    assert "oversubscribed" in v_major.reasoning


def test_verdict_no_data_for_unknown_course():
    from kairos.coursereg.advisor import NO_DATA, verdict

    v = verdict([], "ZZZ9999", profile(tiers={"ZZZ9999": "ue"}))
    assert v.standing == NO_DATA and "no" in v.reasoning.lower()


def test_suggested_order_leverage_and_tiebreak():
    from kairos.coursereg.advisor import (
        CONTESTED, LIKELY, LONG_SHOT, NO_DATA, SAFE, TOUGH, suggested_order,
    )

    standings = {
        "SAFE1": SAFE, "TOUGH1": TOUGH, "LIKELY1": LIKELY,
        "NEW1": NO_DATA, "LONG1": LONG_SHOT,
        "CONT2": CONTESTED, "CONT1": CONTESTED,
    }
    assert suggested_order(standings) == [
        "TOUGH1", "CONT1", "CONT2", "LIKELY1", "NEW1", "LONG1", "SAFE1",
    ]


def test_leverage_warnings():
    from kairos.coursereg.advisor import CONTESTED, NO_DATA, SAFE, leverage_warnings

    # 9 candidates: a SAFE in rank 1, a CONTESTED pushed past RANK_CAP=8.
    order = ["SAFE1", "B", "C", "D", "E", "F", "G", "NEW1", "CONT1"]
    standings = {c: SAFE for c in order}
    standings["CONT1"] = CONTESTED
    standings["NEW1"] = NO_DATA
    messages = " ".join(leverage_warnings(order, standings))
    assert "SAFE1" in messages          # wasted top rank
    assert "CONT1" in messages          # contested unranked
    assert "NEW1" in messages           # no-data note


def test_dossier_rows_split_and_sorted():
    from kairos.coursereg.advisor import dossier_rows

    records = [
        rec("AAA1000", "2425", 1, 2, 1, 2),
        rec("AAA1000", "2526", 1, 2, 3, 4),
        rec("AAA1000", "2526", 2, 2, 5, 6),
        rec("AAA1000", "2526", 1, 3, 7, 8),  # other round: excluded
    ]
    same, other = dossier_rows(records, "AAA1000", 2, 1)
    assert [r.acad_year for r in same] == ["2526", "2425"]  # year-descending
    assert [r.acad_year for r in other] == ["2526"]
