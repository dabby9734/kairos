import copy

import pytest

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
        slider = app.query(Slider).first()
        app.set_focus(slider)
        before = slider.value
        await pilot.press("right")
        assert slider.value == before + 1  # widget adjusted
        assert app.state.config.preferences.weights  # state still coherent


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
