# Arrangement-Structure Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cache the score-independent arrangement grouping so `rank_arrangements` no longer re-groups all ~60k combos on every retune/reweight, removing the ~1.35 s bottleneck that dominates a weight move after the raw-cache.

**Architecture:** Split `rank_arrangements` into a score-independent structure builder (`build_arrangement_structure(space)` — grouping + collapse decision + `slot_opts`, keyed by combo index) and a cheap score-dependent selection. `AppState` caches the structure in `_arr_structure`, rebuilt only when the space changes (the two `self.space` reassignment sites + the lock guard), and reused by every retune and reweight.

**Tech Stack:** Python 3.13, pytest. No new third-party dependencies.

## Global Constraints

- No new third-party dependencies.
- `rank_arrangements(space, config, limit=None, scored=None)` must stay behavior-preserving when called WITHOUT a `structure` (it builds one inline) — the CLI `search()` path and every existing caller/test are untouched.
- `_arr_structure` is invalidated by a **space change only** (lock/rebuild) — NOT by weights, difficulty, or time. Every site that reassigns `self.space` must rebuild it; `retune()` must NOT.
- The cached-structure path must produce arrangements identical (score, variant_count, bids, assignment, order) to the inline path — verified by the equivalence tests.
- Structure references combos by index into the scored list; this is valid because `score_raw`/`weight_scored` preserve `space.combos` order and the structure is rebuilt whenever `space` is replaced.

---

### Task 1: `build_arrangement_structure` + structure-driven `rank_arrangements`

**Files:**
- Modify: `optimiser/search.py` (add `_ArrTemplate` + `build_arrangement_structure` after `_arrangement_key` at line 185; add `_candidates_from_structure`; refactor `rank_arrangements` 217-267)
- Test: `tests/test_search.py`

**Interfaces:**
- Produces:
  - `_ArrTemplate` — frozen dataclass: `member_indices: tuple`, `slot_opts: dict`, `variant_count: int`, `class_keys: tuple`.
  - `build_arrangement_structure(space) -> list[_ArrTemplate]` — score-independent; one template per candidate source, combos referenced by index into `space.combos`.
  - `rank_arrangements(space, config, limit=None, scored=None, structure=None)` — new optional `structure` param; defaults to `build_arrangement_structure(space)` (behavior-preserving).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_search.py` (after `test_rank_arrangements_ranks_by_best_and_limits`, at the end of the file). These reuse the existing module-level `_space` helper and `ALL_WEEKS`. They assert concrete known-correct outputs THROUGH the cached-structure path — behavior-preservation of the inline (`structure=None`) path is already guaranteed by the existing, unchanged `rank_arrangements` tests above.

```python
def test_build_structure_collapse_produces_correct_arrangement(config):
    # Week-twin collapse: 01 odd / 02 even at the same Mon slot -> one collapsed
    # template holding both members -> one arrangement with variant_count 2 and both
    # class numbers offered as a bid (mirrors test_rank_arrangements_collapses_week_twins).
    from optimiser.search import build_arrangement_structure, rank_arrangements

    odd = frozenset({1, 3, 5})
    even = frozenset({2, 4, 6})
    lec = Choice("ALPHA", "Lecture", "1", (Session("Monday", 600, 720, ALL_WEEKS, "COM1"),))
    tut_odd = Choice("ALPHA", "Tutorial", "01", (Session("Monday", 840, 900, odd, "COM1"),))
    tut_even = Choice("ALPHA", "Tutorial", "02", (Session("Monday", 840, 900, even, "COM1"),))
    space = _space((lec, tut_odd), (lec, tut_even))
    structure = build_arrangement_structure(space)
    assert [len(t.member_indices) for t in structure] == [2]  # collapse branch: one 2-member template
    arrs = rank_arrangements(space, config, structure=structure)
    assert len(arrs) == 1 and arrs[0].variant_count == 2
    tut_bid = next(b for b in arrs[0].bids if b.lesson_type == "Tutorial")
    assert dict(tut_bid.options) == {"01": "odd wks", "02": "even wks"}


def test_build_structure_entangle_keeps_variants_separate(config):
    # Opposite-week ALPHA/BETA at the same slot: product (4) != member count (2), so
    # the group must NOT collapse -> two single-member templates, two arrangements.
    from optimiser.search import build_arrangement_structure, rank_arrangements

    odd = frozenset({1, 3, 5})
    even = frozenset({2, 4, 6})
    a_odd = Choice("ALPHA", "Tutorial", "01", (Session("Monday", 840, 900, odd, "COM1"),))
    a_even = Choice("ALPHA", "Tutorial", "02", (Session("Monday", 840, 900, even, "COM1"),))
    b_odd = Choice("BETA", "Laboratory", "L1", (Session("Monday", 840, 900, odd, "COM2"),))
    b_even = Choice("BETA", "Laboratory", "L2", (Session("Monday", 840, 900, even, "COM2"),))
    space = _space((a_odd, b_even), (a_even, b_odd))
    structure = build_arrangement_structure(space)
    assert [len(t.member_indices) for t in structure] == [1, 1]  # entangle branch: two single templates
    arrs = rank_arrangements(space, config, structure=structure)
    assert len(arrs) == 2 and all(a.variant_count == 1 for a in arrs)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_search.py::test_build_structure_collapse_produces_correct_arrangement tests/test_search.py::test_build_structure_entangle_keeps_variants_separate -v`
Expected: FAIL — `ImportError: cannot import name 'build_arrangement_structure'`.

- [ ] **Step 3: Add `_ArrTemplate` and `build_arrangement_structure`**

In `optimiser/search.py`, immediately after `_arrangement_key` (ends line 185), add:

```python
@dataclass(frozen=True)
class _ArrTemplate:
    # A score-INDEPENDENT candidate source for rank_arrangements. Combos are
    # referenced by index into the scored list (== space.combos order). For a
    # collapsed group, member_indices holds every combo in the group and the
    # representative is chosen at selection time by score; for an entangled
    # member, member_indices is a single index.
    member_indices: tuple
    slot_opts: dict          # (module, lesson_type) -> {footprint: weeks}
    variant_count: int
    class_keys: tuple        # per member: tuple(sorted class_no); the collapse tiebreak


def build_arrangement_structure(space) -> list:
    """Precompute the weight/score-INDEPENDENT arrangement grouping for a space:
    group combos by slot layout, build each group's slot_opts, and decide
    collapse (full Cartesian product of same-slot week-variants) vs. entangled.
    Reuse this across retunes/reweights; it changes only when the space does."""
    groups: dict = {}  # _arrangement_key -> [combo index]
    for i, combo in enumerate(space.combos):
        groups.setdefault(_arrangement_key(combo), []).append(i)

    templates: list = []
    for indices in groups.values():
        slot_opts: dict = {}  # keyed by FOOTPRINT (Cartesian guard counts footprints)
        for i in indices:
            for c in space.combos[i]:
                slot_opts.setdefault((c.module, c.lesson_type), {})[c.footprint] = c.sessions[0].weeks
        product = 1
        for by_fp in slot_opts.values():
            product *= len(by_fp)
        if product == len(indices):  # independent -> collapse into one template
            class_keys = tuple(
                tuple(sorted(c.class_no for c in space.combos[i])) for i in indices
            )
            templates.append(_ArrTemplate(tuple(indices), slot_opts, len(indices), class_keys))
        else:  # entangled -> one single-member template per combo
            for i in indices:
                single = {
                    (c.module, c.lesson_type): {c.footprint: c.sessions[0].weeks}
                    for c in space.combos[i]
                }
                templates.append(_ArrTemplate((i,), single, 1, ()))
    return templates
```

- [ ] **Step 4: Add `_candidates_from_structure` and refactor `rank_arrangements`**

In `optimiser/search.py`, replace `rank_arrangements` (lines 217-267) with a helper plus the slimmed function. The candidate list this produces is identical (content AND order) to the current first pass, so `nlargest`/`sorted` selection and `_make_arrangement` are unchanged.

```python
def _candidates_from_structure(structure, scored) -> list:
    """Build (score, entry, slot_opts, variant_count) candidates from a cached
    structure and a fresh scored list. Collapsed templates pick the highest-scoring
    member (tiebreak by class_keys), reproducing the original per-group `min`."""
    candidates = []
    for tmpl in structure:
        idxs = tmpl.member_indices
        if len(idxs) == 1:
            i = idxs[0]
        else:
            best_k = min(
                range(len(idxs)),
                key=lambda k: (-scored[idxs[k]][0], tmpl.class_keys[k]),
            )
            i = idxs[best_k]
        candidates.append((scored[i][0], scored[i], tmpl.slot_opts, tmpl.variant_count))
    return candidates


def rank_arrangements(space, config, limit=None, scored=None, structure=None) -> list:
    """Collapse clash-free timetables that share a slot layout (differing only by
    interchangeable same-slot week-twins) into ranked Arrangements. Twins are
    offered as free per-slot bids only when the group's clash-free combos form a
    full Cartesian product; otherwise the combos are kept as separate
    arrangements (soundness — see design doc). Slot bids additionally list
    same-footprint venue-twins expanded from space.members (I1).

    The weight/score-INDEPENDENT grouping is factored into
    build_arrangement_structure; pass a cached `structure` to skip re-grouping
    (state.AppState does this). Omitting it rebuilds inline — behavior-preserving."""
    if scored is None:
        scored = _score_combos(space, config)
    if structure is None:
        structure = build_arrangement_structure(space)

    candidates = _candidates_from_structure(structure, scored)

    # Select winners by -score (stable in insertion order for ties, matching a
    # full sort), then build bids/venue-expansion ONLY for the survivors.
    if limit:
        selected = heapq.nlargest(limit, candidates, key=lambda cand: cand[0])
    else:
        selected = sorted(candidates, key=lambda cand: -cand[0])
    return [
        _make_arrangement(entry, opts, config, variant_count, space)
        for _score, entry, opts, variant_count in selected
    ]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_search.py -v`
Expected: PASS (all search tests — the existing `rank_arrangements` tests exercise the inline `structure=None` path unchanged, plus the two new equivalence tests).

- [ ] **Step 6: Commit**

```bash
git add optimiser/search.py tests/test_search.py
git commit -m "feat: build_arrangement_structure caches rank_arrangements grouping"
```

---

### Task 2: `AppState` caches `_arr_structure`

**Files:**
- Modify: `optimiser/tui/state.py` (imports 7-16; `AppState` dataclass 48-56; `_rebuild` 83-85; `_rank_from` 87-96; `_apply_locked_change` 135-151)
- Test: `tests/test_tui_state.py`

**Interfaces:**
- Consumes: `build_arrangement_structure` from Task 1.
- Produces:
  - `AppState._arr_structure: list = None` — cached structure for the current space.
  - `_rebuild` and `_apply_locked_change`'s success branch rebuild it after reassigning `self.space`.
  - `_rank_from` passes `structure=self._arr_structure` into `rank_arrangements`.
  - The guard snapshot/restore includes `_arr_structure`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tui_state.py` (the file already has the `state` fixture):

```python
def test_arr_structure_reused_on_weight_change(state):
    from optimiser.search import rank_arrangements

    before = state._arr_structure
    state.set_weight("free_days", 9)
    assert state._arr_structure is before  # weight move must NOT rebuild the structure
    # arrangements still correct: match a full from-scratch rank at these weights
    fresh = rank_arrangements(state.space, state.config, limit=state.config.max_arrangements)
    assert [a.score for a in state.arrangements] == [a.score for a in fresh]


def test_arr_structure_reused_on_difficulty_change(state):
    before = state._arr_structure
    state.set_difficulty("ALPHA", "TUT", 5)
    # difficulty dirties raw (retune rebuilds _raw_cache) but NOT the slot structure
    assert state._arr_structure is before


def test_arr_structure_rebuilt_on_successful_lock(state):
    before = state._arr_structure
    assert state.set_lock("ALPHA", "TUT", "02") is True
    assert state._arr_structure is not before  # new (smaller) space -> new structure


def test_arr_structure_restored_on_rejected_lock(config):
    import copy

    from optimiser.model import Choice, ChoiceGroup, Session

    all_weeks = frozenset(range(1, 14))
    tut = ChoiceGroup(
        "ALPHA", "Tutorial",
        [
            Choice("ALPHA", "Tutorial", "T1", (Session("Monday", 540, 600, all_weeks, "COM1"),)),
            Choice("ALPHA", "Tutorial", "T2", (Session("Tuesday", 540, 600, all_weeks, "COM1"),)),
        ],
    )
    lab = ChoiceGroup(
        "BETA", "Laboratory",
        [Choice("BETA", "Laboratory", "L1", (Session("Monday", 540, 600, all_weeks, "COM1"),))],
    )
    cfg = copy.deepcopy(config)
    cfg.fixed, cfg.locked = {}, {}
    cfg.modules = {"ALPHA": {"TUT": 3}, "BETA": {"LAB": 3}}
    state = AppState.from_parts(cfg, [tut, lab])
    before = state._arr_structure
    assert state.set_lock("ALPHA", "TUT", "T1") is False  # empties the space -> rejected
    assert state._arr_structure is before  # rejected lock restored the prior structure
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tui_state.py::test_arr_structure_reused_on_weight_change tests/test_tui_state.py::test_arr_structure_reused_on_difficulty_change tests/test_tui_state.py::test_arr_structure_rebuilt_on_successful_lock tests/test_tui_state.py::test_arr_structure_restored_on_rejected_lock -v`
Expected: FAIL — `AppState` has no `_arr_structure` attribute.

- [ ] **Step 3: Import the builder, add the field, wire the rebuild sites**

In `optimiser/tui/state.py`, add `build_arrangement_structure` to the search import block (lines 7-16):

```python
from ..search import (
    EnumeratedSpace,
    build_arrangement_structure,
    enumerate_clashfree,
    find_irreconcilable,
    prepare_groups,
    rank,
    rank_arrangements,
    score_raw,
    weight_scored,
)
```

Add the field to the `AppState` dataclass (after `_raw_cache`, line 56):

```python
    _raw_cache: list = None            # cached score_raw(space); reused by reweight()
    _arr_structure: list = None        # cached build_arrangement_structure(space); space-change only
```

Rebuild the structure in `_rebuild` (lines 83-85) — after the space is set, before `retune()`:

```python
    def _rebuild(self):
        self.groups, self.space = self._prepare_space()
        self._arr_structure = build_arrangement_structure(self.space)
        return self.retune()
```

Pass the cached structure through `_rank_from` (lines 87-96):

```python
    def _rank_from(self, scored):
        # Shared ranking tail: build result.top and the capped arrangement list
        # from an already-scored list. arrangements is capped at
        # config.max_arrangements (keeps the TUI ListView bounded); top_n only
        # sizes result.top (the raw timetable list). The arrangement grouping is
        # reused from the cached _arr_structure (rebuilt only on a space change).
        self.result = rank(self.space, self.config, scored=scored)
        self.arrangements = rank_arrangements(
            self.space, self.config, limit=self.config.max_arrangements,
            scored=scored, structure=self._arr_structure,
        )
        return self.result
```

`retune()` is left unchanged — it rebuilds `_raw_cache` (raw depends on difficulty/time) but must NOT touch `_arr_structure`.

- [ ] **Step 4: Include `_arr_structure` in the lock guard and rebuild it on a successful lock**

In `optimiser/tui/state.py`, update `_apply_locked_change` (lines 135-151) so the snapshot/restore carry `_arr_structure` and the success branch rebuilds it:

```python
    def _apply_locked_change(self, mutate) -> bool:
        """Mutate config.locked, rebuild the space, and commit only if the
        result is non-empty; otherwise roll everything back and return False."""
        snapshot = (
            {m: dict(v) for m, v in self.config.locked.items()},
            self.groups, self.space, self.result, self.arrangements,
            self._raw_cache, self._arr_structure,
        )
        mutate()
        prepared, space = self._prepare_space()
        if not space.combos:
            (self.config.locked, self.groups, self.space,
             self.result, self.arrangements,
             self._raw_cache, self._arr_structure) = snapshot
            return False
        self.groups = prepared
        self.space = space
        self._arr_structure = build_arrangement_structure(space)
        self.retune()
        return True
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tui_state.py -v`
Expected: PASS (all state tests, including the four new ones — the existing retune/lock/round-trip/arrangement-cap tests still pass because the cached structure yields identical arrangements).

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (whole suite — the inline `rank_arrangements` path is behavior-preserving and the cached path is proven equivalent).

- [ ] **Step 7: Commit**

```bash
git add optimiser/tui/state.py tests/test_tui_state.py
git commit -m "feat: AppState caches arrangement structure; rebuilt only on space change"
```

---

## Self-Review

**Spec coverage:**
- §1 Structure representation (`_ArrTemplate`, `build_arrangement_structure`, index-based, collapse/entangle) → Task 1 Step 3. ✓
- §2 Selection (`rank_arrangements` with optional `structure`, `_candidates_from_structure`, unchanged `_make_arrangement`/`nlargest`) → Task 1 Step 4. ✓
- §3 State wiring (`_arr_structure` field, rebuild at the two space sites, `_rank_from` passes it, `retune` doesn't touch it, guard snapshots it) → Task 2. ✓
- §4 Testing (equivalence with collapse AND entangle coverage; structure survives weight/difficulty; rebuilt on lock; restored on rejected lock; behavior-preserving) → Tasks 1-2. ✓
- Out-of-scope (`rank` caching, numpy) → correctly not planned. ✓

**Placeholder scan:** clean — every code and test step is complete and concrete. The Task 1 tests deliberately assert concrete known-correct outputs through the cached-structure path (not inline-vs-cached, which would be tautological since both build the same structure); inline-path behavior-preservation is covered by the existing unchanged `rank_arrangements` tests.

**Type consistency:** `build_arrangement_structure(space) -> list[_ArrTemplate]` (Task 1) is consumed by `_candidates_from_structure(structure, scored)` (Task 1) and cached in `AppState._arr_structure` (Task 2), which is passed as `structure=` to `rank_arrangements` (Task 2 `_rank_from`) matching the new signature (Task 1). `_ArrTemplate` field names (`member_indices`, `slot_opts`, `variant_count`, `class_keys`) are identical at definition (Task 1 Step 3) and use (Task 1 Step 4 `_candidates_from_structure`; Task 2 tests read `t.member_indices`). Candidate tuple shape `(score, entry, slot_opts, variant_count)` matches the `_make_arrangement` unpack (`_score, entry, opts, variant_count`), unchanged from today.

**Invalidation-scope check:** `_arr_structure` is written in exactly three places — `_rebuild`, `_apply_locked_change` success branch, and restored (not rebuilt) on the guard reject. `retune()` does not write it. That matches the spec's "space change only" rule; a difficulty/time retune reuses it (asserted by `test_arr_structure_reused_on_difficulty_change`).
