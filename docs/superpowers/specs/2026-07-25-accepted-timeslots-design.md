# User-selected acceptable timeslots

## Problem

The ballot is built from whatever kairos judges viable, ranked by the six
preference weights. Two consequences:

1. Expressing "I'd take any CS1231S tutorial except the 8am ones" means tuning
   weights until the ranking happens to agree — an indirect and unreliable way
   to state a hard preference.
2. Because each group is ranked independently (`ballot.py:96-106`), the ballot
   can put two mutually clashing classes from different groups in the same pass.
   Observed in a real export: `#1 CS1231S TUT[19A]` and `#3 CS2030S LAB[14A]`,
   both Thursday 1400-1600, weeks 3-13. Both would be allocated, and neither
   reopens in tut/lab Round 2 because both groups are filled.

Measured frequency of (2): ~1 in 400 randomised weight/priority combinations —
rare, but unfixable when it lands.

## Decision

Give the user direct control over which timeslots may appear, and leave
clash resolution to them. An automatic deconfliction pass was designed and
rejected: it fixed pass 1 but measurably increased deep-list clashes (7 -> 10
on the reproduced failing config), and it decides on the user's behalf what
they can now decide for themselves while looking at the grid.

**Clashes remain possible and are the user's responsibility.** This design does
not deconflict anything.

## Design

### The insight: `locked` is this feature with one slot

`prepare_groups` (`search.py:19-58`) already restricts the search space through
a precedence cascade:

| tier | config key | restricts group to |
|---|---|---|
| 1 | `fixed` | exactly one class number |
| 2 | `locked` | every class sharing the locked class's `slot_sig` |
| 3 | *(none)* | every class |

`accept` is tier 2 with the "one slot" restriction removed. New cascade:
`fixed` > `locked` > `accept` > all.

### Config

```yaml
accept:
  CS1231S:
    TUT: ['07A', '08A', '19A']
  CS2030S:
    LAB: ['10A', '14A']
```

Same shape and semantics as `locked`, one level deeper: a **list** of class
numbers, each designating *its timeslot*, not itself. Ticking `19A` accepts
`19B` too when they share a `slot_sig` — matching `locked`'s documented
"pins the timeslot, not the class number" behaviour and keeping venue/week
twins available for the ballot.

`Config.accept` is `dict` (code -> dict[abbrev, list[class_no]]), defaulting to
`{}` via `field(default_factory=dict)`, parsed in `config_from_dict` as
`data.get("accept") or {}`, alongside `locked` (`config.py:52`, `:118`).

**A missing or empty entry means "all acceptable", never "exclude".** Forgetting
to tick a group must not silently submit nothing for it and leave the user with
no tutorial at all.

### The only code change

`prepare_groups` gains a branch after the `locked` branch:

```python
accepted = (config.accept.get(group.module) or {}).get(abbrev)
if accepted:
    sigs = set()
    for number in accepted:
        anchor = next((c for c in group.choices if c.class_no == str(number)), None)
        if anchor is None:
            raise SystemExit(
                f"error: {group.module} {abbrev} class {number} "
                "(config 'accept') does not exist"
            )
        sigs.add(anchor.slot_sig)
    chosen = [c for c in group.choices if c.slot_sig in sigs]
    prepared.append(ChoiceGroup(group.module, group.lesson_type, chosen))
    continue
```

The per-number `next(...)` lookup mirrors the `locked` branch (`search.py:34`)
rather than a set-membership filter, precisely so an unknown number raises
instead of being silently dropped — a dropped number would narrow the space
differently than the user asked, with no signal.

Every class number listed must exist, or `SystemExit("error: ...")` naming the
module, abbrev, and offending number — consistent with the `fixed` and `locked`
branches (`search.py:26-29`, `:35-47`). An empty list is treated as absent
(all acceptable), not as "accept nothing", so a stray `TUT: []` cannot silently
empty the space.

### Nothing downstream changes

Because the restriction lands at space construction, the timetable search,
scoring, provenance, ballot, and TUI grid all inherit it. **`ballot.py` is not
touched.** No ranking, snake, or cap logic needs to know this feature exists.

This does mean the **timetable view narrows too**, not just the ballot — kairos
stops showing arrangements built from rejected slots. That is intended: a
timetable containing a slot you rejected is not a timetable you would take.

### Over-restriction

If the accepted set leaves no clash-free timetable, this is the failure mode
`locked` already has:

- TUI: `_apply_locked_change` (`state.py:171`) snapshots, rebuilds, and rolls
  back on empty, toasting instead of applying. The accept toggle reuses it
  verbatim.
- CLI: `SystemExit("error: ...")` from the existing empty-space path.

No new machinery.

### TUI

The Timeslots pane lists offered timeslots per group and binds `l` to
lock/unlock. Add a binding — `a` — toggling accept on the highlighted timeslot,
with a gutter marker in the same idiom as the existing `🔒` and the `●` from
the ballot view. Accept state routes through `_apply_locked_change` so an
over-restricting toggle rolls back with a toast.

`to_config_yaml` (`state.py:308`) gains `"accept": self.config.accept` beside
`"fixed"` and `"locked"`, so `s` persists selections.

### Shortfall stays strict

A narrower pool yields a shorter ballot. `shortfall()` and the export toast
already report this, so no new reporting — but the current message reads
"no further clash-free options", which misattributes the cause when the real
reason is a narrow selection. It needs to distinguish the two.

## Testing

- `prepare_groups`: accept restricts to the union of the named slots' `slot_sig`s;
  twins at an accepted slot survive; an unknown class number exits with an error
  naming it; `accept` is ignored when `fixed` or `locked` covers the same group;
  an empty list and a missing key both mean all-acceptable.
- Config: `accept` round-trips through `config_from_dict` and `to_config_yaml`;
  absent key defaults to `{}`.
- State: an over-restricting accept toggle rolls back and leaves the space
  unchanged (mirrors the existing lock-rollback test).
- Ballot: with `accept` set, every ballot entry's slot is in the accepted set —
  and clashing cross-group entries are still permitted (a regression guard that
  this design does *not* deconflict).

## Out of scope

- Deconflicting the ballot, in any form.
- Warning the user that two selected slots overlap. Worth doing, decided
  separately — surfacing a clash is not the same as resolving one, and the
  ballot view already draws each bid on the grid.

## Docs

`docs/user-guide.md` — the `accept` config key, the `a` binding, and that
clash resolution is the user's job. `docs/architecture.md` — the
`prepare_groups` cascade gains a tier. `docs/development.md` — new test coverage.
