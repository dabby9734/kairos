# Design: Lockable non-balloted slots

## Motivation

Lectures are not always a single option. Three modules in a typical config offer two
lecture classes, and the choice is real:

```
MA1521  class 1: Mon 1000-1200 @UT-AUD1     Wed 1200-1400 @UT-AUD2
        class 2: Tue 1800-2000 @LT11        Fri 1800-2000 @LT11      <- evening
CS1231S class 1: Thu 1200-1400 @UT-AUD1     Fri 1200-1300 @UT-AUD1
        class 2: Thu 1200-1400 @E-Learn_C   Fri 1200-1300 @E-Learn_C <- online
```

MA1521 is a genuine time fork (midday pair vs. two evening lectures). CS1231S is the
same times either way, differing only physical vs. online — which still matters, because
online sessions do not count against the time-window / free-day criteria but do count
toward daily difficulty.

Neither choice is reachable from the TUI today. Two independent causes compound:

1. **The share URL silently hard-pins the choice.** `tui/startup.py:26-27` (mirroring
   `cli.py:81-88`) writes any non-balloted group with >1 option that appeared in the URL
   into `fixed`. A URL containing `MA1521=LEC:1` therefore yields `fixed: {MA1521: {LEC: '1'}}`,
   and `prepare_groups` (`search.py:23-30`) drops class `2` from the search space entirely.
   The alternative is not hidden — it does not exist.
2. **The Classes pane only renders balloted types.** The pane is built from `arr.bids`
   (`app.py:204`), and `_make_arrangement` (`search.py:245`) skips any lesson type not in
   `config.balloted_types` (default `[TUT, LAB, REC, SEC]`). A LEC group never becomes a
   `SlotBid`, so it is never a row, so there is nothing to press `l` on.

Fixing either alone is insufficient: clearing `fixed` leaves the group invisible, and
listing the group leaves it pinned to one class.

## 1. Classes pane gets its own model

The pane currently conflates two ideas: "a slot I can decide" and "a slot I bid for".
They are separated.

- **New `AppState.selectable_groups()`** returns one row per group in `base_groups` with
  more than one distinct `slot_sig`:

  ```python
  {module, lesson_type, abbrev, balloted: bool, current_class_no: str, locked: bool}
  ```

  `current_class_no` comes from the selected arrangement's `assignment`. Rows are sorted
  by `(module, lesson_type)`, matching the existing bid ordering, so the pane's order does
  not visibly change for balloted groups.

- **`app.py:_refresh_slots` reads `selectable_groups()`** instead of `arr.bids`.

- The slot count is taken from `base_groups` (the full offered set), **not** the prepared
  groups, for the same reason `offered_timeslots` does (`tui/state.py:189-193`): a locked
  group has been narrowed to one slot in the prepared set, and counting there would make a
  row disappear the moment the user locked it.

- Groups with exactly one distinct slot are omitted — there is nothing to choose, and an
  inert row that ignores `l` is noise.

- **Groups pinned by `fixed` are also omitted**, even if they still offer more than one
  distinct slot. `prepare_groups` (`search.py:23-30`) applies `fixed` first and
  short-circuits before ever reading `locked`, so a lock written for such a group from the
  pane would be silently ignored: the row and the timeslot row would both show 🔒 while the
  timetable does not move. The pane's model is "a slot I can decide" — a `fixed` group
  offers nothing to decide, so it gets no row.

- `current_class_no` is always available: `assignment` is built from every choice in the
  combo (`search.py:122`), including non-balloted groups, so it covers LEC rows too.

- `balloted` drives a per-row marker, so a ballot *wish* (may not be granted) reads
  differently from a lecture *pick* (allocated with the course).

## 2. `SlotBid` stays a ballot-only concept

No change to `_make_arrangement` (`search.py:245`) or `ballot.ranked_options`
(`ballot.py:45`); both keep their `balloted_types` filters. Lectures therefore never
appear in `arr.bids`, the Bids block, the snake ranking, or `ballot.txt`. You do not
ballot for lectures.

This is the reason the pane needs its own model rather than a relaxed bid filter:
widening `balloted_types` would leak lectures into the ballot output.

## 3. Stop auto-writing `fixed`

`tui/startup.py:_config_from_url` and `cli.py:cmd_init` write the URL's non-balloted picks
to **`locked`** instead of `fixed`. `fixed` reverts to its intended meaning: a
hand-written hard pin to exactly one class, for CLI users who want it.

`locked` is also the more correct representation. It pins the *slot signature*, so pure
venue-twins at the same time stay interchangeable, whereas `fixed` would arbitrarily keep
one of them.

## 4. Migrate existing `fixed` pins on TUI load

Configs already carry auto-written `fixed` entries. `build_state` converts them:

- For each `fixed[code][abbrev]` where `abbrev not in config.balloted_types`, move the
  entry to `locked[code][abbrev]` and drop it from `fixed`.
- Balloted `fixed` entries are left alone — those are deliberate hand-written pins.
- Migration runs in `build_state` **only**. `cmd_run` and `load_config` are untouched, so
  `kairos run` behaviour does not move for CLI-only users.
- `s` (save config) writes the migrated form, so the change becomes durable only when the
  user chooses to save.

The conversion is safe. `locked` narrows a group to its `slot_sig` twin set; where a
class's signature is unique within its group, that resolves to the identical single class
`fixed` would have kept. Because `slot_sig` includes `online` (`model.py:88`), CS1231S's
physical and online lectures have distinct signatures and do not collapse into each other.
Where signatures *do* coincide — same day, time, and online-ness, differing only by venue —
retaining both is the desired behaviour.

## 5. Disambiguate timeslot labels

`_fmt_sessions` (`app.py:73`) renders day and time only, and `offered_timeslots` keys rows
by `slot_sig`. For CS1231S that produces two visually identical rows, making the feature
unusable for the case that motivated it.

Labels gain a venue segment and reuse the existing `~` online marker from
`render.py:111`:

```
  Thu 1200-1400, Fri 1200-1300  @UT-AUD1    (1)
 ~Thu 1200-1400, Fri 1200-1300  @E-Learn_C  (2)
```

**Correction (post-implementation):** the venue segment shows every distinct venue
across the row's classes, joined with `/` — not just the representative's. Showing only
the representative's venue was the original plan here, but it was found to produce false
labels: `slot_sig` deliberately ignores venue, so venue-differing classes (pure
venue-twins at the same day/time/online-ness) merge into one row, and a representative-only
label would misdescribe every non-representative class in that row. The project owner
decided to show the venue list instead; this is what the code implements
(`offered_timeslots`/`_fmt_timeslot` in `tui/state.py` and `tui/app.py`).

## 6. No new locking machinery

`set_lock`, `clear_lock`, `_apply_locked_change` (`tui/state.py:146-180`) and the `locked`
branch of `prepare_groups` are already lesson-type agnostic. `action_toggle_lock`
(`app.py:320`) needs only to source its `(module, abbrev)` from the new pane model.

The existing over-constraint guard applies unchanged: if locking a lecture leaves no
clash-free timetable, `_apply_locked_change` rolls back and the TUI notifies.

## 7. Layout

The results column rebalances toward the week grid:

```css
#top-row      { height: 20%; }  /* was 30% — timetables + warnings */
#classes-row  { height: 20%; }  /* was 15% — now gains LEC rows */
#detail-scroll{ height: 1fr;  }  /* ~55% -> ~60% */
```

Timetables and warnings shrink as requested; the classes row grows slightly because it
gains rows; the week grid absorbs the remainder.

## 8. Testing

- **`prepare_groups`:** a `locked` entry on a non-balloted group narrows it to the
  signature twin set; a group in both `fixed` and `locked` still follows `fixed`.
- **Migration:** non-balloted `fixed` entries convert to `locked` in `build_state`;
  balloted `fixed` entries are preserved; `cmd_run`/`load_config` are unaffected;
  the migrated form round-trips through `to_config_yaml → load_config → prepare_groups`.
- **`selectable_groups()`:** includes multi-slot LEC groups, excludes single-option
  groups, and reports `balloted` and `locked` correctly.
- **Labels:** the CS1231S physical/online pair renders as two distinguishable rows.
- **Ballot isolation:** with a LEC group present and locked, `ballot.snake` output and
  `ballot.txt` contain no LEC entries.
- **TUI (Pilot):** `l` on MA1521 LEC switches to the evening lecture, re-ranks, and marks
  the row locked; pressing `l` again restores.

## Out of scope

- **CourseReg Round 1/2/3 advisor.** Priority Score = A x B x C, rank allocation strategy,
  and CourseRekt-sourced demand/vacancy data are a separate subsystem operating on
  *courses* rather than *slots*. Own spec, queued after this one.
- **Widening `balloted_types`.** Rejected: it would leak lectures into the ballot output,
  which is exactly the coupling this design breaks.
