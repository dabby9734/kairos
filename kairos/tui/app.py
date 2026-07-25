from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from rich.console import Group
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static, TabbedContent, TabPane

from .. import ballot
from ..model import DAYS, LESSON_ABBREV, fmt_clock, fmt_time
from ..output import (
    class_warnings, render_breakdown, render_snake, share_url, snake_legend, snake_rows,
)
from .render import module_colours, render_week_rich
from .widgets import Slider


def _os_clipboard_copy(text: str) -> bool:
    """Write text to the OS clipboard via the platform's clipboard command.
    Returns True on success. Textual's copy_to_clipboard (OSC-52) is unreliable
    across terminals (e.g. macOS Terminal.app ignores it), so this is the
    primary path; OSC-52 remains a best-effort fallback for SSH sessions."""
    if sys.platform == "darwin":
        candidates = [["pbcopy"]]
    elif sys.platform.startswith("win"):
        candidates = [["clip"]]
    else:
        candidates = [
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ]
    for cmd in candidates:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode(), check=True)
                return True
            except Exception:
                continue
    return False

_WEIGHTS = ["free_days", "gaps", "lunch", "same_day_pairing", "time_window", "tough_days"]
_PREFS = [
    ("earliest_start", 360, 1200, 15),
    ("latest_end", 360, 1320, 15),
    ("lunch_start", 600, 900, 15),
    ("lunch_end", 600, 960, 15),
    ("lunch_minutes", 15, 120, 15),
    ("max_difficulty_per_day", 1, 30, 1),
]
_CLOCK_PREFS = {"earliest_start", "latest_end", "lunch_start", "lunch_end"}


def _render_bids(arrangement) -> Text:
    """A 'Bids' block listing each balloted slot's interchangeable class numbers
    (with week labels) for the selected arrangement."""
    if not arrangement.bids:
        return Text("")
    lines = ["Bids (interchangeable per slot):"]
    for bid in arrangement.bids:
        abbrev = LESSON_ABBREV.get(bid.lesson_type, bid.lesson_type)
        opts = " / ".join(
            f"{class_no} ({label})" if label else class_no
            for class_no, label in bid.options
        )
        lines.append(f"  {bid.module} {abbrev}  →  {opts}")
    return Text("\n".join(lines), style="dim")


def _fmt_timeslot(row: dict) -> str:
    """Label one offered_timeslots row. Day/time alone is not enough: a class can
    be offered physically and online at the same day/time (e.g. CS1231S lecture 1
    @UT-AUD1 vs 2 @E-Learn_C), which day/time alone cannot show — the `~` online
    marker (reused from tui.render) and the venue segment each distinguish it,
    since Session.online is derived from the venue string (model.py:63-65), so an
    online class always carries an E-Learn* venue. slot_sig deliberately ignores
    venue, so classes differing only by venue collapse into a single row here —
    the venue segment lists every venue used by the row's classes, not just the
    representative's."""
    sessions = row["sessions"]
    times = ", ".join(
        f"{s.day[:3]} {fmt_time(s.start)}-{fmt_time(s.end)}"
        for s in sorted(sessions, key=lambda s: (DAYS.index(s.day), s.start))
    )
    mark = "~" if any(s.online for s in sessions) else " "
    return f"{mark}{times}  @{'/'.join(row['venues'])}"


class KairosApp(App):
    CSS = """
    #controls { width: 42; }
    #results { width: 1fr; }
    #top-row { height: 20%; }
    #tt-list { width: 45%; border: round $panel; border-title-color: $text; }
    #warnings { width: 1fr; border: round $panel; border-title-color: $text; }
    /* Pair the theme's legible warning/success text with an opaque theme
       surface, so contrast holds whether the app paints its own (dark) surface
       or the terminal's background (which may be light) shows through a
       transparent widget. A foreground colour alone is not enough: $text-warning
       resolves against the active theme, so on a dark theme it is a light amber
       that vanishes on a light terminal. */
    #warnings-text.warn { background: $surface; color: $text-warning; }
    #warnings-text.ok { background: $surface; color: $text-success; }
    #classes-row { height: 20%; }
    #slot-list { width: 45%; border: round $panel; border-title-color: $text; }
    #timeslot-list { width: 1fr; border: round $panel; border-title-color: $text; }
    #detail-scroll { height: 1fr; }
    #ballot-view { height: 1fr; }
    /* auto so a Saturday row or an extra overlap lane is never clipped;
       max-height so a busy week can't crowd out the list below it. */
    #ballot-grid { height: auto; max-height: 50%; }
    #ballot-legend { height: auto; background: $surface; color: $text-muted; }
    #ballot-list { height: 1fr; }
    #ballot-list ListItem { height: auto; }
    """

    BINDINGS = [
        ("1", "show_tab('tab-weights')", "Weights"),
        ("2", "show_tab('tab-diff')", "Difficulty"),
        ("3", "show_tab('tab-times')", "Times"),
        ("4", "show_tab('tab-priority')", "Priority"),
        ("s", "save_config", "save config"),
        ("e", "export_ballot", "export ballot"),
        ("c", "copy_link", "copy link"),
        ("b", "toggle_ballot", "ballot view"),
        ("l", "toggle_lock", "lock slot"),
        ("a", "toggle_accept", "accept slot"),
        ("right", "focus_timeslots", "timeslots"),
        ("left", "focus_classes", "classes"),
        ("escape", "focus_classes", "back"),
        ("[", "move_priority_up", "priority up"),
        ("]", "move_priority_down", "priority down"),
        ("q", "quit", "quit"),
    ]

    def __init__(self, state, config_path: Path) -> None:
        super().__init__()
        self.state = state
        self.config_path = Path(config_path)
        self.selected = 0
        self.ballot_mode = False
        self._timeslots = []
        self._rows = []
        self._ballot_entries = []
        self._current_class = None
        self.colours = module_colours(list(state.config.modules))

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="controls"):
                with TabbedContent():
                    with TabPane("Weights", id="tab-weights"):
                        with VerticalScroll():
                            for name in _WEIGHTS:
                                yield Slider(
                                    name, 0, 10,
                                    int(self.state.config.preferences.weights.get(name, 0)),
                                    key=f"weight:{name}",
                                )
                    with TabPane("Difficulty", id="tab-diff"):
                        with VerticalScroll():
                            for module in self.state.config.modules:
                                for abbrev, value in self.state.config.modules[module].items():
                                    yield Slider(
                                        f"{module} {abbrev}", 1, 5, int(value),
                                        key=f"diff:{module}:{abbrev}",
                                    )
                    with TabPane("Times", id="tab-times"):
                        with VerticalScroll():
                            for name, lo, hi, step in _PREFS:
                                fmt = fmt_clock if name in _CLOCK_PREFS else str
                                yield Slider(
                                    name, lo, hi,
                                    int(getattr(self.state.config.preferences, name)),
                                    step=step, key=f"pref:{name}", fmt=fmt,
                                )
                    with TabPane("Priority", id="tab-priority"):
                        yield ListView(
                            *[ListItem(Label(m), id=f"prio-{m}") for m in self.state.config.priority],
                            id="priority-list",
                        )
            with Vertical(id="results"):
                with Horizontal(id="top-row"):
                    tt_list = ListView(id="tt-list")
                    tt_list.border_title = "Timetables"
                    yield tt_list
                    warnings = VerticalScroll(Static(id="warnings-text"), id="warnings")
                    warnings.border_title = "Warnings"
                    yield warnings
                with Horizontal(id="classes-row"):
                    slot_list = ListView(id="slot-list")
                    slot_list.border_title = "Classes"
                    yield slot_list
                    timeslot_list = ListView(id="timeslot-list")
                    timeslot_list.border_title = "Timeslots"
                    yield timeslot_list
                with VerticalScroll(id="detail-scroll"):
                    yield Static(id="detail")
                # Sibling of #detail-scroll, not a child: ballot view swaps which
                # container is displayed rather than swapping content into one
                # Static, because the ballot list needs to be a focusable ListView.
                ballot_view = Vertical(
                    Static(id="ballot-grid"),
                    Static(id="ballot-legend"),
                    ListView(id="ballot-list"),
                    id="ballot-view",
                )
                ballot_view.display = False
                yield ballot_view
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_results()

    # --- rendering ---

    def _refresh_results(self) -> None:
        tt_list = self.query_one("#tt-list", ListView)
        top = self.state.top_arrangements()
        with self.prevent(ListView.Highlighted):
            tt_list.clear()
            for i, arr in enumerate(top):
                variants = f"  ({arr.variant_count} variants)" if arr.variant_count > 1 else ""
                tt_list.append(ListItem(Label(f"#{i + 1}  {arr.score:+.1f}{variants}")))
            if self.selected >= len(top):
                self.selected = 0
            if top:
                tt_list.index = min(self.selected, len(top) - 1)
        self._refresh_slots()
        self._populate_timeslots()
        self._refresh_detail()

    def _refresh_slots(self) -> None:
        slot_list = self.query_one("#slot-list", ListView)
        prev = slot_list.index
        with self.prevent(ListView.Highlighted):
            slot_list.clear()
            self._rows = []
            top = self.state.top_arrangements()
            if top:
                self._rows = self.state.selectable_groups(top[self.selected].assignment)
                for row in self._rows:
                    lock = "🔒 " if row.locked else ""
                    tag = "  ·ballot" if row.balloted else ""
                    slot_list.append(ListItem(Label(
                        f"{lock}{row.module} {row.abbrev} → {row.current_class_no}{tag}"
                    )))
            if slot_list.children and prev is not None:
                slot_list.index = min(prev, len(slot_list.children) - 1)

    def _populate_timeslots(self) -> None:
        tlist = self.query_one("#timeslot-list", ListView)
        slot_list = self.query_one("#slot-list", ListView)
        self._timeslots = []
        self._current_class = None
        with self.prevent(ListView.Highlighted):
            tlist.clear()
            tlist.border_title = "Timeslots"
            if slot_list.index is not None and 0 <= slot_list.index < len(self._rows):
                row = self._rows[slot_list.index]
                self._current_class = (row.module, row.lesson_type)
                tlist.border_title = f"Timeslots: {row.module} {row.abbrev}"
                self._timeslots = self.state.offered_timeslots(row.module, row.lesson_type)
                locked = self.state.locked_sig(row.module, row.lesson_type)
                accepted = self.state.accepted_sigs(row.module, row.lesson_type)
                locked_idx = 0
                for i, slot in enumerate(self._timeslots):
                    if slot["sig"] == locked:
                        mark = "🔒 "
                    elif accepted is not None and slot["sig"] not in accepted:
                        mark = "✗ "
                    else:
                        mark = ""
                    label = f"{mark}{_fmt_timeslot(slot)} ({'/'.join(slot['class_nos'])})"
                    tlist.append(ListItem(Label(label)))
                    if slot["sig"] == locked:
                        locked_idx = i
                if self._timeslots:
                    tlist.index = locked_idx

    def _refresh_detail(self) -> None:
        detail = self.query_one("#detail", Static)
        warnings_text = self.query_one("#warnings-text", Static)
        top = self.state.top_arrangements()
        if not top:
            detail.update("no clash-free timetables")
            warnings_text.set_classes([])
            warnings_text.update("")
            return
        if self.ballot_mode:
            self._refresh_ballot_list()
            self._refresh_ballot_grid()
            warnings_text.set_classes([])
            warnings_text.update("")
            return
        arr = top[self.selected]
        preview = None
        tlist = self.query_one("#timeslot-list", ListView)
        if (tlist.has_focus and tlist.index is not None and self._current_class
                and 0 <= tlist.index < len(self._timeslots)):
            module, lesson_type = self._current_class
            preview = (module, lesson_type, self._timeslots[tlist.index]["sig"])
        warnings = class_warnings(
            arr.assignment, self.state.config,
            unpairable_slots=self.state.unpairable_slots,
        )
        if warnings:
            warnings_text.set_classes("warn")
            warnings_text.update(Text("\n".join(warnings)))
        else:
            warnings_text.set_classes("ok")
            warnings_text.update(Text("✓ all criteria met"))
        detail.update(
            Group(
                Text(render_breakdown(arr.score, arr.breakdown)),
                Text(""),
                render_week_rich(arr.assignment, self.colours, preview=preview),
                Text(""),
                _render_bids(arr),
                Text(""),
                Text(share_url(arr.assignment, self.state.config.semester)),
            )
        )

    def _ballot_preview(self, entry) -> tuple:
        """The (module, lesson_type, sig) triple render_week_rich highlights for
        a ballot entry. Built from the entry's sessions with exactly the fields
        Choice.slot_sig uses (model.py), so it is comparable to the sigs the
        renderer matches assignment choices against."""
        return (
            entry.module,
            entry.lesson_type,
            frozenset((s.day, s.start, s.end, s.online) for s in entry.sessions),
        )

    def _refresh_ballot_list(self) -> None:
        """Rebuild the ballot list. Called when the entries or their membership
        markers can change (config edits, arrangement selection, priority
        reorder) -- never on cursor movement, which would reset the index."""
        lst = self.query_one("#ballot-list", ListView)
        legend = self.query_one("#ballot-legend", Static)
        prev = lst.index
        self._ballot_entries = self.state.ballot_snake()
        highlight = frozenset()
        # provenance is always set by the time the ballot view can be shown:
        # _refresh_detail only reaches this method when top_arrangements() is
        # non-empty, and _rank_from assigns provenance in the same pass that
        # produces those arrangements.
        if self.selected < len(self.state.provenance.by_arrangement):
            highlight = self.state.provenance.by_arrangement[self.selected]
        with self.prevent(ListView.Highlighted):
            lst.clear()
            if not self._ballot_entries:
                legend.update("")
                return
            legend.update(Text("\n".join(snake_legend(self.state.provenance))))
            for entry, line, continuation in snake_rows(
                self._ballot_entries, self.state.provenance
            ):
                keys = {
                    (entry.module, entry.lesson_type, class_no)
                    for class_no in [entry.class_no, *entry.tied_with]
                }
                # A gutter marker, not reverse video: the ListView cursor is
                # itself an inversion, so membership needs a separate channel.
                mark = "●" if keys & highlight else " "
                text = f"{mark} {line}"
                if continuation is not None:
                    text += f"\n  {continuation}"
                lst.append(ListItem(Label(text)))
            lst.index = min(prev or 0, len(self._ballot_entries) - 1)

    def _refresh_ballot_grid(self) -> None:
        """Redraw the pinned grid with the cursor row's slot previewed on the
        selected timetable. Called on every ballot-list cursor move."""
        grid = self.query_one("#ballot-grid", Static)
        top = self.state.top_arrangements()
        if not top:
            grid.update(Text("no clash-free timetables"))
            return
        lst = self.query_one("#ballot-list", ListView)
        preview = None
        if lst.index is not None and 0 <= lst.index < len(self._ballot_entries):
            preview = self._ballot_preview(self._ballot_entries[lst.index])
        grid.update(
            render_week_rich(
                top[self.selected].assignment, self.colours,
                preview=preview, agenda=False,
            )
        )

    # --- events ---

    def on_slider_changed(self, event: Slider.Changed) -> None:
        key = event.slider.key or ""
        kind, _, rest = key.partition(":")
        if kind == "weight":
            self.state.set_weight(rest, event.value)
        elif kind == "pref":
            self.state.set_pref(rest, event.value)
        elif kind == "diff":
            module, abbrev = rest.split(":", 1)
            self.state.set_difficulty(module, abbrev, event.value)
        self._refresh_results()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        lv = event.list_view
        if lv.id == "tt-list" and lv.index is not None:
            self.selected = lv.index
            self._refresh_slots()
            self._populate_timeslots()
            self._refresh_detail()
        elif lv.id == "slot-list":
            self._populate_timeslots()
            self._refresh_detail()
        elif lv.id == "timeslot-list":
            self._refresh_detail()
        elif lv.id == "ballot-list":
            self._refresh_ballot_grid()

    # --- actions ---

    def action_toggle_ballot(self) -> None:
        self.ballot_mode = not self.ballot_mode
        self.query_one("#detail-scroll").display = not self.ballot_mode
        self.query_one("#ballot-view").display = self.ballot_mode
        if self.ballot_mode:
            self._refresh_detail()
            self.query_one("#ballot-list", ListView).focus()
        else:
            self.query_one("#slot-list", ListView).focus()
            self._refresh_detail()

    def action_focus_timeslots(self) -> None:
        if self.ballot_mode:
            return  # ballot list has no sibling pane to move to; stay put
        self.query_one("#timeslot-list", ListView).focus()
        self._refresh_detail()

    def action_focus_classes(self) -> None:
        # Only leave ballot view when the ballot list itself has focus, so a
        # stray escape/← doesn't blow away the view from some other widget.
        if self.ballot_mode:
            if self.query_one("#ballot-list", ListView).has_focus:
                self.action_toggle_ballot()   # Esc/← leaves ballot view
            return
        self.query_one("#slot-list", ListView).focus()
        self._refresh_detail()

    def action_toggle_lock(self) -> None:
        tlist = self.query_one("#timeslot-list", ListView)
        if (self._current_class is None or tlist.index is None
                or not (0 <= tlist.index < len(self._timeslots))):
            return
        module, lesson_type = self._current_class
        abbrev = LESSON_ABBREV.get(lesson_type, lesson_type)
        row = self._timeslots[tlist.index]
        if self.state.locked_sig(module, lesson_type) == row["sig"]:
            ok = self.state.clear_lock(module, abbrev)
        else:
            ok = self.state.set_lock(module, abbrev, row["rep"])
        if not ok:
            self.notify(f"locking {module} {abbrev} leaves no clash-free timetable")
            return
        self._refresh_results()

    def action_toggle_accept(self) -> None:
        tlist = self.query_one("#timeslot-list", ListView)
        if (self._current_class is None or tlist.index is None
                or not (0 <= tlist.index < len(self._timeslots))):
            return
        module, lesson_type = self._current_class
        abbrev = LESSON_ABBREV.get(lesson_type, lesson_type)
        row = self._timeslots[tlist.index]
        if not self.state.toggle_accept(module, abbrev, lesson_type, row["rep"]):
            self.notify(f"rejecting {module} {abbrev} at that slot leaves no clash-free timetable")
            return
        self._refresh_results()

    def action_save_config(self) -> None:
        self.config_path.write_text(yaml.safe_dump(self.state.to_config_yaml(), sort_keys=False))
        self.notify(f"saved {self.config_path}")

    def action_export_ballot(self) -> None:
        out = self.config_path.parent / "ballot.txt"
        entries = self.state.ballot_snake()
        out.write_text(render_snake(entries, provenance=self.state.provenance))
        missing = ballot.shortfall(entries)
        if missing:
            self.notify(
                f"wrote {out} — only {len(entries)} of {ballot.BALLOT_CAP} ballot slots "
                "used (no further clash-free options, or narrowed by your accepted slots)",
                severity="warning",
            )
        else:
            self.notify(f"wrote {out}")

    def action_show_tab(self, tab_id: str) -> None:
        tabs = self.query_one(TabbedContent)
        tabs.active = tab_id
        pane = self.query_one(f"#{tab_id}")
        focusable = next(iter(pane.query("Slider, ListView")), None)
        if focusable is not None:
            focusable.focus()

    def action_copy_link(self) -> None:
        top = self.state.top_arrangements()
        if not top:
            return
        url = share_url(top[self.selected].assignment, self.state.config.semester)
        self.copy_to_clipboard(url)  # OSC-52 best-effort (SSH / capable terminals)
        if _os_clipboard_copy(url):
            self.notify("copied share link to clipboard")
        else:
            self.notify(f"copy unavailable — link: {url}", timeout=15)

    def action_move_priority_up(self) -> None:
        self._move_priority(-1)

    def action_move_priority_down(self) -> None:
        self._move_priority(1)

    def _move_priority(self, delta: int) -> None:
        lst = self.query_one("#priority-list", ListView)
        if lst.index is None:
            return
        module = self.state.config.priority[lst.index]
        self.state.move_priority(module, delta)
        with self.prevent(ListView.Highlighted):
            lst.clear()
            for m in self.state.config.priority:
                lst.append(ListItem(Label(m)))
            lst.index = self.state.config.priority.index(module)  # highlight follows the moved module
        if self.ballot_mode:
            self._refresh_detail()


def run_app(state, config_path: Path) -> None:
    KairosApp(state, config_path).run()
