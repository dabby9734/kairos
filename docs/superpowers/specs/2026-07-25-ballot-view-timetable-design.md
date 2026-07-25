# Ballot view shows the timetable

## Problem

The TUI's ballot view (`b`) replaces the whole detail pane with the snake list.
The week grid disappears, so nothing on screen connects a ballot position to the
timeslot it bids for. A user reading "7. CS2040S TUT[09] choice C Wed 1000-1100"
has to hold the grid in their head to know where that lands.

Both halves of the link already exist and never meet:

- `render_week_rich` (`kairos/tui/render.py:28`) accepts
  `preview=(module, lesson_type, slot_sig)` and highlights that slot — either as
  an extra reverse-video strip, or by inverting the class's existing strip in
  place when the previewed slot is the one it already occupies (*flash mode*,
  `render.py:52-59`).
- `render_snake_rich` (`kairos/output.py:267`) reverse-videos ballot rows
  belonging to the selected arrangement.

Today only the Timeslots pane drives `preview`, and only non-ballot view draws
the grid.

## Design

In ballot view the detail pane becomes two stacked widgets: a pinned compact
week grid on top, a cursorable ballot list below. Moving the cursor to a ballot
row drives the grid's `preview` for that row's class.

Direction is row → grid. The grid always shows the **currently selected
timetable** (`#N` from the Timetables pane); it never swaps arrangements as the
cursor moves. The ballot is global — built across all arrangements — so a row
may name a class absent from timetable #N; that row draws as a preview strip
beside the class's current strip, reading "this bid would move CS2040S here". A
row naming the class already placed there hits flash mode and inverts in place.

Side-by-side layout is impossible: the grid is `5 + 13*8 = 109` columns.

### Widgets

Inside `#results`, as a sibling of the existing `#detail-scroll`:

```
Vertical#ballot-view
  Static#ballot-grid      height: auto; max-height: 50%
  ListView#ballot-list    height: 1fr
```

`action_toggle_ballot` flips `display` on `#detail-scroll` and `#ballot-view`
rather than swapping content into one `Static`. Entering ballot view focuses
`#ballot-list`; `escape` while it has focus leaves ballot view (today `escape`
is bound to `focus_classes`, which stays the behaviour outside ballot view).

Grid height: header + 5 weekday rows, plus a Saturday row when the arrangement
uses one (`_render_days`, `output.py:11`) and one extra row per overlap lane.
Typically 6–7 rows, hence `height: auto` with a `max-height` guard rather than a
fixed height that would clip a Saturday or a lane.

### Compact grid

`render_week_rich` gains `agenda: bool = True`. When false it emits strips only,
skipping the per-day times/venues lines (`render.py:142-151`). Every existing
call keeps the default and is byte-identical; only `#ballot-grid` passes
`agenda=False`.

This is the one reason the grid fits: with agenda the grid runs 30+ rows and
leaves no room for the list.

### Preview from a ballot row

`BallotOption` (`kairos/ballot.py:15`) carries `sessions`, so the preview sig is
built the same way `Choice.slot_sig` (`kairos/model.py:84`) does:

```python
frozenset((s.day, s.start, s.end, s.online) for s in option.sessions)
```

Same fields, same order, same type — directly comparable to the sigs
`render_week_rich` matches against.

### Two affordances, one reverse-video

A `ListView` cursor is itself a background inversion, so cursor and "belongs to
timetable #N" would be indistinguishable. Blink is not an option
(Terminal.app ignores SGR 5 — a documented hard rule).

Reverse becomes the cursor, owned by Textual. Arrangement membership moves to a
leading gutter marker on each row: `●` for rows in timetable #N, a space
otherwise. A separate channel that survives on light and dark terminals and
cannot collide with the cursor.

Membership comes from `provenance.by_arrangement[self.selected]`
(`kairos/provenance.py:32`), matched against the row's key set — the entry's own
`(module, lesson_type, class_no)` plus one per `tied_with` class number. This is
the same key set `render_snake_rich` builds today (`output.py:287-291`) and the
same one `cluster_stats` is called with (`output.py:229-233`).

### `snake_rows`: replacing the text re-parse

`render_snake_rich` renders text and then re-parses it line by line to map lines
back to entries — testing `line[:3].strip().rstrip(".").isdigit()` and skipping
`"↳ interchangeable with"` continuation lines (`output.py:280-295`). A
`ListView` needs one item per entry, so that parse cannot survive.

Extract from `render_snake`:

```python
def snake_rows(entries: list, provenance) -> list:
    """(entry, line, continuation | None) per ballot entry, columns aligned."""
```

- `render_snake` joins these rows and is byte-identical, including the
  three-line `best`/`typical` legend header, column alignment across mixed
  widths, and the `""` for empty entries. Its 8 tests and the `ballot.txt`
  export path (`app.py:379`, `cli.py:168`) are untouched.
- The TUI builds one `ListItem` per row, each holding the primary line and its
  continuation line when present.
- `render_snake_rich` and its 3 tests are deleted. Its only caller is the branch
  being replaced, and the line-position parsing it exists to perform is exactly
  what `snake_rows` removes.

A side effect worth noting: `render_snake_rich` is the only Rich import in
`output.py` (lazy, `output.py:273`). Removing it leaves `output.py` entirely
Rich-free, and all Rich rendering confined to `tui/render.py`.

`snake_rows` is only meaningful with a provenance (the `provenance=None` branch
of `render_snake` is a plain unaligned list and has no TUI consumer), so it
takes `provenance` as a required argument and `render_snake` keeps its early
`provenance is None` return unchanged.

### Refresh split

Rebuilding the `ListView` resets its cursor, so rebuild and highlight are
separate:

- `_refresh_ballot_list()` — rebuilds items. Called when the ballot content or
  the membership markers can change: config edits and arrangement selection
  (from `_refresh_results`), priority reordering, and on entering ballot view.
  Preserves the cursor index across rebuilds, clamped, the way `_refresh_slots`
  already does (`app.py:235-236`).
- `_refresh_ballot_grid()` — redraws `#ballot-grid` with the cursor row's
  preview. Called on every `#ballot-list` highlight.

`on_list_view_highlighted` gains a `ballot-list` branch calling only the second.

Warnings stay cleared in ballot view, as today (`app.py:282-283`).

## Testing

Pure-core tests (`tests/test_output.py`):

- `snake_rows` returns one row per entry, in ballot order.
- A row's continuation is populated iff the entry has `tied_with`.
- `"\n".join` over `snake_rows` output reproduces `render_snake(...,
  provenance=...)` exactly — the byte-identity guarantee, asserted directly.
- Existing `render_snake` tests unchanged; the 3 `render_snake_rich` tests
  removed.

Render tests (`tests/test_tui_render.py`):

- `agenda=False` drops agenda lines and keeps every strip row.
- `agenda=True` is byte-identical to omitting it.
- A preview still renders under `agenda=False` (the strip, not the dropped
  `(preview)` agenda line).

## Out of scope

Locking a slot (`l`) from a ballot row. The row → `(module, lesson_type, sig)`
mapping would make it mechanical, but it is a separate interaction and not part
of making the relation visible.

## Docs

`docs/user-guide.md` (ballot view behaviour and the `●` marker),
`docs/architecture.md:247` (output.py is now Rich-free), `:262-264` (drop
`render_snake_rich`, add `snake_rows`)
and `:384` (the `agenda` parameter), `docs/development.md:43` (the new render
test coverage).
