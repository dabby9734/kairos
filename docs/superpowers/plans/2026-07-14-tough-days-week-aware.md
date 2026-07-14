# Week-Aware Tough Days Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `tough_days` scoring component (and its matching class-warning) week-aware, so that same-day sessions running in disjoint teaching weeks — e.g. a lab and a tutorial that alternate weeks — are not counted as simultaneous load.

**Architecture:** Extract a single shared helper `tough_day_peaks(choices, config)` in `optimiser/scoring.py` that returns, per over-cap day, the peak single-week difficulty. Both `score_assignment` (penalty) and `output.class_warnings` (warning) consume it, so scoring and warnings stay in lockstep (structural parity, not two hand-mirrored copies). A fast path keeps it cheap: the naive all-session daily sum is an upper bound on the weekly peak, so days already under the cap skip the per-week recount.

**Tech Stack:** Python ≥3.11, pytest. No new dependencies.

## Background — why this is correct and cheap

`scoring.score_assignment`'s current `tough_days` sums every session's module difficulty per day, ignoring which weeks each session runs. When a module schedules e.g. a Laboratory on weeks {1,2,4,…} and a Tutorial on weeks {3,5,9} on the same weekday (they never co-occur), the old code counts both, inflating that day's difficulty. Clash detection is already week-aware (`Session.clashes` intersects week sets), so such timetables are valid; only the difficulty aggregation was week-blind.

Week-aware peak = the maximum, over all teaching weeks, of the summed difficulty of the sessions active that week. Because the naive sum counts a superset of any single week's sessions, **naive_sum ≥ peak** always. Therefore a day whose naive sum is ≤ cap cannot have a week-aware peak > cap, and needs no per-week computation. Measured overhead of the shared helper vs. the old inline loop is ~1.15× on the component and ~3% on a full `score_assignment` call (benchmarked on a real 6-module timetable), because the per-week recount runs only on the rare days that breach the cap.

## Global Constraints

- **Parity:** `class_warnings`' tough-day check and `score_assignment`'s `tough_days` penalty must both derive from the SAME `tough_day_peaks` helper. A day is penalised iff it is warned, with the same peak value.
- `tough_days` counts ALL sessions including online (`Session.online`) — unchanged from today. (This differs from time_window/lunch, which exclude online — do not change those.)
- Difficulty per session is `config.difficulty(choice.module, choice.lesson_type)` where `lesson_type` is the full name (e.g. `"Tutorial"`).
- `Session.weeks` is a `frozenset` of ints (`optimiser/api.normalise_weeks` guarantees non-empty: a real list, else weeks 1–13). The helper must still not crash on an empty set (`max(..., default=0)`).
- Penalty formula unchanged in shape: `-sum(peak - cap)` over days whose peak exceeds `max_difficulty_per_day`. Warning message unchanged in shape: `⚠ {day} exceeds max difficulty ({peak} > {cap})` — but the reported number is now the weekly PEAK, not the naive sum.
- Behavior must be identical to today for any timetable whose same-day sessions all share the same weeks (the common case) — the existing `test_tough_days_counts_online` (all-weeks sessions) must still pass unchanged.
- No new dependencies. Run tests with `.venv/bin/pytest`.

---

### Task 1: `tough_day_peaks` helper + week-aware scoring

**Files:**
- Modify: `optimiser/scoring.py` (add `tough_day_peaks`; rewrite the `tough_days` block of `score_assignment`, currently lines ~37-44)
- Test: `tests/test_scoring.py`

**Interfaces:**
- Produces: `tough_day_peaks(choices, config) -> dict[str, int]` — maps each weekday whose week-aware peak difficulty exceeds `config.preferences.max_difficulty_per_day` to that peak value; days at or under the cap are absent. `choices` is any iterable of `Choice`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_scoring.py` (the `choice`, `sess`, `raw`, `ALL_WEEKS` helpers and the `config` fixture already exist there; `Choice` and `Session` are already imported):

```python
def test_tough_day_peaks_reports_peak_week(config):
    from optimiser.scoring import tough_day_peaks

    w13 = frozenset({1, 3})
    cs = [
        Choice("ALPHA", "Tutorial", "01", (Session("Monday", 600, 660, w13, "COM1"),)),
        Choice("BETA", "Laboratory", "L1", (Session("Monday", 720, 780, w13, "COM1"),)),
        Choice("BETA", "Recitation", "R1", (Session("Monday", 840, 900, w13, "COM1"),)),
    ]
    # cap is 8; all three share weeks 1&3, so week 1 load = 4+3+3 = 10.
    assert tough_day_peaks(cs, config) == {"Monday": 10}


def test_tough_days_week_aware_ignores_disjoint_weeks(config):
    # Naive Monday difficulty 4+3+3 = 10 > cap 8, but the diff-3 recitation runs on
    # weeks disjoint from the other two, so no single week exceeds 8 (peak = 7).
    w13 = frozenset({1, 3})
    w24 = frozenset({2, 4})
    cs = [
        choice("ALPHA", "Tutorial", "01", Session("Monday", 600, 660, w13, "COM1")),
        choice("BETA", "Laboratory", "L1", Session("Monday", 720, 780, w13, "COM1")),
        choice("BETA", "Recitation", "R1", Session("Monday", 840, 900, w24, "COM1")),
    ]
    assert raw(cs, config, "tough_days") == 0


def test_tough_days_week_aware_penalises_overlapping_weeks(config):
    # Same three classes, but the recitation now shares weeks 1&3 -> week 1 load is
    # 4+3+3 = 10 > cap 8 -> penalty of (10 - 8) = 2.
    w13 = frozenset({1, 3})
    cs = [
        choice("ALPHA", "Tutorial", "01", Session("Monday", 600, 660, w13, "COM1")),
        choice("BETA", "Laboratory", "L1", Session("Monday", 720, 780, w13, "COM1")),
        choice("BETA", "Recitation", "R1", Session("Monday", 840, 900, w13, "COM1")),
    ]
    assert raw(cs, config, "tough_days") == pytest.approx(-2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_scoring.py -k "tough_day_peaks or week_aware" -v`
Expected: FAIL — `test_tough_day_peaks_reports_peak_week` errors with `ImportError: cannot import name 'tough_day_peaks'`; the two `week_aware` tests fail because the current code sums all sessions (`raw` returns `-2` for the disjoint case, expected `0`).

- [ ] **Step 3: Add the `tough_day_peaks` helper**

In `optimiser/scoring.py`, add this function immediately after `_merged_intervals` (before `score_assignment`):

```python
def tough_day_peaks(choices, config) -> dict:
    """{day: peak_weekly_difficulty} for days whose week-aware peak exceeds
    max_difficulty_per_day. The peak is the largest, over all teaching weeks, of
    the summed difficulty of the sessions active that week — so alternating-week
    sessions on the same day (e.g. a lab and tutorial that never co-occur) are
    not double-counted. All sessions count, including online, as tough_days
    always has. Fast path: the naive all-session daily sum is an upper bound on
    the peak, so days whose naive sum is already <= cap cannot exceed it and skip
    the per-week recount."""
    cap = config.preferences.max_difficulty_per_day
    naive: dict = {}
    per_day: dict = {}
    for c in choices:
        difficulty = config.difficulty(c.module, c.lesson_type)
        for s in c.sessions:
            naive[s.day] = naive.get(s.day, 0) + difficulty
            per_day.setdefault(s.day, []).append((difficulty, s.weeks))
    peaks: dict = {}
    for day, total in naive.items():
        if total <= cap:
            continue
        by_week: dict = {}
        for difficulty, weeks in per_day[day]:
            for w in weeks:
                by_week[w] = by_week.get(w, 0) + difficulty
        peak = max(by_week.values(), default=0)
        if peak > cap:
            peaks[day] = peak
    return peaks
```

- [ ] **Step 4: Rewrite the `tough_days` block in `score_assignment`**

In `optimiser/scoring.py`, replace the current tough_days block (the `tough: dict = {}` loop and the `raw["tough_days"] = -sum(...)` that follows, currently ~lines 37-44):

```python
    tough: dict = {}
    for c in choices:
        difficulty = config.difficulty(c.module, c.lesson_type)
        for s in c.sessions:
            tough[s.day] = tough.get(s.day, 0) + difficulty
    raw["tough_days"] = -sum(
        max(0, total - prefs.max_difficulty_per_day) for total in tough.values()
    )
```

with:

```python
    raw["tough_days"] = -sum(
        peak - prefs.max_difficulty_per_day
        for peak in tough_day_peaks(choices, config).values()
    )
```

(`prefs = config.preferences` is already bound at the top of `score_assignment`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_scoring.py -v`
Expected: PASS — the three new tests plus every existing scoring test, including `test_tough_days_counts_online` (all-weeks sessions → peak equals naive sum → unchanged result).

- [ ] **Step 6: Commit**

```bash
git add optimiser/scoring.py tests/test_scoring.py
git commit -m "feat: week-aware tough_days via shared tough_day_peaks helper"
```

---

### Task 2: Week-aware tough-day warning (parity)

**Files:**
- Modify: `optimiser/output.py` (extend the scoring import; rewrite the `tough_days` block of `class_warnings`, currently lines ~83-93)
- Test: `tests/test_output.py`

**Interfaces:**
- Consumes: `scoring.tough_day_peaks(choices, config) -> dict[str, int]` (Task 1).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_output.py` (the `_choice`, `_sess`, `class_warnings`, `config` helpers/fixtures and the `Choice`/`Session` imports and `ALL_WEEKS` already exist there):

```python
def test_class_warnings_tough_day_week_aware_ignores_disjoint_weeks(config):
    # Naive Monday difficulty 10 > cap 8, but the recitation's weeks are disjoint
    # from the other two (peak week load 7) -> no tough-day warning (parity).
    w13 = frozenset({1, 3})
    w24 = frozenset({2, 4})
    a = {
        ("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", Session("Monday", 600, 660, w13, "COM1")),
        ("BETA", "Laboratory"): _choice("BETA", "Laboratory", "L1", Session("Monday", 720, 780, w13, "COM1")),
        ("BETA", "Recitation"): _choice("BETA", "Recitation", "R1", Session("Monday", 840, 900, w24, "COM1")),
    }
    assert not any("exceeds max difficulty" in w for w in class_warnings(a, config))


def test_class_warnings_tough_day_reports_peak_week(config):
    # Overlapping weeks: week 1 load 4+3+3 = 10 -> the warning names the peak (10),
    # not the naive all-session sum (also 10 here, but the message must be the peak).
    w13 = frozenset({1, 3})
    a = {
        ("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", Session("Monday", 600, 660, w13, "COM1")),
        ("BETA", "Laboratory"): _choice("BETA", "Laboratory", "L1", Session("Monday", 720, 780, w13, "COM1")),
        ("BETA", "Recitation"): _choice("BETA", "Recitation", "R1", Session("Monday", 840, 900, w13, "COM1")),
    }
    assert "⚠ Monday exceeds max difficulty (10 > 8)" in class_warnings(a, config)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_output.py -k "tough_day_week_aware or tough_day_reports_peak" -v`
Expected: FAIL — the disjoint-weeks test fails because the current `class_warnings` sums all sessions and emits a warning for Monday (10 > 8) that shouldn't be there.

- [ ] **Step 3: Extend the scoring import in `output.py`**

Change the existing import line (currently `from .scoring import COMPONENT_LEGEND, _merged_intervals`) to:

```python
from .scoring import COMPONENT_LEGEND, _merged_intervals, tough_day_peaks
```

- [ ] **Step 4: Rewrite the tough_days block of `class_warnings`**

In `optimiser/output.py`, replace the current tough_days block of `class_warnings` (the `tough: dict = {}` loop and the `for day in sorted(tough, ...)` warning loop, currently ~lines 83-93):

```python
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
```

with:

```python
    # tough_days: days whose week-aware PEAK difficulty exceeds the cap. Uses the
    # same tough_day_peaks helper as scoring, so a day is warned iff it is
    # penalised; the reported number is the peak single-week load, not the naive
    # all-session sum. All sessions count, including online.
    peaks = tough_day_peaks(assignment.values(), config)
    for day in sorted(peaks, key=DAYS.index):
        warnings.append(
            f"⚠ {day} exceeds max difficulty ({peaks[day]} > {prefs.max_difficulty_per_day})"
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_output.py -v`
Expected: PASS — the two new tests plus every existing output test, including `test_class_warnings_tough_day_counts_online` (all-weeks sessions → peak equals naive sum → same `9 > 8` warning as before).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS — all tests green (no scoring/output regressions).

- [ ] **Step 7: Commit**

```bash
git add optimiser/output.py tests/test_output.py
git commit -m "fix: tough-day warnings match week-aware scoring"
```

---

## Self-review notes

- **Coverage:** the shared-helper design (Global Constraint: parity) is implemented in Task 1 and consumed in Task 2; the fast-path is in the helper; behavior-preservation for whole-semester weeks is asserted by the untouched `*_counts_online` tests in both suites.
- **No placeholders:** every step carries complete code and exact commands.
- **Type consistency:** `tough_day_peaks(choices, config) -> dict[str, int]` is defined in Task 1 and called with a list (`score_assignment`) and with `dict_values` (`class_warnings`) — both iterables of `Choice`, matching the signature.
