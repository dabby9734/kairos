import copy

import pytest
from textual.widgets import ListView, Static

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


async def test_copy_link_uses_os_clipboard(state, tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "optimiser.tui.app._os_clipboard_copy",
        lambda text: captured.setdefault("url", text) or True,
    )
    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        await pilot.press("c")
    assert "url" in captured
    assert captured["url"].startswith("https://nusmods.com/timetable/sem-1/share?")


async def test_number_key_switches_tab(state, tmp_path):
    from textual.widgets import TabbedContent

    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        await pilot.press("3")
        assert app.query_one(TabbedContent).active == "tab-times"
        await pilot.press("1")
        assert app.query_one(TabbedContent).active == "tab-weights"


async def test_slider_updown_moves_focus(state, tmp_path):
    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        weight_sliders = [s for s in app.query(Slider) if (s.key or "").startswith("weight:")]
        first, second = weight_sliders[0], weight_sliders[1]
        app.set_focus(first)
        await pilot.press("down")
        assert app.focused is second  # down → next slider
        await pilot.press("up")
        assert app.focused is first  # up → previous slider
        # up at the top clamps (stays put, does not leave the group)
        await pilot.press("up")
        assert app.focused is first


async def test_copy_link_failure_surfaces_url(state, tmp_path, monkeypatch):
    notes = []
    monkeypatch.setattr("optimiser.tui.app._os_clipboard_copy", lambda text: False)
    app = OptimiserApp(state, tmp_path / "config.yaml")
    monkeypatch.setattr(app, "notify", lambda msg, **kw: notes.append(msg))
    async with app.run_test() as pilot:
        await pilot.press("c")
    assert any("nusmods.com/timetable/sem-1/share?" in n for n in notes)


async def test_warnings_show_in_timetable_mode_only(state, tmp_path, monkeypatch):
    from rich.console import Console

    monkeypatch.setattr("optimiser.tui.app.class_warnings", lambda a, c, space=None: ["⚠ SENTINEL"])
    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        warnings_text = app.query_one("#warnings-text", Static)
        console = Console()
        with console.capture() as cap:
            console.print(warnings_text._Static__content)
        assert "SENTINEL" in cap.get()  # timetable mode shows warnings
        await pilot.press("b")  # switch to ballot view
        with console.capture() as cap:
            console.print(warnings_text._Static__content)
        assert "SENTINEL" not in cap.get()  # ballot mode empties the pane


async def test_detail_shows_bids_block(state, tmp_path):
    from rich.console import Console
    from textual.widgets import Static

    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        detail = app.query_one("#detail", Static)
        console = Console()
        with console.capture() as cap:
            console.print(detail._Static__content)  # textual 8.2.8: read raw stored content
        rendered = cap.get()
        assert "Bids" in rendered  # the interchangeable-bids block is present
        # assert on ACTUAL bid content: the balloted ALPHA Tutorial slot renders
        assert "ALPHA TUT" in rendered


def _slot_labels(app):
    from textual.widgets import Label, ListView

    # textual 8.2.8's Static/Label has no public renderable; read the raw stored content
    return [str(lbl._Static__content) for lbl in app.query_one("#slot-list", ListView).query(Label)]


async def test_slot_list_lists_balloted_slots(state, tmp_path):
    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        labels = _slot_labels(app)
        # ALPHA Tutorial is a balloted slot; BETA Lecture is fixed and excluded
        assert any("ALPHA TUT" in t for t in labels)
        assert not any("LEC" in t for t in labels)


async def test_lock_slot_marks_and_reduces(state, tmp_path):
    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        before = len(app.state.top_arrangements())
        slot_list = app.query_one("#slot-list", ListView)
        app.set_focus(slot_list)
        slot_list.index = 0  # ALPHA Tutorial
        await pilot.press("l")
        assert len(app.state.top_arrangements()) < before
        assert any("🔒" in t for t in _slot_labels(app))


async def test_lock_then_unlock_restores(state, tmp_path):
    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        before = len(app.state.top_arrangements())
        slot_list = app.query_one("#slot-list", ListView)
        app.set_focus(slot_list)
        slot_list.index = 0
        await pilot.press("l")   # lock ALPHA Tutorial
        await pilot.press("l")   # unlock the same row (index 0 restored)
        assert len(app.state.top_arrangements()) == before
        assert not any("🔒" in t for t in _slot_labels(app))


async def test_all_criteria_met_shown_when_no_warnings(state, tmp_path, monkeypatch):
    from rich.console import Console

    monkeypatch.setattr("optimiser.tui.app.class_warnings", lambda a, c, space=None: [])
    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        warnings_text = app.query_one("#warnings-text", Static)
        console = Console()
        with console.capture() as cap:
            console.print(warnings_text._Static__content)
        assert "all criteria met" in cap.get()
