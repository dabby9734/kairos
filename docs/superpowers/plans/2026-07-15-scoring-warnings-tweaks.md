# Scoring & Warnings Tweaks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make lunch breaks a −2/day penalty, show all TUI warnings in a dedicated scrollable pane, let a weight of 0 disable a component's warnings, and stop penalising/warning module pairings that are impossible because the offered slots never share a day.

**Architecture:** Four independent changes. (1) A one-line raw-value bump in `scoring.py`. (2) A shared `pairing_impossibility(members)` helper in `scoring.py` consumed by both scoring (`compute_raw`/`score_raw`) and warnings (`class_warnings`), so a suppressed warning always corresponds to a scoring change. (3) Weight-0 guards + impossible-slot suppression in `class_warnings`. (4) A `VerticalScroll` warnings pane in the TUI that calls `class_warnings` with the space.

**Tech Stack:** Python 3.13, pytest, Textual. No new third-party dependencies.

## Global Constraints

- No new third-party dependencies.
- `class_warnings(assignment, config, space=None)` and `compute_raw(choices, config, unpairable_modules=frozenset())` MUST be behavior-preserving when the new optional argument is omitted — every non-TUI caller and existing test relies on the default.
- Scoring and warnings must stay mirrored: both derive impossibility from `space.members` via the same `pairing_impossibility` helper.
- Impossibility is defined over **offered campus (non-online) days** from `space.members`, not over the ~60k clash-free combos.
- An unpairable module contributes a constant to every arrangement, so ranking/ballot order is unchanged; only absolute scores shift.

---

### Task 1: Lunch penalty −2 per lunchless day

**Files:**
- Modify: `optimiser/scoring.py:117`
- Test: `tests/test_scoring.py:78-84`

**Interfaces:**
- Produces: `compute_raw` returns `raw["lunch"] == -2 * lunchless` (was `-1 * lunchless`).

- [ ] **Step 1: Update the failing test**

In `tests/test_scoring.py`, change `test_lunch_penalty` (lines 78-84) so the blocked-day case expects `-2`:

```python
def test_lunch_penalty(config):
    # 11:00-14:00 solid class -> no lunch block -> raw -2 (lunch is critical)
    blocked = [choice("ALPHA", "Lecture", "1", sess("Monday", 660, 840))]
    assert raw(blocked, config, "lunch") == -2
    # 11:00-12:00 class leaves 12:00-14:00 free -> ok
    fine = [choice("ALPHA", "Lecture", "1", sess("Monday", 660, 720))]
    assert raw(fine, config, "lunch") == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_scoring.py::test_lunch_penalty -v`
Expected: FAIL — `assert -1 == -2`.

- [ ] **Step 3: Change the raw lunch penalty**

In `optimiser/scoring.py`, line 117, inside `compute_raw`:

```python
    raw["gaps"] = -gap_minutes / 60
    raw["lunch"] = -2 * lunchless
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_scoring.py::test_lunch_penalty -v`
Expected: PASS.

- [ ] **Step 5: Run the scoring suite and fix any incidental lunch-dependent expectations**

Run: `.venv/bin/python -m pytest tests/test_scoring.py -q`
Expected: PASS. `test_total_is_weighted_sum` uses a 09:00-11:00 class (lunch 11:00-14:00 free → lunch raw 0), so it is unaffected. If any other test that asserts an absolute total involves a lunchless day, update the expected number to reflect the doubled penalty and add a one-line comment noting the −2/day change.

- [ ] **Step 6: Commit**

```bash
git add optimiser/scoring.py tests/test_scoring.py
git commit -m "feat: lunch penalty is -2 per lunchless day"
```

---

### Task 2: `pairing_impossibility` helper + scoring counts unpairable modules as satisfied

**Files:**
- Modify: `optimiser/scoring.py` (add `pairing_impossibility` after `tough_day_peaks`, ends line 56; change `compute_raw` signature line 59 and the `same_day_pairing` line 94)
- Modify: `optimiser/search.py` (import from `.scoring` line 8; `score_raw` lines 109-117)
- Test: `tests/test_scoring.py`

**Interfaces:**
- Produces:
  - `pairing_impossibility(members) -> tuple[frozenset, frozenset]` — from `space.members` (`(module, lesson_type) -> {footprint: [Choice]}`), returns `(unpairable_modules, unpairable_slots)`. `unpairable_modules`: modules with a campus lecture whose non-lecture slots can NONE fall on a lecture day. `unpairable_slots`: `(module, lesson_type)` non-lecture slots that can never reach a lecture day.
  - `compute_raw(choices, config, unpairable_modules=frozenset())` — `same_day_pairing` counts `paired_modules | unpairable_modules`.
- Consumes: `score_raw(space, config)` computes `unpairable_modules` once via `pairing_impossibility(space.members)` and passes it to every `compute_raw` call.

- [ ] **Step 1: Write the failing tests**

Add to the end of `tests/test_scoring.py` (helpers `choice`, `sess`, `ALL_WEEKS` already exist at the top):

```python
def _members(*choices):
    # Mirror space.members: (module, lesson_type) -> {footprint: [Choice]}
    members: dict = {}
    for c in choices:
        members.setdefault((c.module, c.lesson_type), {}).setdefault(c.footprint, []).append(c)
    return members


def test_pairing_impossibility_flags_disjoint_module():
    from optimiser.scoring import pairing_impossibility

    lec = choice("ALPHA", "Lecture", "1", sess("Monday", 600, 720))
    tut = choice("ALPHA", "Tutorial", "01", sess("Tuesday", 840, 900))  # never Monday
    unpair_mods, unpair_slots = pairing_impossibility(_members(lec, tut))
    assert unpair_mods == frozenset({"ALPHA"})
    assert unpair_slots == frozenset({("ALPHA", "Tutorial")})


def test_pairing_impossibility_pairable_module_is_empty():
    from optimiser.scoring import pairing_impossibility

    lec = choice("ALPHA", "Lecture", "1", sess("Monday", 600, 720))
    tut = choice("ALPHA", "Tutorial", "01", sess("Monday", 840, 900))  # shares Monday
    unpair_mods, unpair_slots = pairing_impossibility(_members(lec, tut))
    assert unpair_mods == frozenset()
    assert unpair_slots == frozenset()


def test_pairing_impossibility_mixed_flags_only_impossible_slot():
    from optimiser.scoring import pairing_impossibility

    lec = choice("ALPHA", "Lecture", "1", sess("Monday", 600, 720))
    tut = choice("ALPHA", "Tutorial", "01", sess("Monday", 840, 900))   # pairable
    lab = choice("ALPHA", "Laboratory", "L1", sess("Tuesday", 840, 900))  # impossible
    unpair_mods, unpair_slots = pairing_impossibility(_members(lec, tut, lab))
    assert unpair_mods == frozenset()  # module can still pair via the tutorial
    assert unpair_slots == frozenset({("ALPHA", "Laboratory")})


def test_pairing_impossibility_ignores_online_lecture():
    from optimiser.scoring import pairing_impossibility

    online_lec = choice("ALPHA", "Lecture", "1", sess("Monday", 600, 720, venue="E-Learn_C"))
    tut = choice("ALPHA", "Tutorial", "01", sess("Tuesday", 840, 900))
    unpair_mods, unpair_slots = pairing_impossibility(_members(online_lec, tut))
    # no campus lecture -> pairing does not apply -> nothing flagged
    assert unpair_mods == frozenset()
    assert unpair_slots == frozenset()


def test_compute_raw_counts_unpairable_module_as_satisfied():
    from optimiser.scoring import compute_raw

    lec = choice("ALPHA", "Lecture", "1", sess("Monday", 600, 720))
    tut = choice("ALPHA", "Tutorial", "01", sess("Tuesday", 840, 900))  # does not pair
    cs = [lec, tut]
    # default: unpaired -> 0
    assert compute_raw(cs, config_stub())["same_day_pairing"] == 0
    # declared unpairable -> counts as satisfied (no penalty)
    assert compute_raw(cs, config_stub(), frozenset({"ALPHA"}))["same_day_pairing"] == 1
```

Add this small config stub near the top of `tests/test_scoring.py` (after the imports) — `compute_raw` only reads `config.preferences` and `config.difficulty`, and this fixture-free helper keeps the new tests independent of the `config` fixture:

```python
def config_stub():
    from optimiser.config import DEFAULT_PREFERENCES, Config, Preferences

    return Config(
        acad_year="2026-2027", semester=1,
        balloted_types=["TUT", "LAB", "REC", "SEC"],
        modules={"ALPHA": 3}, fixed={}, priority=["ALPHA"],
        preferences=Preferences(
            earliest_start=600, latest_end=1080, max_difficulty_per_day=8,
            lunch_start=660, lunch_end=840, lunch_minutes=60,
            weights=dict(DEFAULT_PREFERENCES["weights"]),
        ),
        alternatives_per_module=4, top_n=5,
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_scoring.py -k "pairing_impossibility or unpairable" -v`
Expected: FAIL — `ImportError: cannot import name 'pairing_impossibility'` / `compute_raw() takes 2 positional arguments but 3 were given`.

- [ ] **Step 3: Add `pairing_impossibility` to `scoring.py`**

In `optimiser/scoring.py`, immediately after `tough_day_peaks` (ends line 56), add:

```python
def pairing_impossibility(members):
    """From space.members ((module, lesson_type) -> {footprint: [Choice]}),
    find pairings that can never occur because the offered slots share no campus
    day. Returns (unpairable_modules, unpairable_slots):
      - unpairable_modules: modules WITH a campus lecture whose non-lecture slots
        can NONE fall on a lecture day -> scoring counts them as satisfied.
      - unpairable_slots: {(module, lesson_type)} non-lecture slots that can never
        reach a lecture day -> their same-day warning is suppressed.
    Days are taken over offered campus (non-online) sessions, matching the
    same_day_pairing criterion (which ignores online lectures)."""
    lec_days: dict = {}   # module -> set of campus days its lecture is offered on
    slot_days: dict = {}  # (module, lesson_type) -> set of campus days offered
    for (module, lesson_type), by_fp in members.items():
        days = {
            s.day
            for choices in by_fp.values()
            for c in choices
            for s in c.sessions
            if not s.online
        }
        if lesson_type == "Lecture":
            lec_days.setdefault(module, set()).update(days)
        else:
            slot_days.setdefault((module, lesson_type), set()).update(days)

    unpairable_slots = set()
    pairable_by_module: dict = {}  # module -> any non-lecture slot pairable?
    for (module, lesson_type), days in slot_days.items():
        ld = lec_days.get(module)
        pairable = bool(ld) and bool(days & ld)
        if ld and not pairable:
            unpairable_slots.add((module, lesson_type))
        if ld:
            pairable_by_module[module] = pairable_by_module.get(module, False) or pairable

    unpairable_modules = frozenset(
        module for module, pairable in pairable_by_module.items() if not pairable
    )
    return unpairable_modules, frozenset(unpairable_slots)
```

- [ ] **Step 4: Thread `unpairable_modules` through `compute_raw`**

In `optimiser/scoring.py`, change the `compute_raw` signature (line 59) and the `same_day_pairing` assignment (line 94):

```python
def compute_raw(choices, config, unpairable_modules=frozenset()) -> dict:
```

```python
    raw["same_day_pairing"] = len(paired_modules | unpairable_modules)
```

(`paired_modules` is already a `set` a few lines above, so the union is valid.)

- [ ] **Step 5: Compute and pass it in `score_raw`**

In `optimiser/search.py`, extend the scoring import (line 8):

```python
from .scoring import compute_raw, pairing_impossibility, weight_raw
```

Change `score_raw` (lines 109-117) to compute the set once and pass it to every combo:

```python
def score_raw(space: EnumeratedSpace, config) -> list:
    """The expensive, weight-INDEPENDENT scoring pass: compute each combo's raw
    criteria once. Cache this; a weight change only needs weight_scored (below)."""
    unpairable_modules, _ = pairing_impossibility(space.members)
    entries = []
    for combo in space.combos:
        raw = compute_raw(list(combo), config, unpairable_modules)
        assignment = {(c.module, c.lesson_type): c for c in combo}
        entries.append((raw, assignment, combo))
    return entries
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_scoring.py -q`
Expected: PASS. Existing pairing tests use `score_assignment` (default empty `unpairable_modules`) and the standard fixtures where ALPHA can pair (tutorial 01 on Monday shares the Monday lecture), so no existing expectation shifts.

- [ ] **Step 7: Run the search/state suites and fix any incidental score expectations**

Run: `.venv/bin/python -m pytest tests/test_search.py tests/test_tui_state.py -q`
Expected: PASS. The default `alpha_json`/`beta_json` space has no fully-unpairable module (ALPHA pairs on Monday; BETA's lecture is online, so it has no campus lecture and is never flagged), so `unpairable_modules` is empty and scores are unchanged. If a fixture with a campus-lecture module whose non-lecture slots never share the lecture day surfaces, update the expected `same_day_pairing`/total to the corrected value with a comment.

- [ ] **Step 8: Commit**

```bash
git add optimiser/scoring.py optimiser/search.py tests/test_scoring.py
git commit -m "feat: impossible pairings count as satisfied (no penalty)"
```

---

### Task 3: `class_warnings` — weight-0 disable + impossible-slot suppression

**Files:**
- Modify: `optimiser/output.py:58-145` (`class_warnings`)
- Test: `tests/test_output.py`

**Interfaces:**
- Consumes: `pairing_impossibility` from Task 2.
- Produces: `class_warnings(assignment, config, space=None) -> list[str]`. Each of the four warning blocks (`time_window`, `tough_days`, `same_day_pairing`, `lunch`) is skipped when its weight is 0. When `space` is given, `same_day_pairing` warnings for `(module, lesson_type)` in `unpairable_slots` are suppressed. `space=None` reproduces today's behavior exactly.

- [ ] **Step 1: Write the failing tests**

Add to the end of `tests/test_output.py`. The existing tests there build an `assignment` dict `{(module, lesson_type): Choice}`; reuse that shape. Import helpers as the existing tests do (check the top of the file for `choice`/`sess`-style helpers; if the file builds Choices inline, mirror that style).

```python
def test_class_warnings_suppressed_when_weight_zero(config):
    import copy

    from optimiser.model import Choice, Session

    all_weeks = frozenset(range(1, 14))
    # 11:00-14:00 solid ALPHA lecture -> normally a lunch warning
    a = {("ALPHA", "Lecture"): Choice("ALPHA", "Lecture", "1",
         (Session("Monday", 660, 840, all_weeks, "COM1"),))}
    assert any("lunch" in w for w in class_warnings(a, config))
    off = copy.deepcopy(config)
    off.preferences.weights["lunch"] = 0
    assert not any("lunch" in w for w in class_warnings(a, off))


def test_class_warnings_pairing_suppressed_when_weight_zero(config):
    import copy

    from optimiser.model import Choice, Session

    all_weeks = frozenset(range(1, 14))
    a = {
        ("ALPHA", "Lecture"): Choice("ALPHA", "Lecture", "1",
            (Session("Monday", 600, 720, all_weeks, "COM1"),)),
        ("ALPHA", "Tutorial"): Choice("ALPHA", "Tutorial", "01",
            (Session("Tuesday", 540, 600, all_weeks, "COM1"),)),
    }
    assert any("same-day" in w for w in class_warnings(a, config))
    off = copy.deepcopy(config)
    off.preferences.weights["same_day_pairing"] = 0
    assert not any("same-day" in w for w in class_warnings(a, off))


def test_class_warnings_pairing_suppressed_when_impossible(config):
    from optimiser.model import Choice, Session
    from optimiser.search import EnumeratedSpace

    all_weeks = frozenset(range(1, 14))
    lec = Choice("ALPHA", "Lecture", "1", (Session("Monday", 600, 720, all_weeks, "COM1"),))
    tut = Choice("ALPHA", "Tutorial", "01", (Session("Tuesday", 540, 600, all_weeks, "COM1"),))
    a = {("ALPHA", "Lecture"): lec, ("ALPHA", "Tutorial"): tut}
    # Offered slots: lecture only Monday, tutorial only Tuesday -> pairing impossible.
    members = {
        ("ALPHA", "Lecture"): {lec.footprint: [lec]},
        ("ALPHA", "Tutorial"): {tut.footprint: [tut]},
    }
    space = EnumeratedSpace(combos=(), members=members)
    # Without space: warns as before.
    assert any("same-day" in w for w in class_warnings(a, config))
    # With space: the impossible pairing is suppressed.
    assert not any("same-day" in w for w in class_warnings(a, config, space=space))


def test_class_warnings_pairing_mixed_suppresses_only_impossible(config):
    from optimiser.model import Choice, Session
    from optimiser.search import EnumeratedSpace

    all_weeks = frozenset(range(1, 14))
    lec = Choice("ALPHA", "Lecture", "1", (Session("Monday", 600, 720, all_weeks, "COM1"),))
    # Tutorial offered Monday (pairable) but placed Tuesday here; lab offered only Tuesday.
    tut = Choice("ALPHA", "Tutorial", "01", (Session("Tuesday", 540, 600, all_weeks, "COM1"),))
    tut_mon = Choice("ALPHA", "Tutorial", "02", (Session("Monday", 780, 840, all_weeks, "COM1"),))
    lab = Choice("ALPHA", "Laboratory", "L1", (Session("Tuesday", 780, 840, all_weeks, "COM1"),))
    a = {
        ("ALPHA", "Lecture"): lec,
        ("ALPHA", "Tutorial"): tut,
        ("ALPHA", "Laboratory"): lab,
    }
    members = {
        ("ALPHA", "Lecture"): {lec.footprint: [lec]},
        ("ALPHA", "Tutorial"): {tut.footprint: [tut], tut_mon.footprint: [tut_mon]},
        ("ALPHA", "Laboratory"): {lab.footprint: [lab]},
    }
    space = EnumeratedSpace(combos=(), members=members)
    warnings = class_warnings(a, config, space=space)
    # Tutorial CAN pair (offered Monday) -> still warned; Lab can't -> suppressed.
    assert any("ALPHA TUT" in w and "same-day" in w for w in warnings)
    assert not any("ALPHA LAB" in w and "same-day" in w for w in warnings)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_output.py -k "weight_zero or impossible or mixed" -v`
Expected: FAIL — weight-0 cases still warn; `space=` cases still warn (and `class_warnings` rejects the `space` kwarg).

- [ ] **Step 3: Add the import**

In `optimiser/output.py`, extend the scoring import (line 4):

```python
from .scoring import COMPONENT_LEGEND, _merged_intervals, pairing_impossibility, tough_day_peaks
```

- [ ] **Step 4: Rewrite `class_warnings` with weight guards and impossible-slot suppression**

Replace `class_warnings` (lines 58-145) with the version below. Changes from today: signature gains `space=None`; `weights` is read once; each block is wrapped in a weight-0 guard; the `same_day_pairing` block skips `unpairable_slots`. Everything else is byte-for-byte the current logic.

```python
def class_warnings(assignment: dict, config, space=None) -> list[str]:
    """Human-readable warnings for classes/days that fail the user's criteria in
    this timetable. Each check mirrors scoring.score_assignment so warnings and
    score never disagree. free_days (a bonus) and gaps (an aggregate) produce no
    per-class warning. A component whose weight is 0 is disabled: it produces no
    warnings. When `space` is given, same_day_pairing warnings are suppressed for
    slots that can never share a lecture day (the pairing is impossible, not a
    fixable problem). Returns [] when nothing is violated."""
    prefs = config.preferences
    weights = prefs.weights
    warnings: list[str] = []

    # time_window: campus sessions starting early / ending late (online excluded)
    if weights.get("time_window", 0) != 0:
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

    # tough_days: days whose week-aware PEAK difficulty exceeds the cap.
    if weights.get("tough_days", 0) != 0:
        peaks = tough_day_peaks(assignment.values(), config)
        for day in sorted(peaks, key=DAYS.index):
            warnings.append(
                f"⚠ {day} exceeds max difficulty ({peaks[day]} > {prefs.max_difficulty_per_day})"
            )

    # same_day_pairing: mirror scoring's per-MODULE bonus (capped 1/module). Warn
    # only for modules that earn ZERO pairing, and skip slots that can never share
    # a lecture day (unpairable_slots) — those pairings are impossible, not fixable.
    if weights.get("same_day_pairing", 0) != 0:
        unpairable_slots = frozenset()
        if space is not None:
            _unpair_mods, unpairable_slots = pairing_impossibility(space.members)
        lecture_days: dict = {}
        for choice in assignment.values():
            if choice.lesson_type == "Lecture":
                lecture_days.setdefault(choice.module, set()).update(
                    s.day for s in choice.sessions if not s.online
                )
        nonlecture_by_module: dict = {}
        for (module, lesson_type), choice in assignment.items():
            if lesson_type == "Lecture":
                continue
            nonlecture_by_module.setdefault(module, []).append((lesson_type, choice))
        unpaired = []
        for module, classes in nonlecture_by_module.items():
            days = lecture_days.get(module)
            if not days:
                continue
            if any(s.day in days for _, choice in classes for s in choice.sessions):
                continue  # module already earns its pairing bonus; score is maxed
            for lesson_type, _ in classes:
                if (module, lesson_type) in unpairable_slots:
                    continue  # pairing impossible: no penalty, no warning
                abbrev = LESSON_ABBREV.get(lesson_type, lesson_type)
                unpaired.append((module, abbrev))
        for module, abbrev in sorted(unpaired):
            warnings.append(f"⚠ {module} {abbrev} not same-day as its lecture")

    # lunch: per day with no free block >= lunch_minutes in the lunch window
    if weights.get("lunch", 0) != 0:
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

- [ ] **Step 5: Run the output suite to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_output.py -q`
Expected: PASS — the four new tests plus every existing `class_warnings` test (which call `class_warnings(a, config)` with all default positive weights and no `space`, so they are unaffected).

- [ ] **Step 6: Commit**

```bash
git add optimiser/output.py tests/test_output.py
git commit -m "feat: weight-0 disables warnings; suppress impossible same-day pairings"
```

---

### Task 4: TUI dedicated scrollable warnings pane

**Files:**
- Modify: `optimiser/tui/app.py` (`CSS` lines 78-84; `compose` results block lines 144-147; `_refresh_detail` lines 183-211)
- Test: `tests/test_tui_app.py` (`test_warnings_show_in_timetable_mode_only` lines 121-136; `test_all_criteria_met_shown_when_no_warnings` lines 196-207)

**Interfaces:**
- Consumes: `class_warnings(assignment, config, space=...)` from Task 3.
- Produces: a `VerticalScroll(id="warnings")` containing `Static(id="warnings-text")`, populated by `_refresh_detail`; `#detail` no longer contains warnings.

- [ ] **Step 1: Update the two affected TUI tests**

In `tests/test_tui_app.py`, replace `test_warnings_show_in_timetable_mode_only` (lines 121-136) with a version that reads the new pane and uses the new 3-arg signature:

```python
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
```

Replace `test_all_criteria_met_shown_when_no_warnings` (lines 196-207) with:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest "tests/test_tui_app.py::test_warnings_show_in_timetable_mode_only" "tests/test_tui_app.py::test_all_criteria_met_shown_when_no_warnings" -v`
Expected: FAIL — no `#warnings-text` widget exists yet (`NoMatches`).

- [ ] **Step 3: Add the warnings pane to the CSS and compose**

In `optimiser/tui/app.py`, update the `CSS` block (lines 78-84):

```python
    CSS = """
    #controls { width: 42; }
    #results { width: 1fr; }
    #tt-list { height: 25%; }
    #slot-list { height: 15%; }
    #detail { height: 1fr; }
    #warnings { height: 30%; border: round $primary; }
    """
```

In `compose`, update the `#results` block (lines 144-147) to add the pane after `#detail`:

```python
            with Vertical(id="results"):
                yield ListView(id="tt-list")
                yield ListView(id="slot-list")
                yield Static(id="detail")
                warnings = VerticalScroll(Static(id="warnings-text"), id="warnings")
                warnings.border_title = "Warnings"
                yield warnings
```

(`VerticalScroll` and `Static` are already imported at the top of the file.)

- [ ] **Step 4: Update `_refresh_detail` to populate the pane and drop warnings from `#detail`**

Replace `_refresh_detail` (lines 183-211) with:

```python
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
```

- [ ] **Step 5: Run the TUI suite to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_tui_app.py -q`
Expected: PASS — the two updated tests plus the rest. `test_detail_shows_bids_block` still passes because bids remain in `#detail`.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (whole suite).

- [ ] **Step 7: Commit**

```bash
git add optimiser/tui/app.py tests/test_tui_app.py
git commit -m "feat: TUI shows warnings in a dedicated scrollable pane"
```

---

## Self-Review

**Spec coverage:**
- Feature 1 (lunch −2/day) → Task 1. ✓
- Feature 2 (dedicated scrollable warnings pane; empty in ballot mode; pass space) → Task 4. ✓
- Feature 3a (weight 0 disables warnings, all four blocks) → Task 3 Step 4. ✓
- Feature 3b (impossible pairings: no penalty via `compute_raw`/`score_raw`; no warning via `class_warnings`; shared `pairing_impossibility` from `space.members`) → Task 2 (scoring) + Task 3 (warnings). ✓
- Out-of-scope items (no `lunch_penalty` key, no `disabled:` list, no "(off)" annotation, no clash-aware pairability) → correctly not planned. ✓

**Placeholder scan:** clean — every code and test step is concrete. The two "fix incidental expectations" steps (Task 1 Step 5, Task 2 Step 7) name the exact fixtures, explain why the common fixtures are unaffected, and specify what to change if a shift appears; they are verification-with-contingency, not deferred work.

**Type consistency:** `pairing_impossibility(members) -> (frozenset, frozenset)` (Task 2 Step 3) is consumed as `unpairable_modules, _` in `score_raw` (Task 2 Step 5) and `_unpair_mods, unpairable_slots` in `class_warnings` (Task 3 Step 4) — matching the 2-tuple. `compute_raw(choices, config, unpairable_modules=frozenset())` (Task 2 Step 4) is called with the third positional arg only in `score_raw` (Task 2 Step 5) and defaulted everywhere else. `class_warnings(assignment, config, space=None)` (Task 3 Step 4) is called with `space=self.state.space` in `_refresh_detail` (Task 4 Step 4) and monkeypatched as `lambda a, c, space=None` (Task 4 Step 1). Widget ids `#warnings` / `#warnings-text` are defined in `compose` (Task 4 Step 3) and read in `_refresh_detail` and both tests (Task 4 Steps 1, 4). Consistent throughout.

**Mirror-invariant check:** scoring counts `paired_modules | unpairable_modules` (Task 2) and warnings suppress `unpairable_slots` (Task 3); both derive from `space.members` via `pairing_impossibility`. A fully-unpairable module is in `unpairable_modules` (scored satisfied) and all its slots are in `unpairable_slots` (no warning), so score and warnings agree.
