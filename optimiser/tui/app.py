from __future__ import annotations

from pathlib import Path

import yaml
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static, TabbedContent, TabPane

from ..model import LESSON_ABBREV
from ..output import render_breakdown, render_snake, render_week, share_url
from .widgets import Slider

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


class OptimiserApp(App):
    CSS = """
    #controls { width: 42; }
    #results { width: 1fr; }
    #tt-list { height: 40%; }
    #detail { height: 1fr; }
    """

    BINDINGS = [
        ("s", "save_config", "save config"),
        ("e", "export_ballot", "export ballot"),
        ("c", "copy_link", "copy link"),
        ("b", "toggle_ballot", "ballot view"),
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
                yield ListView(id="tt-list")
                yield Static(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_results()

    # --- rendering ---

    def _refresh_results(self) -> None:
        tt_list = self.query_one("#tt-list", ListView)
        tt_list.clear()
        top = self.state.top_timetables()
        for i, (total, _, _) in enumerate(top):
            tt_list.append(ListItem(Label(f"#{i + 1}  {total:+.1f}")))
        if self.selected >= len(top):
            self.selected = 0
        self._refresh_detail()

    def _refresh_detail(self) -> None:
        detail = self.query_one("#detail", Static)
        top = self.state.top_timetables()
        if not top:
            detail.update("no clash-free timetables")
            return
        if self.ballot_mode:
            detail.update(render_snake(self.state.ballot_snake()))
            return
        total, breakdown, assignment = top[self.selected]
        detail.update(
            render_breakdown(total, breakdown)
            + "\n\n"
            + render_week(assignment)
            + "\n\n"
            + share_url(assignment, self.state.config.semester)
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
            module, abbrev = rest.split(":")
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

    def action_save_config(self) -> None:
        self.config_path.write_text(yaml.safe_dump(self.state.to_config_yaml(), sort_keys=False))
        self.notify(f"saved {self.config_path}")

    def action_export_ballot(self) -> None:
        out = self.config_path.parent / "ballot.txt"
        out.write_text(render_snake(self.state.ballot_snake()))
        self.notify(f"wrote {out}")

    def action_copy_link(self) -> None:
        top = self.state.top_timetables()
        if not top:
            return
        _, _, assignment = top[self.selected]
        self.copy_to_clipboard(share_url(assignment, self.state.config.semester))
        self.notify("copied share link")

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
        if self.ballot_mode:
            self._refresh_detail()


def run_app(state, config_path: Path) -> None:
    OptimiserApp(state, config_path).run()
