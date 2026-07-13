# NUS Course Optimiser — Design Spec

**Date:** 2026-07-13
**Status:** Draft for review

## Purpose

A Python CLI that, given a set of NUS modules and the user's preferences, searches all
valid timetable combinations and produces:

1. The top-N best timetables, each with a score breakdown and a clickable NUSMods share link.
2. Ranked backup tutorial choices per module (distinct alternatives, not just the top timetables' picks).
3. A snake-order ("flop-table") ballot ranking of up to 20 entries, ready to key into
   EduRec tutorial registration, following the method: `1A 2A 3A 4A 5A 5B 4B 3B 2B 1B 1C ...`

## Non-goals

- No web UI (CLI only).
- No automatic submission to EduRec.
- No vacancy/popularity data (NUSMods API does not expose it); risk handling comes from
  snake ordering and backup diversity, per the balloting guide.

## CLI

Two subcommands:

### `optimiser init <nusmods-share-url>`

Bootstraps `config.yaml`:

1. Parse the share URL for semester and modules (e.g. `CS1231S=TUT:07A,LEC:2&...`).
2. Fetch each module from the NUSMods API; discover its lesson types and slot counts.
3. Pin lecture choices from the URL (see "Fixed vs balloted slots" below).
4. Interactively prompt for a 1–5 difficulty per (module, lesson type), one at a time,
   offering a default of 3.
5. Prompt for module priority order (die-die-must-get first) for the snake ranking.
6. Write `config.yaml` including preference/weight defaults. If a config already exists,
   warn and require confirmation before overwriting.

### `optimiser run`

Reads `config.yaml`, fetches/caches module data, runs the search, prints the three outputs.

## Data layer

- **Source:** NUSMods public API, `https://api.nusmods.com/v2/{acadYear}/modules/{code}.json`
  (e.g. `2026-2027`). The `semesterData` entry for the configured semester holds the
  `timetable` list of lessons: `{classNo, lessonType, day, startTime, endTime, weeks, venue}`.
- **Caching:** raw JSON cached under `data/cache/{acadYear}-{sem}-{code}.json` with a
  configurable TTL (default 24 h) so slot updates (e.g. MA1522 tutorials, unpublished as of
  writing) are picked up while repeated runs stay offline-fast.
- **Lesson type mapping:** API uses full names (`Lecture`, `Tutorial`, `Recitation`,
  `Laboratory`, `Sectional Teaching`); share URLs use abbreviations (`LEC`, `TUT`, `REC`,
  `LAB`, `SEC`). A single mapping table converts both ways.
- **ClassNo bundling:** all lessons sharing a `classNo` within a lesson group form one
  choice — picking the group means attending all its sessions (e.g. a Mon+Wed lecture).
- **Online lessons:** a lesson whose venue starts with `E-Learn` is classified `online`
  (confirmed in live data: CS1231S LEC 2 is `E-Learn_C`).

## Fixed vs balloted slots

No manual pinning config. Two automatic mechanisms:

1. **Single-option groups** (e.g. CS2030S has one lecture group) are fixed.
2. **Non-balloted lesson types** — config holds `balloted_types` (default
   `[TUT, LAB, REC, SEC]`). For types outside this list (i.e. lectures, locked in during
   course registration), the user's choice is read from the share URL given to `init` and
   stored in the config as `fixed:`. TUT/LAB/REC/SEC selections in the URL are ignored —
   they are what we are optimising.

If a lecture group has multiple options but no URL selection exists, the search treats it
as a free variable and a warning is printed.

## Config (`config.yaml`)

```yaml
acad_year: 2026-2027
semester: 1
balloted_types: [TUT, LAB, REC, SEC]
modules:
  CS1231S:
    difficulty: {LEC: 3, TUT: 4}
  CS2030S:
    difficulty: {LEC: 3, REC: 4, LAB: 2}
  MA1521:
    difficulty: 3            # shorthand: all components
  MA1522:
    difficulty: {LEC: 1, REC: 5}
  UTW1001X:
    difficulty: 1
fixed:                        # written by init from the share URL
  CS1231S: {LEC: "2"}
  MA1522: {LEC: "2"}
priority: [CS2030S, CS1231S, MA1522, MA1521, UTW1001X]
preferences:
  earliest_start: "10:00"
  latest_end: "18:00"
  max_difficulty_per_day: 8
  lunch_window: ["11:00", "14:00"]
  lunch_minutes: 60
  weights:
    time_window: 3
    tough_days: 5
    same_day_pairing: 2
    free_days: 4
    gaps: 1
    lunch: 3
alternatives_per_module: 4
top_n: 5
```

Difficulty is 1–5 per (module, lesson type); a bare number applies to every component.

## Search (`search.py`)

Depth-first enumeration over lesson groups, one choice per group:

- **Order** groups by fewest options first (fixed groups assigned up front).
- **Clash pruning:** reject a partial assignment as soon as two lessons overlap. Two
  lessons clash only if same day, overlapping times, **and** overlapping week sets
  (odd/even-week classes can share a slot).
- **Footprint dedup:** within a group, choices with identical schedule footprints
  (same set of `(day, startTime, endTime, weeks)` sessions) are collapsed to one
  representative during search and expanded afterwards — all members of a footprint class
  share the same conditional score. This keeps the worst case (tens of millions of raw
  combos) to seconds.
- **Tracking:** a bounded max-heap of the global top-N *distinct-footprint* timetables,
  plus, for ballot generation, `best_score[group][footprint]` — the best complete-timetable
  score achievable using that footprint.
- If zero clash-free timetables exist, report which group pair is irreconcilable.

## Scoring (`scoring.py`)

Score = weighted sum; each component reported separately in output. Online lessons are
excluded from all physical-presence components (time window, free days, gaps, lunch) but
**included** in tough-day difficulty sums. A day with only online lessons counts as free.

| Component | Definition |
|---|---|
| `time_window` | penalty per minute of on-campus class before `earliest_start` / after `latest_end` |
| `tough_days` | per day: `max(0, sum(difficulty of that day's lessons) − max_difficulty_per_day)`, penalised proportionally |
| `same_day_pairing` | bonus per module whose tutorial-type lesson shares a day with its lecture (only when the lecture is on-campus) |
| `free_days` | bonus per weekday (Mon–Fri) with no on-campus lessons |
| `gaps` | penalty per idle minute between consecutive on-campus lessons on a day |
| `lunch` | penalty per day with on-campus lessons but no free block ≥ `lunch_minutes` inside `lunch_window` |

## Ballot generation (`ballot.py`)

1. For each balloted group, rank footprints by `best_score[group][footprint]` descending;
   expand footprints to concrete classNos (ties within a footprint listed together — they
   are interchangeable, giving free extra backups).
2. Take the top `alternatives_per_module` distinct classNos per group as choices A, B, C, D.
3. Order modules by `priority`; emit snake order (A-round in priority order, B-round
   reversed, C-round forward, ...), capped at 20 entries.
4. Note: modules can contribute multiple balloted groups (CS2030S REC + LAB). Each balloted
   group is its own "column" in the snake, positioned by its module's priority (REC before
   LAB within the same module).

## Output (`output.py`)

1. **Top-N timetables:** terminal week grid (days × hours, module+type+classNo in cells,
   online lessons marked), score breakdown table, NUSMods share URL
   (`https://nusmods.com/timetable/sem-{sem}/share?CODE=TYPE:NO,...`).
2. **Per-group ranked alternatives:** choice letter, classNo, day/time/venue, conditional
   best score.
3. **Snake ballot list:** numbered 1–20, each entry with module, lesson type, classNo,
   day/time/venue for double-checking against EduRec.

## Module structure

```
optimiser/
  config.yaml            (generated by init; gitignored? no — user may want it versioned, keep it)
  optimiser/
    __init__.py
    api.py               fetch + cache
    model.py             Lesson, ChoiceGroup, Timetable dataclasses; clash logic
    search.py            enumeration, pruning, top-N, per-footprint bests
    scoring.py           scoring components
    ballot.py            alternatives + snake order
    output.py            grid, share links, ballot rendering
    cli.py               argparse: init / run
  data/cache/            (gitignored)
  tests/
```

Dependencies: `requests`, `PyYAML`; `pytest` for tests. Python ≥ 3.11.

## Error handling

- Unknown module code / module absent in semester → clear error naming the module.
- API unreachable → fall back to cache regardless of TTL, with a warning; error only if
  no cache exists.
- Balloted group with fewer slots than `alternatives_per_module` → use what exists.
- Share URL parse failures → error showing the offending fragment.

## Testing

`pytest`, with a small checked-in fixture of real API JSON (trimmed):

- weeks-aware clash detection (incl. odd/even non-clash)
- classNo bundling (multi-session groups)
- footprint dedup and expansion
- each scoring component in isolation, incl. online-lesson exclusions
- per-footprint best tracking against brute-force on a tiny fixture
- snake ordering: even distribution, uneven counts, multi-group modules, 20-cap
- share URL parse/generate round-trip
