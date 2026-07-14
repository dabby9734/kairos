# TUI Overlap Lanes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render non-clashing time-overlapping classes (alternating-week pairs sharing a slot) as stacked lanes in the TUI week grid, so every class gets its own coloured bar instead of the second one silently losing its strip.

**Architecture:** Rewrite `render_week_rich` in `optimiser/tui/render.py` to partition each day's blocks into lanes by real time-interval overlap (greedy first-fit), then render one strip row per lane (first lane keeps the `Mon`/`Tue` gutter, extra lanes get a blank gutter), followed by the unchanged agenda. Within a lane, drawing is byte-for-byte the current single-row logic (per-lane cursor, drift clamp, label truncation, online dim).

**Tech Stack:** Python ≥3.11, Rich (Text/Group), pytest. No new dependencies.

## Global Constraints

- **Lanes split by real TIME-interval overlap, not rounded-cell adjacency.** Two blocks share a lane iff their `[start, end)` minute intervals do not overlap. Back-to-back classes (`a.end == b.start`) stay in the SAME lane; only genuinely overlapping classes get separate lanes. This preserves today's single-row layout for sequential/back-to-back classes.
- **Agenda is authoritative:** every session for the day is recorded in the agenda regardless of whether its strip is drawable; a class must never disappear.
- **Days with no overlap render exactly one strip row** — visually identical to today. A day with no classes still renders one row (the day gutter only).
- Within a lane, keep the existing drawing exactly: `span_start = max(start_h, first_hour, cursor)`, `span_end = min(end_h, last_hour + 1)`, skip when `span_end <= span_start` (undrawable → no strip, still agenda'd), leading spaces to `span_start`, label = `MODULE [TYPE]` or `MODULE` (with `~` prefix + `dim` style when online), width `(span_end - span_start) * CELL`.
- First lane row prefix is `f"{day[:3]:5}"`; every extra lane row prefix is 5 spaces (`"     "`).
- Deterministic: blocks sorted by `(start, end)`; first-fit lane search from the top.
- `CELL`, `GRID_HOURS`, `WEEKDAYS` come from `..output`; `LESSON_ABBREV`, `fmt_time` from `..model` (imports already present). No new imports needed.

---

### Task 1: Lane-based `render_week_rich`

**Files:**
- Modify: `optimiser/tui/render.py` (rewrite `render_week_rich`, currently lines 28-98)
- Test: `tests/test_tui_render.py`

**Interfaces:**
- `render_week_rich(assignment: dict, colours: dict) -> Group` — signature unchanged. `assignment` keyed `(module, lesson_type) -> Choice`; `colours` maps module → `(bg, fg)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tui_render.py` (the `_choice`, `_plain`, `module_colours`, `render_week_rich`, `Choice`, `Session`, `ALL_WEEKS` names already exist there):

```python
def test_overlapping_classes_get_separate_lanes():
    # A 14:00-17:00 lab (odd weeks) and a 15:00-17:00 tutorial (even weeks) share
    # the 15:00-17:00 cells but never clash -> each gets its own lane/bar.
    w_odd = frozenset({1, 3, 5})
    w_even = frozenset({2, 4, 6})
    assignment = {
        ("CS2040", "Laboratory"): Choice(
            "CS2040", "Laboratory", "L1", (Session("Monday", 840, 1020, w_odd, "COM1"),)
        ),
        ("MA1521", "Tutorial"): Choice(
            "MA1521", "Tutorial", "T1", (Session("Monday", 900, 1020, w_even, "COM2"),)
        ),
    }
    text = _plain(render_week_rich(assignment, module_colours(["CS2040", "MA1521"])))
    lines = text.splitlines()
    mon = next(i for i, l in enumerate(lines) if l.startswith("Mon"))
    assert "CS2040 [LAB]" in lines[mon]           # first lane keeps the day gutter
    assert "MA1521 [TUT]" in lines[mon + 1]       # second class gets its own lane
    assert lines[mon + 1].startswith("     ")     # extra lane has a blank 5-char gutter
    assert not lines[mon + 1][:5].strip()         # gutter is blank, not a day name
    # both classes still listed in the agenda
    assert "1400-1700 CS2040 LAB[L1]" in text
    assert "1500-1700 MA1521 TUT[T1]" in text


def test_non_overlapping_day_uses_single_lane():
    # Two sequential classes (10:00-12:00, 13:00-14:00) do NOT overlap -> one lane
    # row holding both, immediately followed by the agenda (no second lane).
    assignment = {
        ("AAA", "Lecture"): _choice("AAA", "Lecture", "1", "Monday", 600, 720),
        ("BBB", "Tutorial"): _choice("BBB", "Tutorial", "1", "Monday", 780, 840),
    }
    text = _plain(render_week_rich(assignment, module_colours(["AAA", "BBB"])))
    lines = text.splitlines()
    mon = next(i for i, l in enumerate(lines) if l.startswith("Mon"))
    assert "AAA" in lines[mon] and "BBB" in lines[mon]   # both share the single lane
    assert lines[mon + 1].startswith("       ")          # next line is agenda (7 spaces), not a 2nd lane
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/pytest tests/test_tui_render.py -k "separate_lanes or single_lane" -v`
Expected: `test_overlapping_classes_get_separate_lanes` FAILS — the current single-row renderer clamps the tutorial to `span_end <= span_start` and drops its strip, so `"MA1521 [TUT]"` is not in `lines[mon + 1]` (that line is the agenda). (`test_non_overlapping_day_uses_single_lane` may already pass under current behaviour; that's fine — it guards against regressions from the rewrite.)

- [ ] **Step 3: Rewrite `render_week_rich`**

Replace the entire `render_week_rich` function in `optimiser/tui/render.py` (lines 28-98) with:

```python
def render_week_rich(assignment: dict, colours: dict) -> Group:
    """A Rich renderable of the week grid. Each class is a coloured strip spanning
    its hours, labelled `MODULE [TYPE]` (or just `MODULE` when the strip is too
    narrow), with an agenda of times/venues below each day. Classes whose times
    overlap (non-clashing alternating-week pairs sharing a slot) are stacked on
    separate lanes so every class gets a visible bar; the agenda below always
    lists every class, even one whose strip is undrawable."""
    hours = list(GRID_HOURS)
    first_hour = hours[0]
    last_hour = hours[-1]

    header = Text("     ")
    for hour in hours:
        header.append(f"{hour:02d}00".ljust(CELL))
    rows: list = [header]

    for day in WEEKDAYS:
        # block = (start, end, start_h, end_h, module, abbrev, class_no, venue, online)
        blocks = []
        for (module, lesson_type), choice in sorted(assignment.items()):
            abbrev = LESSON_ABBREV.get(lesson_type, lesson_type)
            for session in choice.sessions:
                if session.day != day:
                    continue
                blocks.append((
                    session.start,
                    session.end,
                    session.start // 60,
                    (session.end + 59) // 60,
                    module,
                    abbrev,
                    choice.class_no,
                    session.venue,
                    session.online,
                ))
        blocks.sort()

        # Lane assignment by real time-interval overlap: a block joins the first
        # lane whose last-placed session ends at or before this block starts
        # (blocks are start-sorted, so that means no time overlap). Back-to-back
        # classes stay in one lane; genuinely overlapping classes open a new one.
        lanes: list = []
        lane_end: list = []  # latest end-minute placed in each lane
        for block in blocks:
            start, end = block[0], block[1]
            for i, last_end in enumerate(lane_end):
                if last_end <= start:
                    lanes[i].append(block)
                    lane_end[i] = end
                    break
            else:
                lanes.append([block])
                lane_end.append(end)

        # Render one strip row per lane; a day with no classes still gets one row.
        for li, lane in enumerate(lanes or [[]]):
            row = Text(f"{day[:3]:5}" if li == 0 else "     ")
            cursor = first_hour
            for start, end, start_h, end_h, module, abbrev, class_no, venue, online in lane:
                span_start = max(start_h, first_hour, cursor)
                span_end = min(end_h, last_hour + 1)
                if span_end <= span_start:
                    continue  # undrawable (out of range / cell already used); agenda keeps it
                if span_start > cursor:
                    row.append(" " * ((span_start - cursor) * CELL))
                width = (span_end - span_start) * CELL
                mark = "~" if online else ""
                full = f"{mark}{module} [{abbrev}]"
                label = (full if len(full) <= width else f"{mark}{module}")[:width].ljust(width)
                bg, fg = colours.get(module, ("white", "black"))
                style = f"{fg} on {bg}" + (" dim" if online else "")
                row.append(label, style=style)
                cursor = span_end
            rows.append(row)

        # Agenda: every block for the day, sorted by start time.
        for start, end, _sh, _eh, module, abbrev, class_no, venue, online in sorted(blocks):
            note = " (online)" if online else ""
            rows.append(Text(
                f"       {fmt_time(start)}-{fmt_time(end)} {module} "
                f"{abbrev}[{class_no}] @{venue}{note}"
            ))

    return Group(*rows)
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `.venv/bin/pytest tests/test_tui_render.py -k "separate_lanes or single_lane" -v`
Expected: PASS (both new tests).

- [ ] **Step 5: Run the whole render suite (regression guard)**

Run: `.venv/bin/pytest tests/test_tui_render.py -v`
Expected: PASS — all existing tests stay green, including `test_back_to_back_halfhour_classes_do_not_drift` (sequential half-hour classes remain one lane because they don't overlap in time), `test_subhour_classes_both_listed_in_agenda`, and `test_out_of_grid_class_listed_in_agenda` (agenda invariant).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS — no regressions elsewhere (`test_tui_app.py` renders the detail pane through this function).

- [ ] **Step 7: Commit**

```bash
git add optimiser/tui/render.py tests/test_tui_render.py
git commit -m "feat: stack time-overlapping classes on separate lanes in the week grid"
```

---

## Self-review

- **Coverage:** the spec's lane algorithm (time-overlap first-fit), gutter rule (first lane vs blank), one-row-when-no-overlap, and agenda invariant are all in Task 1; the two new tests assert the overlap→2-lanes and no-overlap→1-lane behaviours; existing tests guard the agenda/undrawable/drift invariants named in the spec's testing section.
- **Placeholders:** none — full function body and full test code provided.
- **Type/name consistency:** the block tuple is unpacked in the same 9-field order everywhere it's used (lane loop, agenda loop); `render_week_rich` keeps its exact signature; the `lanes or [[]]` idiom guarantees one row for empty days.
