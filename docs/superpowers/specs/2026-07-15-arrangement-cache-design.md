# Design: cache the score-independent arrangement structure

## Motivation

The raw-cache feature made a weight-slider retune reweight cached `raw` values
instead of re-scoring, removing the ~1.46 s `score_raw` pass. Measurement on the
real config (59,748 combos) then showed the retune floor is now
`rank_arrangements` at ~1.35 s, which `reweight()` still runs in full every move —
so a weight move is ~1.8 s, not the sub-100 ms the raw-cache alone was hoped to
reach.

`rank_arrangements` does two intertwined things per call: (1) **group** all combos
by `_arrangement_key`, compute each group's `slot_opts`, and decide collapse vs.
entangled — this is pure *combo structure*, ~1.35 s; and (2) **select** the winning
representative per group and the top-`limit` — score-dependent and cheap. Part (1)
depends only on the combo set — not on weights, difficulty, or time — so it can be
computed once per space and reused across every retune and reweight.

This is the next lever after the raw-cache (which it builds on): raw-cache made
scoring cheap; this makes the *grouping* cheap.

## Scope (chosen: `rank_arrangements` only)

Cache the `rank_arrangements` grouping + collapse decision. `rank` (~0.35 s, which
builds `result.top` and `best_by_footprint` for the ballot) is **out of scope** and
becomes the remaining floor; caching its footprint structure is a possible later
lever. No new third-party dependencies.

**Expected outcome:** weight move ~1.8 s → ~0.5 s (floor = `rank` 0.35 s + reweight
0.09 s). Bonus: because the structure survives difficulty/time changes too, those
retunes also drop the ~1.35 s (~3.3 s → ~1.9 s).

## 1. Structure representation (`optimiser/search.py`)

A new **`build_arrangement_structure(space) -> list`** produces one *candidate
template* per candidate source, referencing combos by **index** into the scored
list. Indices are stable because `score_raw`/`weight_scored` preserve
`space.combos` order, and the structure is rebuilt whenever `space` is replaced.

Each template is a small **frozen dataclass** `_ArrTemplate` with:
- `member_indices: tuple[int]` — combos this candidate draws from.
- `slot_opts: dict` — `(module, lesson_type) -> {footprint: weeks}`, as
  `rank_arrangements` builds today (used by `_make_arrangement`).
- `variant_count: int`.
- `class_keys: tuple` — per member (aligned to `member_indices`), the combo-fixed
  tiebreak `tuple(sorted(c.class_no for c in combo))`. Only meaningful for
  collapsed groups (used to break score ties when picking the representative).

Construction mirrors the current first pass exactly:
- Group entries by `_arrangement_key(combo)` (over `space.combos`, tracking each
  combo's index).
- Per group, build `slot_opts` (keyed by footprint, as today) and
  `product = ∏ len(by_fp)`.
- **Collapsed** (`product == len(members)`): one template with all member indices,
  the group `slot_opts`, `variant_count = len(members)`, and per-member
  `class_keys`.
- **Entangled** (else): one template per member — `member_indices = (i,)`, that
  combo's own single-combo `slot_opts`, `variant_count = 1`.

## 2. Selection (`optimiser/search.py`)

`rank_arrangements(space, config, limit=None, scored=None, structure=None)`:
- `scored` defaults to `_score_combos(space, config)` (unchanged).
- `structure` defaults to `build_arrangement_structure(space)` — so the CLI
  `search()` path and any caller that omits `structure` is **byte-for-byte
  behavior-preserving** (same cost as today, just reorganised).
- Build candidates from the structure + `scored`:
  - Collapsed template: pick the representative member by
    `min(..., key=lambda k: (-scored[member_indices[k]][0], class_keys[k]))`,
    reproducing today's `min(entries, key=(-score, sorted-class_no))`.
  - Entangled template (`len(member_indices) == 1`): the single member.
  - Candidate = `(score, scored[i], slot_opts, variant_count)` where `i` is the
    chosen member and `score = scored[i][0]`.
- Select the top `limit` via `heapq.nlargest` (or `sorted` when `limit` is falsy),
  exactly as today, then `_make_arrangement` for the survivors only.

`_make_arrangement`, `SlotBid`, `Arrangement`, and `_arrangement_key` are
unchanged. The extracted candidate-building may live in a small helper
(`_candidates_from_structure(structure, scored)`) so `rank_arrangements` stays
readable.

## 3. State wiring (`optimiser/tui/state.py`)

The structure depends on `space` alone, so it is rebuilt only where `space` is
replaced — never inside `retune()`.

- **New field `AppState._arr_structure`** (default `None`).
- **`_rebuild`:** after `self.groups, self.space = self._prepare_space()`, set
  `self._arr_structure = build_arrangement_structure(self.space)` before calling
  `retune()`.
- **`_apply_locked_change` success branch:** after `self.space = space`, set
  `self._arr_structure = build_arrangement_structure(space)` before `retune()`.
- **`retune()`** rebuilds `self._raw_cache` (raw still depends on difficulty/time)
  but does **not** touch `_arr_structure`.
- **`_rank_from(scored)`** passes `structure=self._arr_structure` into
  `rank_arrangements(...)`. Both `retune()` and `reweight()` route through
  `_rank_from`, so both reuse the cached structure.
- **Guard:** `_apply_locked_change`'s snapshot/restore tuple gains
  `self._arr_structure`, so a rejected lock restores the prior structure alongside
  `_raw_cache` and the rest.

Invalidation summary — `_arr_structure` is invalidated by a **space change only**
(lock/rebuild); `_raw_cache` by **difficulty/time/space**; weights invalidate
neither (reweight reuses both).

## 4. Testing

- **Equivalence:** for a fixture space, `rank_arrangements(space, config, scored=S)`
  (inline structure) equals `rank_arrangements(space, config, scored=S,
  structure=build_arrangement_structure(space))` — identical arrangements, scores,
  bids, and order. This is the safety net that the cached path matches the live
  path.
- **Structure survives a weight change:** after `set_weight`, `state._arr_structure`
  is the same object (identity unchanged) and the arrangements still match a full
  from-scratch `rank_arrangements`.
- **Structure rebuilt on lock, restored on rejected lock:** a successful lock
  produces a new `_arr_structure` for the reduced space; a rejected lock (empty
  space) restores the prior `_arr_structure` (identity check).
- **Collapse and entangle both covered:** the equivalence test's fixture must
  include at least one collapsed group (interchangeable twins) and one entangled
  group, so both template kinds are exercised — the existing `groups` fixture
  (ALPHA tutorials collapse; the L1-clash entangles) already provides this.
- **Behavior-preserving:** CLI `search()` and the full existing suite stay green.

## Out of scope (separate follow-ups)

- **Caching `rank`** (`result.top` heap + `best_by_footprint` structure), the
  ~0.35 s that becomes the new floor. The footprint *keys* are score-independent
  and cacheable, but this touches the ballot's `best_by_footprint` contract, so it
  deserves its own spec if sub-200 ms weight moves are wanted.
- **numpy / vectorisation** — unchanged rejection; the remaining hot loops are
  irregular per-group work, not array math.
