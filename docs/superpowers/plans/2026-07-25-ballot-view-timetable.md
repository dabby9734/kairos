# Ballot View Shows The Timetable — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the TUI's ballot view, show a compact week grid pinned above a cursorable ballot list, so moving the cursor to a ballot row highlights the timeslot that row bids for.

**Architecture:** `output.py` gains `snake_rows` / `snake_legend`, extracted from `render_snake`, so the TUI can build one `ListItem` per ballot entry instead of re-parsing rendered text; `render_snake_rich` and its text re-parse are deleted. `tui/render.py`'s `render_week_rich` gains `agenda=False` to emit strips only. `tui/app.py` replaces the ballot branch of `_refresh_detail` with a `#ballot-view` container (`#ballot-grid` Static + `#ballot-legend` Static + `#ballot-list` ListView) toggled by `display`, and drives the grid's existing `preview=` from the list cursor.

**Tech Stack:** Python 3.11+, Textual, Rich, pytest (async tests need no marker).

## Global Constraints

Copied verbatim from `CLAUDE.md`; every task's requirements implicitly include these.

- `model/scoring/search/ballot/provenance` stay pure — no I/O in the core.
- Every sort needs an explicit deterministic tiebreak (usually `class_no`).
- User-facing errors: `raise SystemExit("error: ...")`.
- **No terminal blink (SGR 5); use reverse video** — Terminal.app ignores blink.
- `BALLOT_CAP` (`kairos/ballot.py`) is the single source for the 20-slot budget.
- Comments state constraints the code can't show, not narration.
- Changing CLI flags, config keys, TUI bindings, or scoring? Update the affected docs page in the same change (Task 4 does this).
- All tests must pass: `.venv/bin/pytest -q`.

Design spec: `docs/superpowers/specs/2026-07-25-ballot-view-timetable-design.md`.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `kairos/output.py` | Add `snake_legend`, `snake_rows`; `render_snake` composes them; delete `render_snake_rich` | 1, 3 |
| `kairos/tui/render.py` | `render_week_rich` gains `agenda: bool = True` | 2 |
| `kairos/tui/app.py` | Ballot view widgets, refresh split, cursor→preview, `●` marker | 3 |
| `tests/test_output.py` | `snake_legend` / `snake_rows` tests; delete 3 `render_snake_rich` tests | 1, 3 |
| `tests/test_tui_render.py` | `agenda` parameter tests | 2 |
| `tests/test_tui_app.py` | Ballot view toggle, list contents, preview sig, cursor preservation | 3 |
| `docs/user-guide.md`, `docs/architecture.md`, `docs/development.md` | Documentation | 4 |

---

### Task 1: `snake_legend` and `snake_rows` in `output.py`

Extract per-entry row building out of `render_snake` so callers can get rows
directly. `render_snake`'s output must stay byte-identical — it is written to
`ballot.txt` (`app.py:379`) and printed by `cli.py:168`.

**Files:**
- Modify: `kairos/output.py:198-264` (`render_snake`)
- Test: `tests/test_output.py`

**Interfaces:**
- Consumes: `_when(sessions)` (`output.py:175`), `LESSON_ABBREV` (`kairos/model.py`), `provenance.cluster_stats(keys)` returning `ClusterStats | None` with fields `ceiling: float, median: float, support: int, ceiling_tier: int, median_tier: int` (`kairos/provenance.py:12`), `provenance.total: int`.
- Produces:
  - `snake_legend(provenance) -> list[str]` — the two explanatory lines above the ballot table.
  - `snake_rows(entries, provenance) -> list[tuple]` — one `(entry, line, continuation)` triple per entry, in ballot order, columns aligned across the whole ballot. `entry` is the `BallotOption` itself; `line` is the rendered row, `.rstrip()`ed; `continuation` is the `"↳ interchangeable with ..."` line or `None`. Returns `[]` for empty `entries`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_output.py` (import `render_snake` is already at line 3; add
`snake_legend, snake_rows` to that import):

```python
def _prov_stub(total=10):
    from kairos.provenance import ClusterStats

    class Prov:
        def __init__(self):
            self.total = total

        def cluster_stats(self, keys):
            return ClusterStats(-14.0, -14.0, 5, 1, 1)

    return Prov()


def _snake_entry(module="ALPHA", lesson_type="Tutorial", class_no="01", tied_with=None):
    from kairos.ballot import BallotOption
    from kairos.model import Session

    weeks = frozenset(range(1, 14))
    return BallotOption(
        module, lesson_type, class_no, "A", 3.0,
        (Session("Monday", 600, 660, weeks, "COM1"),), list(tied_with or []),
    )


def test_snake_rows_one_row_per_entry_in_ballot_order():
    entries = [_snake_entry(class_no="01"), _snake_entry(class_no="02")]
    rows = snake_rows(entries, _prov_stub())
    assert [entry for entry, _line, _cont in rows] == entries
    assert " 1. ALPHA TUT[01]" in rows[0][1]
    assert " 2. ALPHA TUT[02]" in rows[1][1]


def test_snake_rows_continuation_only_when_tied():
    plain, tied = _snake_entry(class_no="01"), _snake_entry(class_no="02", tied_with=["03"])
    rows = snake_rows([plain, tied], _prov_stub())
    assert rows[0][2] is None
    assert "↳ interchangeable with 03" in rows[1][2]


def test_snake_rows_empty_entries():
    assert snake_rows([], _prov_stub()) == []


def test_snake_rows_columns_align_across_mixed_widths():
    short = _snake_entry(module="AA", class_no="1")
    wide = _snake_entry(module="LONGMODULE", lesson_type="Laboratory", class_no="B99")
    rows = snake_rows([short, wide], _prov_stub())
    starts = [line.index("choice ") for _entry, line, _cont in rows]
    assert len(set(starts)) == 1  # the choice column starts at the same offset


def test_snake_legend_reports_provenance_total():
    lines = snake_legend(_prov_stub(total=42))
    assert len(lines) == 2
    assert lines[0].startswith("best    =")
    assert "42 clash-free timetables" in lines[1]


def test_render_snake_is_legend_plus_snake_rows():
    # The byte-identity guarantee: ballot.txt and `kairos run` output must not
    # move when the TUI starts consuming rows directly.
    entries = [_snake_entry(class_no="01"), _snake_entry(class_no="02", tied_with=["03"])]
    prov = _prov_stub()
    lines = [*snake_legend(prov), ""]
    for _entry, line, cont in snake_rows(entries, prov):
        lines.append(line)
        if cont is not None:
            lines.append(cont)
    assert "\n".join(lines) == render_snake(entries, provenance=prov)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_output.py -k "snake_rows or snake_legend or legend_plus" -q`

Expected: FAIL with `ImportError: cannot import name 'snake_legend' from 'kairos.output'`.

- [ ] **Step 3: Implement `snake_legend` and `snake_rows`**

In `kairos/output.py`, insert both functions immediately *before* `render_snake`
(after `render_options`, which ends at line 195):

```python
def snake_legend(provenance) -> list:
    """The two explanatory lines printed above the ballot table."""
    return [
        "best    = ceiling: the best timetable containing this class",
        f"typical = median of the {provenance.total} clash-free timetables containing it",
    ]


def snake_rows(entries: list, provenance) -> list:
    """One `(entry, line, continuation)` triple per ballot entry, in ballot
    order, with columns aligned across the whole ballot. `continuation` is the
    interchangeable-twins line, or None when the entry has no twins.

    Split out of render_snake so a caller needing per-entry rows -- the TUI's
    ballot ListView, which needs one widget per entry -- gets them directly
    rather than rendering text and parsing entry boundaries back out of it."""
    if not entries:
        return []
    cells = []
    for position, option in enumerate(entries, 1):
        abbrev = LESSON_ABBREV.get(option.lesson_type, option.lesson_type)
        stats = provenance.cluster_stats(
            {
                (option.module, option.lesson_type, class_no)
                for class_no in [option.class_no, *option.tied_with]
            }
        )
        best = "" if stats is None else f"best #{stats.ceiling_tier} ({stats.ceiling:+.1f})"
        typical = (
            "" if stats is None else f"typical #{stats.median_tier} ({stats.median:+.1f})"
        )
        cells.append((
            option,
            f"{position:2}. {option.module} {abbrev}[{option.class_no}]",
            f"choice {option.letter}",
            _when(option.sessions),
            best,
            typical,
        ))

    widths = [max(len(cell[i]) for cell in cells) for i in range(1, 6)]
    rows = []
    for option, label, choice, when, best, typical in cells:
        line = (
            f"{label:<{widths[0]}}  {choice:<{widths[1]}}  {when:<{widths[2]}}  "
            f"{best:<{widths[3]}}  {typical}"
        ).rstrip()
        continuation = (
            f"{'':<{widths[0]}}    ↳ interchangeable with {', '.join(option.tied_with)}"
            if option.tied_with
            else None
        )
        rows.append((option, line, continuation))
    return rows
```

- [ ] **Step 4: Rewrite `render_snake`'s provenance branch to use them**

In `kairos/output.py`, replace everything from `    rows = []` (line 225) to the
end of `render_snake` (line 264, `    return "\n".join(lines)`) with:

```python
    lines = [*snake_legend(provenance), ""]
    for _option, line, continuation in snake_rows(entries, provenance):
        lines.append(line)
        if continuation is not None:
            lines.append(continuation)
    return "\n".join(lines)
```

Leave lines 198-223 untouched: the docstring, the `if not entries: return ""`
guard, and the whole `provenance is None` branch are unchanged.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`

Expected: PASS. Every pre-existing `render_snake` test (alignment, continuation
lines, missing stats, empty entries, `provenance=None` identity) and the three
`render_snake_rich` tests still pass — `render_snake_rich` calls `render_snake`,
whose output has not moved.

- [ ] **Step 6: Commit**

```bash
git add kairos/output.py tests/test_output.py
git commit -m "refactor: extract snake_legend and snake_rows from render_snake"
```

---

### Task 2: `agenda` parameter on `render_week_rich`

The pinned grid must fit above the ballot list. With agenda lines the grid runs
30+ rows; without them it is the header plus one row per day per lane.

**Files:**
- Modify: `kairos/tui/render.py:28-153` (`render_week_rich`)
- Test: `tests/test_tui_render.py`

**Interfaces:**
- Produces: `render_week_rich(assignment, colours, preview=None, agenda=True) -> Group`. With `agenda=False`, per-day times/venues lines (including the `(preview)` line) are omitted; strip rows, lane stacking, day selection and preview/flash styling are unchanged. `agenda=True` is byte-identical to omitting the argument, so all existing callers and tests are unaffected.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tui_render.py` (the helpers `_choice`, `_plain`,
`module_colours`, `render_week_rich`, `Choice`, `Session` and `ALL_WEEKS`
already exist there):

```python
def test_agenda_false_drops_agenda_keeps_strips():
    assignment = {("CS2030S", "Laboratory"): _choice("CS2030S", "Laboratory", "14B", "Monday", 840, 960)}
    colours = module_colours(["CS2030S"])
    compact = _plain(render_week_rich(assignment, colours, agenda=False))
    assert "CS2030S [LAB]" in compact   # the strip survives
    assert "@COM1" not in compact       # the agenda line is gone
    assert "14:00-16:00" not in compact
    # header + Mon-Fri, one lane each, and no Saturday in this assignment
    assert len([ln for ln in compact.splitlines() if ln.strip()]) == 6


def test_agenda_true_matches_default():
    assignment = {("CS2030S", "Laboratory"): _choice("CS2030S", "Laboratory", "14B", "Monday", 840, 960)}
    colours = module_colours(["CS2030S"])
    assert _plain(render_week_rich(assignment, colours, agenda=True)) == _plain(
        render_week_rich(assignment, colours)
    )


def test_agenda_false_still_draws_preview_strip():
    assignment = {("CS2030S", "Tutorial"): _choice("CS2030S", "Tutorial", "01", "Monday", 600, 660)}
    colours = module_colours(["CS2030S"])
    sig = frozenset({("Wednesday", 840, 900, False)})
    compact = _plain(render_week_rich(assignment, colours, preview=("CS2030S", "Tutorial", sig), agenda=False))
    assert compact.count("CS2030S") == 2  # the real strip plus the preview strip
    assert "(preview)" not in compact     # that line lives in the agenda
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_tui_render.py -k agenda -q`

Expected: FAIL with `TypeError: render_week_rich() got an unexpected keyword argument 'agenda'`.

- [ ] **Step 3: Add the parameter**

In `kairos/tui/render.py`, change the signature on line 28:

```python
def render_week_rich(assignment: dict, colours: dict, preview=None, agenda=True) -> Group:
```

- [ ] **Step 4: Document it in the docstring**

Append this paragraph to the end of `render_week_rich`'s docstring (after the
`preview` paragraph ending `...alongside the class's current slot.`, line 40):

```
    `agenda=False` drops the per-day times/venues lines, leaving strips only.
    The TUI's ballot view pins the grid above a scrolling list, where the full
    agenda would consume the whole pane.
```

- [ ] **Step 5: Gate the agenda block**

In `kairos/tui/render.py`, the agenda block is currently lines 142-151:

```python
        # Agenda: every block for the day, sorted by start time.
        for start, end, _sh, _eh, module, abbrev, class_no, venue, online, mode in sorted(blocks):
```

Guard it by adding the `if agenda:` line above the comment and indenting the
comment and the whole `for` loop body one level:

```python
        if agenda:
            # Agenda: every block for the day, sorted by start time.
            for start, end, _sh, _eh, module, abbrev, class_no, venue, online, mode in sorted(blocks):
                if mode == "preview":
                    rows.append(Text(f"       {fmt_time(start)}-{fmt_time(end)} {module} {abbrev} (preview)"))
                    continue
                note = " (online)" if online else ""
                rows.append(Text(
                    f"       {fmt_time(start)}-{fmt_time(end)} {module} "
                    f"{abbrev}[{class_no}] @{venue}{note}",
                ))
```

- [ ] **Step 6: Run the render tests**

Run: `.venv/bin/pytest tests/test_tui_render.py -q`

Expected: PASS — the three new tests plus every existing one (the defaulted
`agenda=True` path is unchanged).

- [ ] **Step 7: Commit**

```bash
git add kairos/tui/render.py tests/test_tui_render.py
git commit -m "feat: render_week_rich can omit the per-day agenda"
```

---

### Task 3: Ballot view shows the grid

Replace the ballot branch of `_refresh_detail` with a dedicated container, and
delete `render_snake_rich` — this task removes its only caller.

**Files:**
- Modify: `kairos/tui/app.py` — CSS (96-114), imports (17-19), `__init__` (134-143), `compose` (195-196), `_refresh_detail` (271-284), `on_list_view_highlighted` (328-339), `action_toggle_ballot` (343-345), `_move_priority` (426-427)
- Modify: `kairos/output.py` — delete `render_snake_rich` (267-296)
- Test: `tests/test_tui_app.py`, `tests/test_output.py` (delete 3 tests)

**Interfaces:**
- Consumes: `snake_legend(provenance)`, `snake_rows(entries, provenance)` (Task 1); `render_week_rich(..., agenda=False)` (Task 2); `state.ballot_snake() -> list[BallotOption]`, `state.top_arrangements()`, `state.provenance` (`Provenance | None`) with `by_arrangement: tuple[frozenset[(module, lesson_type, class_no)]]` (`kairos/provenance.py:32`).
- Produces: `KairosApp._ballot_preview(entry) -> tuple` returning `(module, lesson_type, sig)` where `sig` is `frozenset((day, start, end, online), ...)`; `KairosApp._refresh_ballot_list()` and `KairosApp._refresh_ballot_grid()`; widget ids `#ballot-view`, `#ballot-grid`, `#ballot-legend`, `#ballot-list`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tui_app.py` (`ListView` and `Static` are already imported at
line 4; the `state` fixture already exists at line 12):

```python
async def test_ballot_view_toggles_container_display(state, tmp_path):
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#detail-scroll").display is True
        assert app.query_one("#ballot-view").display is False
        await pilot.press("b")
        await pilot.pause()
        assert app.query_one("#detail-scroll").display is False
        assert app.query_one("#ballot-view").display is True
        assert app.query_one("#ballot-list", ListView).has_focus  # cursor is ready
        await pilot.press("b")
        await pilot.pause()
        assert app.query_one("#detail-scroll").display is True
        assert app.query_one("#ballot-view").display is False


async def test_ballot_list_has_one_item_per_entry(state, tmp_path):
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        await pilot.press("b")
        await pilot.pause()
        assert len(app.query_one("#ballot-list", ListView).children) == len(
            app.state.ballot_snake()
        )


async def test_ballot_grid_is_compact(state, tmp_path):
    from rich.console import Console

    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        await pilot.press("b")
        await pilot.pause()
        console = Console(width=200)
        with console.capture() as cap:
            console.print(app.query_one("#ballot-grid", Static)._Static__content)
        text = cap.get()
        assert "Mon" in text        # the grid is drawn
        assert "@COM1" not in text  # ...without agenda lines


async def test_ballot_preview_sig_matches_slot_sig(state, tmp_path):
    # The preview triple must be directly comparable to the sigs render_week_rich
    # matches against, i.e. Choice.slot_sig's (day, start, end, online) fields.
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        await pilot.press("b")
        await pilot.pause()
        entry = app.state.ballot_snake()[0]
        module, lesson_type, sig = app._ballot_preview(entry)
        assert (module, lesson_type) == (entry.module, entry.lesson_type)
        assert sig == frozenset(
            (s.day, s.start, s.end, s.online) for s in entry.sessions
        )


async def test_ballot_membership_marker_tracks_selected_timetable(state, tmp_path):
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        await pilot.press("b")
        await pilot.pause()
        labels = [
            str(item.query_one("Label").renderable)
            for item in app.query_one("#ballot-list", ListView).children
        ]
        assert labels  # the fixture produces a non-empty ballot
        assert all(line[0] in "● " for line in labels)       # marker occupies the gutter
        assert any(line.startswith("●") for line in labels)  # some row is in timetable #1

        # The marked rows are exactly the selected arrangement's classes.
        marked = {
            entry.class_no
            for entry, line in zip(app._ballot_entries, labels)
            if line.startswith("●")
        }
        highlight = app.state.provenance.by_arrangement[app.selected]
        expected = {
            class_no
            for entry in app._ballot_entries
            for class_no in [entry.class_no]
            if {
                (entry.module, entry.lesson_type, twin)
                for twin in [entry.class_no, *entry.tied_with]
            }
            & highlight
        }
        assert marked == expected


async def test_ballot_list_rebuild_preserves_cursor(state, tmp_path):
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        await pilot.press("b")
        await pilot.pause()
        lst = app.query_one("#ballot-list", ListView)
        lst.index = 2
        await pilot.pause()
        app._refresh_ballot_list()
        await pilot.pause()
        assert lst.index == 2  # a rebuild must not throw the cursor to the top
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_tui_app.py -k ballot -q`

Expected: FAIL with `NoMatches: No nodes match '#ballot-view'`.

- [ ] **Step 3: Add the CSS**

In `kairos/tui/app.py`, add these rules at the end of the `CSS` string, after
`#detail-scroll { height: 1fr; }` (line 112):

```
    #ballot-view { height: 1fr; }
    /* auto so a Saturday row or an extra overlap lane is never clipped;
       max-height so a busy week can't crowd out the list below it. */
    #ballot-grid { height: auto; max-height: 50%; }
    #ballot-legend { height: auto; color: $text-muted; }
    #ballot-list { height: 1fr; }
    #ballot-list ListItem { height: auto; }
```

- [ ] **Step 4: Update the imports**

Replace lines 17-19 of `kairos/tui/app.py`:

```python
from ..output import (
    class_warnings, render_breakdown, render_snake, share_url, snake_legend, snake_rows,
)
```

(`render_snake_rich` is dropped; `snake_legend` and `snake_rows` are added.)

- [ ] **Step 5: Compose the ballot view**

In `kairos/tui/app.py`, replace lines 195-196:

```python
                with VerticalScroll(id="detail-scroll"):
                    yield Static(id="detail")
```

with:

```python
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
```

- [ ] **Step 6: Add the preview helper and the two refresh methods**

In `kairos/tui/app.py`, insert these three methods immediately after
`_refresh_detail` (which ends at line 312, the closing `)` of `detail.update(`):

```python
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
        if self.state.provenance is not None and self.selected < len(
            self.state.provenance.by_arrangement
        ):
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
```

- [ ] **Step 7: Initialise the entry cache**

In `kairos/tui/app.py`'s `__init__`, add after `self._rows = []` (line 141):

```python
        self._ballot_entries = []
```

- [ ] **Step 8: Rewrite the ballot branch of `_refresh_detail`**

Replace lines 271-284 of `kairos/tui/app.py` (the whole `if self.ballot_mode:`
block) with:

```python
        if self.ballot_mode:
            self._refresh_ballot_list()
            self._refresh_ballot_grid()
            warnings_text.set_classes([])
            warnings_text.update("")
            return
```

- [ ] **Step 9: Rewrite `action_toggle_ballot`**

Replace lines 343-345:

```python
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
```

- [ ] **Step 10: Drive the grid from the cursor, and make Esc leave ballot view**

In `on_list_view_highlighted` (lines 328-339), add a branch before the closing
of the method, after the `timeslot-list` branch:

```python
        elif lv.id == "ballot-list":
            self._refresh_ballot_grid()
```

Then replace `action_focus_classes` (lines 351-353) so Esc leaves ballot view
instead of focusing a pane hidden behind it:

```python
    def action_focus_classes(self) -> None:
        if self.ballot_mode:
            self.action_toggle_ballot()   # Esc/← leaves ballot view
            return
        self.query_one("#slot-list", ListView).focus()
        self._refresh_detail()
```

- [ ] **Step 11: Keep the priority-reorder refresh working**

`_move_priority` (lines 426-427) ends with:

```python
        if self.ballot_mode:
            self._refresh_detail()
```

This needs no edit — `_refresh_detail`'s ballot branch now rebuilds both
widgets. Confirm the two lines are still present and unchanged.

- [ ] **Step 12: Delete `render_snake_rich` and its tests**

Delete `kairos/output.py` lines 267-296 (the entire `render_snake_rich`
function). It is the module's only Rich import (lazy, line 273), so `output.py`
becomes Rich-free.

Delete these three tests from `tests/test_output.py`:
`test_render_snake_rich_reverses_highlighted_rows`,
`test_render_snake_rich_without_highlight_has_no_reverse_spans`,
`test_render_snake_rich_matches_plain_text` (lines 431-500).

- [ ] **Step 13: Verify output.py imports no Rich**

Run: `grep -rn "rich" kairos/output.py`

Expected: no output.

- [ ] **Step 14: Run the full suite**

Run: `.venv/bin/pytest -q`

Expected: PASS. Note `test_warnings_paint_opaque_theme_surface` (line 32) and
`test_export_ballot_shortfall_warns` (line 200) both press `b` and assert the
warnings pane empties — that behaviour is preserved by Step 8.

- [ ] **Step 15: Look at it running**

Run: `.venv/bin/kairos tui`

Press `b`, then arrow down the ballot list. Confirm: the grid stays pinned and
compact; the highlighted row's class shows a reverse-video strip (inverted in
place when it is the class already on that slot, an extra strip otherwise);
`●` marks the rows belonging to the displayed timetable; Esc returns.

- [ ] **Step 16: Commit**

```bash
git add kairos/tui/app.py kairos/output.py tests/test_tui_app.py tests/test_output.py
git commit -m "feat: ballot view shows the week grid, previewing the cursor's slot"
```

---

### Task 4: Documentation

Required by the docs-upkeep rule in `CLAUDE.md`: TUI bindings changed.

**Files:**
- Modify: `docs/user-guide.md:344-366`
- Modify: `docs/architecture.md:245-248, 262-266, 382-386`
- Modify: `docs/development.md:43`

**Interfaces:**
- Consumes: everything shipped in Tasks 1-3. Produces no code.

- [ ] **Step 1: Update the user guide's prose**

In `docs/user-guide.md`, replace the `b` clause in the "Other keys" paragraph
(line 344, `` `b` toggles the ballot view, highlighting the classes that belong
to the currently-selected timetable; ``) with:

```
`b` toggles the ballot view, which pins a compact week grid above the ballot
list: arrow down the list and the grid highlights the timeslot that ballot
position bids for, either inverting the class's existing strip or drawing the
candidate strip beside it. A `●` in the left gutter marks the rows belonging to
the currently-selected timetable. Esc returns to the timetable view.
```

- [ ] **Step 2: Update the keybinding table**

In `docs/user-guide.md`, the table at lines 353-366. Change the `← / Esc` row to
mention ballot view, and add a row for the ballot cursor. The `← / Esc` row
becomes:

```
| ← / Esc | back to the Classes pane (or out of the ballot view) |
```

Add this row immediately after the `` `b` `` row:

```
| ↑ / ↓ (in the ballot view) | move the ballot cursor; the grid previews that slot |
```

- [ ] **Step 3: Update architecture.md's output.py section**

In `docs/architecture.md`, replace the sentence at lines 247-248 (`Only
render_snake_rich imports Rich, and it does so lazily, so the plain-text paths
stay Rich-free.`) with:

```
It imports no Rich at all: every Rich renderable is built in `tui/render.py`.
```

Then replace the bullet at lines 262-266 (`render_options`, `render_snake`, and
`render_snake_rich` ...) with:

```
- `render_options`, `render_snake`, and `snake_rows` draw the backup-choices
  table and the snake-order ballot, with best/typical tier columns when given a
  `Provenance`. `snake_rows` returns one `(entry, line, continuation)` triple
  per ballot entry and `snake_legend` the two explanatory lines above them;
  `render_snake` joins both. The TUI consumes the rows directly so its ballot
  `ListView` gets one item per entry.
```

- [ ] **Step 4: Update architecture.md's render.py section**

In `docs/architecture.md`, update the signature at line 384 from
`render_week_rich(assignment, colours, preview=None)` to
`render_week_rich(assignment, colours, preview=None, agenda=True)`, and append
this sentence to the end of that paragraph:

```
`agenda=False` drops the per-day times/venues lines; the ballot view uses it so
the pinned grid leaves room for the ballot list below it.
```

- [ ] **Step 5: Update development.md's test-layout table**

In `docs/development.md`, append to the `test_tui_render.py` row (line 43),
after `and preview/flash bar inversion.`:

```
 Also the `agenda=False` compact mode used by the ballot view.
```

- [ ] **Step 6: Verify the docs match the code**

Run: `grep -rn "render_snake_rich" docs/user-guide.md docs/architecture.md docs/development.md kairos/`

Expected: no output. (Historical plans and specs under `docs/superpowers/` are a
record of past work and are deliberately not rewritten.)

- [ ] **Step 7: Run the full suite one last time**

Run: `.venv/bin/pytest -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add docs/user-guide.md docs/architecture.md docs/development.md
git commit -m "docs: document the ballot view's pinned week grid"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: widgets and `display`
toggle → Task 3 Steps 3/5/9; compact grid → Task 2 + Task 3 Step 6; preview sig
from `BallotOption.sessions` → Task 3 Step 6 (`_ballot_preview`) and its test;
`●` marker vs reverse cursor → Task 3 Step 6 and its test; `snake_rows` and the
`render_snake_rich` deletion → Tasks 1 and 3 Step 12; output.py becoming
Rich-free → Task 3 Step 13 and Task 4 Step 3; refresh split → Task 3 Step 6 with
a cursor-preservation test; warnings stay cleared → Task 3 Step 8; docs → Task 4.
Out-of-scope (locking from a ballot row) has no task, as intended.

**Placeholder scan.** No TBDs; every code step carries the actual code, every
test step the actual test body, every run step the exact command and expected
result.

**Type consistency.** `snake_rows` returns `(entry, line, continuation)` at
definition (Task 1 Step 3) and is unpacked in that order at both consumers
(Task 1 Step 4, Task 3 Step 6). `snake_legend` returns `list[str]` and is
`"\n".join`ed at both consumers. `_ballot_preview` returns the same 3-tuple
shape `render_week_rich`'s `preview` expects, with `sig` a
`frozenset((day, start, end, online))` matching `Choice.slot_sig`
(`model.py:84`). `agenda` is keyword-named identically at definition (Task 2
Step 3) and call site (Task 3 Step 6). Widget ids `#ballot-view`,
`#ballot-grid`, `#ballot-legend`, `#ballot-list` are defined once in `compose`
(Task 3 Step 5) and match every `query_one`, CSS rule and test.

**One spec deviation, deliberate.** The spec described three widgets; the plan
adds a fourth, `#ballot-legend`, plus a `snake_legend` helper. The
`best`/`typical` legend is not per-entry, so it cannot live in the `ListView`
without becoming a selectable row the cursor would land on. Extracting it keeps
`render_snake` byte-identical and avoids duplicating the strings in the TUI.
