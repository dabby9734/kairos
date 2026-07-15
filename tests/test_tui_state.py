import copy

import pytest

from optimiser.api import build_groups, semester_timetable
from optimiser.tui.state import AppState, normalize_difficulties


@pytest.fixture
def state(alpha_json, beta_json, config):
    groups = build_groups("ALPHA", semester_timetable(alpha_json, 1)) + build_groups(
        "BETA", semester_timetable(beta_json, 1)
    )
    return AppState.from_parts(copy.deepcopy(config), groups)


def test_from_parts_enumerates_and_ranks(state):
    assert not state.is_empty()
    assert state.result.top  # ranked timetables present
    assert state.space.combos == state.space.combos  # stored


def test_normalize_expands_shorthand(alpha_json, beta_json, config):
    groups = build_groups("BETA", semester_timetable(beta_json, 1))
    cfg = copy.deepcopy(config)
    cfg.modules["BETA"] = 3  # int shorthand
    normalize_difficulties(cfg, groups)
    assert isinstance(cfg.modules["BETA"], dict)
    assert all(v == 3 for v in cfg.modules["BETA"].values())


def test_set_weight_reranks(state):
    before = [t for t, _, _ in state.top_timetables()]
    state.set_weight("free_days", 100)
    after = [t for t, _, _ in state.top_timetables()]
    assert after != before or state.config.preferences.weights["free_days"] == 100


def test_set_difficulty_changes_scoring(state):
    # Lower the daily cap to 0 so every difficulty point is penalised by
    # tough_days — then any difficulty change must move the scores.
    state.set_pref("max_difficulty_per_day", 0)
    before = [t for t, _, _ in state.top_timetables()]
    state.set_difficulty("BETA", "LAB", 5)
    assert state.config.modules["BETA"]["LAB"] == 5
    after = [t for t, _, _ in state.top_timetables()]
    assert after != before


def test_set_pref_updates_preferences(state):
    state.set_pref("earliest_start", 540)
    assert state.config.preferences.earliest_start == 540


def test_move_priority_reorders_without_rescore(state):
    scores_before = [t for t, _, _ in state.top_timetables()]
    order_before = list(state.config.priority)
    state.move_priority(order_before[-1], -1)  # move last module up
    assert state.config.priority != order_before
    scores_after = [t for t, _, _ in state.top_timetables()]
    assert scores_after == scores_before  # priority doesn't affect timetable scores


def test_ballot_helpers(state):
    options = state.ballot_options()
    snake = state.ballot_snake()
    assert isinstance(options, dict)
    assert isinstance(snake, list)


def test_top_arrangements_returns_arrangements(state):
    from optimiser.search import Arrangement, SlotBid

    arrs = state.top_arrangements()
    assert arrs and all(isinstance(a, Arrangement) for a in arrs)
    assert all(isinstance(a.bids, list) for a in arrs)
    # the balloted ALPHA Tutorial slot must actually produce a bid somewhere
    assert any(a.bids for a in arrs)
    assert all(isinstance(b, SlotBid) for a in arrs for b in a.bids)


def test_arrangements_not_capped_to_top_n(config):
    # Fix A: the arrangement list is truly unlimited, NOT truncated to top_n.
    from optimiser.model import Choice, ChoiceGroup, Session

    cfg = copy.deepcopy(config)
    cfg.top_n = 5
    cfg.fixed = {}
    all_weeks = frozenset(range(1, 14))
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    choices = [
        Choice("ALPHA", "Tutorial", f"{i:02d}", (Session(day, 540, 600, all_weeks, "COM1"),))
        for i, day in enumerate(days, start=1)
    ]
    groups = [ChoiceGroup("ALPHA", "Tutorial", choices)]
    state = AppState.from_parts(cfg, groups)
    arrs = state.top_arrangements()
    # six distinct-day tutorials -> six distinct arrangements, exceeding top_n=5
    assert len(arrs) == 6
    assert len(arrs) > state.config.top_n


def test_to_config_yaml_roundtrips(tmp_path, state):
    import yaml

    from optimiser.config import load_config

    data = state.to_config_yaml()
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    reloaded = load_config(path)  # must not raise
    assert reloaded.semester == state.config.semester
    assert reloaded.preferences.earliest_start == state.config.preferences.earliest_start
    assert "max_arrangements" in data
    assert reloaded.max_arrangements == state.config.max_arrangements


def test_set_lock_shrinks_and_keeps_twins(state):
    before = len(state.space.combos)
    assert state.set_lock("ALPHA", "TUT", "02") is True
    assert state.is_locked("ALPHA", "TUT")
    assert len(state.space.combos) < before
    # locking the slot keeps its interchangeable twins (02/03) in the ballot
    opts = state.ballot_options()[("ALPHA", "Tutorial")]
    assert {"02", "03"} <= {o.class_no for o in opts}


def test_clear_lock_restores(state):
    before = len(state.space.combos)
    state.set_lock("ALPHA", "TUT", "02")
    assert state.clear_lock("ALPHA", "TUT") is True
    assert not state.is_locked("ALPHA", "TUT")
    assert len(state.space.combos) == before


def test_set_lock_empty_guard_leaves_state_unchanged(config):
    import copy

    from optimiser.model import Choice, ChoiceGroup, Session

    all_weeks = frozenset(range(1, 14))
    tut = ChoiceGroup(
        "ALPHA", "Tutorial",
        [
            Choice("ALPHA", "Tutorial", "T1", (Session("Monday", 540, 600, all_weeks, "COM1"),)),
            Choice("ALPHA", "Tutorial", "T2", (Session("Tuesday", 540, 600, all_weeks, "COM1"),)),
        ],
    )
    lab = ChoiceGroup(
        "BETA", "Laboratory",
        [Choice("BETA", "Laboratory", "L1", (Session("Monday", 540, 600, all_weeks, "COM1"),))],
    )
    cfg = copy.deepcopy(config)
    cfg.fixed, cfg.locked = {}, {}
    cfg.modules = {"ALPHA": {"TUT": 3}, "BETA": {"LAB": 3}}
    state = AppState.from_parts(cfg, [tut, lab])
    before = len(state.space.combos)  # only (T2, L1) is clash-free -> 1
    # locking ALPHA TUT to the Monday slot clashes the only lab -> empty
    assert state.set_lock("ALPHA", "TUT", "T1") is False
    assert not state.is_locked("ALPHA", "TUT")
    assert len(state.space.combos) == before  # rolled back


def test_locked_roundtrips_through_config(tmp_path, state):
    import yaml

    from optimiser.config import load_config
    from optimiser.search import prepare_groups

    state.set_lock("ALPHA", "TUT", "02")
    data = state.to_config_yaml()
    assert data["locked"] == {"ALPHA": {"TUT": "02"}}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    reloaded = load_config(path)
    prepared = prepare_groups(state.base_groups, reloaded)
    tut = next(g for g in prepared if g.key == ("ALPHA", "Tutorial"))
    assert sorted(c.class_no for c in tut.choices) == ["02", "03"]


def test_reweight_equivalent_to_full_retune(state):
    # A weight change via reweight() must match a full rescore at the same weights.
    state.config.preferences.weights["free_days"] = 9
    state.reweight()
    reweighted = [t for t, _, _ in state.top_timetables()]
    state.retune()  # full rescore at the same weights
    full = [t for t, _, _ in state.top_timetables()]
    assert reweighted == full


def test_set_weight_does_not_recompute_raw(state, monkeypatch):
    # The whole point of the cache: a weight slider must NOT re-run compute_raw.
    import optimiser.search as search

    calls = {"n": 0}
    real = search.compute_raw
    monkeypatch.setattr(search, "compute_raw", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or real(*a, **k))
    state.set_weight("free_days", 7)
    assert calls["n"] == 0  # served entirely from _raw_cache


def test_set_difficulty_rebuilds_raw_cache(state, monkeypatch):
    # A difficulty change dirties raw, so it MUST rebuild the cache (compute_raw runs).
    import optimiser.search as search

    calls = {"n": 0}
    real = search.compute_raw
    monkeypatch.setattr(search, "compute_raw", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or real(*a, **k))
    state.set_difficulty("ALPHA", "TUT", 5)
    assert calls["n"] > 0


def test_lock_guard_restores_raw_cache(config):
    import copy

    from optimiser.model import Choice, ChoiceGroup, Session

    all_weeks = frozenset(range(1, 14))
    tut = ChoiceGroup(
        "ALPHA", "Tutorial",
        [
            Choice("ALPHA", "Tutorial", "T1", (Session("Monday", 540, 600, all_weeks, "COM1"),)),
            Choice("ALPHA", "Tutorial", "T2", (Session("Tuesday", 540, 600, all_weeks, "COM1"),)),
        ],
    )
    lab = ChoiceGroup(
        "BETA", "Laboratory",
        [Choice("BETA", "Laboratory", "L1", (Session("Monday", 540, 600, all_weeks, "COM1"),))],
    )
    cfg = copy.deepcopy(config)
    cfg.fixed, cfg.locked = {}, {}
    cfg.modules = {"ALPHA": {"TUT": 3}, "BETA": {"LAB": 3}}
    state = AppState.from_parts(cfg, [tut, lab])
    before = state._raw_cache
    assert state.set_lock("ALPHA", "TUT", "T1") is False  # empties the space
    assert state._raw_cache is before  # rejected lock rolled the cache back


def test_retune_caps_arrangements_at_max_arrangements(config):
    # retune must materialize at most config.max_arrangements distinct arrangements.
    from optimiser.model import Choice, ChoiceGroup, Session

    cfg = copy.deepcopy(config)
    cfg.fixed = {}
    cfg.max_arrangements = 3
    all_weeks = frozenset(range(1, 14))
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    choices = [
        Choice("ALPHA", "Tutorial", f"{i:02d}", (Session(day, 540, 600, all_weeks, "COM1"),))
        for i, day in enumerate(days, start=1)
    ]
    groups = [ChoiceGroup("ALPHA", "Tutorial", choices)]
    state = AppState.from_parts(cfg, groups)
    # six distinct-day arrangements exist, but the cap keeps only three
    assert len(state.top_arrangements()) == 3
