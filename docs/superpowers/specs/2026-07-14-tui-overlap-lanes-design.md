# TUI Week Grid — Overlap Lanes Design

**Date:** 2026-07-14
**Status:** Approved

## Problem

`render_week_rich` (in `optimiser/tui/render.py`) draws each weekday as a single
strip row: coloured bars laid left-to-right with a cursor that never draws
backwards. When two classes occupy the same hour cell(s) — which happens for
non-clashing **alternating-week** classes (e.g. a lab on even weeks and a
tutorial on odd weeks sharing 14:00–17:00, or two different modules whose
fortnightly slots land on the same hour) — only the first gets a coloured bar.
The second is clamped to `span_end <= span_start` and dropped from the strip.
It survives only in the agenda text below the day (an earlier fix guaranteed the
agenda never loses it), so the user sees the agenda line but no bar.

Because the optimiser forbids real clashes, **every** overlap that reaches the
grid is a genuine non-clashing alternating-weeks pair — safe to display in
parallel.

## Solution: lane-based rendering

Replace each day's single strip row with **1–N lane rows**, computed by greedy
interval partitioning (the standard minimum-tracks algorithm for overlapping
intervals). Each class gets a full coloured bar in some lane.

Example (Tuesday: PC1201 LEC 12–14, EG1311 LAB 15–17, PC1201 TUT 16–17 where
LAB and TUT alternate weeks):

```
Tue          PC1201 [LEC]            EG1311 [LAB]
                                     PC1201 [TUT]
   1200-1400 PC1201 LEC[1] @LT26
   1500-1700 EG1311 LAB[11] @E4-02-06
   1600-1700 PC1201 TUT[5] @S11-0301
```

### Algorithm

For each weekday:

1. Build the day's blocks exactly as today: `(start_h, end_h, module, abbrev,
   class_no, venue, online, start, end)`, where `start_h = start // 60` and
   `end_h = (end + 59) // 60`. Record every block in the agenda first (preserving
   the "never lose a class" invariant).
2. Sort blocks by `(start_h, start)`.
3. **Lane assignment (first-fit):** maintain a list of lanes, each tracking its
   own `cursor` (next free hour cell, initialised to `first_hour`). For each
   block, compute its drawable span (see step 4) and place it in the **first lane
   whose `cursor <= span_start`**; if no existing lane qualifies, append a new
   lane. First-fit from the top of the lane list, so lane order is deterministic.
4. **Drawable span (unchanged from today, applied per lane):**
   `span_start = max(start_h, first_hour, lane.cursor)`,
   `span_end = min(end_h, last_hour + 1)`. If `span_end <= span_start` the block
   is undrawable in the grid — it is **not** assigned a lane, but it is already in
   the agenda, so it is never lost. (This keeps the current out-of-range/edge
   behaviour.)
   - Note: because lane assignment considers `lane.cursor`, and a block only
     joins a lane whose cursor `<= span_start`, the clamp `max(..., lane.cursor)`
     never actually pushes a block forward within its chosen lane — the drift
     clamp still guards the half-hour back-to-back case *within* a lane exactly
     as today.
5. **Render:** one `Text` row per lane. The **first lane** row is prefixed with
   `f"{day[:3]:5}"`; every subsequent lane row is prefixed with 5 spaces. Within
   a lane, bars are laid out identically to today (leading spaces to
   `span_start`, then the `bg on fg` (+ `dim` if online) label of width
   `(span_end - span_start) * CELL`, truncated to `MODULE [TYPE]` or `MODULE`).
6. After all lane rows, append the agenda lines (sorted by start), unchanged.

Days with no overlap yield exactly **one** lane row — visually identical to
today. Lane count equals the maximum cell-overlap depth on that day.

### Preserved invariants

- The agenda is the authoritative list; any class undrawable in the grid still
  appears in the agenda.
- Online strips keep the `~` mark and `dim` style; offline keep `fg on bg`.
- Label truncation (`MODULE [TYPE]` → `MODULE` when the strip is too narrow) is
  unchanged.
- Header row (hour labels) and the 5-char day gutter are unchanged.

## Out of scope (YAGNI)

- **No week annotation** on strips (e.g. "wks 4,6,8"). The request is to *see*
  the overlap; the agenda carries details and an 8-char cell has no room.
- **`output.render_week`** (the plain-text grid used by the non-TUI `run`
  command) has the same limitation but is untouched here — the user hits this in
  the TUI. A follow-up can bring it to parity if wanted.
- No interactivity, no per-lane colour legend.

## Testing

New/updated tests in `tests/test_tui_render.py`:

- **Overlap → two lanes:** a day with two disjoint-week classes sharing a cell
  renders two lane rows; both module strips are present (styled), the second
  lane row begins with the 5-space blank gutter, and both classes appear in the
  agenda.
- **No overlap → one lane:** a normal day renders exactly one strip row per day
  (guards against regressions / spurious extra rows).
- **Undrawable class still in agenda:** a class whose hours fall outside the grid
  is absent from the strips but present in the agenda (existing invariant).
- Existing `test_tui_render.py` tests stay green.
