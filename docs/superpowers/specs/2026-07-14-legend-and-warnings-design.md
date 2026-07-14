# Scoring Legend & Class Warnings — Design

**Date:** 2026-07-14
**Status:** Approved

## Goal

Make the TUI's scoring self-explanatory and surface where a timetable falls
short of the user's preferences:

1. **Legend** — explain what each scoring component means, inline in the
   breakdown shown in the detail pane.
2. **Warnings** — a list, per selected timetable, naming the specific classes
   (and days) that couldn't be matched to their criteria.

Both features are additive to the existing pure core + thin Textual layer. No
new widgets, no new app state.

## Feature 1: Scoring legend (inline)

The six scoring components (`free_days`, `gaps`, `lunch`, `same_day_pairing`,
`time_window`, `tough_days`) are computed in `scoring.score_assignment` and
rendered by `output.render_breakdown`. Users currently see the component names
with raw/weighted values but no explanation.

**Change:**

- Add a `COMPONENT_LEGEND: dict[str, str]` in `scoring.py`, one short
  human-readable description per component. It lives next to the raw-value
  definitions so description and computation stay in sync. Each description
  carries its own direction hint in prose (e.g. "(more = better)",
  "(fewer = better)").
- `output.render_breakdown` appends the description to each component line as a
  trailing `  — <description>`, keeping the existing raw/weighted alignment.

Example output:

```
score: +4.20
  free_days          raw +2.00  weighted +4.00  — whole free weekdays (more = better)
  gaps               raw -0.50  weighted -0.50  — idle hours between classes (fewer = better)
  lunch              raw -1.00  weighted -1.00  — days with no lunch break
  ...
```

`render_breakdown` reads descriptions from `COMPONENT_LEGEND` by component name;
a missing key falls back to no trailing description (defensive, so an unknown
future component never breaks rendering).

## Feature 2: Class warnings

A new pure function:

```python
def class_warnings(assignment: dict, config) -> list[str]
```

lives in `output.py` (it produces display strings and reads `LESSON_ABBREV` /
`fmt_time` already imported there). It returns human-readable warning lines for
the selected timetable, checking four criteria. Each check **mirrors exactly how
`score_assignment` computes the corresponding penalty**, so warnings never
disagree with the score.

| Criterion          | Granularity | Warning condition (matches scoring) |
|--------------------|-------------|-------------------------------------|
| `time_window`      | per session | A **campus** session (online excluded, as in scoring) starting before `earliest_start` or ending after `latest_end`. |
| `tough_days`       | per day     | A day whose total difficulty — summed over **all** sessions incl. online, as in scoring — exceeds `max_difficulty_per_day`. |
| `same_day_pairing` | per class   | A non-lecture class whose module **has a campus lecture** but the class is on none of that lecture's days. Modules with no campus lecture are skipped (pairing is impossible, not a violation). |
| `lunch`            | per day     | A day with no free block ≥ `lunch_minutes` within `[lunch_start, lunch_end]`, computed the same way as scoring's `lunchless`. |

`free_days` (a bonus) and `gaps` (an aggregate with no single responsible class)
produce no warnings.

**Message formats** (illustrative):

```
⚠ CS3230 LEC Mon 0800 starts before your earliest 0900
⚠ CS3230 LEC Fri 1900 ends after your latest 1800
⚠ Wednesday exceeds max difficulty (7 > 5)
⚠ CS2103 TUT not same-day as its lecture
⚠ Thursday has no lunch break
```

Ordering: by day then time where a session is named; day-level warnings
(tough_days, lunch) grouped in weekday order. Exact ordering is a detail for the
implementation plan; determinism (stable across identical input) is the
requirement.

Empty result → the caller shows a single `✓ all criteria met` line.

## Feature 3: Wiring in the TUI

`OptimiserApp._refresh_detail` (in `optimiser/tui/app.py`) currently builds a
Rich `Group` of: breakdown, week grid, share URL. In **timetable mode** (not
ballot mode), it appends after the week grid:

- a blank line, then
- either the warning lines (each a `Text` styled dim yellow) or the single
  `✓ all criteria met` line (styled dim green),

built from `class_warnings(assignment, self.state.config)`.

Ballot mode is unchanged. No new bindings, widgets, or state.

## Testing

New tests in `tests/`, following the existing pure-core pattern:

- `class_warnings`: one focused test per criterion — a fixture that violates it
  yields the expected warning string; a clean fixture yields `[]`. Include a
  case proving online sessions are excluded from `time_window` but counted in
  `tough_days` (guards the scoring-parity invariant), and a case proving a
  module with no campus lecture produces no `same_day_pairing` warning.
- `render_breakdown`: assert each component line carries its `COMPONENT_LEGEND`
  description.

## Out of scope

- No warnings for `gaps`/`free_days`.
- No interactivity on warnings (no click-to-jump, no filtering).
- Ballot view is untouched.
