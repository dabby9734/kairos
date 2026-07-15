# Design: cache per-combo `raw`, reweight on weight sliders

## Motivation

The live-tuning TUI re-scores every clash-free combo on every slider move.
`AppState.retune()` calls `_score_combos(space, config)` — which runs
`score_assignment` over each combo — then feeds the result to `rank` and
`rank_arrangements`. On a loose real config (~59,748 combos) that is ~3.3 s per
move, and the dominant cost is the per-combo scoring itself.

The key structural fact (`scoring.py:119-120`): each combo's six `raw` criteria
are computed first and are **fully weight-independent** — the preference
`weights` only multiply in at the very end. So once `raw` is cached per combo, a
**weight-slider** move (the most common interaction) skips re-scoring: the
re-weight itself is ~90 ms over ~60k combos.

> **Measured outcome (real config, 59,748 combos):** this cache removes the
> ~1.46 s `score_raw`/`compute_raw` pass on weight moves, taking a retune from
> ~3.37 s to ~1.80 s — a **~2× speedup**, not the sub-100 ms an earlier estimate
> claimed. That estimate was wrong: it modelled only the scoring pass and ignored
> `rank_arrangements`, which `reweight()` still runs in full (~1.35 s) and which
> now dominates. `rank_arrangements`'s cost is its per-combo `_arrangement_key`
> grouping + Cartesian soundness check — and that structure is **also
> weight-independent**, so caching it is the clear next lever (separate
> follow-up) that unlocks the rest of the win. This feature is a correct,
> foundational first step (it introduces the `reweight` path the ranking cache
> will build on), not the whole optimisation.

This is a complementary lever to the shipped lock-slots feature: locking shrinks
the *combo count*; caching makes the scoring half of each retune *free*.

## Scope (chosen: weight-reweight only)

Only **weight sliders** reweight from cache. Difficulty sliders, time-preference
sliders, and any lock/re-enumeration path do a **full rescore** that rebuilds the
cache. This is deliberate: `raw` genuinely depends on difficulty and the time
prefs (`tough_days` on module difficulty + `max_difficulty_per_day`;
`time_window` on `earliest_start`/`latest_end`; `lunch` on the lunch window), so
those sliders cannot reweight. Weight sliders touch none of the raw-affecting
inputs, so their reweight is provably equivalent to a full rescore.

Per-component partial invalidation (recompute only `tough_days` on a difficulty
move, only `time_window`+`lunch` on a time move) is **explicitly out of scope** —
it multiplies the code and tests for the less-common sliders and can be a
follow-up if the ~3.3 s on those paths ever bothers the user in practice. No new
third-party dependencies (numpy rejected: the pure-Python reweight is already
sub-100 ms, imperceptible to a human on a single move).

## 1. Scoring split (`optimiser/scoring.py`)

Split `score_assignment` into its two natural halves:

- **`compute_raw(choices, config) -> dict`** — the weight-independent work: every
  line of the current `score_assignment` that builds the `raw` dict (campus/day
  grouping, `time_window`, `tough_days` via `tough_day_peaks`, `same_day_pairing`,
  `free_days`, `gaps`, `lunch`). Returns the six-key `raw` dict.
- **`weight_raw(raw, config) -> (total, breakdown)`** — the cheap tail:
  `breakdown = {name: (value, config.preferences.weights[name] * value) for name, value in raw.items()}`,
  `total = sum(weighted for _, weighted in breakdown.values())`.

`score_assignment(choices, config)` becomes a thin wrapper —
`weight_raw(compute_raw(choices, config), config)` — returning the same
`(total, breakdown)` as today, so `class_warnings`, the CLI, and existing scoring
tests are untouched.

## 2. Cache layer (`optimiser/search.py`)

Two functions beneath the existing `_score_combos`:

- **`score_raw(space, config) -> list`** — the cacheable, expensive pass. For each
  combo: `raw = compute_raw(list(combo), config)`,
  `assignment = {(c.module, c.lesson_type): c for c in combo}`; returns
  `[(raw, assignment, combo), ...]`.
- **`weight_scored(raw_entries, config) -> list`** — the cheap pass:
  `[(total, breakdown, assignment, combo), ...]` where
  `(total, breakdown) = weight_raw(raw, config)`. Returns **exactly** the tuple
  shape `_score_combos` returns today.

`_score_combos(space, config)` becomes
`weight_scored(score_raw(space, config), config)`, so `rank`, `rank_arrangements`,
and the CLI `search()` path see no change (the `scored=` sharing already in place
continues to work).

## 3. State wiring (`optimiser/tui/state.py`)

- **New field `AppState._raw_cache`** — holds `score_raw(space, config)` for the
  current `space`. Default `None`; populated on every full build.
- **`retune()` (full path)** rebuilds the cache, then reweights and ranks:
  ```
  self._raw_cache = score_raw(self.space, self.config)
  scored = weight_scored(self._raw_cache, self.config)
  self.result = rank(self.space, self.config, scored=scored)
  self.arrangements = rank_arrangements(self.space, self.config,
                                        limit=self.config.max_arrangements, scored=scored)
  return self.result
  ```
- **New `reweight()` (cheap path)** reuses the cache, skipping `score_raw`:
  ```
  scored = weight_scored(self._raw_cache, self.config)
  self.result = rank(...); self.arrangements = rank_arrangements(...)
  return self.result
  ```
  The `rank`/`rank_arrangements` lines are identical to `retune`'s; extract a
  private `self._rank_from(scored)` helper so the two paths share the ranking tail
  and cannot drift.
- **Routing:** `set_weight` → `reweight()`. `set_difficulty`, `set_pref`, and
  every lock / `_rebuild` / `_prepare_space` path → `retune()` (they dirty `raw`
  or the combo set).
- **Guard:** `_apply_locked_change`'s snapshot/restore tuple gains
  `self._raw_cache`, so a rejected lock rolls the cache back alongside
  `groups`/`space`/`result`/`arrangements`.

The cache is valid exactly while the combo set and the raw-affecting config
(difficulty, time prefs, `max_difficulty_per_day`) are unchanged. Every mutator
that can change those goes through `retune()`; only `set_weight` uses `reweight()`.

## 4. Testing

- **Equivalence (safety net):** after a weight change, `reweight()` yields the
  same `result.top` scores and `arrangements` scores as a full `retune()` at the
  same weights.
- **No-recompute:** a weight-slider change does not call `compute_raw` (monkeypatch
  a counter / spy) — proves the cache is actually reused, not silently rebuilt.
- **Cache rebuild on non-weight paths:** `set_difficulty` and `set_pref` change the
  scores (existing scoring behavior) and repopulate `_raw_cache`; a difficulty
  change followed by a weight reweight reflects the new difficulty.
- **Guard rollback:** a rejected `set_lock` (empty space) restores `_raw_cache`
  along with the rest of state.
- **Behavior-preserving:** CLI `search()` output and `score_assignment` return
  value unchanged; existing suite stays green.

## Out of scope (separate follow-ups)

- **Per-component partial invalidation** for difficulty/time sliders (recompute
  only the dirtied `raw` components). Deferred; revisit only if those sliders'
  full rescore becomes a felt problem.
- **Ranking-structure cache** (the follow-up this feature enables): cache
  `rank_arrangements`'s weight-independent grouping (`_arrangement_key` clusters +
  the Cartesian soundness result) so a `reweight()` only re-scores group
  representatives and re-selects the top-`limit`, instead of re-grouping all ~60k
  combos (~1.35 s today). This is the lever that takes the weight-move retune from
  ~1.8 s toward the original sub-100 ms goal. Deserves its own spec.
- **numpy vectorisation** of the reweight/ranking. Rejected: the pure-Python
  reweight is already ~90 ms; numpy would add a dependency for an imperceptible
  gain on that step unless the combo count grows 10-100×.
