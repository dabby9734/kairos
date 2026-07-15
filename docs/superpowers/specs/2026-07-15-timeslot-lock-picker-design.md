# Design: pick-class → pick-timeslot lock picker

A new TUI locking workflow: select a class from the Classes list, browse its
offered timeslots in a dedicated pane, and lock the class to a chosen timeslot —
with a live blinking bar on the week grid showing where the candidate timeslot
would sit. Replaces the current "lock whatever the shown timetable places"
workflow.

## Motivation

Today, locking (`action_toggle_lock`, `l`) reads the class number from the
currently displayed timetable and pins it. To lock a class to a specific
timeslot you must first navigate to a timetable that already places it there.
The user wants the inverse: choose the class, then choose the timeslot directly,
seeing where it lands before committing.

## Key mechanic (already in place)

`prepare_groups` locks by **slot signature**, not class number:
`_slot_sig(choice) = frozenset((day, start, end, online) for each session)` —
ignoring class number, venue, and weeks. Locking to any class number keeps every
interchangeable class at that timeslot (venue/week twins). So "a timeslot" is a
distinct `_slot_sig`, and locking to it via any representative class number is
exactly the existing behaviour.

## Layout

The Classes row becomes a horizontal split; the top row (Timetables | Warnings)
and the detail grid below are unchanged.

```
┌ Timetables ─────┐┌ Warnings ──────────────┐
└─────────────────┘└────────────────────────┘
┌ Classes ────────┐┌ Timeslots: ALPHA TUT ──┐
│▸ALPHA TUT       ││ 🔒 Mon 14:00–15:00 (01/02)
│ BETA LAB        ││  ▸ Tue 09:00–10:00 (05)
└─────────────────┘└────────────────────────┘
  breakdown + week grid (blinking bar) + bids + link   (scrolls)
```

- `#classes-row` — `Horizontal`, height ~15%, containing `#slot-list` (Classes)
  and a new `#timeslot-list` (Timeslots), split by width (~45% / `1fr`), each with
  a `round $panel` border and `border-title-color: $text`.
- `#slot-list` keeps its id and "Classes" title; `#timeslot-list` is a new
  `ListView` titled `Timeslots: <MODULE> <ABBREV>`.

## `state.py` — offered-timeslot enumeration

Add to `AppState`:

```python
def offered_timeslots(self, module, lesson_type):
    """Distinct offered timeslots for a class, from the FULL offered set
    (base_groups, so a current lock does not narrow it). Returns a list of
    dicts sorted by (day index, start):
      {"sig": frozenset, "class_nos": [str], "sessions": (Session, ...), "rep": str}
    where sig is _slot_sig, class_nos are all class numbers sharing the sig
    (sorted), sessions is the representative choice's sessions (for rendering),
    and rep is the representative class number to lock with."""
```

- Find the `ChoiceGroup` in `self.base_groups` matching `(module, lesson_type)`.
- Group its choices by `_slot_sig` (import `_slot_sig` from `..search`).
- For each sig: `class_nos` = sorted class numbers; `rep` = `class_nos[0]`;
  `sessions` = the first choice's sessions.
- Sort rows by `(DAYS.index(first session day), first session start)`.
- Return `[]` if the class isn't in `base_groups`.

```python
def locked_sig(self, module, lesson_type):
    """The _slot_sig this class is currently locked to, or None. Resolved from
    config.locked's class number via base_groups."""
```

- `abbrev = LESSON_ABBREV.get(lesson_type, lesson_type)`;
  `class_no = config.locked.get(module, {}).get(abbrev)`; `None` → `None`.
- Find the choice with that class number in the class's `base_groups` group and
  return its `_slot_sig` (or `None` if not found).

## `render.py` — blinking preview bar

`render_week_rich(assignment, colours, preview=None)`:

- `preview` is `None` or `(module, lesson_type, sig)` where `sig` is a
  `_slot_sig` (frozenset of `(day, start, end, online)`).
- **Show-both:** the normal assignment renders unchanged (the class keeps its
  current strip); the preview adds extra blocks for each `(day, start, end,
  online)` in `sig`, on their day, styled with the module's colour **plus
  `blink`** and a leading `▌`/marker so the candidate is unmistakable.
- Preview blocks join the same lane-packing as real blocks (so an overlap with an
  existing class opens a new lane rather than being hidden), and appear in the
  agenda line for that day labelled e.g. `ALPHA [TUT] → (preview)`.
- When `preview is None`, output is byte-for-byte today's.

Implementation note: extend the per-day `blocks` tuple with a trailing `blink`
flag (default `False`); the style string appends `" blink"` when set. All
existing call sites build non-blink blocks.

## `app.py` — panes, focus, actions

**Compose.** Replace the single `#slot-list` yield with a `Horizontal(id=
"classes-row")` holding `#slot-list` (title "Classes") and `#timeslot-list`
(a `ListView`).

**Highlighting a class repopulates Timeslots.** `on_list_view_highlighted` gains
a branch: when `#slot-list` highlight changes, rebuild `#timeslot-list` from
`state.offered_timeslots(module, lesson_type)` for the highlighted class,
updating the pane's `border_title` to `Timeslots: <MODULE> <ABBREV>`. Each row:
`{🔒 }{day-times} ({class_nos})`, e.g. `🔒 Mon 14:00–15:00 (01/02)`; the `🔒`
prefixes the row whose sig equals `state.locked_sig(...)`. Reset the Timeslots
highlight to the locked row if any, else row 0.

**Browsing Timeslots drives the bar.** When `#timeslot-list` highlight changes
(and it is focused), store the candidate `(module, lesson_type, sig)` and call
`_refresh_detail`, which passes it as `preview=` to `render_week_rich`. When
focus leaves `#timeslot-list`, clear the candidate (no bar).

**Focus flow.** New bindings/behaviour:
- `Tab` / `→` while `#slot-list` focused → focus `#timeslot-list`.
- `Esc` / `←` while `#timeslot-list` focused → focus `#slot-list` (clears bar).

**Lock (`l`).** `action_toggle_lock` is rewritten to be timeslot-based:
- Require `#timeslot-list` focused with a highlighted row and a highlighted class;
  otherwise no-op.
- Resolve `module, lesson_type` from the highlighted Classes row and the
  `sig`/`rep` from the highlighted Timeslots row.
- If that sig is the currently locked sig (`state.locked_sig`): `clear_lock`.
- Else: `set_lock(module, abbrev, rep)`.
- On rejection (`ok is False`): existing notification, no change.
- On success: `_refresh_results()` (re-rank) and repopulate Timeslots so the `🔒`
  marker moves.

The old behaviour — `l` locking the class number shown in the current timetable —
is removed.

## Testing

- `state.py`: `offered_timeslots` returns one row per distinct sig (twins
  collapsed), sorted by day/time, with all class numbers and a representative;
  returns `[]` for an unknown class. `locked_sig` returns the locked sig and
  `None` when unlocked.
- `render.py`: with `preview=(module, lesson_type, sig)` the rendered grid
  contains a `blink`-styled bar at the sig's day/time and still contains the
  class's current strip (show-both); `preview=None` is unchanged.
- `app.py` (Textual pilot): highlighting a class populates `#timeslot-list` with
  the right title and rows; `Tab` moves focus into it; browsing a row renders the
  blinking preview into `#detail`; `l` on a timeslot locks the class (reduces the
  space / marks `🔒`) and `l` again on the locked row unlocks; a lock that empties
  the space surfaces the notification and leaves state unchanged.
- Full suite stays green; the two existing lock tests (`test_lock_slot_marks_and
  _reduces`, `test_lock_then_unlock_restores`) are rewritten to drive the new
  timeslot-based flow.

## Out of scope

- No multi-select / batch locking.
- No reordering or filtering of the Timeslots list beyond day/time sort.
- No change to how locks persist in `config.yaml` (still `locked: {module:
  {abbrev: class_no}}`, written with the representative class number).
- No clash-aware dimming of impossible candidate timeslots (the bar always shows;
  a bad lock is still rejected on `l`).
