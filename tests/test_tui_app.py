import copy

import pytest
from textual.widgets import ListView

from optimiser.api import build_groups, semester_timetable
from optimiser.tui.app import OptimiserApp
from optimiser.tui.state import AppState
from optimiser.tui.widgets import Slider


@pytest.fixture
def state(alpha_json, beta_json, config):
    groups = build_groups("ALPHA", semester_timetable(alpha_json, 1)) + build_groups(
        "BETA", semester_timetable(beta_json, 1)
    )
    return AppState.from_parts(copy.deepcopy(config), groups)


async def test_slider_adjust_reranks(state, tmp_path):
    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        slider = next(s for s in app.query(Slider) if s.key == "weight:free_days")
        app.set_focus(slider)
        before_weight = app.state.config.preferences.weights["free_days"]
        before_totals = [t for t, _, _ in app.state.top_timetables()]
        await pilot.press("right")
        assert slider.value == before_weight + 1  # widget adjusted
        # state actually re-ranked: weight applied and totals changed
        assert app.state.config.preferences.weights["free_days"] == before_weight + 1
        after_totals = [t for t, _, _ in app.state.top_timetables()]
        assert after_totals != before_totals


async def test_priority_reorder_follows_module(state, tmp_path):
    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        lst = app.query_one("#priority-list", ListView)
        app.set_focus(lst)
        last_index = len(app.state.config.priority) - 1
        lst.index = last_index
        moved_module = app.state.config.priority[last_index]
        await pilot.press("[")
        # the module actually moved up one position
        assert app.state.config.priority.index(moved_module) == last_index - 1
        # the highlight follows the moved module (this is what makes consecutive
        # moves work; fails against the pre-fix code where lst.index is stale)
        assert app.state.config.priority[lst.index] == moved_module


async def test_toggle_ballot_view(state, tmp_path):
    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        assert app.ballot_mode is False
        await pilot.press("b")
        assert app.ballot_mode is True
        await pilot.press("b")
        assert app.ballot_mode is False


async def test_save_config_writes_file(state, tmp_path):
    path = tmp_path / "config.yaml"
    app = OptimiserApp(state, path)
    async with app.run_test() as pilot:
        await pilot.press("s")
    assert path.exists()  # config written
    import yaml

    assert yaml.safe_load(path.read_text())["semester"] == state.config.semester
