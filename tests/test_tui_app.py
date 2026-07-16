import copy

import pytest
from textual.widgets import ListView, Static

from kairos.api import build_groups, semester_timetable
from kairos.tui.app import KairosApp
from kairos.tui.state import AppState
from kairos.tui.widgets import Slider


@pytest.fixture
def state(alpha_json, beta_json, config):
    groups = build_groups("ALPHA", semester_timetable(alpha_json, 1)) + build_groups(
        "BETA", semester_timetable(beta_json, 1)
    )
    return AppState.from_parts(copy.deepcopy(config), groups)


async def test_slider_adjust_reranks(state, tmp_path):
    app = KairosApp(state, tmp_path / "config.yaml")
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
    app = KairosApp(state, tmp_path / "config.yaml")
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


async def test_move_priority_emits_no_highlighted_events(state, tmp_path, monkeypatch):
    # Rebuilding #priority-list must not post ListView.Highlighted (re-entrancy
    # guard, same invariant as the other list rebuilds — see commit 2fec8c5).
    seen = []
    original = KairosApp.on_list_view_highlighted

    def spy(self, event):
        seen.append(event.list_view.id)
        return original(self, event)

    monkeypatch.setattr(KairosApp, "on_list_view_highlighted", spy)
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        lst = app.query_one("#priority-list", ListView)
        app.set_focus(lst)
        lst.index = len(app.state.config.priority) - 1
        await pilot.pause()
        before = seen.count("priority-list")   # mount/focus events are allowed
        await pilot.press("[")                  # move up -> rebuilds the list
        await pilot.pause()
        assert seen.count("priority-list") == before  # rebuild emitted none


async def test_toggle_ballot_view(state, tmp_path):
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        assert app.ballot_mode is False
        await pilot.press("b")
        assert app.ballot_mode is True
        await pilot.press("b")
        assert app.ballot_mode is False


async def test_save_config_writes_file(state, tmp_path):
    path = tmp_path / "config.yaml"
    app = KairosApp(state, path)
    async with app.run_test() as pilot:
        await pilot.press("s")
    assert path.exists()  # config written
    import yaml

    assert yaml.safe_load(path.read_text())["semester"] == state.config.semester


async def test_copy_link_uses_os_clipboard(state, tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "kairos.tui.app._os_clipboard_copy",
        lambda text: captured.setdefault("url", text) or True,
    )
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        await pilot.press("c")
    assert "url" in captured
    assert captured["url"].startswith("https://nusmods.com/timetable/sem-1/share?")


async def test_number_key_switches_tab(state, tmp_path):
    from textual.widgets import TabbedContent

    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        await pilot.press("3")
        assert app.query_one(TabbedContent).active == "tab-times"
        await pilot.press("1")
        assert app.query_one(TabbedContent).active == "tab-weights"


async def test_slider_updown_moves_focus(state, tmp_path):
    app = KairosApp(state, tmp_path / "config.yaml")
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
    monkeypatch.setattr("kairos.tui.app._os_clipboard_copy", lambda text: False)
    app = KairosApp(state, tmp_path / "config.yaml")
    monkeypatch.setattr(app, "notify", lambda msg, **kw: notes.append(msg))
    async with app.run_test() as pilot:
        await pilot.press("c")
    assert any("nusmods.com/timetable/sem-1/share?" in n for n in notes)


async def test_warnings_show_in_timetable_mode_only(state, tmp_path, monkeypatch):
    from rich.console import Console

    monkeypatch.setattr("kairos.tui.app.class_warnings", lambda a, c, space=None: ["⚠ SENTINEL"])
    app = KairosApp(state, tmp_path / "config.yaml")
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

    app = KairosApp(state, tmp_path / "config.yaml")
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
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        labels = _slot_labels(app)
        # ALPHA Tutorial is a balloted slot; BETA Lecture is fixed and excluded
        assert any("ALPHA TUT" in t for t in labels)
        assert not any("LEC" in t for t in labels)


async def test_lock_timeslot_marks_and_reduces(state, tmp_path):
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        before = len(app.state.top_arrangements())
        slot_list = app.query_one("#slot-list", ListView)
        app.set_focus(slot_list)
        slot_list.index = 0                 # ALPHA Tutorial
        await pilot.pause()
        await pilot.press("right")          # into Timeslots
        app.query_one("#timeslot-list", ListView).index = 0  # Mon 14:00 (01)
        await pilot.pause()
        await pilot.press("l")              # lock that timeslot
        assert len(app.state.top_arrangements()) < before
        assert any("🔒" in t for t in _timeslot_labels(app))


async def test_lock_then_unlock_timeslot_restores(state, tmp_path):
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        before = len(app.state.top_arrangements())
        slot_list = app.query_one("#slot-list", ListView)
        app.set_focus(slot_list)
        slot_list.index = 0
        await pilot.pause()
        await pilot.press("right")
        app.query_one("#timeslot-list", ListView).index = 0
        await pilot.pause()
        await pilot.press("l")              # lock
        await pilot.press("l")              # unlock the same (now-locked) timeslot
        assert len(app.state.top_arrangements()) == before
        assert not any("🔒" in t for t in _timeslot_labels(app))


async def test_all_criteria_met_shown_when_no_warnings(state, tmp_path, monkeypatch):
    from rich.console import Console

    monkeypatch.setattr("kairos.tui.app.class_warnings", lambda a, c, space=None: [])
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        warnings_text = app.query_one("#warnings-text", Static)
        console = Console()
        with console.capture() as cap:
            console.print(warnings_text._Static__content)
        assert "all criteria met" in cap.get()


def _timeslot_labels(app):
    from textual.widgets import Label, ListView

    return [str(lbl._Static__content) for lbl in app.query_one("#timeslot-list", ListView).query(Label)]


async def test_timeslots_populate_from_highlighted_class(state, tmp_path):
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        slot_list = app.query_one("#slot-list", ListView)
        app.set_focus(slot_list)
        slot_list.index = 0  # ALPHA Tutorial
        await pilot.pause()
        labels = _timeslot_labels(app)
        # two offered timeslots: Mon 14:00 (01) and Tue 09:00 (02/03)
        # (fmt_time renders "1400", not "14:00" — matches the rest of the codebase,
        # e.g. tests/test_output.py's "Mon 1400-1500" for this same fixture)
        assert any("Mon 1400-1500 (01)" in t for t in labels)
        assert any("Tue 0900-1000 (02/03)" in t for t in labels)
        assert "ALPHA TUT" in str(app.query_one("#timeslot-list", ListView).border_title)


async def test_browsing_timeslot_shows_blinking_preview(state, tmp_path):
    from rich.console import Console

    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        slot_list = app.query_one("#slot-list", ListView)
        app.set_focus(slot_list)
        slot_list.index = 0
        await pilot.pause()
        await pilot.press("right")          # focus the Timeslots pane
        tl = app.query_one("#timeslot-list", ListView)
        assert tl.has_focus
        tl.index = 1                         # highlight the Tue 09:00 candidate
        await pilot.pause()
        console = Console()
        with console.capture() as cap:
            console.print(app.query_one("#detail", Static)._Static__content)
        assert "(preview)" in cap.get()      # candidate rendered as a preview bar
