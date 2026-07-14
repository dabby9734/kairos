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
    before = [t for t, _, _ in state.top_timetables()]
    # crank a component difficulty to force tough_days penalties
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


def test_to_config_yaml_roundtrips(tmp_path, state):
    import yaml

    from optimiser.config import load_config

    data = state.to_config_yaml()
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    reloaded = load_config(path)  # must not raise
    assert reloaded.semester == state.config.semester
    assert reloaded.preferences.earliest_start == state.config.preferences.earliest_start
