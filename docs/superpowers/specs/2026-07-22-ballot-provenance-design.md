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
`alternatives_per_module: 4`.

**Provenance against displayed timetables is mostly empty.** Only 13 of 20
ballot entries appear in one of the 5 displayed timetables. Annotating "which
of your top timetables is this in?" would leave 7 entries blank, reading as
"the tool put junk in my ballot".

**Ordinal arrangement rank is near-meaningless.** 363 arrangements share only
30 distinct scores; 9 tie at the best score of −19.0, 22 at another. A class in
a joint-best timetable could render as `best: #7` purely from tiebreak order.
Hence tiers over distinct scores, not ordinal position.

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

### 5. Testing

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

## Out of scope

**CLI displays combos, TUI displays arrangements.** `cli.py:141` iterates
`result.top` (combo-ranked) while the TUI shows `rank_arrangements` output.
These orderings can diverge when collapsing occurs. Provenance tiers are defined
over arrangements in both surfaces, so a CLI user comparing `best #3` against
the CLI's own third displayed timetable may find they disagree. No collapsing
occurs under the current `config.yaml` (363 combos, 363 arrangements), so this
is latent rather than active. Worth a follow-up.

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
