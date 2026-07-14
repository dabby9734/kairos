# Distinct Arrangements & Interchangeable Bids Design

**Date:** 2026-07-14
**Status:** Approved

## Problem

The ranked timetable list shows up to `top_n` (5) timetables. When a balloted
group has classes at the **same day/time but different weeks** (e.g. EG1311
LAB[03] on odd weeks and LAB[04] on even weeks), those classes have **different
footprints** (weeks are part of `Choice.footprint`), so:

1. They are enumerated as **separate** clash-free timetables.
2. They **score identically** (no scoring component distinguishes odd vs even
   weeks — except a second-order week-aware `tough_days` effect when they
   co-occur with other same-day classes).
3. So the top list fills with **look-alike duplicates** that differ only by
   which week-twin was chosen, crowding out genuinely different arrangements.

The user brute-forces the whole space and wants to (a) collapse these look-alike
twins into one entry that lists all the class numbers to bid, and (b) see **all**
distinct arrangements, not just 5.

## Non-goal / correctness boundary

**Enumeration stays footprint-exact.** Odd/even twins **clash differently** — a
clash requires overlapping weeks, so LAB[03] (odd) and LAB[04] (even) collide
with different sets of other classes. Collapsing twins *before* clash-checking
would be unsound (it could invent an invalid timetable or hide a valid one).
`enumerate_clashfree` is unchanged; all collapsing happens at the presentation
layer over already-validated clash-free combos.

## Solution

### 1. Group ranked combos into "distinct arrangements" (`search.py`)

New data types and function:

```
@dataclass(frozen=True)
class SlotBid:
    module: str
    lesson_type: str
    options: tuple  # (class_no, week_label) pairs — the interchangeable twins at this slot

@dataclass
class Arrangement:
    score: float          # the BEST score among the collapsed variants
    breakdown: dict       # breakdown of the best variant
    assignment: dict      # representative (best-scoring) {(module, lesson_type): Choice}
    bids: list            # list[SlotBid], one per group
    variant_count: int    # how many clash-free timetables collapsed into this arrangement

def rank_arrangements(space, config, limit=None) -> list[Arrangement]
```

Algorithm (single pass over `space.combos`, O(combos) time, O(arrangements)
memory):

- **Arrangement key** for a combo = `frozenset` of `(module, lesson_type,
  session.day, session.start, session.end, session.online)` over every session
  of every chosen class — i.e. the slot layout, **ignoring class number and
  weeks**.
- Score each combo with `score_assignment`. Accumulate per key:
  - the best `(score, breakdown, assignment)` seen so far (ties broken
    deterministically, e.g. by the representative's sorted class numbers);
  - per `(module, lesson_type)` slot, the set of `(class_no, weeks)` used;
  - the set of full combos (as a tuple of class numbers) placed in this key, to
    check independence (below).
- **Independence / entanglement guard (soundness):** within a key group, the
  collapsed bids are only presented as *independent per-slot choices* if the set
  of clash-free combos equals the Cartesian product of the per-slot option sets
  (`len(combos_in_group) == prod(len(options[slot]))`). This holds in the common
  case (twins live in one group; other slots have a single option). If it does
  **not** hold — the rare case where two different modules' balloted classes
  share the same day/time with odd/even splits, so picking one twin forces
  another — the group is **not** collapsed: each distinct combo becomes its own
  `Arrangement`. This guarantees every listed per-slot bid participates in a
  genuinely clash-free timetable.
- Sort arrangements by `-score`; apply `limit` (None = all).

`week_label(weeks)` helper (`model.py`): `""` for all-weeks (13 weeks), `"even
wks"` / `"odd wks"` for pure even/odd sets, else a compact `"wks 2,4,6"`.

### 2. Show all distinct arrangements

`AppState` gains `top_arrangements()` returning `rank_arrangements(space, config,
limit=config.top_n or None)`. `top_n` is reinterpreted as an **optional cap on
arrangements**: `0`/absent → show all. Default becomes "all" (the twins collapse,
so the list stays sane). Because grouping is a single pass, this adds no
enumeration cost.

### 3. TUI presentation (`tui/app.py`)

- **List:** one row per arrangement, best-first: `#i  {score:+.1f}` plus a
  `(N variants)` suffix when `variant_count > 1`.
- **Detail pane:** breakdown + week grid (of the representative) + warnings + a
  new **Bids** block + share URL (representative). The Bids block lists each
  balloted slot's interchangeable class numbers with week labels:
  ```
  Bids (interchangeable per slot):
    EG1311 LAB  Mon 1200-1400  →  03 (odd wks) / 04 (even wks)
    CS1010 TUT  Wed 1300-1400  →  06
  ```
  The block lists **every balloted slot** (the ones the user actually bids for in
  EduRec), each with its interchangeable class numbers — even a slot with a
  single option, so the bid list is complete. Fixed and non-balloted slots
  (e.g. lectures) are omitted from the Bids block (they need no bid).
- The week grid + warnings + share URL continue to use the representative
  assignment, so all previously-built features keep working unchanged.

### 4. Ballot view consistency (`ballot.py`)

`ranked_options` currently groups interchangeable classes by exact footprint
(`result.members` is footprint-keyed), so odd/even twins are **not** tied there
either. Extend the tie-grouping to the **slot signature** `(day, start, end,
online)` (weeks-agnostic) so the ballot/snake output also collapses twins,
annotating each with its `week_label`. This reuses the existing `tied_with`
machinery and keeps the ballot consistent with the new arrangements list.

## Testing

- `rank_arrangements`: (a) two week-twins in one group collapse to a single
  arrangement whose `SlotBid` lists both class numbers with correct week labels;
  (b) two independent twin groups collapse to one arrangement (Cartesian product
  holds); (c) the entangled cross-module-same-slot case does **not** collapse
  (falls back to separate arrangements); (d) an arrangement's `score` is the best
  among its variants; (e) `limit` caps the count.
- `week_label`: all-weeks → `""`; even/odd → labels; mixed → compact list.
- TUI: the list shows all arrangements with the `(N variants)` suffix; the detail
  Bids block lists a twinned slot's class numbers.
- Existing `search.py`/ballot/TUI tests stay green; `enumerate_clashfree` and
  scoring are unchanged.

## Out of scope

- No change to enumeration or clash logic.
- No change to `output.render_week` (plain-text `run` grid); the `run` CLI can
  adopt arrangements in a follow-up.
- No new bidding automation — the user still bids in EduRec manually.
