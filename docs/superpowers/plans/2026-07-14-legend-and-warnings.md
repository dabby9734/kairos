# Scoring Legend & Class Warnings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add inline descriptions to the scoring breakdown and a per-timetable list of classes/days that fail the user's preference criteria, surfaced in the TUI detail pane.

**Architecture:** Two additions to the pure core in `optimiser/`, consumed by the thin Textual layer. A `COMPONENT_LEGEND` dict in `scoring.py` feeds descriptions into `output.render_breakdown`. A new pure function `output.class_warnings(assignment, config)` re-derives each penalty exactly as `scoring.score_assignment` does (reusing `scoring._merged_intervals` for lunch) so warnings never disagree with the score. `OptimiserApp._refresh_detail` appends the warnings below the week grid in timetable mode only.

**Tech Stack:** Python ≥3.11, Rich (already a Textual dep), pytest / pytest-asyncio.

## Global Constraints

- Warnings and legend descriptions must mirror `scoring.score_assignment` exactly — a class flagged as violating a criterion must be one that actually cost score in that component, and vice versa.
- Assignment dicts are keyed `(module, lesson_type) -> Choice`; `lesson_type` is the full name (e.g. `"Tutorial"`), abbreviated for display via `model.LESSON_ABBREV`.
- Online sessions (`Session.online`, venue starts with `"E-Learn"`) are excluded from `time_window`, `lunch`, and `same_day_pairing` but **counted** in `tough_days` — match this split precisely.
- No new dependencies. Pure functions live in `optimiser/`, display strings use `LESSON_ABBREV` / `fmt_time` from `model`.
- `⚠ ` (U+26A0 + space) prefixes each warning line; `✓ all criteria met` is the empty-state line.

---

### Task 1: Scoring-component legend

**Files:**
- Modify: `optimiser/scoring.py` (add `COMPONENT_LEGEND` near top)
- Modify: `optimiser/output.py:1-3` (import), `optimiser/output.py:48-52` (`render_breakdown`)
- Test: `tests/test_output.py`

**Interfaces:**
- Produces: `scoring.COMPONENT_LEGEND: dict[str, str]` (component name → one-line description). `render_breakdown(total: float, breakdown: dict) -> str` unchanged signature, now appends `   — <description>` per line when the component has a legend entry.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_output.py`:

```python
def test_render_breakdown_includes_legend_descriptions():
    from optimiser.scoring import COMPONENT_LEGEND

    text = render_breakdown(3.5, {"gaps": (-2.0, -2.0), "free_days": (2, 8.0)})
    assert COMPONENT_LEGEND["gaps"] in text
    assert COMPONENT_LEGEND["free_days"] in text


def test_render_breakdown_unknown_component_has_no_description():
    # A component with no legend entry must still render (no trailing dash).
    text = render_breakdown(1.0, {"mystery": (1.0, 1.0)})
    assert "mystery" in text
    assert "—" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_output.py::test_render_breakdown_includes_legend_descriptions -v`
Expected: FAIL with `ImportError: cannot import name 'COMPONENT_LEGEND'`

- [ ] **Step 3: Add `COMPONENT_LEGEND` to `scoring.py`**

Insert after the `WEEKDAYS = DAYS[:5]` line (around line 5) in `optimiser/scoring.py`:

```python
COMPONENT_LEGEND = {
    "free_days": "whole free weekdays (more = better)",
    "gaps": "idle hours between classes (fewer = better)",
    "lunch": "days with no lunch break (fewer = better)",
    "same_day_pairing": "tutorials/labs sharing a day with their lecture (more = better)",
    "time_window": "class-hours outside your preferred window (fewer = better)",
    "tough_days": "difficulty piled past your daily cap (less = better)",
}
```

- [ ] **Step 4: Wire descriptions into `render_breakdown`**

In `optimiser/output.py`, change the import line (currently `from .model import DAYS, LESSON_ABBREV, fmt_time`) to also import the legend:

```python
from .model import DAYS, LESSON_ABBREV, fmt_time
from .scoring import COMPONENT_LEGEND
```

Then replace `render_breakdown` (lines 48-52) with:

```python
def render_breakdown(total: float, breakdown: dict) -> str:
    lines = [f"score: {total:+.2f}"]
    for name, (raw, weighted) in sorted(breakdown.items()):
        desc = COMPONENT_LEGEND.get(name)
        suffix = f"   — {desc}" if desc else ""
        lines.append(f"    {name:18} raw {raw:+8.2f}   weighted {weighted:+8.2f}{suffix}")
    return "\n".join(lines)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_output.py -v`
Expected: PASS (new legend tests plus the existing `test_render_breakdown`)

- [ ] **Step 6: Guard against an import cycle**

Run: `.venv/bin/python -c "import optimiser.output, optimiser.scoring"`
Expected: no output, exit 0 (confirms `output → scoring` import introduces no cycle)

- [ ] **Step 7: Commit**

```bash
git add optimiser/scoring.py optimiser/output.py tests/test_output.py
git commit -m "feat: describe each scoring component inline in the breakdown"
```

---

### Task 2: `class_warnings` pure function

**Files:**
- Modify: `optimiser/output.py` (add `_merged_intervals` to the scoring import; add `class_warnings`)
- Test: `tests/test_output.py`

**Interfaces:**
- Consumes: `scoring.COMPONENT_LEGEND` (Task 1), `scoring._merged_intervals(sessions) -> list[[start, end]]`, `config.preferences` (`earliest_start`, `latest_end`, `max_difficulty_per_day`, `lunch_start`, `lunch_end`, `lunch_minutes`), `config.difficulty(module, lesson_type_full) -> int`.
- Produces: `class_warnings(assignment: dict, config) -> list[str]` — deterministic list of `⚠ …` lines, grouped in fixed component order (time_window, tough_days, same_day_pairing, lunch); empty list when nothing violates.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_output.py`. The `config` fixture (from `conftest.py`) has `earliest_start=600` (10:00), `latest_end=1080` (18:00), `max_difficulty_per_day=8`, lunch window `660–840` (11:00–14:00), `lunch_minutes=60`, and difficulties `ALPHA {LEC:2, TUT:4}`, `BETA 3`.

```python
from optimiser.output import class_warnings


def _choice(module, ltype, class_no, *sessions):
    return Choice(module, ltype, class_no, tuple(sessions))


def _sess(day, start, end, venue="COM1"):
    return Session(day, start, end, ALL_WEEKS, venue)


def test_class_warnings_time_window_before_earliest(config):
    # ALPHA TUT 09:00-11:00, earliest 10:00 -> starts too early.
    a = {("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", _sess("Monday", 540, 660))}
    warnings = class_warnings(a, config)
    assert warnings == ["⚠ ALPHA TUT Mon 0900 starts before your earliest 1000"]


def test_class_warnings_time_window_after_latest(config):
    # ALPHA TUT 17:00-19:00, latest 18:00 -> ends too late.
    a = {("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", _sess("Monday", 1020, 1140))}
    assert class_warnings(a, config) == ["⚠ ALPHA TUT Mon 1900 ends after your latest 1800"]


def test_class_warnings_time_window_ignores_online(config):
    # Online 08:00-10:00 lecture is excluded from the time window, like scoring.
    a = {("ALPHA", "Lecture"): _choice("ALPHA", "Lecture", "1", _sess("Monday", 480, 600, "E-Learn_C"))}
    assert class_warnings(a, config) == []


def test_class_warnings_tough_day_counts_online(config):
    # ALPHA LEC(online) 2 + ALPHA TUT 4 + BETA LAB 3 = 9 > 8, all Monday.
    a = {
        ("ALPHA", "Lecture"): _choice("ALPHA", "Lecture", "1", _sess("Monday", 600, 720, "E-Learn_C")),
        ("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", _sess("Monday", 780, 840)),
        ("BETA", "Laboratory"): _choice("BETA", "Laboratory", "L1", _sess("Monday", 960, 1080)),
    }
    assert "⚠ Monday exceeds max difficulty (9 > 8)" in class_warnings(a, config)


def test_class_warnings_same_day_pairing_unpaired(config):
    # ALPHA lecture Monday (campus), tutorial Tuesday -> not paired.
    a = {
        ("ALPHA", "Lecture"): _choice("ALPHA", "Lecture", "1", _sess("Monday", 600, 720)),
        ("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", _sess("Tuesday", 600, 660)),
    }
    assert "⚠ ALPHA TUT not same-day as its lecture" in class_warnings(a, config)


def test_class_warnings_no_pairing_when_no_campus_lecture(config):
    # Lecture is online-only -> pairing is impossible, so it is NOT a violation.
    a = {
        ("ALPHA", "Lecture"): _choice("ALPHA", "Lecture", "1", _sess("Monday", 600, 720, "E-Learn_C")),
        ("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", _sess("Tuesday", 600, 660)),
    }
    assert not any("same-day" in w for w in class_warnings(a, config))


def test_class_warnings_no_lunch(config):
    # One class spans the whole 11:00-14:00 window -> no lunch block.
    a = {("ALPHA", "Lecture"): _choice("ALPHA", "Lecture", "1", _sess("Monday", 600, 900))}
    assert "⚠ Monday has no lunch break" in class_warnings(a, config)


def test_class_warnings_clean_timetable_is_empty(config):
    # Lecture 10:00-12:00 + tutorial 13:00-14:00, same day: in window, paired,
    # under the difficulty cap, and leaves a 60-min lunch block.
    a = {
        ("ALPHA", "Lecture"): _choice("ALPHA", "Lecture", "1", _sess("Monday", 600, 720)),
        ("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", _sess("Monday", 780, 840)),
    }
    assert class_warnings(a, config) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_output.py -k class_warnings -v`
Expected: FAIL with `ImportError: cannot import name 'class_warnings'`

- [ ] **Step 3: Implement `class_warnings`**

In `optimiser/output.py`, extend the scoring import to bring in the shared lunch helper:

```python
from .scoring import COMPONENT_LEGEND, _merged_intervals
```

Then add this function (place it after `render_breakdown`):

```python
def class_warnings(assignment: dict, config) -> list[str]:
    """Human-readable warnings for classes/days that fail the user's criteria in
    this timetable. Each check mirrors scoring.score_assignment so warnings and
    score never disagree. free_days (a bonus) and gaps (an aggregate) produce no
    per-class warning. Returns [] when nothing is violated."""
    prefs = config.preferences
    warnings: list[str] = []

    # time_window: campus sessions starting early / ending late (online excluded)
    tw = []
    for (module, lesson_type), choice in assignment.items():
        abbrev = LESSON_ABBREV.get(lesson_type, lesson_type)
        for s in choice.sessions:
            if s.online:
                continue
            if s.start < prefs.earliest_start:
                tw.append((DAYS.index(s.day), s.start,
                    f"⚠ {module} {abbrev} {s.day[:3]} {fmt_time(s.start)} "
                    f"starts before your earliest {fmt_time(prefs.earliest_start)}"))
            if s.end > prefs.latest_end:
                tw.append((DAYS.index(s.day), s.start,
                    f"⚠ {module} {abbrev} {s.day[:3]} {fmt_time(s.end)} "
                    f"ends after your latest {fmt_time(prefs.latest_end)}"))
    warnings.extend(text for _, _, text in sorted(tw))

    # tough_days: per day whose total difficulty (all sessions incl. online) > cap
    tough: dict = {}
    for choice in assignment.values():
        difficulty = config.difficulty(choice.module, choice.lesson_type)
        for s in choice.sessions:
            tough[s.day] = tough.get(s.day, 0) + difficulty
    for day in sorted(tough, key=DAYS.index):
        if tough[day] > prefs.max_difficulty_per_day:
            warnings.append(
                f"⚠ {day} exceeds max difficulty ({tough[day]} > {prefs.max_difficulty_per_day})"
            )

    # same_day_pairing: non-lecture class whose module has a campus lecture but
    # sits on none of that lecture's days. No campus lecture -> pairing is
    # impossible, so not a violation.
    lecture_days: dict = {}
    for choice in assignment.values():
        if choice.lesson_type == "Lecture":
            lecture_days.setdefault(choice.module, set()).update(
                s.day for s in choice.sessions if not s.online
            )
    unpaired = []
    for (module, lesson_type), choice in assignment.items():
        if lesson_type == "Lecture":
            continue
        days = lecture_days.get(module)
        if not days:
            continue
        if not any(s.day in days for s in choice.sessions):
            abbrev = LESSON_ABBREV.get(lesson_type, lesson_type)
            unpaired.append((module, abbrev))
    for module, abbrev in sorted(unpaired):
        warnings.append(f"⚠ {module} {abbrev} not same-day as its lecture")

    # lunch: per day with no free block >= lunch_minutes in the lunch window
    # (campus sessions only; identical arithmetic to scoring's lunchless count)
    by_day: dict = {}
    for choice in assignment.values():
        for s in choice.sessions:
            if not s.online:
                by_day.setdefault(s.day, []).append(s)
    for day in sorted(by_day, key=DAYS.index):
        merged = _merged_intervals(by_day[day])
        free_blocks = []
        cursor = prefs.lunch_start
        for start, end in merged:
            if end <= prefs.lunch_start or start >= prefs.lunch_end:
                continue
            if start > cursor:
                free_blocks.append(start - cursor)
            cursor = max(cursor, end)
        if prefs.lunch_end > cursor:
            free_blocks.append(prefs.lunch_end - cursor)
        if max(free_blocks, default=0) < prefs.lunch_minutes:
            warnings.append(f"⚠ {day} has no lunch break")

    return warnings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_output.py -k class_warnings -v`
Expected: PASS (all eight `class_warnings` tests)

- [ ] **Step 5: Run the full suite (parity guard)**

Run: `.venv/bin/pytest -q`
Expected: PASS — every previously green test still passes.

- [ ] **Step 6: Commit**

```bash
git add optimiser/output.py tests/test_output.py
git commit -m "feat: class_warnings surfaces criteria a timetable fails"
```

---

### Task 3: Show legend + warnings in the TUI detail pane

**Files:**
- Modify: `optimiser/tui/app.py:15` (import), `optimiser/tui/app.py:147-165` (`_refresh_detail`)
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Consumes: `output.class_warnings(assignment, config) -> list[str]` (Task 2), already-rendered `render_breakdown` legend (Task 1).
- Produces: no new public interface; `_refresh_detail` now appends a warnings block after the week grid in timetable mode.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tui_app.py` (add `Static` to the existing `from textual.widgets import ...` line):

```python
async def test_warnings_show_in_timetable_mode_only(state, tmp_path, monkeypatch):
    from rich.console import Console
    from textual.widgets import Static

    monkeypatch.setattr("optimiser.tui.app.class_warnings", lambda a, c: ["⚠ SENTINEL"])
    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        detail = app.query_one("#detail", Static)
        console = Console()
        with console.capture() as cap:
            console.print(detail.renderable)
        assert "SENTINEL" in cap.get()  # timetable mode shows warnings
        await pilot.press("b")  # switch to ballot view
        with console.capture() as cap:
            console.print(detail.renderable)
        assert "SENTINEL" not in cap.get()  # ballot mode omits them


async def test_all_criteria_met_shown_when_no_warnings(state, tmp_path, monkeypatch):
    from rich.console import Console
    from textual.widgets import Static

    monkeypatch.setattr("optimiser.tui.app.class_warnings", lambda a, c: [])
    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        detail = app.query_one("#detail", Static)
        console = Console()
        with console.capture() as cap:
            console.print(detail.renderable)
        assert "all criteria met" in cap.get()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_tui_app.py -k "warnings or criteria" -v`
Expected: FAIL — `AttributeError: module 'optimiser.tui.app' has no attribute 'class_warnings'` (monkeypatch target missing).

- [ ] **Step 3: Import `class_warnings` in `app.py`**

Change the import line in `optimiser/tui/app.py` (currently `from ..output import render_breakdown, render_snake, share_url`) to:

```python
from ..output import class_warnings, render_breakdown, render_snake, share_url
```

- [ ] **Step 4: Append the warnings block in `_refresh_detail`**

Replace the timetable-mode tail of `_refresh_detail` (the `total, breakdown, assignment = top[self.selected]` block, lines 156-165) with:

```python
        total, breakdown, assignment = top[self.selected]
        warnings = class_warnings(assignment, self.state.config)
        if warnings:
            warning_block = Text("\n".join(warnings), style="dim yellow")
        else:
            warning_block = Text("✓ all criteria met", style="dim green")
        detail.update(
            Group(
                Text(render_breakdown(total, breakdown)),
                Text(""),
                render_week_rich(assignment, self.colours),
                Text(""),
                warning_block,
                Text(""),
                Text(share_url(assignment, self.state.config.semester)),
            )
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_tui_app.py -k "warnings or criteria" -v`
Expected: PASS (both new tests)

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS — all tests green.

- [ ] **Step 7: Commit**

```bash
git add optimiser/tui/app.py tests/test_tui_app.py
git commit -m "feat: show scoring legend and class warnings in the TUI detail pane"
```

---

## Notes for the implementer

- The `config` and `state` pytest fixtures come from `tests/conftest.py` and `tests/test_tui_app.py` respectively — do not redefine them.
- `_merged_intervals` and `COMPONENT_LEGEND` are imported from `optimiser.scoring` into `optimiser.output`. `scoring` imports nothing from `output`, so this is not a cycle (Task 1 Step 6 verifies).
- Warning message wording is asserted verbatim in tests; if you change wording, update the tests in the same commit.
- Run everything with the project venv: `.venv/bin/pytest`.
