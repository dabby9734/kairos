# Ballot provenance: linking the ballot back to the timetables

Date: 2026-07-22
Status: approved, ready for planning

## Problem

The TUI shows ranked timetables. It then shows a 20-entry ballot. Nothing on
screen connects the two, and the number that produced the ballot ordering is
never displayed.

`render_snake` (`output.py:198`) prints position, module, class number, choice
letter and times. No score. `render_options` (`output.py:181`) does print
`best score`, but the TUI ballot view only ever calls `render_snake`
(`app.py:261`, `app.py:356`), and `AppState.ranked_options` (`state.py:295`)
has no caller in `app.py` at all — only tests. The exported `ballot.txt`
likewise carries no scores.

The failure mode this targets: **the user does not trust the ordering and
hand-reorders it**, which is worse than submitting it as generated, because the
snake ordering and greedy fill are deliberate.

Investigation found the distrust is partly justified. See "What the data
showed" below — for tied entries the ranking really was arbitrary, and one
ranking signal was anti-correlated with quality.

## What the data showed

Measured against the repo's `config.yaml` (CS1231S / CS2030S / MA1521 / MA1522 /
UTW1001X), 363 clash-free arrangements, `top_n: 5`,
`alternatives_per_module: 4`, with `gaps` and `same_day_pairing` weighted 0.

All cluster-level figures below were re-verified against this config after it
was retuned mid-analysis, and reproduce exactly. Any figure quoted here should
be treated as weight-dependent: the *conclusions* (ties dominate, support is
anti-correlated with quality, median discriminates) held across both weight
sets tested, but the specific numbers will move when weights change. Tests must
therefore assert on ordering relationships, never on literal scores.

**Provenance against displayed timetables is mostly empty.** Only 13 of 20
ballot entries appear in one of the 5 displayed timetables. Annotating "which
of your top timetables is this in?" would leave 7 entries blank, reading as
"the tool put junk in my ballot".

**Ordinal arrangement rank is near-meaningless.** 363 arrangements share only
15 distinct scores, and 70 of them tie at the best score of −14.0. A class in a
joint-best timetable could render as `best: #58` purely from tiebreak order.
Hence tiers over distinct scores, not ordinal position.

(Measured after the weight retune noted above. An earlier reading under
different weights gave 30 distinct scores with 9 tied at the best; the tie
problem is worse under the current weights, not better, so this conclusion is
robust to retuning rather than an artefact of one weight set.)

**`best_score` ties are the normal case, and the fallback was class number.**
`ballot.py:84` sorts `(-best_score, class_no)`. Seven CS1231S tutorial clusters
tie at ceiling −14.0, so their A/B/C/D/E/F/G letters were pure class-number
ordering presented as a ranking.

**Raw support count is anti-correlated with quality.** Support = how many
arrangements contain a class.

| cluster | support | joint-best | median |
|---|---|---|---|
| `UTW1001X SEC[2]` | 264 | 33 | −20.0 |
| `UTW1001X SEC[4]` | 99 | 37 | −19.0 |
| `CS1231S TUT[07]` | 29 | 25 | −14.0 |
| `CS1231S TUT[22A]` | 29 | 4 | −19.0 |
| `CS2030S REC[02]` | 48 | 0 | −33.0 |

`SEC[2]` has the highest support in the ballot yet is worse than `SEC[4]` on
both quality measures. `TUT[07]` and `TUT[22A]` have identical support and 6×
different quality. `REC[02]` appears in 48 arrangements, all bad.

An earlier iteration of this design proposed breaking ties on support. That was
wrong and would have caused a regression: it demoted `CS1231S TUT[09]`
(support 6) as a "knife-edge lottery ticket" when 5 of its 6 arrangements are
joint-best with median −14.0 — a narrow but excellent option.

**Median score of containing arrangements is the signal that discriminates.**
Across the seven clusters tied at ceiling −14.0, median splits them cleanly
into `{07, 08, 09, 10}` at −14.0 and `{22, 24, 25}` at −19.0.

**Twins consume the slot budget.** `all_options` emits one entry per class
number, so interchangeable twins land in consecutive positions and
`fill_to_cap` takes all copies of one timeslot before reaching the next. 13 of
20 slots went to CS1231S tutorials covering only 4 distinct timeslots.

## Design

### 1. `kairos/provenance.py` (new module)

```python
def arrangement_provenance(space, config, scored=None, structure=None) -> Provenance
```

```python
@dataclass(frozen=True)
class Provenance:
    total: int      # arrangements considered
    tiers: int      # distinct scores
    stats: dict     # (module, lesson_type, class_no) -> ClusterStats
    members: dict   # arrangement index -> frozenset((module, lesson_type, class_no))

@dataclass(frozen=True)
class ClusterStats:
    ceiling: float      # max score over arrangements containing the cluster
    median: float       # median score over those arrangements
    support: int        # how many arrangements contain the cluster
    ceiling_tier: int   # 1-based tier of `ceiling` among distinct scores
    median_tier: int    # 1-based tier of `median`
```

Tiers are competition ranks over **distinct** arrangement scores, descending:
every arrangement at the best score is tier 1, the next distinct score is tier
2. `median` may fall between two observed scores, in which case its tier is the
tier of the best distinct score `<= median`.

Statistics are computed at **cluster** level — the set of arrangements
containing *any* member of an interchangeable cluster — because twins are
substitutable by construction. Every member of a cluster shares one
`ClusterStats`.

Computation reuses `_candidates_from_structure(structure, scored)`
(`search.py:279`) rather than `rank_arrangements`, skipping `_make_arrangement`'s
bid construction and venue expansion. Class numbers are recovered by expanding
each candidate's `slot_opts` footprints through `space.members`. Single pass,
O(arrangements × slots).

**Provenance must be computed over the full candidate set, never over
`AppState.arrangements`.** That list is capped at `config.max_arrangements`
(default 50, `state.py:121`) to bound the TUI's ListView. Deriving provenance
from it would make the TUI report "of 50" while the CLI reports "of 363" —
reintroducing the very cross-surface inconsistency this design removes.
`_candidates_from_structure` is uncapped and cheap, because the cost of
`rank_arrangements` is bid construction, which it skips.

**Index alignment is a load-bearing invariant.** `Provenance.members` is keyed
by position in the full score-sorted candidate list. The TUI highlights a
selection indexed into the capped list from `rank_arrangements(limit=...)`,
which selects via `heapq.nlargest`. These agree only because `nlargest` is
equivalent to a stable descending sort — asserted in the comment at
`search.py:317` but currently untested. If it drifts, highlighting marks the
wrong ballot rows silently. Section 5 pins it.

Placement: `search.py` owns ranking and `ballot.py` owns ballot construction;
this is the join between them and belongs cleanly in neither. Both files are
already large.

### 2. `ballot.py` — ordering

`all_options` gains an optional `provenance` parameter. When omitted it
reproduces today's `(-best_score, class_no)` ordering exactly, so existing
callers and tests are unaffected and the change is opt-in at the call site.

When supplied, two changes:

**Cluster sort** becomes `(-ceiling, -median, -support, class_no)`. Ceiling
first (best case attainable), median second (typical outcome), support only as
a tiebreak among genuine equals, class number last for determinism.

**Twins interleave.** Instead of emitting a cluster's members consecutively,
emit round-robin across clusters: the first member of every cluster in sorted
order, then the second member of every cluster, and so on. A second copy of a
timeslot only helps if the first was full, so it should never outrank fresh
timeslot coverage. Letters remain assigned positionally over the emitted list,
preserving the invariant that any prefix carries correct letters — which is what
lets `ranked_options` and `fill_to_cap` slice without recomputing.

Measured effect: distinct timeslots covered by the 20-slot ballot rises from 12
to 17. CS1231S TUT goes from 4 timeslots across 10 slots to 7 timeslots across 7.

No magic constants. The rule is stateable in one sentence, which matters
because transparency is the goal.

### 3. `output.py` — rendering

`render_snake(entries, provenance=None)`, output unchanged when `provenance` is
`None`.

```
=== ballot ranking (snake order, cap 20) ===
best    = ceiling: the best timetable containing this class
typical = median of the 363 clash-free timetables containing it

 1. CS2030S REC[05]   choice A  Wed 1400-1500  best #1 (-14.0)  typical #3 (-19.0)
 2. CS2030S LAB[10A]  choice A  Thu 1000-1200  best #1 (-14.0)  typical #3 (-19.0)
                        ↳ interchangeable with 10B
 3. CS1231S TUT[07A]  choice A  Tue 1000-1200  best #1 (-14.0)  typical #1 (-14.0)
                        ↳ interchangeable with 07B, 07C
```

Both columns are shown unconditionally, giving a stable column layout that
diffs cleanly across runs. `best` is frequently constant across the whole ballot
(the ballot contains only each group's top options, so ceilings coincide); this
is accepted in exchange for layout predictability.

Scores are rendered alongside tiers because the raw score is directly
comparable to the `score:` line on each displayed timetable — that comparability
is the ballot↔timetable link this work exists to create.

`interchangeable with` moves to an indented continuation line; adding two
columns to lines already reaching ~86 characters would overflow the TUI panel.
Column widths are computed from the actual entries rather than fixed constants.

### 4. TUI live highlighting

Selecting an arrangement highlights the ballot entries contained in it, using
`Provenance.members`. Highlighting uses **reverse video, not blink** —
Terminal.app ignores SGR 5.

`AppState` caches the `Provenance` alongside its existing `scored` and
`structure` caches; it is weight-independent in structure but score-dependent in
values, so it invalidates on retune exactly as `scored` does.

This also resolves the dead `AppState.ranked_options` (`state.py:295`): either
wire it up or delete it.

### 5. Unify the ranking unit across CLI and TUI

The CLI displays combo-ranked timetables (`cli.py:141` iterates `result.top`)
while the TUI displays arrangements. Provenance tiers are defined over
arrangements, so without this the CLI would print `best #3` next to its own
third timetable and mean two different things.

`cmd_run` is restructured to mirror `AppState._rank_from` (`state.py:113`),
which already derives both from one scoring pass:

```python
space = search.enumerate_clashfree(groups)
scored = search.score_combos(space, config)
result = search.rank(space, config, scored=scored)          # ballot still needs
                                                            # best_by_footprint + members
structure = search.build_arrangement_structure(space)
prov = provenance.arrangement_provenance(space, config, scored=scored,
                                         structure=structure)
arrangements = search.rank_arrangements(space, config, limit=config.top_n,
                                        scored=scored, structure=structure)
```

Display then iterates `arrangements`, reading `arr.score`, `arr.breakdown` and
`arr.assignment` — all already carried on `Arrangement`.

`_score_combos` is promoted to public `score_combos`. It is currently private
yet already imported directly by tests (`test_search.py:155`, `:255`, `:307`,
`:314`), and now has three legitimate callers (CLI, provenance, tests). Rename
and update those references.

`search.search()` stays as-is: `cmd_run` no longer uses it, but four tests do
(`test_search.py:94`, `:103`, `:116`, `:145`) and it remains a reasonable
convenience wrapper.

Two user-visible consequences:

- **`top_n` changes meaning** from "combos shown" to "arrangements shown".
  Because arrangements collapse same-slot week-twins, `top_n: 5` now yields 5
  *distinct layouts* rather than up to 5 near-identical timetables. This is an
  improvement but is a semantic change to the config key and should be noted in
  the README.
- **The header should report both counts**, since `evaluated` counts combos
  while provenance denominators count arrangements:
  `evaluated 363 clash-free timetable shapes (363 distinct arrangements)`.
  These coincide under the current `config.yaml`; they diverge whenever
  collapsing occurs, and showing both is what makes the annotation denominators
  self-explaining.

Optionally surface `arr.variant_count` when greater than 1, so a collapsed
arrangement discloses that it stands for several week-variants. Not required.

### 6. Testing

- `arrangement_provenance` against a hand-built fixture: ceiling, median,
  support, tier assignment, cluster-level aggregation over twins.
- Tier edge cases: all arrangements tied (one tier); median falling between two
  observed scores.
- Ordering: pin the `SEC[4]` > `SEC[2]` inversion, and that `TUT[09]`
  (support 6, median −14.0) is **not** demoted below `TUT[22A]`
  (support 29, median −19.0).
- Twin interleaving: clusters round-robin, letters stay positionally correct,
  `ranked_options` remains a prefix of `all_options`.
- `all_options` with `provenance=None` is byte-identical to current behaviour.
- `render_snake` with `provenance=None` is byte-identical to current output.
- Column alignment with mixed-width entries and multi-session classes.
- **Index alignment:** for a space where collapsing occurs and scores tie,
  `rank_arrangements(space, config, limit=n)` returns exactly the first `n`
  entries of the uncapped `rank_arrangements(space, config)`, and both agree
  positionally with `Provenance.members` keys. This pins the `heapq.nlargest`
  ≡ stable-sort assumption that TUI highlighting depends on.
- **Provenance is cap-independent:** `arrangement_provenance` returns identical
  `total` and `stats` for `max_arrangements` of 3, 50, and unset.
- **Cross-surface agreement:** for one config, the CLI's `timetable #k` and the
  TUI's k-th arrangement have equal score and assignment.

## Out of scope

**Whether twins should be ranked at all.** This design reorders them behind
distinct timeslots but still ranks every twin. Whether a third copy of a
timeslot beats a fourth distinct timeslot depends on per-class demand data,
which is not available for Tutorial Reg.

## Risks

**This changes the ballot the user submits.** Not a display-only change. The
repo's `ballot.txt` was generated from a different config than the current
`config.yaml`, so the effect on the user's real ballot is unverified — re-run
and compare before relying on it.

**Median is computed over arrangements, which are not equally likely.** It
answers "of the timetables containing this class, what is the typical quality",
not "what will I probably get". Without allocation-probability data this is the
best available proxy, but the header wording should not overclaim.
