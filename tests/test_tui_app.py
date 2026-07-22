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


@pytest.fixture
def gamma_state(alpha_json, gamma_json, config):
    groups = build_groups("ALPHA", semester_timetable(alpha_json, 1)) + build_groups(
        "GAMMA", semester_timetable(gamma_json, 1)
    )
    cfg = copy.deepcopy(config)
    cfg.fixed = {}
    cfg.modules = {"ALPHA": {"LEC": 2, "TUT": 4}, "GAMMA": 3}
    cfg.priority = ["ALPHA", "GAMMA"]
    return AppState.from_parts(cfg, groups)


def test_fmt_timeslot_distinguishes_physical_from_online(gamma_state):
    from kairos.tui.app import _fmt_timeslot

    rows = gamma_state.offered_timeslots("GAMMA", "Lecture")
    assert len(rows) == 2  # same times, different online-ness -> distinct sigs
    labels = [_fmt_timeslot(row) for row in rows]
    assert labels[0] != labels[1]          # the whole point
    assert any("E-Learn_C" in lb for lb in labels)
    assert any(lb.startswith("~") for lb in labels)  # online marker


async def test_lecture_row_appears_and_locks(state, tmp_path):
    state.config.fixed = {}
    state._rebuild()
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        slot_list = app.query_one("#slot-list", ListView)
        keys = [(r.module, r.abbrev) for r in app._rows]
        assert ("BETA", "LEC") in keys  # lecture is now a row

        slot_list.index = keys.index(("BETA", "LEC"))
        app.set_focus(slot_list)
        await pilot.pause()
        tlist = app.query_one("#timeslot-list", ListView)
        assert len(app._timeslots) == 2  # both lecture slots offered

        app.set_focus(tlist)
        tlist.index = 1
        await pilot.press("l")
        await pilot.pause()
        assert app.state.is_locked("BETA", "LEC")


async def test_locked_lecture_never_enters_ballot(state, tmp_path):
    state.config.fixed = {}
    state._rebuild()
    assert state.set_lock("BETA", "LEC", "2")
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test():
        for arr in app.state.top_arrangements():
            assert all(b.lesson_type != "Lecture" for b in arr.bids)
        assert all(e.lesson_type != "Lecture" for e in app.state.ballot_snake())


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


def _ballot_entries(n):
    from kairos.ballot import BallotOption
    from kairos.model import Session

    sess = Session("Monday", 600, 660, frozenset(range(1, 14)), "COM1")
    return [
        BallotOption("ALPHA", "Tutorial", f"{i:02d}", chr(ord("A") + i), 0.0, (sess,), [])
        for i in range(n)
    ]


async def test_export_ballot_shortfall_warns(state, tmp_path, monkeypatch):
    app = KairosApp(state, tmp_path / "config.yaml")
    monkeypatch.setattr(app.state, "ballot_snake", lambda: _ballot_entries(5))
    notes, kwargs = [], []
    monkeypatch.setattr(app, "notify", lambda msg, **kw: (notes.append(msg), kwargs.append(kw)))
    async with app.run_test() as pilot:
        await pilot.press("e")
    out = tmp_path / "ballot.txt"
    assert out.exists()  # the file is still written even though the ballot fell short
    assert any("only 5 of 20 ballot slots used" in n for n in notes)
    assert kwargs[-1].get("severity") == "warning"


async def test_export_ballot_full_notifies_without_warning(state, tmp_path, monkeypatch):
    app = KairosApp(state, tmp_path / "config.yaml")
    monkeypatch.setattr(app.state, "ballot_snake", lambda: _ballot_entries(20))
    notes, kwargs = [], []
    monkeypatch.setattr(app, "notify", lambda msg, **kw: (notes.append(msg), kwargs.append(kw)))
    async with app.run_test() as pilot:
        await pilot.press("e")
    out = tmp_path / "ballot.txt"
    assert notes == [f"wrote {out}"]  # plain notify, no shortfall wording
    assert kwargs == [{}]  # no severity kwarg on the full-ballot branch


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

    monkeypatch.setattr("kairos.tui.app.class_warnings", lambda a, c, space=None, unpairable_slots=None: ["⚠ SENTINEL"])
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


async def test_slot_list_lists_every_multi_slot_group(state, tmp_path):
    # The default config fixture pins BETA LEC via `fixed`, which now excludes it
    # from the pane (Finding 1) — clear it so this test exercises the unfixed,
    # genuinely selectable case it's meant to cover.
    state.config.fixed = {}
    state._rebuild()
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        labels = _slot_labels(app)
        # balloted groups are listed and tagged as such
        assert any("ALPHA TUT" in t and "·ballot" in t for t in labels)
        # BETA Lecture offers two classes, so it is selectable even though it is
        # not balloted — this is the row that did not exist before
        assert any("BETA LEC" in t and "·ballot" not in t for t in labels)
        # ALPHA Lecture offers exactly one class: nothing to choose, so no row
        assert not any("ALPHA LEC" in t for t in labels)


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

    monkeypatch.setattr("kairos.tui.app.class_warnings", lambda a, c, space=None, unpairable_slots=None: [])
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
        # two offered timeslots: Mon 14:00 (01) and Tue 09:00 (02/03). 02 and 03
        # share a slot_sig (slot_sig ignores venue) so they collapse into one row;
        # that row lists every distinct venue its classes use, not just one.
        # (fmt_time renders "1400", not "14:00" — matches the rest of the codebase,
        # e.g. tests/test_output.py's "Mon 1400-1500" for this same fixture)
        assert any("Mon 1400-1500  @COM1-0201 (01)" in t for t in labels)
        assert any("Tue 0900-1000  @COM1-0201/COM1-0202 (02/03)" in t for t in labels)
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


async def test_default_timeslot_cursor_flashes_not_previews(state, tmp_path):
    # _populate_timeslots seeds the Timeslots cursor onto the class's own
    # locked/current slot_sig (see state.py). That's exactly the case flash
    # mode exists for: highlighting the slot the class already occupies must
    # blink it in place rather than draw a redundant "(preview)" bar. This
    # pins that default-cursor path end-to-end, since the neighbouring
    # test_browsing_timeslot_shows_blinking_preview only exercises preview
    # mode (it moves the cursor to index 1).
    from rich.console import Console

    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        app.query_one("#slot-list", ListView).index = 0
        app._populate_timeslots()
        app.query_one("#timeslot-list", ListView).focus()
        await pilot.pause()
        app._refresh_detail()
        await pilot.pause()
        console = Console()
        with console.capture() as cap:
            console.print(app.query_one("#detail", Static)._Static__content)
        # If flash mode stopped firing (e.g. the slot_sig comparison in
        # render.py broke), this default-position highlight would fall back
        # to preview mode instead, injecting a "(preview)" agenda line.
        assert "(preview)" not in cap.get()


async def test_week_grid_gets_more_height_than_the_top_row(state, tmp_path):
    app = KairosApp(state, tmp_path / "config.yaml")
    # Size is pinned: the assertion compares integer row counts, so it must not
    # depend on the harness default. At 100x30 the results column is 28 rows —
    # before: top=8 classes=4 detail=16; after: top=5 classes=5 detail=18.
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        top_row = app.query_one("#top-row")
        detail = app.query_one("#detail-scroll")
        # timetables + warnings shrank; the week grid absorbs the remainder
        assert detail.size.height >= 3 * top_row.size.height
