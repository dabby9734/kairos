import copy

import pytest

from kairos.api import build_groups, semester_timetable
from kairos.tui.state import AppState, normalize_difficulties


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


def test_ballot_snake_fills_beyond_the_per_group_cap(state):
    """The export path must apply the fill, not just the per-group cap."""
    from kairos.ballot import all_options, ranked_options

    state.config.alternatives_per_module = 1
    full = all_options(state.result, state.config)
    # Precondition: at least one group has an unused option, otherwise the strict
    # assertion below would be unsatisfiable and the test would be meaningless.
    assert any(len(opts) > 1 for opts in full.values())
    capped_total = sum(len(v) for v in ranked_options(state.result, state.config).values())
    # STRICT >: `>=` would pass even if fill_to_cap were never called, since the
    # snake can only ever grow relative to the capped view.
    assert len(state.ballot_snake()) > capped_total


def test_top_arrangements_returns_arrangements(state):
    from kairos.search import Arrangement, SlotBid

    arrs = state.top_arrangements()
    assert arrs and all(isinstance(a, Arrangement) for a in arrs)
    assert all(isinstance(a.bids, list) for a in arrs)
    # the balloted ALPHA Tutorial slot must actually produce a bid somewhere
    assert any(a.bids for a in arrs)
    assert all(isinstance(b, SlotBid) for a in arrs for b in a.bids)


def test_arrangements_not_capped_to_top_n(config):
    # Fix A: the arrangement list is truly unlimited, NOT truncated to top_n.
    from kairos.model import Choice, ChoiceGroup, Session

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

    from kairos.config import load_config

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

    from kairos.model import Choice, ChoiceGroup, Session

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

    from kairos.config import load_config
    from kairos.search import prepare_groups

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
    # The whole point of the cache: a weight slider must NOT re-run the raw pass.
    # score_raw combines per-choice fragments via _combine, so that is the probe.
    import kairos.search as search

    calls = {"n": 0}
    real = search._combine
    monkeypatch.setattr(search, "_combine", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or real(*a, **k))
    state.set_weight("free_days", 7)
    assert calls["n"] == 0  # served entirely from _raw_cache


def test_set_difficulty_rebuilds_raw_cache(state, monkeypatch):
    # A difficulty change dirties raw, so it MUST rebuild the cache (the raw pass
    # re-runs). score_raw combines per-choice fragments via _combine.
    import kairos.search as search

    calls = {"n": 0}
    real = search._combine
    monkeypatch.setattr(search, "_combine", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or real(*a, **k))
    state.set_difficulty("ALPHA", "TUT", 5)
    assert calls["n"] > 0


def test_lock_guard_restores_raw_cache(config):
    import copy

    from kairos.model import Choice, ChoiceGroup, Session

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
    from kairos.model import Choice, ChoiceGroup, Session

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


def test_arr_structure_reused_on_weight_change(state):
    from kairos.search import rank_arrangements

    before = state._arr_structure
    state.set_weight("free_days", 9)
    assert state._arr_structure is before  # weight move must NOT rebuild the structure
    # arrangements still correct: match a full from-scratch rank at these weights
    fresh = rank_arrangements(state.space, state.config, limit=state.config.max_arrangements)
    assert [a.score for a in state.arrangements] == [a.score for a in fresh]


def test_arr_structure_reused_on_difficulty_change(state):
    before = state._arr_structure
    state.set_difficulty("ALPHA", "TUT", 5)
    # difficulty dirties raw (retune rebuilds _raw_cache) but NOT the slot structure
    assert state._arr_structure is before


def test_arr_structure_rebuilt_on_successful_lock(state):
    before = state._arr_structure
    assert state.set_lock("ALPHA", "TUT", "02") is True
    assert state._arr_structure is not before  # new (smaller) space -> new structure


def test_arr_structure_restored_on_rejected_lock(config):
    import copy

    from kairos.model import Choice, ChoiceGroup, Session

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
    before = state._arr_structure
    assert state.set_lock("ALPHA", "TUT", "T1") is False  # empties the space -> rejected
    assert state._arr_structure is before  # rejected lock restored the prior structure


def test_unpairable_reused_on_weight_change(state):
    before = state._unpairable
    state.set_weight("gaps", 9)
    assert state._unpairable is before  # weight move must NOT recompute pairing impossibility


def test_unpairable_rebuilt_on_lock_and_restored_on_rejected_lock(config):
    import copy

    from kairos.model import Choice, ChoiceGroup, Session

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

    before = state._unpairable
    assert state.set_lock("ALPHA", "TUT", "T2") is True  # narrows the space -> commit
    assert state._unpairable is not before  # rebuilt for the new space

    # Rejected lock: the pre-mutation cache is restored.
    before_rejected = state._unpairable
    assert state.set_lock("ALPHA", "TUT", "T1") is False  # empties the space -> rejected
    assert state._unpairable is before_rejected  # restored on rollback


def test_offered_timeslots_collapses_twins_and_sorts(state):
    rows = state.offered_timeslots("ALPHA", "Tutorial")
    # Fixture: 01 Mon 14:00-15:00; 02 & 03 both Tue 09:00-10:00 (share a slot sig).
    # -> two rows, Monday before Tuesday.
    assert [r["class_nos"] for r in rows] == [["01"], ["02", "03"]]
    assert rows[0]["rep"] == "01" and rows[1]["rep"] == "02"
    mon = rows[0]["sessions"][0]
    assert (mon.day, mon.start, mon.end) == ("Monday", 840, 900)


def test_offered_timeslots_unknown_class_is_empty(state):
    assert state.offered_timeslots("NOPE", "Tutorial") == []


def test_locked_sig_none_then_set(state):
    assert state.locked_sig("ALPHA", "Tutorial") is None
    assert state.set_lock("ALPHA", "TUT", "01") is True
    sig = state.locked_sig("ALPHA", "Tutorial")
    assert sig == frozenset({("Monday", 840, 900, False)})


def test_selectable_groups_lists_multi_slot_groups_including_lectures(state):
    # The default config fixture pins BETA LEC via `fixed` — clear it first so
    # this test exercises the "unfixed, genuinely selectable" case rather than
    # the excluded-fixed-group case (covered separately).
    state.config.fixed = {}
    state._rebuild()
    arr = state.top_arrangements()[0]
    rows = state.selectable_groups(arr.assignment)
    keys = [(r.module, r.abbrev) for r in rows]
    # BETA LEC has two classes (Fri online / Thu physical) -> selectable
    assert ("BETA", "LEC") in keys
    # ALPHA LEC has a single class (one Mon+Wed bundle) -> nothing to choose
    assert ("ALPHA", "LEC") not in keys
    # Ordering is on (module, lesson_type), NOT (module, abbrev) — assert the key
    # the implementation actually sorts by. (Sorting `keys` here would not
    # discriminate: no pair in LESSON_ABBREV makes the two orders diverge.)
    order = [(r.module, r.lesson_type) for r in rows]
    assert order == sorted(order)


def test_selectable_groups_marks_balloted_and_current_class(state):
    state.config.fixed = {}  # see note above
    state._rebuild()
    arr = state.top_arrangements()[0]
    rows = {(r.module, r.abbrev): r for r in state.selectable_groups(arr.assignment)}
    assert rows[("ALPHA", "TUT")].balloted is True
    assert rows[("BETA", "LEC")].balloted is False
    # current class number is read off the selected arrangement's assignment
    expected = arr.assignment[("BETA", "Lecture")].class_no
    assert rows[("BETA", "LEC")].current_class_no == expected


def test_selectable_groups_excludes_fixed_group_even_with_multiple_slots(state):
    # Finding 1: prepare_groups applies `fixed` before ever reading `locked` and
    # short-circuits, so a group pinned by `fixed` must not render a pane row —
    # pressing `l` on it would write a `locked` entry that is silently ignored,
    # and the row would falsely show as locked while the timetable never moves.
    #
    # migrate_fixed_to_locked (tui/startup.py) clears non-balloted `fixed`
    # entries at TUI load, so the surviving real-world case is a balloted
    # hand-written pin. Model that here: BETA LEC is not balloted by default, so
    # mark it balloted and set config.fixed directly on the state's config
    # (rather than going through build_state, which would migrate it away).
    state.config.balloted_types = list(state.config.balloted_types) + ["LEC"]
    state.config.fixed = {"BETA": {"LEC": "1"}}
    state._rebuild()
    arr = state.top_arrangements()[0]
    rows = state.selectable_groups(arr.assignment)
    keys = [(r.module, r.abbrev) for r in rows]
    assert ("BETA", "LEC") not in keys


def test_selectable_groups_excludes_group_collapsing_to_one_slot_sig(delta_json, config):
    # DELTA TUT has two classes at the same day/time/online-ness, differing only
    # by venue -> one slot_sig despite two classes. This is the discriminating
    # case for the "< 2 distinct slot_sigs" filter: a single-class group would be
    # excluded trivially, but this proves the filter counts SIGS, not classes.
    groups = build_groups("DELTA", semester_timetable(delta_json, 1))
    # Precondition: without this the assertion below passes vacuously if the
    # fixture's group construction ever changes shape (e.g. collapses to one class).
    tut = next(g for g in groups if g.module == "DELTA" and g.lesson_type == "Tutorial")
    assert len(tut.choices) == 2
    assert len({c.slot_sig for c in tut.choices}) == 1
    cfg = copy.deepcopy(config)
    cfg.fixed, cfg.locked = {}, {}
    cfg.modules = {"DELTA": {"TUT": 3}}
    cfg.priority = ["DELTA"]
    state = AppState.from_parts(cfg, groups)
    keys = [(r.module, r.abbrev) for r in state.selectable_groups({})]
    assert ("DELTA", "TUT") not in keys


def test_selectable_groups_counts_slots_from_base_groups(state):
    # Locking narrows the PREPARED group to one slot. The row must survive,
    # otherwise the pane row vanishes the instant the user locks it.
    state.config.fixed = {}
    state._rebuild()
    assert state.set_lock("BETA", "LAB", "L1")
    arr = state.top_arrangements()[0]
    rows = {(r.module, r.abbrev): r for r in state.selectable_groups(arr.assignment)}
    assert ("BETA", "LAB") in rows
    assert rows[("BETA", "LAB")].locked is True
