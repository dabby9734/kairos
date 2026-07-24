import yaml

from kairos.coursereg.model import DemandRecord, Profile


def rec(course, year, sem, rnd, demand, vacancy):
    return DemandRecord(course, year, sem, rnd, demand, vacancy)


def make_records():
    # AAA1000 contested, BBB1000 safe, CCC1000 long shot; all S1 round 2.
    out = []
    for year, (a, b, c) in {
        "2324": (90, 40, 200), "2425": (110, 50, 180), "2526": (95, 60, 210),
    }.items():
        out += [
            rec("AAA1000", year, 1, 2, a, 100),
            rec("BBB1000", year, 1, 2, b, 100),
            rec("CCC1000", year, 1, 2, c, 100),
        ]
    return out


def make_profile(ranked=False, order=None):
    tiers = {"AAA1000": "major", "BBB1000": "major", "CCC1000": "major"}
    return Profile(seniority=2, semester=1, round=2, tiers=tiers,
                   order=order or list(tiers), ranked=ranked)


def make_state(**kw):
    from kairos.coursereg.tui.state import AdvisorState

    return AdvisorState(make_profile(**kw), make_records())


def test_fresh_profile_opens_in_suggested_order():
    state = make_state()
    # leverage order: CONTESTED (AAA) then LONG_SHOT (CCC) then SAFE (BBB)
    assert state.order == ["AAA1000", "CCC1000", "BBB1000"]
    assert state.order == state.suggested


def test_ranked_profile_keeps_saved_order():
    state = make_state(ranked=True, order=["BBB1000", "AAA1000", "CCC1000"])
    assert state.order == ["BBB1000", "AAA1000", "CCC1000"]


def test_rows_carry_rank_standing_tier():
    state = make_state()
    rows = state.rows()
    assert rows[0] == (1, "AAA1000", "CONTESTED", "major")
    assert [row[0] for row in rows] == [1, 2, 3]  # all within RANK_CAP


def test_move_reorders_and_clamps():
    state = make_state()
    new_index = state.move(0, 1)
    assert new_index == 1 and state.order[1] == "AAA1000"
    assert state.move(0, -1) == 0  # clamped at the top


def test_cycle_tier_recomputes_verdicts():
    state = make_state()
    assert state.verdicts["AAA1000"].standing == "CONTESTED"
    state.cycle_tier("AAA1000")  # major -> ue
    assert state.profile.tiers["AAA1000"] == "ue"
    assert state.verdicts["AAA1000"].standing == "TOUGH"


def test_toggle_round_recomputes():
    state = make_state()
    state.toggle_round()
    assert state.profile.round == 3
    # No round-3 records exist -> everything becomes NO_DATA.
    assert all(v.standing == "NO_DATA" for v in state.verdicts.values())
    state.toggle_round()
    assert state.profile.round == 2


def test_restore_suggested_after_manual_moves():
    state = make_state()
    state.move(0, 2)
    assert state.order != state.suggested
    state.restore_suggested()
    assert state.order == state.suggested


def test_warnings_flag_safe_in_top_ranks():
    state = make_state(ranked=True, order=["BBB1000", "AAA1000", "CCC1000"])
    assert any("BBB1000" in w for w in state.warnings())


def test_to_yaml_round_trips_with_ranked_flag():
    from kairos.coursereg.model import profile_from_dict

    state = make_state()
    state.move(0, 1)
    data = yaml.safe_load(state.to_yaml())
    again = profile_from_dict(data)
    assert again.ranked is True
    assert again.order == state.order
