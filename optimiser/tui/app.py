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

from ..model import LESSON_ABBREV
from ..output import class_warnings, render_breakdown, render_snake, share_url
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


def _fmt_clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


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


class OptimiserApp(App):
    CSS = """
    #controls { width: 42; }
    #results { width: 1fr; }
    #top-row { height: 30%; }
    #tt-list { width: 45%; border: round $panel; border-title-color: $text; }
    #warnings { width: 1fr; border: round $panel; border-title-color: $text; }
    #slot-list { height: 15%; border: round $panel; border-title-color: $text; }
    #detail-scroll { height: 1fr; }
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
                                fmt = _fmt_clock if name in _CLOCK_PREFS else str
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
                slot_list = ListView(id="slot-list")
                slot_list.border_title = "Classes"
                yield slot_list
                with VerticalScroll(id="detail-scroll"):
                    yield Static(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_results()

    # --- rendering ---

    def _refresh_results(self) -> None:
        tt_list = self.query_one("#tt-list", ListView)
        tt_list.clear()
        top = self.state.top_arrangements()
        for i, arr in enumerate(top):
            variants = f"  ({arr.variant_count} variants)" if arr.variant_count > 1 else ""
            tt_list.append(ListItem(Label(f"#{i + 1}  {arr.score:+.1f}{variants}")))
        if self.selected >= len(top):
            self.selected = 0
        if top:
            tt_list.index = min(self.selected, len(top) - 1)
        self._refresh_detail()

    def _refresh_slots(self) -> None:
        slot_list = self.query_one("#slot-list", ListView)
        prev = slot_list.index
        slot_list.clear()
        top = self.state.top_arrangements()
        if top:
            arr = top[self.selected]
            for bid in arr.bids:
                abbrev = LESSON_ABBREV.get(bid.lesson_type, bid.lesson_type)
                class_no = arr.assignment[(bid.module, bid.lesson_type)].class_no
                lock = "🔒 " if self.state.is_locked(bid.module, abbrev) else ""
                slot_list.append(ListItem(Label(f"{lock}{bid.module} {abbrev} → {class_no}")))
        if slot_list.children and prev is not None:
            slot_list.index = min(prev, len(slot_list.children) - 1)

    def _refresh_detail(self) -> None:
        self._refresh_slots()
        detail = self.query_one("#detail", Static)
        warnings_text = self.query_one("#warnings-text", Static)
        top = self.state.top_arrangements()
        if not top:
            detail.update("no clash-free timetables")
            warnings_text.update("")
            return
        if self.ballot_mode:
            detail.update(render_snake(self.state.ballot_snake()))
            warnings_text.update("")
            return
        arr = top[self.selected]
        warnings = class_warnings(arr.assignment, self.state.config, space=self.state.space)
        if warnings:
            warnings_text.update(Text("\n".join(warnings), style="dim yellow"))
        else:
            warnings_text.update(Text("✓ all criteria met", style="dim green"))
        detail.update(
            Group(
                Text(render_breakdown(arr.score, arr.breakdown)),
                Text(""),
                render_week_rich(arr.assignment, self.colours),
                Text(""),
                _render_bids(arr),
                Text(""),
                Text(share_url(arr.assignment, self.state.config.semester)),
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
        if event.list_view.id == "tt-list" and event.list_view.index is not None:
            self.selected = event.list_view.index
            self._refresh_detail()

    # --- actions ---

    def action_toggle_ballot(self) -> None:
        self.ballot_mode = not self.ballot_mode
        self._refresh_detail()

    def action_toggle_lock(self) -> None:
        slot_list = self.query_one("#slot-list", ListView)
        top = self.state.top_arrangements()
        if slot_list.index is None or not top:
            return
        arr = top[self.selected]
        if slot_list.index >= len(arr.bids):
            return
        bid = arr.bids[slot_list.index]
        abbrev = LESSON_ABBREV.get(bid.lesson_type, bid.lesson_type)
        if self.state.is_locked(bid.module, abbrev):
            ok = self.state.clear_lock(bid.module, abbrev)
        else:
            class_no = arr.assignment[(bid.module, bid.lesson_type)].class_no
            ok = self.state.set_lock(bid.module, abbrev, class_no)
        if not ok:
            self.notify(f"locking {bid.module} {abbrev} leaves no clash-free timetable")
            return
        self._refresh_results()

    def action_save_config(self) -> None:
        self.config_path.write_text(yaml.safe_dump(self.state.to_config_yaml(), sort_keys=False))
        self.notify(f"saved {self.config_path}")

    def action_export_ballot(self) -> None:
        out = self.config_path.parent / "ballot.txt"
        out.write_text(render_snake(self.state.ballot_snake()))
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
        lst.clear()
        for m in self.state.config.priority:
            lst.append(ListItem(Label(m)))
        lst.index = self.state.config.priority.index(module)  # highlight follows the moved module
        if self.ballot_mode:
            self._refresh_detail()


def run_app(state, config_path: Path) -> None:
    OptimiserApp(state, config_path).run()
