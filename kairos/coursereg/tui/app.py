from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from ..advisor import NO_DATA, ratio
from ..model import UNLIMITED

_TIER_ABBREV = {"core": "core", "major": "maj", "ue": "ue"}


def _fmt_year(short: str) -> str:
    return f"AY{short[:2]}/{short[2:]}"


def _fmt_count(value) -> str:
    if value is None:
        return "?"
    if value == UNLIMITED:
        return "∞"
    return str(value)


def _history_lines(rows, dim: bool) -> list[Text]:
    lines = []
    for record in rows:
        r = ratio(record.demand, record.vacancy)
        ratio_text = "" if r is None else ("∞" if r == float("inf") else f"{r:.2f}")
        over = "  over" if r is not None and r > 1 else ""
        line = Text(
            f"  {_fmt_year(record.acad_year)}  "
            f"{_fmt_count(record.demand)} / {_fmt_count(record.vacancy)}"
            f"  {ratio_text}{over}"
        )
        if dim:
            line.stylize("dim")
        lines.append(line)
    return lines


class AdvisorApp(App):
    CSS = """
    #ranking { width: 44; border: round $panel; border-title-color: $text; }
    #dossier { width: 1fr; border: round $panel; border-title-color: $text; }
    #summary { height: 4; border: round $panel; border-title-color: $text; }
    """

    BINDINGS = [
        ("j", "cursor_down", "down"),
        ("k", "cursor_up", "up"),
        ("J", "move_down", "move down"),
        ("K", "move_up", "move up"),
        ("a", "advisor_order", "advisor order"),
        ("t", "cycle_tier", "tier"),
        ("r", "toggle_round", "round 2/3"),
        ("s", "save", "save"),
        ("q", "quit", "quit"),
    ]

    def __init__(self, state, config_path: Path) -> None:
        super().__init__()
        self.state = state
        self.config_path = Path(config_path)

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            with Horizontal():
                yield ListView(id="ranking")
                yield Static(id="dossier")
            yield Static(id="summary")
        yield Footer()

    def on_mount(self) -> None:
        # Assumption surfaced per spec: stated in the header bar, always visible.
        self.sub_title = "assumes independent per-course queues"
        self.query_one("#ranking", ListView).border_title = "Ranking"
        self.query_one("#dossier", Static).border_title = "Dossier"
        self.query_one("#summary", Static).border_title = "Notes"
        self._refresh_ranking(keep_index=0)

    # ------------------------------------------------------------- rendering

    def _refresh_ranking(self, keep_index: int) -> None:
        ranking = self.query_one("#ranking", ListView)
        ranking.clear()
        for rank, course, standing, tier in self.state.rows():
            rank_text = f"{rank:>2}" if rank is not None else "--"
            label = f"{rank_text}  {course:<10} {standing:<9} {_TIER_ABBREV[tier]}"
            ranking.append(ListItem(Label(label)))
        ranking.index = min(keep_index, len(self.state.order) - 1)
        self._refresh_detail()
        self._refresh_summary()

    def _selected_course(self) -> str:
        index = self.query_one("#ranking", ListView).index or 0
        return self.state.order[index]

    def _refresh_detail(self) -> None:
        course = self._selected_course()
        v = self.state.verdicts[course]
        same, other = self.state.dossier(course)
        parts = [Text(f"{course} — {v.standing}", style="bold")]
        parts.append(
            Text(f"round {self.state.profile.round}, "
                 f"S{self.state.profile.semester} history:")
        )
        if same:
            parts.extend(_history_lines(same, dim=False))
        elif v.standing == NO_DATA:
            parts.append(Text("  (none)", style="dim"))
        if other:
            parts.append(Text("other semester (context only):", style="dim"))
            parts.extend(_history_lines(other, dim=True))
        parts.append(Text(f"reasoning: {v.reasoning}"))
        self.query_one("#dossier", Static).update(Text("\n").join(parts))

    def _refresh_summary(self) -> None:
        notes = self.state.warnings()
        text = "\n".join(notes[:3]) if notes else "no leverage warnings"
        self.query_one("#summary", Static).update(text)

    # --------------------------------------------------------------- actions

    def action_cursor_down(self) -> None:
        self.query_one("#ranking", ListView).action_cursor_down()
        self._refresh_detail()

    def action_cursor_up(self) -> None:
        self.query_one("#ranking", ListView).action_cursor_up()
        self._refresh_detail()

    def action_move_down(self) -> None:
        index = self.query_one("#ranking", ListView).index or 0
        self._refresh_ranking(keep_index=self.state.move(index, 1))

    def action_move_up(self) -> None:
        index = self.query_one("#ranking", ListView).index or 0
        self._refresh_ranking(keep_index=self.state.move(index, -1))

    def action_advisor_order(self) -> None:
        self.state.restore_suggested()
        self._refresh_ranking(keep_index=0)

    def action_cycle_tier(self) -> None:
        index = self.query_one("#ranking", ListView).index or 0
        self.state.cycle_tier(self._selected_course())
        self._refresh_ranking(keep_index=index)

    def action_toggle_round(self) -> None:
        index = self.query_one("#ranking", ListView).index or 0
        self.state.toggle_round()
        self._refresh_ranking(keep_index=index)

    def action_save(self) -> None:
        self.config_path.write_text(self.state.to_yaml())
        self.notify(f"saved {self.config_path}")


def run_advisor(state, config_path: Path) -> None:
    AdvisorApp(state, config_path).run()
