# Design: Lock decided slots

## Motivation

The live-tuning TUI enumerates every clash-free timetable. On an under-constrained
config (12 groups) that is ~59,748 combos → ~22,964 distinct arrangements, and a
retune scores all of them (~3.3 s per slider move). Once a user has *decided* on a
particular slot — "my CS2030S Lab is the Wednesday 2pm one" — there is no reason to
keep exploring the other Lab slots. Letting the user **lock** a decided slot both
expresses that intent and cuts the combo count at its source (the count is a product
over each free group's option count, so fixing a group divides the space).

Locking is therefore the primary performance lever *and* a real usability feature:
the same action that says "keep this" also makes everything else faster.

## Key behaviour: lock the slot, keep interchangeable twins

Locking pins the **slot** (day/time/online signature), not a single class number. When
the user locks "CS2030S Lab → 05", the group is restricted to every class sharing 05's
`(day, start, end, online)` signature — its week-twins and venue-twins (e.g. `05` odd /
`07` even) — and all *other* Lab slots are dropped.

Consequences:
- **Maximum search shrink.** The group collapses from many options to the twins at one
  slot, and those twins already collapse into a single arrangement variant, so the
  effect on the combo product is essentially the same as a hard single-class pin.
- **Ballot still shows interchangeability.** Because both twins remain in the space, the
  existing clash-set grouping in `ballot.ranked_options` keeps surfacing them as
  "bid 05 / 07", and it stays *correct* as further slots are locked (it is recomputed
  against the actual reduced space, never a frozen snapshot).

This is deliberately distinct from the pre-existing `fixed:` config (a hard pin to
exactly one class, used by CLI users): `fixed` keeps one class; `locked` keeps the
interchangeable set at the slot.

## 1. Config & data model

- **New config field `locked`:** `module → {lesson_abbrev: class_no}`, e.g.
  ```yaml
  locked:
    CS2030S:
      LAB: "05"
  ```
  Added to the `Config` dataclass and its loader in `optimiser/config.py` (mirroring how
  `fixed` is parsed/defaulted, default `{}`). Emitted by `AppState.to_config_yaml`.
- **`prepare_groups` expansion** (`optimiser/search.py`): for a group whose
  `(module, abbrev)` appears in `locked`, restrict its choices to those sharing the
  locked class's `(day, start, end, online)` slot signature. If the locked class number
  does not exist in the group's choices, raise the same style of `SystemExit` error that
  `fixed` raises for a missing class (fail loud on a stale config).
- **Precedence with `fixed`:** `fixed` is applied first and wins. A group present in
  `fixed` is never additionally narrowed by `locked` (and the TUI will not offer to lock
  an already-`fixed` group). This keeps existing CLI behaviour unchanged.

## 2. Search / state rebuild

Locking changes the *prepared groups*, so it requires re-enumeration, not just the
re-scoring that `retune` does today.

- **New `AppState.set_lock(module, abbrev, class_no)` and `clear_lock(module, abbrev)`:**
  mutate `config.locked`, then re-run `prepare_groups → enumerate_clashfree → retune`,
  rebuilding `self.space`, `self.result`, and `self.arrangements`. (Extract the
  `from_parts` build sequence into a shared helper so `set_lock`/`clear_lock` reuse it.)
- **Over-constraint guard:** if applying a lock yields an empty space
  (`enumerate_clashfree` produces no combos), do **not** commit it — restore the previous
  `config.locked`/`space`/results and return a failure signal so the TUI can warn
  ("locking CS2030S LAB leaves no clash-free timetable"). Locks are always reversible.
- Difficulty normalisation (`normalize_difficulties`) must run on the rebuilt prepared
  groups exactly as `from_parts` does, so locking cannot desync difficulty resolution.

## 3. TUI interaction

- **Slot list widget:** a focusable `ListView` (`#slot-list`) in the results pane showing
  the currently-selected arrangement's *balloted* slots — one row per `SlotBid`
  (`module abbrev → current class`), with a 🔒 prefix when that group is locked.
  Non-balloted / single-option groups are already effectively fixed and are not listed.
- **`l` — toggle lock** on the highlighted slot:
  - If unlocked: `set_lock(module, abbrev, class_no)` using the class from the
    *selected arrangement*'s assignment for that group.
  - If locked: `clear_lock(module, abbrev)`.
  - On success: re-enumerate + re-rank, refresh the arrangements list, the slot list
    (locked rows keep their 🔒), and the detail pane. On the empty-space guard firing:
    `self.notify(...)` the warning and leave state unchanged.
- **Persistence:** locks live in session state; **`s`** (existing save action) writes
  `config.locked` to `config.yaml` alongside the other edits. No implicit disk writes.
- **Focus:** the slot list joins the existing focus order (arrangements list, sliders,
  priority list); a binding to jump focus to it, and the `l` binding, are added to
  `BINDINGS`. Exact placement/height is a layout detail for the plan.

## 4. Ballot / interchangeability

No new ballot code. Because locking keeps the slot's interchangeable twins in the space,
`ballot.ranked_options`'s clash-set grouping already lists them as interchangeable, and
the week-label annotations still flow from the arrangement bids. A locked slot simply has
fewer competing slots around it.

## 5. Testing

- **Unit (`prepare_groups`):** a `locked` entry restricts the group to the slot-signature
  twin set and drops other slots; a missing locked class raises `SystemExit`; a group in
  both `fixed` and `locked` follows `fixed`.
- **State:** `set_lock` shrinks `space.combos` and changes the ranking; `clear_lock`
  restores the prior combo count; the empty-space guard leaves state unchanged and
  signals failure.
- **Round-trip:** `locked` survives `to_config_yaml → load_config → prepare_groups`.
- **TUI (Pilot):** pressing `l` on a slot marks it 🔒 and reduces the arrangement count;
  a locked slot's twins still appear as interchangeable in the ballot view; pressing `l`
  again unlocks and restores.

## Out of scope (separate follow-ups)

- **Raw-value caching optimisation:** caching each combo's pre-weight `raw` criteria so
  that *weight*-slider retunes become a re-weighted sum (near-instant) is a separate,
  high-value optimisation to be specced on its own. Not required for this feature.
- **Heavy dependencies rejected:** numpy vectorisation is marginal once `raw` is cached;
  constraint solvers (OR-Tools/CP-SAT) fight the "enumerate-and-rank-many" model and are
  not pursued.
