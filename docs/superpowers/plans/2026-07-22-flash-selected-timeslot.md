# Flash Selected Timeslot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the highlighted Timeslots row is the slot a class already occupies, blink that class's existing bar and agenda line in place instead of drawing a duplicate preview bar below it.

**Architecture:** Entirely inside `render_week_rich` in `kairos/tui/render.py`. The function already receives the `assignment`, so it can compare the previewed `slot_sig` against the class's current choice itself. On a match it enters *flash mode*: it appends no preview block (so no second lane opens and no `(preview)` agenda line appears) and instead marks the class's real blocks so their strips and agenda lines render with Rich's `blink` style. `kairos/tui/app.py` is untouched — it keeps passing the same `preview=(module, lesson_type, sig)` triple.

**Tech Stack:** Python 3.13, Rich (renderables + styles), Textual (the TUI host), pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-22-flash-selected-timeslot-design.md`.
- Branch: `feat/flash-selected-timeslot` (already created; the spec is committed on it).
- Run tests with the project venv: `.venv/bin/python -m pytest`.
- "Same slot" means whole-slot equality — `Choice.slot_sig == p_sig` (`kairos/model.py:84`). Partial session overlap is **not** special-cased; it stays in preview mode.
- Existing tests `tests/test_tui_render.py:62`, `:168`, `:189` pin preview mode and must keep passing unchanged.

---

### Task 1: Flash the already-scheduled slot instead of duplicating it

**Files:**
- Modify: `kairos/tui/render.py:28-131` (`render_week_rich`)
- Test: `tests/test_tui_render.py` (append two tests)

**Interfaces:**
- Consumes: `Choice.slot_sig` (`kairos/model.py:84`) — a `frozenset` of `(day, start, end, online)` tuples; `assignment` is a `dict` keyed by `(module, lesson_type)` with `Choice` values.
- Produces: no signature change. `render_week_rich(assignment, colours, preview=None)` keeps its exact call shape, so `kairos/tui/app.py:283` needs no edit.

Internal to the function, the last element of each block tuple changes from a `blink` bool to a `mode` string with exactly three values: `""` (normal class), `"preview"` (phantom candidate bar), `"flash"` (real class that is the highlighted slot). Blocks are ordered with `blocks.sort()` and ties can reach that final element, so keeping it a single comparable type (`str` vs `str`) avoids a `TypeError`.

- [ ] **Step 1: Write the two failing tests**

Append to `tests/test_tui_render.py`:

```python
def test_previewing_current_slot_draws_no_duplicate_bar():
    # Highlighting the slot the class already occupies must add nothing at all:
    # no second lane, no "(preview)" agenda line. Flash mode changes only style,
    # so the plain text must be byte-identical to rendering with no preview.
    assignment = {("CS2030S", "Tutorial"): _choice("CS2030S", "Tutorial", "01", "Monday", 840, 900)}
    sig = frozenset({("Monday", 840, 900, False)})
    colours = module_colours(["CS2030S"])
    flashed = _plain(render_week_rich(assignment, colours, preview=("CS2030S", "Tutorial", sig)))
    assert flashed == _plain(render_week_rich(assignment, colours))
    assert "(preview)" not in flashed


def test_flashed_slot_blinks_strip_and_agenda():
    # Both the strip and its agenda line carry the blink SGR (5), and the strip
    # keeps CS2030S's own colour pair (black on green -> 30;42) underneath it.
    assignment = {("CS2030S", "Tutorial"): _choice("CS2030S", "Tutorial", "01", "Monday", 840, 900)}
    sig = frozenset({("Monday", 840, 900, False)})
    colours = module_colours(["CS2030S"])
    console = Console(width=200, force_terminal=True, color_system="standard")
    with console.capture() as cap:
        console.print(render_week_rich(assignment, colours, preview=("CS2030S", "Tutorial", sig)))
    lines = cap.get().splitlines()
    strip = next(line for line in lines if line.startswith("Mon"))
    agenda = next(line for line in lines if "TUT[01]" in line)
    for line in (strip, agenda):
        assert "\x1b[5m" in line or ";5m" in line or "\x1b[5;" in line
    assert "30;42" in strip
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_tui_render.py -k "duplicate_bar or blinks_strip" -v
```

Expected: both FAIL. `test_previewing_current_slot_draws_no_duplicate_bar` fails on the equality assert (today's output has an extra lane row and a `1400-1500 CS2030S TUT (preview)` line). `test_flashed_slot_blinks_strip_and_agenda` fails at the `agenda` line's blink assert (today the agenda line carries no escapes at all).

- [ ] **Step 3: Detect flash mode and suppress the preview day expansion**

In `kairos/tui/render.py`, replace lines 44-46:

```python
    preview_days = None
    if preview is not None:
        preview_days = {p_day for p_day, _start, _end, _online in preview[2]}
```

with:

```python
    # Flash mode: the previewed slot is exactly the one this class already
    # occupies. Nothing new gets drawn — the real strips and agenda lines blink
    # in place, rather than a phantom block opening a redundant second lane.
    flash_key = None
    preview_days = None
    if preview is not None:
        p_module, p_lesson_type, p_sig = preview
        current = assignment.get((p_module, p_lesson_type))
        if current is not None and current.slot_sig == p_sig:
            flash_key = (p_module, p_lesson_type)
        else:
            # Force a day row for a candidate landing on an otherwise-empty day.
            # Unnecessary in flash mode: every matched day already has the class.
            preview_days = {p_day for p_day, _start, _end, _online in p_sig}
```

- [ ] **Step 4: Tag the real blocks with their mode**

Replace lines 51-67 (the `for (module, lesson_type), choice in sorted(...)` block builder). The two changes are the new `mode` local and swapping the trailing `False,  # blink` for it:

```python
        for (module, lesson_type), choice in sorted(assignment.items()):
            abbrev = LESSON_ABBREV.get(lesson_type, lesson_type)
            mode = "flash" if (module, lesson_type) == flash_key else ""
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
                    mode,
                ))
        blocks.sort()
```

- [ ] **Step 5: Skip the phantom block in flash mode**

Replace lines 70-80 (the `if preview is not None:` block). `p_module`, `p_lesson_type` and `p_sig` are now unpacked once at the top of the function, so the re-unpack goes away:

```python
        if preview is not None and flash_key is None:
            p_abbrev = LESSON_ABBREV.get(p_lesson_type, p_lesson_type)
            for p_day, p_start, p_end, p_online in p_sig:
                if p_day != day:
                    continue
                blocks.append((
                    p_start, p_end, p_start // 60, (p_end + 59) // 60,
                    p_module, p_abbrev, "", "", p_online, "preview",
                ))
            blocks.sort()
```

- [ ] **Step 6: Blink the strip for both modes**

In the lane-rendering loop, replace line 103's unpack and line 115's style. Any non-empty `mode` blinks, which covers `"preview"` (unchanged behaviour) and `"flash"` (new):

```python
            for start, end, start_h, end_h, module, abbrev, class_no, venue, online, mode in lane:
```

```python
                style = f"{fg} on {bg}" + (" dim" if online else "") + (" blink" if mode else "")
```

- [ ] **Step 7: Blink the agenda line in flash mode**

Replace lines 121-129 (the agenda loop):

```python
        # Agenda: every block for the day, sorted by start time.
        for start, end, _sh, _eh, module, abbrev, class_no, venue, online, mode in sorted(blocks):
            if mode == "preview":
                rows.append(Text(f"       {fmt_time(start)}-{fmt_time(end)} {module} {abbrev} (preview)"))
                continue
            note = " (online)" if online else ""
            rows.append(Text(
                f"       {fmt_time(start)}-{fmt_time(end)} {module} "
                f"{abbrev}[{class_no}] @{venue}{note}",
                style="blink" if mode == "flash" else "",
            ))
```

- [ ] **Step 8: Update the docstring**

Replace the `render_week_rich` docstring (lines 29-34) with one that documents the two preview modes:

```python
    """A Rich renderable of the week grid. Each class is a coloured strip spanning
    its hours, labelled `MODULE [TYPE]` (or just `MODULE` when the strip is too
    narrow), with an agenda of times/venues below each day. Classes whose times
    overlap (non-clashing alternating-week pairs sharing a slot) are stacked on
    separate lanes so every class gets a visible bar; the agenda below always
    lists every class, even one whose strip is undrawable.

    `preview` is an optional `(module, lesson_type, slot_sig)` triple for the
    timeslot the user is currently highlighting. If that class is already on this
    exact slot, its existing strip and agenda line blink in place and nothing is
    added. Otherwise the candidate is drawn as an extra blinking strip plus a
    `(preview)` agenda line, alongside the class's current slot."""
```

- [ ] **Step 9: Run the new tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_tui_render.py -k "duplicate_bar or blinks_strip" -v
```

Expected: both PASS.

- [ ] **Step 10: Run the full suite to verify nothing regressed**

```bash
.venv/bin/python -m pytest
```

Expected: all tests pass, including `test_saturday_preview_creates_saturday_row`, `test_preview_bar_is_blink_styled_and_shows_both` and `test_preview_none_unchanged`, which pin preview mode.

- [ ] **Step 11: Commit**

```bash
git add kairos/tui/render.py tests/test_tui_render.py
git commit -m "fix: flash the selected timeslot instead of duplicating its bar

Highlighting the slot a class already occupies appended a phantom block
that time-overlapped the real one, opening a second lane and drawing a
redundant bar plus a (preview) agenda line. Whole-slot matches now blink
the existing strip and agenda line in place and add nothing."
```
