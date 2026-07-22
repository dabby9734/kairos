# Flash the selected timeslot instead of duplicating its bar

Date: 2026-07-22

## Problem

Highlighting a row in the Timeslots pane previews that candidate slot on the
week grid: `kairos/tui/app.py:270` passes `preview=(module, lesson_type, sig)`
into `render_week_rich`, which appends a phantom block for each previewed
session (`kairos/tui/render.py:70-80`).

When the highlighted row *is* the slot the class already occupies — the common
case, since `_populate_timeslots` seeds the pane's cursor on the locked slot
(`kairos/tui/app.py:250`) — the phantom block time-overlaps the real one. Lane
assignment (`kairos/tui/render.py:88-97`) therefore opens a second lane and
draws a redundant bar directly below the existing one, plus a redundant
`(preview)` agenda line.

The bar and its agenda line should instead flash in place, with nothing added.

## Behaviour

Let `p_module`, `p_lesson_type`, `p_sig` be the preview triple.

**Flash mode** applies when `assignment[(p_module, p_lesson_type)]` exists and
its `slot_sig` equals `p_sig` — a whole-slot match, the same comparison the 🔒
lock marker already uses (`kairos/tui/app.py:244`). In flash mode:

- No preview block is appended, so no extra lane and no extra bar.
- The class's real strips blink, keeping their module colour.
- The class's real agenda lines blink, keeping their normal
  `1000-1200 CS2040S LEC[01] @LT19` text. No `(preview)` line is emitted.

**Preview mode** — anything else, including a class absent from the assignment
and a candidate slot that merely shares *some* sessions with the current one —
keeps today's behaviour exactly: phantom blinking bar plus a `(preview)` agenda
line. Partial overlaps are deliberately not special-cased; whole-slot equality
is the only notion of "same slot" in the codebase and introducing a second one
is not worth the ambiguity.

## Implementation

Contained to `render_week_rich` in `kairos/tui/render.py`. `app.py` is
unchanged — it still passes the same `preview` triple, and render decides how
to draw it.

1. **Detect the match** before building preview blocks, from the `assignment`
   argument already in hand.

2. **Widen the block state.** The last element of each block tuple is today a
   `blink` bool. It becomes a `mode` string with three values:

   | `mode` | meaning | strip | agenda |
   |---|---|---|---|
   | `""` | normal scheduled class | plain | plain |
   | `"preview"` | phantom candidate | blink | `... (preview)` |
   | `"flash"` | real class that is the highlighted slot | blink | normal text, `style="blink"` |

   Blocks are sorted with `blocks.sort()`; ties can reach the final element, so
   the field stays a single comparable type (`str` vs `str`) and no `TypeError`
   is introduced.

3. **Skip `preview_days` in flash mode.** That set exists to force a day row for
   a candidate landing on an otherwise-empty day (`kairos/tui/render.py:44-46`).
   Every matched day already renders because the real class sits on it.

4. **Update the `render_week_rich` docstring** to describe the two modes.

## Testing

Added to `tests/test_tui_render.py`, following the existing `_plain` / ANSI
capture style used by `test_preview_bar_is_blink_styled_and_shows_both`:

- Previewing a class's own current slot draws exactly one bar for it — the
  module's strip label appears once across the day's strip rows.
- That strip and its agenda line both carry the blink SGR while the strip keeps
  the module's colour pair.
- No `(preview)` agenda line is emitted in flash mode.

The existing tests at `tests/test_tui_render.py:62`, `:168` and `:189` must keep
passing unchanged; each previews a slot different from the assigned one, so they
pin preview mode.
