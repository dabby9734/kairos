# Ballot Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Annotate each ballot entry with the ceiling and median score of the timetables containing it, reorder the ballot on those signals, and make "timetable #k" mean the same thing in the CLI and the TUI.

**Architecture:** A new `kairos/provenance.py` computes, over *every* clash-free arrangement, which classes each one contains. `ballot.py` consumes that to replace its class-number tiebreak with `(-ceiling, -median, -support, class_no)` and to interleave interchangeable twins behind distinct timeslots. `output.py` renders the numbers; `cli.py` switches from combo-ranked to arrangement-ranked display so its timetable numbering matches the annotations.

**Tech Stack:** Python 3.13, pytest, Textual (TUI), Rich (rendering). No new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-22-ballot-provenance-design.md`.
- **Tests must assert on ordering relationships, never on literal scores.** Scores are weight-dependent and `config.yaml` is user-tuned; literal-score assertions will break on any slider change.
- **Backward compatibility is a hard requirement:** `all_options`, `ranked_options` and `render_snake` called *without* a provenance argument must produce byte-identical output to today.
- Provenance is always computed over the **uncapped** candidate set, never over `AppState.arrangements` (capped at `config.max_arrangements`, default 50).
- Float comparisons use a `1e-9` tolerance, matching existing practice in `search.py`.
- Run tests with `.venv/bin/pytest`.

---

### Task 1: Promote internal helpers to public API

Three modules will need `_score_combos` and `_candidates_from_structure`. Both are already imported directly by tests, so the leading underscore is not buying encapsulation.

**Files:**
- Modify: `kairos/search.py:146-150`, `kairos/search.py:279`, `kairos/search.py:155`, `kairos/search.py:310`, `kairos/search.py:314`
- Modify: `tests/test_search.py:12-16`, `tests/test_search.py:155`, `:255`, `:307`, `:314`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Rename the two helpers in `kairos/search.py`**

At line 146, rename `_score_combos` to `score_combos`:

```python
def score_combos(space: EnumeratedSpace, config) -> list:
    """Score every clash-free combo exactly once. Returns
    [(total, breakdown, assignment, combo), ...] so callers (rank,
    rank_arrangements, arrangement_provenance, state.retune) can share a single
    scoring pass (M5)."""
    return weight_scored(score_raw(space, config), config)
```

At line 279, rename `_candidates_from_structure` to `candidates_from_structure`:

```python
def candidates_from_structure(structure, scored) -> list:
```

Update the three internal call sites — line 155 (`rank`), line 310 (`rank_arrangements`), line 314 (`rank_arrangements`) — to use the new names.

- [ ] **Step 2: Update test references**

In `tests/test_search.py`, replace every `_score_combos` with `score_combos` (lines 155, 255, 307, 314). Rename `test_weight_scored_matches_score_combos` body imports accordingly.

- [ ] **Step 3: Move the `groups` fixture to conftest**

Delete lines 11-16 of `tests/test_search.py` (the `groups` fixture) and append it to `tests/conftest.py`:

```python
@pytest.fixture
def groups(alpha_json, beta_json, config):
    from kairos.api import build_groups, semester_timetable
    from kairos.search import prepare_groups

    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1)) + build_groups(
        "BETA", semester_timetable(beta_json, 1)
    )
    return prepare_groups(gs, config)
```

- [ ] **Step 4: Run the full suite to verify nothing broke**

Run: `.venv/bin/pytest -q`
Expected: PASS, same test count as before this task.

- [ ] **Step 5: Commit**

```bash
git add kairos/search.py tests/test_search.py tests/conftest.py
git commit -m "refactor: make score_combos and candidates_from_structure public"
```

---

### Task 2: The provenance module

**Files:**
- Create: `kairos/provenance.py`
- Test: `tests/test_provenance.py`

**Interfaces:**
- Consumes: `search.score_combos(space, config)`, `search.build_arrangement_structure(space)`, `search.candidates_from_structure(structure, scored)` from Task 1.
- Produces:
  - `ClusterStats(ceiling: float, median: float, support: int, ceiling_tier: int, median_tier: int)` — frozen dataclass.
  - `Provenance` with fields `total: int`, `scores: tuple`, `distinct: tuple`, `by_arrangement: tuple[frozenset]`, `by_class: dict`; property `tiers -> int`; methods `tier_of(score) -> int` and `cluster_stats(keys) -> ClusterStats | None`.
  - `arrangement_provenance(space, config, scored=None, structure=None) -> Provenance`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_provenance.py`:

```python
import pytest

from kairos.provenance import arrangement_provenance
from kairos.search import (
    build_arrangement_structure,
    enumerate_clashfree,
    rank_arrangements,
    score_combos,
)


@pytest.fixture
def prov(groups, config):
    space = enumerate_clashfree(groups)
    return arrangement_provenance(space, config), space


def test_total_matches_arrangement_count(prov, config):
    provenance, space = prov
    assert provenance.total == len(rank_arrangements(space, config))


def test_scores_are_descending(prov):
    provenance, _ = prov
    assert list(provenance.scores) == sorted(provenance.scores, reverse=True)


def test_distinct_scores_are_deduped_and_descending(prov):
    provenance, _ = prov
    assert list(provenance.distinct) == sorted(set(provenance.scores), reverse=True)
    assert provenance.tiers == len(set(provenance.scores))


def test_tier_of_observed_score_is_its_rank(prov):
    provenance, _ = prov
    for tier, score in enumerate(provenance.distinct, 1):
        assert provenance.tier_of(score) == tier


def test_tier_of_interpolated_score_takes_the_worse_tier(prov):
    # A median falling between two observed scores must never claim a better
    # tier than any arrangement actually achieved.
    provenance, _ = prov
    if len(provenance.distinct) < 2:
        pytest.skip("needs at least two distinct scores")
    high, low = provenance.distinct[0], provenance.distinct[1]
    between = (high + low) / 2
    assert provenance.tier_of(between) == 2


def test_cluster_stats_aggregates_over_all_members(prov):
    # ALPHA tutorials 02 and 03 are venue twins sharing a footprint, so the
    # union of their arrangements is the cluster's support.
    provenance, _ = prov
    keys = {("ALPHA", "Tutorial", "02"), ("ALPHA", "Tutorial", "03")}
    stats = provenance.cluster_stats(keys)
    union = set(provenance.by_class[("ALPHA", "Tutorial", "02")]) | set(
        provenance.by_class[("ALPHA", "Tutorial", "03")]
    )
    assert stats.support == len(union)
    assert stats.ceiling == max(provenance.scores[i] for i in union)


def test_cluster_stats_returns_none_for_unknown_class(prov):
    provenance, _ = prov
    assert provenance.cluster_stats({("ALPHA", "Tutorial", "99")}) is None


def test_ceiling_is_never_worse_than_median(prov):
    provenance, _ = prov
    for key in provenance.by_class:
        stats = provenance.cluster_stats({key})
        assert stats.ceiling >= stats.median
        assert stats.ceiling_tier <= stats.median_tier


def test_by_arrangement_and_by_class_agree(prov):
    provenance, _ = prov
    for index, keys in enumerate(provenance.by_arrangement):
        for key in keys:
            assert index in provenance.by_class[key]


def test_single_distinct_score_yields_one_tier(groups, config):
    # Every weight zero -> every arrangement scores the same -> exactly one tier.
    for name in list(config.preferences.weights):
        config.preferences.weights[name] = 0
    space = enumerate_clashfree(groups)
    provenance = arrangement_provenance(space, config)
    assert provenance.tiers == 1
    assert all(provenance.tier_of(score) == 1 for score in provenance.scores)


def test_provenance_is_independent_of_max_arrangements(groups, config):
    # AppState caps its arrangement list; provenance must not inherit that cap,
    # or the TUI would report "of 3" where the CLI reports the true total.
    space = enumerate_clashfree(groups)
    config.max_arrangements = 3
    capped = arrangement_provenance(space, config)
    config.max_arrangements = 500
    uncapped = arrangement_provenance(space, config)
    assert capped.total == uncapped.total
    assert capped.scores == uncapped.scores
    assert capped.by_class == uncapped.by_class


def test_indices_align_with_rank_arrangements(groups, config):
    # TUI highlighting indexes provenance.by_arrangement with a selection made
    # against rank_arrangements(limit=...). They agree only because nlargest is
    # equivalent to a stable descending sort. Pin it.
    space = enumerate_clashfree(groups)
    scored = score_combos(space, config)
    structure = build_arrangement_structure(space)
    provenance = arrangement_provenance(space, config, scored=scored, structure=structure)
    full = rank_arrangements(space, config, scored=scored, structure=structure)
    assert [a.score for a in full] == list(provenance.scores)
    for limit in (1, 2, len(full)):
        capped = rank_arrangements(
            space, config, limit=limit, scored=scored, structure=structure
        )
        assert [a.score for a in capped] == [a.score for a in full[:limit]]
        assert [a.assignment for a in capped] == [a.assignment for a in full[:limit]]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_provenance.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'kairos.provenance'`

- [ ] **Step 3: Write the implementation**

Create `kairos/provenance.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from statistics import median as _median

from .search import build_arrangement_structure, candidates_from_structure, score_combos

TOLERANCE = 1e-9


@dataclass(frozen=True)
class ClusterStats:
    """Quality of the arrangements containing one interchangeable cluster.

    `ceiling` is the best score attainable with this cluster; `median` is the
    typical outcome. Ceiling alone is a poor ranking signal because ties
    dominate, and raw `support` is anti-correlated with quality -- see the
    design doc's "What the data showed"."""

    ceiling: float
    median: float
    support: int
    ceiling_tier: int
    median_tier: int


@dataclass(frozen=True)
class Provenance:
    total: int
    scores: tuple            # per arrangement index, descending
    distinct: tuple          # distinct scores, descending; tier == index + 1
    by_arrangement: tuple    # index -> frozenset of (module, lesson_type, class_no)
    by_class: dict           # (module, lesson_type, class_no) -> tuple of indices

    @property
    def tiers(self) -> int:
        return len(self.distinct)

    def tier_of(self, score: float) -> int:
        """1-based tier of `score` among distinct arrangement scores.

        A score between two observed values (a median can be) takes the tier of
        the best distinct score <= it, so an interpolated value never claims a
        better tier than any arrangement actually achieved."""
        for index, value in enumerate(self.distinct):
            if value <= score + TOLERANCE:
                return index + 1
        return len(self.distinct)

    def cluster_stats(self, keys) -> ClusterStats | None:
        """Stats over every arrangement containing ANY of `keys`.

        Callers pass a whole interchangeable cluster, because twins are
        substitutable by construction -- a timetable using one has a valid twin
        using another. Returns None when no arrangement contains any of them
        (a class that is never part of a clash-free timetable)."""
        indices = set()
        for key in keys:
            indices.update(self.by_class.get(key, ()))
        if not indices:
            return None
        values = [self.scores[index] for index in indices]
        ceiling = max(values)
        middle = _median(values)
        return ClusterStats(
            ceiling=ceiling,
            median=middle,
            support=len(values),
            ceiling_tier=self.tier_of(ceiling),
            median_tier=self.tier_of(middle),
        )


def arrangement_provenance(space, config, scored=None, structure=None) -> Provenance:
    """Which classes each clash-free arrangement contains, and how good it is.

    Built from candidates_from_structure rather than rank_arrangements: the
    expensive part of rank_arrangements is _make_arrangement's bid construction
    and venue expansion, none of which is needed here.

    ALWAYS covers every arrangement. Do not reuse AppState.arrangements, which
    is capped at config.max_arrangements to bound the TUI's ListView -- feeding
    that in would make the TUI's denominators disagree with the CLI's."""
    if scored is None:
        scored = score_combos(space, config)
    if structure is None:
        structure = build_arrangement_structure(space)

    candidates = candidates_from_structure(structure, scored)
    # Must match rank_arrangements' ordering exactly: TUI highlighting indexes
    # by_arrangement with a selection made against rank_arrangements(limit=...).
    candidates.sort(key=lambda candidate: -candidate[0])

    scores = []
    by_arrangement = []
    by_class: dict = {}
    for index, (score, _entry, slot_opts, _variants) in enumerate(candidates):
        keys = set()
        for (module, lesson_type), by_footprint in slot_opts.items():
            members = space.members.get((module, lesson_type), {})
            for footprint in by_footprint:
                for sibling in members.get(footprint, []):
                    keys.add((module, lesson_type, sibling.class_no))
        frozen = frozenset(keys)
        scores.append(score)
        by_arrangement.append(frozen)
        for key in frozen:
            by_class.setdefault(key, []).append(index)

    distinct: list = []
    for score in scores:
        if not distinct or abs(score - distinct[-1]) > TOLERANCE:
            distinct.append(score)

    return Provenance(
        total=len(scores),
        scores=tuple(scores),
        distinct=tuple(distinct),
        by_arrangement=tuple(by_arrangement),
        by_class={key: tuple(indices) for key, indices in by_class.items()},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_provenance.py -q`
Expected: PASS (one test may report SKIPPED if the fixture space has a single distinct score)

- [ ] **Step 5: Commit**

```bash
git add kairos/provenance.py tests/test_provenance.py
git commit -m "feat: add arrangement provenance with cluster quality stats"
```

---

### Task 3: Rank ballot options on provenance

Replaces the class-number tiebreak that currently decides most of the ballot's ordering.

**Files:**
- Modify: `kairos/ballot.py:53-103` (the `all_options` cluster/emit block), `kairos/ballot.py:106-119` (`ranked_options`)
- Test: `tests/test_ballot.py`

**Interfaces:**
- Consumes: `Provenance.cluster_stats(keys) -> ClusterStats | None` from Task 2.
- Produces: `all_options(result, config, provenance=None)` and `ranked_options(result, config, provenance=None)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ballot.py`:

```python
class FakeProvenance:
    """Minimal stand-in: maps a class number to (ceiling, median, support)."""

    def __init__(self, table):
        self.table = table
        self.total = 100

    def cluster_stats(self, keys):
        from kairos.provenance import ClusterStats

        rows = [self.table[k] for k in keys if k in self.table]
        if not rows:
            return None
        ceiling = max(r[0] for r in rows)
        median = max(r[1] for r in rows)
        support = max(r[2] for r in rows)
        return ClusterStats(ceiling, median, support, 1, 1)


def test_all_options_without_provenance_is_unchanged(config):
    result = fake_result(config)
    assert all_options(result, config) == all_options(result, config, provenance=None)


def test_provenance_breaks_ceiling_ties_on_median(config):
    # Both ALPHA clusters tie on ceiling. Cluster {03} has the better median,
    # so it must outrank {01,02} despite a higher class number.
    result = fake_result(config)
    result.best_by_footprint = {k: 10.0 for k in result.best_by_footprint}
    prov = FakeProvenance({
        ("ALPHA", "Tutorial", "01"): (10.0, -30.0, 50),
        ("ALPHA", "Tutorial", "02"): (10.0, -30.0, 50),
        ("ALPHA", "Tutorial", "03"): (10.0, -10.0, 5),
        ("BETA", "Laboratory", "L1"): (9.0, -10.0, 5),
        ("BETA", "Laboratory", "L2"): (7.0, -10.0, 5),
    })
    tut = all_options(result, config, provenance=prov)[("ALPHA", "Tutorial")]
    assert [o.class_no for o in tut] == ["03", "01", "02"]


def test_high_support_does_not_beat_better_median(config):
    # The UTW1001X SEC[2] vs SEC[4] inversion from the design doc: the option
    # appearing in far MORE arrangements is worse on median and must lose.
    result = fake_result(config)
    result.best_by_footprint = {k: 10.0 for k in result.best_by_footprint}
    prov = FakeProvenance({
        ("ALPHA", "Tutorial", "01"): (10.0, -20.0, 264),
        ("ALPHA", "Tutorial", "02"): (10.0, -20.0, 264),
        ("ALPHA", "Tutorial", "03"): (10.0, -19.0, 99),
        ("BETA", "Laboratory", "L1"): (9.0, -10.0, 5),
        ("BETA", "Laboratory", "L2"): (7.0, -10.0, 5),
    })
    tut = all_options(result, config, provenance=prov)[("ALPHA", "Tutorial")]
    assert [o.class_no for o in tut] == ["03", "01", "02"]


def test_narrow_but_excellent_option_is_not_demoted(config):
    # CS1231S TUT[09] from the design doc: support 6 but median at the best
    # score. Support must not drag it below a broad-but-mediocre option.
    result = fake_result(config)
    result.best_by_footprint = {k: 10.0 for k in result.best_by_footprint}
    prov = FakeProvenance({
        ("ALPHA", "Tutorial", "01"): (10.0, -19.0, 29),
        ("ALPHA", "Tutorial", "02"): (10.0, -19.0, 29),
        ("ALPHA", "Tutorial", "03"): (10.0, -14.0, 6),
        ("BETA", "Laboratory", "L1"): (9.0, -10.0, 5),
        ("BETA", "Laboratory", "L2"): (7.0, -10.0, 5),
    })
    tut = all_options(result, config, provenance=prov)[("ALPHA", "Tutorial")]
    assert [o.class_no for o in tut] == ["03", "01", "02"]


def test_support_breaks_median_ties(config):
    result = fake_result(config)
    result.best_by_footprint = {k: 10.0 for k in result.best_by_footprint}
    prov = FakeProvenance({
        ("ALPHA", "Tutorial", "01"): (10.0, -14.0, 5),
        ("ALPHA", "Tutorial", "02"): (10.0, -14.0, 5),
        ("ALPHA", "Tutorial", "03"): (10.0, -14.0, 40),
        ("BETA", "Laboratory", "L1"): (9.0, -10.0, 5),
        ("BETA", "Laboratory", "L2"): (7.0, -10.0, 5),
    })
    tut = all_options(result, config, provenance=prov)[("ALPHA", "Tutorial")]
    assert [o.class_no for o in tut] == ["03", "01", "02"]


def test_ranked_options_forwards_provenance(config):
    result = fake_result(config)
    result.best_by_footprint = {k: 10.0 for k in result.best_by_footprint}
    prov = FakeProvenance({
        ("ALPHA", "Tutorial", "01"): (10.0, -30.0, 50),
        ("ALPHA", "Tutorial", "02"): (10.0, -30.0, 50),
        ("ALPHA", "Tutorial", "03"): (10.0, -10.0, 5),
        ("BETA", "Laboratory", "L1"): (9.0, -10.0, 5),
        ("BETA", "Laboratory", "L2"): (7.0, -10.0, 5),
    })
    tut = ranked_options(result, config, provenance=prov)[("ALPHA", "Tutorial")]
    assert tut[0].class_no == "03"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ballot.py -q -k "provenance or median or support or narrow"`
Expected: FAIL with `TypeError: all_options() got an unexpected keyword argument 'provenance'`

- [ ] **Step 3: Change the signature and the cluster sort**

In `kairos/ballot.py`, change line 26:

```python
def all_options(result, config, provenance=None) -> dict:
```

Extend its docstring with:

```
    When `provenance` is given, clusters are ranked
    (-ceiling, -median, -support, class_no) instead of (-best_score, class_no).
    best_score ties are the normal case, not the exception, so the old fallback
    to class number was an arbitrary ordering presented as a real one. Omitting
    `provenance` reproduces that old ordering exactly.
```

Replace lines 78-84 (from the `# class numbers within a cluster` comment through `scored.sort(...)`) with:

```python
        # class numbers within a cluster fold in venue-twins (I1 for the ballot);
        # sort by class_no for deterministic letters / ordering (M4)
        entries = []
        for cl in clusters:
            cl_choices = sorted(cl["choices"], key=lambda c: c.class_no)
            stats = None
            if provenance is not None:
                stats = provenance.cluster_stats(
                    {(module, lesson_type, c.class_no) for c in cl_choices}
                )
            entries.append((cl["best"], stats, cl_choices))

        if provenance is None:
            entries.sort(key=lambda e: (-e[0], e[2][0].class_no))
        else:
            entries.sort(
                key=lambda e: (
                    -(e[1].ceiling if e[1] else e[0]),
                    -(e[1].median if e[1] else e[0]),
                    -(e[1].support if e[1] else 0),
                    e[2][0].class_no,
                )
            )
```

Then replace lines 86-100 (the `options = []` emit loop) with:

```python
        options = []
        for best, stats, choices in entries:
            class_nos = [c.class_no for c in choices]
            score = stats.ceiling if stats is not None else best
            for c in choices:
                options.append(
                    BallotOption(
                        module=module,
                        lesson_type=lesson_type,
                        class_no=c.class_no,
                        letter=chr(ord("A") + len(options)),
                        best_score=score,
                        sessions=c.sessions,
                        tied_with=[n for n in class_nos if n != c.class_no],
                    )
                )
```

- [ ] **Step 4: Forward provenance through `ranked_options`**

Replace lines 106 and 116 of `kairos/ballot.py`:

```python
def ranked_options(result, config, provenance=None) -> dict:
```

```python
    full = all_options(result, config, provenance=provenance)
```

- [ ] **Step 5: Run the ballot tests**

Run: `.venv/bin/pytest tests/test_ballot.py -q`
Expected: PASS, including all pre-existing tests (they pass no provenance, so ordering is unchanged)

- [ ] **Step 6: Commit**

```bash
git add kairos/ballot.py tests/test_ballot.py
git commit -m "feat: rank ballot options on ceiling, median, then support"
```

---

### Task 4: Interleave interchangeable twins

Today a cluster's twins occupy consecutive ballot positions, so `fill_to_cap` spends every copy of one timeslot before reaching the next. Measured effect of this task: distinct timeslots covered by the 20-slot ballot rises from 12 to 17.

**Files:**
- Modify: `kairos/ballot.py` (the emit loop from Task 3)
- Test: `tests/test_ballot.py`

**Interfaces:**
- Consumes: the `entries` list built in Task 3 — `[(best, stats, cl_choices), ...]`, already sorted.
- Produces: no signature change; only the order of `BallotOption`s within a group.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ballot.py`:

```python
def test_twins_interleave_behind_distinct_timeslots(config):
    # ALPHA cluster {01} and cluster {02,03} both viable. Without interleaving
    # the order is 01, 02, 03; with it, the second copy of the {02,03} timeslot
    # moves behind every distinct timeslot.
    result = fake_result(config)
    result.best_by_footprint = {k: 10.0 for k in result.best_by_footprint}
    prov = FakeProvenance({
        ("ALPHA", "Tutorial", "01"): (10.0, -10.0, 9),
        ("ALPHA", "Tutorial", "02"): (10.0, -14.0, 5),
        ("ALPHA", "Tutorial", "03"): (10.0, -14.0, 5),
        ("BETA", "Laboratory", "L1"): (9.0, -10.0, 5),
        ("BETA", "Laboratory", "L2"): (7.0, -10.0, 5),
    })
    tut = all_options(result, config, provenance=prov)[("ALPHA", "Tutorial")]
    assert [o.class_no for o in tut] == ["01", "02", "03"]
    # 02 is round 1 of its cluster, 03 is round 2 and lands last
    assert tut[1].class_no == "02" and tut[2].class_no == "03"


def test_interleaving_puts_second_copies_after_all_firsts(config):
    # Two clusters that each hold two twins: rounds must alternate, not group.
    from kairos.model import Choice

    def ch(no, day):
        return Choice("ALPHA", "Tutorial", no, (sess(day),))

    a1, a2 = ch("01", "Monday"), ch("02", "Monday")
    b1, b2 = ch("03", "Tuesday"), ch("04", "Tuesday")
    members = {("ALPHA", "Tutorial"): {a1.footprint: [a1, a2], b1.footprint: [b1, b2]}}
    best = {
        ("ALPHA", "Tutorial", a1.footprint): 10.0,
        ("ALPHA", "Tutorial", b1.footprint): 10.0,
    }
    result = SearchResult(top=[], best_by_footprint=best, members=members, evaluated=2)
    prov = FakeProvenance({
        ("ALPHA", "Tutorial", "01"): (10.0, -10.0, 9),
        ("ALPHA", "Tutorial", "02"): (10.0, -10.0, 9),
        ("ALPHA", "Tutorial", "03"): (10.0, -14.0, 5),
        ("ALPHA", "Tutorial", "04"): (10.0, -14.0, 5),
    })
    tut = all_options(result, config, provenance=prov)[("ALPHA", "Tutorial")]
    assert [o.class_no for o in tut] == ["01", "03", "02", "04"]


def test_interleaved_letters_stay_positional(config):
    result = fake_result(config)
    result.best_by_footprint = {k: 10.0 for k in result.best_by_footprint}
    prov = FakeProvenance({
        ("ALPHA", "Tutorial", "01"): (10.0, -10.0, 9),
        ("ALPHA", "Tutorial", "02"): (10.0, -14.0, 5),
        ("ALPHA", "Tutorial", "03"): (10.0, -14.0, 5),
        ("BETA", "Laboratory", "L1"): (9.0, -10.0, 5),
        ("BETA", "Laboratory", "L2"): (7.0, -10.0, 5),
    })
    tut = all_options(result, config, provenance=prov)[("ALPHA", "Tutorial")]
    assert [o.letter for o in tut] == ["A", "B", "C"]


def test_interleaving_preserves_tied_with(config):
    result = fake_result(config)
    result.best_by_footprint = {k: 10.0 for k in result.best_by_footprint}
    prov = FakeProvenance({
        ("ALPHA", "Tutorial", "01"): (10.0, -10.0, 9),
        ("ALPHA", "Tutorial", "02"): (10.0, -14.0, 5),
        ("ALPHA", "Tutorial", "03"): (10.0, -14.0, 5),
        ("BETA", "Laboratory", "L1"): (9.0, -10.0, 5),
        ("BETA", "Laboratory", "L2"): (7.0, -10.0, 5),
    })
    tut = all_options(result, config, provenance=prov)[("ALPHA", "Tutorial")]
    by_no = {o.class_no: o for o in tut}
    assert by_no["02"].tied_with == ["03"]
    assert by_no["03"].tied_with == ["02"]


def test_ranked_options_is_still_a_prefix_with_provenance(config):
    result = fake_result(config)
    result.best_by_footprint = {k: 10.0 for k in result.best_by_footprint}
    prov = FakeProvenance({
        ("ALPHA", "Tutorial", "01"): (10.0, -10.0, 9),
        ("ALPHA", "Tutorial", "02"): (10.0, -14.0, 5),
        ("ALPHA", "Tutorial", "03"): (10.0, -14.0, 5),
        ("BETA", "Laboratory", "L1"): (9.0, -10.0, 5),
        ("BETA", "Laboratory", "L2"): (7.0, -10.0, 5),
    })
    config.alternatives_per_module = 2
    full = all_options(result, config, provenance=prov)
    capped = ranked_options(result, config, provenance=prov)
    for key, options in capped.items():
        assert options == full[key][: len(options)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ballot.py -q -k "interleav"`
Expected: FAIL — `assert ['01','02','03'] == ['01','03','02','04']` style mismatches, because twins still emit consecutively

- [ ] **Step 3: Replace the emit loop with a round-robin**

In `kairos/ballot.py`, replace the emit loop written in Task 3 with:

```python
        options = []
        if provenance is None:
            rounds = [[(best, stats, choices, c) for c in choices]
                      for best, stats, choices in entries]
            plan = [item for group in rounds for item in group]
        else:
            # Round-robin across clusters: every cluster's first class, then
            # every cluster's second, and so on. A second copy of a timeslot
            # only helps if the first was full, so it must never outrank fresh
            # timeslot coverage under the 20-slot cap.
            depth = max((len(choices) for _b, _s, choices in entries), default=0)
            plan = [
                (best, stats, choices, choices[round_no])
                for round_no in range(depth)
                for best, stats, choices in entries
                if round_no < len(choices)
            ]

        for best, stats, choices, c in plan:
            class_nos = [x.class_no for x in choices]
            score = stats.ceiling if stats is not None else best
            options.append(
                BallotOption(
                    module=module,
                    lesson_type=lesson_type,
                    class_no=c.class_no,
                    letter=chr(ord("A") + len(options)),
                    best_score=score,
                    sessions=c.sessions,
                    tied_with=[n for n in class_nos if n != c.class_no],
                )
            )
```

- [ ] **Step 4: Run the full ballot suite**

Run: `.venv/bin/pytest tests/test_ballot.py -q`
Expected: PASS — the pre-existing tests pass no provenance and take the unchanged branch

- [ ] **Step 5: Commit**

```bash
git add kairos/ballot.py tests/test_ballot.py
git commit -m "feat: interleave interchangeable twins behind distinct timeslots"
```

---

### Task 5: Render provenance columns

**Files:**
- Modify: `kairos/output.py:198-210`
- Test: `tests/test_output.py`

**Interfaces:**
- Consumes: `Provenance.cluster_stats(keys)`, `Provenance.total` from Task 2. The cluster's key set is reconstructed from `option.class_no` plus `option.tied_with`.
- Produces: `render_snake(entries, provenance=None) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_output.py`:

```python
def test_render_snake_without_provenance_is_unchanged():
    from kairos.ballot import BallotOption
    from kairos.model import Session

    weeks = frozenset(range(1, 14))
    entry = BallotOption(
        "ALPHA", "Tutorial", "01", "A", 3.0,
        (Session("Monday", 600, 660, weeks, "COM1"),), [],
    )
    assert render_snake([entry]) == render_snake([entry], provenance=None)


def test_render_snake_shows_best_and_typical():
    from kairos.ballot import BallotOption
    from kairos.model import Session
    from kairos.provenance import ClusterStats

    class Prov:
        total = 363

        def cluster_stats(self, keys):
            return ClusterStats(-14.0, -19.0, 29, 1, 3)

    weeks = frozenset(range(1, 14))
    entry = BallotOption(
        "ALPHA", "Tutorial", "01", "A", 3.0,
        (Session("Monday", 600, 660, weeks, "COM1"),), [],
    )
    text = render_snake([entry], provenance=Prov())
    assert "best #1 (-14.0)" in text
    assert "typical #3 (-19.0)" in text
    assert "363" in text


def test_render_snake_moves_interchangeable_to_continuation_line():
    from kairos.ballot import BallotOption
    from kairos.model import Session
    from kairos.provenance import ClusterStats

    class Prov:
        total = 363

        def cluster_stats(self, keys):
            return ClusterStats(-14.0, -14.0, 29, 1, 1)

    weeks = frozenset(range(1, 14))
    entry = BallotOption(
        "ALPHA", "Tutorial", "01", "A", 3.0,
        (Session("Monday", 600, 660, weeks, "COM1"),), ["02", "03"],
    )
    lines = render_snake([entry], provenance=Prov()).splitlines()
    body = [line for line in lines if "ALPHA" in line or "interchangeable" in line]
    assert "interchangeable" not in body[0]
    assert "interchangeable with 02, 03" in body[1]


def test_render_snake_handles_missing_stats():
    from kairos.ballot import BallotOption
    from kairos.model import Session

    class Prov:
        total = 363

        def cluster_stats(self, keys):
            return None

    weeks = frozenset(range(1, 14))
    entry = BallotOption(
        "ALPHA", "Tutorial", "01", "A", 3.0,
        (Session("Monday", 600, 660, weeks, "COM1"),), [],
    )
    text = render_snake([entry], provenance=Prov())
    assert "ALPHA" in text


def test_render_snake_columns_align_across_mixed_widths():
    from kairos.ballot import BallotOption
    from kairos.model import Session
    from kairos.provenance import ClusterStats

    class Prov:
        total = 363

        def cluster_stats(self, keys):
            return ClusterStats(-14.0, -19.0, 29, 1, 3)

    weeks = frozenset(range(1, 14))
    short = BallotOption(
        "A1", "Tutorial", "1", "A", 3.0,
        (Session("Monday", 600, 660, weeks, "COM1"),), [],
    )
    wide = BallotOption(
        "LONGMODULE", "Laboratory", "L12", "B", 3.0,
        (
            Session("Tuesday", 840, 960, weeks, "COM1"),
            Session("Friday", 840, 960, weeks, "COM1"),
        ),
        [],
    )
    lines = [
        line
        for line in render_snake([short, wide], provenance=Prov()).splitlines()
        if "best #" in line
    ]
    assert len(lines) == 2
    assert lines[0].index("best #") == lines[1].index("best #")
    assert lines[0].index("typical #") == lines[1].index("typical #")


def test_render_snake_empty_entries():
    class Prov:
        total = 0

        def cluster_stats(self, keys):
            return None

    assert render_snake([], provenance=Prov()) == ""
    assert render_snake([]) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_output.py -q -k snake`
Expected: FAIL with `TypeError: render_snake() got an unexpected keyword argument 'provenance'`

- [ ] **Step 3: Write the implementation**

Replace `render_snake` in `kairos/output.py` (lines 198-210) with:

```python
def render_snake(entries: list, provenance=None) -> str:
    """The ballot, in submission order.

    With `provenance`, each row carries the ceiling and median score of the
    arrangements containing it, as `#tier (score)`. The raw score is shown
    alongside the tier because it is directly comparable to the `score:` line on
    each displayed timetable -- that comparability is the point of the
    annotation. Both columns render unconditionally so the layout is stable
    across runs; `best` is frequently constant, which is accepted."""
    if not entries:
        return ""
    if provenance is None:
        lines = []
        for position, option in enumerate(entries, 1):
            tie = (
                f"  (interchangeable with {', '.join(option.tied_with)})"
                if option.tied_with
                else ""
            )
            lines.append(
                f"{position:2}. {option.module} "
                f"{LESSON_ABBREV.get(option.lesson_type, option.lesson_type)}"
                f"[{option.class_no}]  choice {option.letter}  "
                f"{_when(option.sessions)}{tie}"
            )
        return "\n".join(lines)

    rows = []
    for position, option in enumerate(entries, 1):
        abbrev = LESSON_ABBREV.get(option.lesson_type, option.lesson_type)
        stats = provenance.cluster_stats(
            {
                (option.module, option.lesson_type, class_no)
                for class_no in [option.class_no, *option.tied_with]
            }
        )
        best = "" if stats is None else f"best #{stats.ceiling_tier} ({stats.ceiling:+.1f})"
        typical = (
            "" if stats is None else f"typical #{stats.median_tier} ({stats.median:+.1f})"
        )
        rows.append(
            (
                f"{position:2}. {option.module} {abbrev}[{option.class_no}]",
                f"choice {option.letter}",
                _when(option.sessions),
                best,
                typical,
                option.tied_with,
            )
        )

    widths = [max(len(row[i]) for row in rows) for i in range(5)]
    lines = [
        "best    = ceiling: the best timetable containing this class",
        f"typical = median of the {provenance.total} clash-free timetables containing it",
        "",
    ]
    for row in rows:
        lines.append(
            f"{row[0]:<{widths[0]}}  {row[1]:<{widths[1]}}  {row[2]:<{widths[2]}}  "
            f"{row[3]:<{widths[3]}}  {row[4]}".rstrip()
        )
        if row[5]:
            lines.append(
                f"{'':<{widths[0]}}    ↳ interchangeable with {', '.join(row[5])}"
            )
    return "\n".join(lines)
```

- [ ] **Step 4: Run the output tests**

Run: `.venv/bin/pytest tests/test_output.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kairos/output.py tests/test_output.py
git commit -m "feat: annotate ballot rows with ceiling and median tiers"
```

---

### Task 6: Unify the CLI's ranking unit

`cli.py` displays combo-ranked timetables while the TUI displays arrangements, so `best #3` would mean something different from the CLI's own "timetable #3".

**Files:**
- Modify: `kairos/cli.py:118-160`
- Test: `tests/test_cli_run.py`

**Interfaces:**
- Consumes: `search.score_combos`, `search.build_arrangement_structure`, `search.rank_arrangements` (Task 1); `arrangement_provenance` (Task 2); `all_options(..., provenance=)` and `ranked_options(..., provenance=)` (Task 3); `render_snake(..., provenance=)` (Task 5).
- Produces: no new API.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_run.py`:

Both tests use the `config_file` fixture and `run_cli` helper already defined at
the top of `tests/test_cli_run.py` (lines 7-33). Append:

```python
def test_run_reports_both_counts_and_annotates_ballot(
    tmp_path, config_file, monkeypatch, capsys, alpha_json, beta_json
):
    # The header must state the arrangement total, because the ballot's
    # annotation denominators count arrangements while `evaluated` counts combos.
    import re

    out = run_cli(
        tmp_path, config_file, monkeypatch, capsys,
        {"ALPHA": alpha_json, "BETA": beta_json},
    )
    assert re.search(
        r"evaluated \d+ clash-free timetable shapes \(\d+ distinct arrangements\)", out
    )
    assert "best #" in out
    assert "typical #" in out


def test_cli_timetables_are_arrangement_ranked(
    tmp_path, config_file, monkeypatch, capsys, alpha_json, beta_json
):
    # Cross-surface agreement: the CLI's "timetable #1" must be the first
    # ARRANGEMENT, so a ballot row's "best #t" is comparable against it.
    from kairos.api import build_groups, semester_timetable
    from kairos.config import load_config
    from kairos.search import enumerate_clashfree, prepare_groups, rank_arrangements

    out = run_cli(
        tmp_path, config_file, monkeypatch, capsys,
        {"ALPHA": alpha_json, "BETA": beta_json},
    )
    cfg = load_config(config_file)
    groups = prepare_groups(
        build_groups("ALPHA", semester_timetable(alpha_json, 1))
        + build_groups("BETA", semester_timetable(beta_json, 1)),
        cfg,
    )
    arrangements = rank_arrangements(enumerate_clashfree(groups), cfg, limit=cfg.top_n)
    assert f"score: {arrangements[0].score:+.2f}" in out
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_cli_run.py -q -k both_counts`
Expected: FAIL — the header has no `(N distinct arrangements)` and the ballot has no `best #`

- [ ] **Step 3: Restructure `cmd_run`**

In `kairos/cli.py`, add the import near the existing ones:

```python
from .provenance import arrangement_provenance
```

Replace lines 128-153 with:

```python
    space = search.enumerate_clashfree(groups)
    scored = search.score_combos(space, config)
    result = search.rank(space, config, scored=scored)
    if not result.top:
        pair = search.find_irreconcilable(groups)
        if pair:
            first, second = pair
            raise SystemExit(
                "error: no clash-free timetable — every "
                f"{first.module} {first.lesson_type} clashes with every "
                f"{second.module} {second.lesson_type}"
            )
        raise SystemExit("error: no clash-free timetable found")

    structure = search.build_arrangement_structure(space)
    prov = arrangement_provenance(space, config, scored=scored, structure=structure)
    arrangements = search.rank_arrangements(
        space, config, limit=config.top_n, scored=scored, structure=structure
    )

    # Both counts: `evaluated` counts combos, provenance denominators count
    # arrangements. They coincide until collapsing occurs; showing both is what
    # makes the ballot's "of N" self-explaining.
    print(
        f"evaluated {result.evaluated} clash-free timetable shapes "
        f"({prov.total} distinct arrangements)\n"
    )
    for position, arrangement in enumerate(arrangements, 1):
        print(f"=== timetable #{position} ===")
        print(output.render_breakdown(arrangement.score, arrangement.breakdown))
        print(output.render_week(arrangement.assignment))
        print(output.share_url(arrangement.assignment, config.semester))
        print()

    full = ballot.all_options(result, config, provenance=prov)
    print("=== backup choices per balloted group ===")
    print(output.render_options(ballot.ranked_options(result, config, provenance=prov)))
    entries = ballot.snake(ballot.fill_to_cap(full, config), config)
    print(f"\n=== ballot ranking (snake order, cap {ballot.BALLOT_CAP}) ===")
    print(output.render_snake(entries, provenance=prov))
```

- [ ] **Step 4: Run the CLI tests**

Run: `.venv/bin/pytest tests/test_cli_run.py -q`
Expected: PASS

- [ ] **Step 5: Note the `top_n` semantic change in the README**

`top_n` now counts *arrangements* rather than combos. Because arrangements collapse same-slot week-twins, `top_n: 5` yields 5 distinct layouts instead of up to 5 near-identical timetables. Find the `top_n` description in `README.md` and update it to say "how many distinct timetable arrangements to display".

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add kairos/cli.py tests/test_cli_run.py README.md
git commit -m "feat: display arrangements in the CLI so timetable numbering matches provenance"
```

---

### Task 7: Cache provenance in the TUI state

**Files:**
- Modify: `kairos/tui/state.py:9-16` (imports), `:69-72` (fields), `:113-124` (`_rank_from`), `:166-177` (snapshot/restore), `:294-299` (ballot accessors)
- Test: `tests/test_tui_state.py`

**Interfaces:**
- Consumes: `arrangement_provenance` (Task 2).
- Produces: `AppState.provenance -> Provenance`; `AppState.ballot_options()` and `AppState.ballot_snake()` now pass it through.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tui_state.py`:

These use the `state` fixture already defined at the top of
`tests/test_tui_state.py` (lines 9-15). Append:

```python
def test_state_exposes_provenance_over_all_arrangements(state):
    from kairos.search import rank_arrangements

    assert state.provenance is not None
    assert state.provenance.total == len(rank_arrangements(state.space, state.config))


def test_provenance_ignores_max_arrangements_cap(alpha_json, beta_json, config):
    # arrangements is capped for the ListView; provenance must not be, or the
    # TUI's "of N" would disagree with the CLI's.
    cfg = copy.deepcopy(config)
    cfg.max_arrangements = 1
    groups = build_groups("ALPHA", semester_timetable(alpha_json, 1)) + build_groups(
        "BETA", semester_timetable(beta_json, 1)
    )
    st = AppState.from_parts(cfg, groups)
    assert len(st.arrangements) == 1
    assert st.provenance.total > 1


def test_reweight_refreshes_provenance(state):
    before = state.provenance
    state.config.preferences.weights["lunch"] = 9
    state.reweight()
    assert state.provenance is not before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_tui_state.py -q -k provenance`
Expected: FAIL with `AttributeError: 'AppState' object has no attribute 'provenance'`

- [ ] **Step 3: Add the field and populate it**

In `kairos/tui/state.py`, add to the imports from `..search`:

```python
    score_combos,
```

and add a new import:

```python
from ..provenance import arrangement_provenance
```

Add the field alongside `arrangements` (near line 69):

```python
    provenance: object = None          # arrangement_provenance(space); UNCAPPED
```

In `_rank_from` (line 113), after the `self.result = rank(...)` line and before `self.arrangements = ...`, insert:

```python
        # Uncapped on purpose: arrangements below is capped at
        # config.max_arrangements to bound the ListView, but provenance
        # denominators must match the CLI's totals.
        self.provenance = arrangement_provenance(
            self.space, self.config, scored=scored, structure=self._arr_structure
        )
```

- [ ] **Step 4: Include provenance in the lock snapshot**

In `_apply_locked_change` (lines 166-177), add `self.provenance` to the saved tuple and to the restore unpacking, keeping the same position in both:

```python
            snapshot = (
                self.groups, self.space, self.result, self.arrangements,
                self.provenance,
                self._raw_cache, self._arr_structure, self._unpairable,
            )
```

```python
            (self.groups, self.space,
             self.result, self.arrangements,
             self.provenance,
             self._raw_cache, self._arr_structure, self._unpairable) = snapshot
```

- [ ] **Step 5: Pass provenance to the ballot accessors**

Replace the bodies at lines 294-299:

```python
    def ballot_options(self) -> dict:
        return ballot.ranked_options(self.result, self.config, provenance=self.provenance)

    def ballot_snake(self) -> list:
        full = ballot.all_options(self.result, self.config, provenance=self.provenance)
        return ballot.snake(ballot.fill_to_cap(full, self.config), self.config)
```

- [ ] **Step 6: Resolve the dead `ballot_options` accessor**

`AppState.ballot_options()` has no caller in `kairos/tui/app.py` — only tests
reference it. Confirm:

```bash
grep -rn "ballot_options" kairos tests
```

If the only hits are its definition in `kairos/tui/state.py` and test code,
delete the method and any test that exercises it *solely* to cover the method
(tests that call `kairos.ballot.ranked_options` directly must stay). The TUI's
ballot view uses `ballot_snake()`; a second accessor that nothing renders is a
maintenance liability now that both take a provenance argument.

- [ ] **Step 7: Run the TUI state tests**

Run: `.venv/bin/pytest tests/test_tui_state.py -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add kairos/tui/state.py tests/test_tui_state.py
git commit -m "feat: cache uncapped provenance in AppState"
```

---

### Task 8: Highlight the selected timetable's classes in the ballot

**Files:**
- Modify: `kairos/output.py` (add `render_snake_rich`), `kairos/tui/app.py:17` (import), `kairos/tui/app.py:260-263` (ballot branch), `kairos/tui/app.py:353-357` (export)
- Test: `tests/test_output.py`, `tests/test_tui_render.py`

**Interfaces:**
- Consumes: `Provenance.by_arrangement` (Task 2), `AppState.provenance` (Task 7).
- Produces: `render_snake_rich(entries, provenance, highlight=frozenset()) -> rich.text.Text`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_output.py`:

```python
def test_render_snake_rich_reverses_highlighted_rows():
    # Reverse video, NOT blink: Terminal.app ignores SGR 5.
    from kairos.ballot import BallotOption
    from kairos.model import Session
    from kairos.output import render_snake_rich
    from kairos.provenance import ClusterStats

    class Prov:
        total = 10

        def cluster_stats(self, keys):
            return ClusterStats(-14.0, -14.0, 5, 1, 1)

    weeks = frozenset(range(1, 14))
    hit = BallotOption(
        "ALPHA", "Tutorial", "01", "A", 3.0,
        (Session("Monday", 600, 660, weeks, "COM1"),), [],
    )
    miss = BallotOption(
        "BETA", "Laboratory", "L1", "A", 3.0,
        (Session("Tuesday", 600, 660, weeks, "COM1"),), [],
    )
    text = render_snake_rich(
        [hit, miss], Prov(), highlight=frozenset({("ALPHA", "Tutorial", "01")})
    )
    styles = {str(span.style) for span in text.spans}
    assert "reverse" in styles
    assert "blink" not in styles


def test_render_snake_rich_without_highlight_has_no_reverse_spans():
    from kairos.ballot import BallotOption
    from kairos.model import Session
    from kairos.output import render_snake_rich
    from kairos.provenance import ClusterStats

    class Prov:
        total = 10

        def cluster_stats(self, keys):
            return ClusterStats(-14.0, -14.0, 5, 1, 1)

    weeks = frozenset(range(1, 14))
    entry = BallotOption(
        "ALPHA", "Tutorial", "01", "A", 3.0,
        (Session("Monday", 600, 660, weeks, "COM1"),), [],
    )
    text = render_snake_rich([entry], Prov(), highlight=frozenset())
    assert all("reverse" not in str(span.style) for span in text.spans)


def test_render_snake_rich_matches_plain_text():
    from kairos.ballot import BallotOption
    from kairos.model import Session
    from kairos.output import render_snake, render_snake_rich
    from kairos.provenance import ClusterStats

    class Prov:
        total = 10

        def cluster_stats(self, keys):
            return ClusterStats(-14.0, -14.0, 5, 1, 1)

    weeks = frozenset(range(1, 14))
    entry = BallotOption(
        "ALPHA", "Tutorial", "01", "A", 3.0,
        (Session("Monday", 600, 660, weeks, "COM1"),), [],
    )
    prov = Prov()
    assert render_snake_rich([entry], prov).plain == render_snake([entry], provenance=prov)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_output.py -q -k snake_rich`
Expected: FAIL with `ImportError: cannot import name 'render_snake_rich'`

- [ ] **Step 3: Implement `render_snake_rich`**

Add to `kairos/output.py`, after `render_snake`:

```python
def render_snake_rich(entries: list, provenance, highlight=frozenset()):
    """render_snake as a Rich Text, with rows belonging to the selected
    arrangement in reverse video.

    Reverse, not blink: Terminal.app ignores SGR 5, so a blinking affordance is
    invisible for some users."""
    from rich.text import Text

    plain = render_snake(entries, provenance=provenance)
    text = Text(plain)
    if not highlight or not entries:
        return text

    lines = plain.splitlines()
    offset = 0
    row = 0
    for line in lines:
        length = len(line)
        is_continuation = "↳ interchangeable with" in line
        if not is_continuation and line.strip() and line[:3].strip().rstrip(".").isdigit():
            option = entries[row]
            keys = {
                (option.module, option.lesson_type, class_no)
                for class_no in [option.class_no, *option.tied_with]
            }
            if keys & highlight:
                text.stylize("reverse", offset, offset + length)
            row += 1
        offset += length + 1
    return text
```

- [ ] **Step 4: Run the output tests**

Run: `.venv/bin/pytest tests/test_output.py -q`
Expected: PASS

- [ ] **Step 5: Wire it into the TUI**

In `kairos/tui/app.py`, extend the import on line 17:

```python
from ..output import (
    class_warnings, render_breakdown, render_snake, render_snake_rich, share_url,
)
```

Replace the ballot branch (lines 260-263) with:

```python
        if self.ballot_mode:
            highlight = frozenset()
            if self.state.provenance is not None and self.selected < len(
                self.state.provenance.by_arrangement
            ):
                highlight = self.state.provenance.by_arrangement[self.selected]
            detail.update(
                render_snake_rich(
                    self.state.ballot_snake(), self.state.provenance, highlight=highlight
                )
            )
            warnings_text.update("")
            return
```

- [ ] **Step 6: Annotate the exported ballot too**

In `action_export_ballot` (line 356), replace the write with:

```python
        out.write_text(render_snake(entries, provenance=self.state.provenance))
```

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS

- [ ] **Step 8: Verify against the real config**

Run: `.venv/bin/python -m kairos run`
Expected: the header reads `evaluated N clash-free timetable shapes (N distinct arrangements)`, and every ballot row carries `best #… (…)` and `typical #… (…)`. Confirm the ballot covers more distinct timeslots than before the change.

- [ ] **Step 9: Commit**

```bash
git add kairos/output.py kairos/tui/app.py tests/test_output.py
git commit -m "feat: highlight the selected timetable's classes in the ballot view"
```

---

## Deferred, with rationale

**`fill_to_cap`'s global tiebreak still falls through to module name.** Its candidate key is `(-option.best_score, module, lesson_type, class_no)` (`ballot.py:159`) — the same class of arbitrary tiebreak this plan fixes inside a group. It is left alone deliberately: the measured 12→17 timeslot-coverage improvement was obtained with `fill_to_cap` unchanged, and altering the global allocator would invalidate that measurement. Carrying `median` into the key is a coherent follow-up that needs its own before/after measurement.

**Letters break past 26 options per group.** `chr(ord("A") + len(options))` produces `[`, `\`, `]` beyond `Z`. Pre-existing, unchanged by this plan, and unreachable at the current cap of 20 ballot slots.

**Whether twins should be ranked at all.** This plan reorders them behind distinct timeslots but still ranks every twin. Whether a third copy of a timeslot beats a fourth distinct timeslot depends on per-class demand data, which is not available for Tutorial Reg.
