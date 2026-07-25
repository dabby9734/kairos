# Kairos user guide

Kairos is an NUS timetable optimiser. Give it the module picks from your
NUSMods draft timetable, tell it what you care about (a lunch break, no 9am
starts, an even spread of difficulty across the week), and it searches every
clash-free way to schedule your tutorials, labs, recitations, and sectional
classes, scores each one against your preferences, and prints a ranked list
you can paste straight into NUS tutorial-slot registration. It also ships an
interactive terminal app (`kairos tui`) for tuning those preferences live and
watching the ranking update.

This guide covers:

- [How NUS tutorial balloting works](#how-nus-tutorial-balloting-works) — the
  process kairos is built around
- [Getting started](#getting-started) — install and generate your first config
- [config.yaml reference](#configyaml-reference) — every key, annotated
- [Running it: kairos run](#running-it-kairos-run) — reading the CLI's output
- [The TUI](#the-tui) — the interactive live-tuning app
- [CourseReg advisor (`kairos advise`)](#coursereg-advisor-kairos-advise) — a
  separate what-if ranking tool for CourseReg, not the tutorial ballot
- [FAQ / gotchas](#faq--gotchas)

## How NUS tutorial balloting works

Tutorial/lab/recitation/sectional registration at NUS is a **separate
exercise from course allocation**. By the time you're balloting for a
timeslot, you already have a confirmed seat in the module — this ballot only
decides which specific tutorial group, lab session, recitation, or sectional
class you get. There's no priority score involved the way there is for course
registration; it runs on your ranked list of choices.

The part that catches people out: you rank up to **20 tutorial/lab timeslots
in total, across every module you're registered for** — not 20 per module.
It's a single global budget. If you're taking five modules and each has a
tutorial you need to slot in, those five choices (plus whatever backups you
list) all draw from the same pool of 20 ranked entries.

NUS's own guidance is blunt about what happens if you rank fewer: a shorter
list "may also mean that a student may not be successful in getting a
tutorial allocated at all." There's no benefit to leaving slots unused — every
empty slot is a lottery ticket you didn't buy. That's why kairos always fills
all 20 slots it can: once your explicit backups run out, it keeps adding the
next-best options group by group until either the list hits 20 or it runs out
of genuinely clash-free options to offer.

If you don't get your first choice, Round 2 follows: classes you already won
in Round 1 are removed from the pool, and you rank up to 20 fresh choices for
whatever's still open.

For the order in which choices are submitted, kairos uses the "mirror
method" (also called snake ordering) that's common, community-validated
practice among NUS students: your best option for every module goes first,
then the second-best option for every module (in reverse order), then the
third round, and so on. Be clear about what this is: **NUS does not publish
the ballot's actual allocation algorithm**, so this ordering is not confirmed
official behaviour — it's a strategy that experienced students have found
gives good outcomes, not a guarantee.

## Getting started

You'll need:

- Python 3.11 or later
- a terminal

**1. Build a draft timetable on [NUSMods](https://nusmods.com)** — add your
modules, pick any classes as placeholders (kairos will search over the
alternatives), and copy the "share" link from the timetable's share button.

**2. Set up the virtual environment and install kairos:**

    python3 -m venv .venv
    .venv/bin/pip install -e .

**3. Generate a config from your share URL:**

    .venv/bin/kairos init "https://nusmods.com/timetable/sem-1/share?CS1231S=TUT:07A,LEC:2&..."

Quote the URL — it contains `&` characters, and without the quotes your shell
will cut the URL short at the first one.

`kairos init` will ask you two kinds of question, both of which shape the
results later:

- **A difficulty rating from 1 to 5 for each class component of each module**
  (lecture, tutorial, lab, ...), defaulting to 3 if you just press enter.
  This feeds the "daily overload" criterion — a day stacked with several
  high-difficulty classes gets penalised even if it isn't literally clashing.
- **A priority order for your modules, most important first** — asked once,
  at the end, defaulting to the order the modules appeared in your share URL.
  This sets the column order of the ballot's snake: every module's best
  option is listed in this order before any module's second-best (see the
  snake ordering above).

This writes `config.yaml` in the current directory. From here you tweak that
file directly — see the next section — then run `kairos run`.

## config.yaml reference

Here's a real generated config, as a concrete example:

```yaml
acad_year: 2026-2027
semester: 1
balloted_types:
- TUT
- LAB
- REC
- SEC
modules:
  CS1231S:
    difficulty:
      LEC: 3
      TUT: 4
  CS2030S:
    difficulty:
      LAB: 5
      LEC: 4
      REC: 4
  MA1521:
    difficulty:
      LEC: 2
  MA1522:
    difficulty:
      LEC: 2
  UTW1001X:
    difficulty:
      SEC: 2
fixed: {}
locked:
  CS1231S:
    LEC: '2'
  MA1521:
    LEC: '1'
  MA1522:
    LEC: '2'
priority:
- CS2030S
- CS1231S
- MA1522
- MA1521
- UTW1001X
preferences:
  earliest_start: 09:00
  latest_end: '18:00'
  max_difficulty_per_day: 10
  lunch_window:
  - '11:00'
  - '14:00'
  lunch_minutes: 60
  weights:
    time_window: 5
    tough_days: 3
    same_day_pairing: 0
    free_days: 5
    gaps: 0
    lunch: 7
alternatives_per_module: 4
top_n: 5
max_arrangements: 50
```

Key by key:

- **`acad_year`, `semester`** — which NUSMods dataset to fetch (e.g. modules
  and timeslots offered in AY2026-2027 semester 1).
- **`balloted_types`** — which class types get included in the 20-slot
  ballot. Defaults to `TUT`, `LAB`, `REC`, `SEC`. Lectures are never in this
  list by default, so they're never balloted (see the FAQ below).
- **`modules.<code>.difficulty.<component>`** — a 1–5 rating per class
  component (`LEC`, `TUT`, `LAB`, ...). Feeds the `tough_days` criterion:
  higher-difficulty classes stacked on the same day push you past
  `max_difficulty_per_day` sooner.
- **`fixed`** — pin an exact class number for a group (e.g. `TUT: '07A'`).
  The group is then locked to that one class and drops out of the search
  entirely — and out of the TUI's Classes pane too, since there's nothing
  left to decide. `fixed` wins over `locked` if a group somehow has both.
- **`locked`** — pin a *timeslot*, not a specific class number. Kairos finds
  the class you named, notes its exact day/start/end (ignoring venue and
  which teaching weeks it runs), and keeps every class that shares that same
  slot in play. So if two classes run at the same time in different venues,
  or on alternating weeks, locking one still leaves its "twin" available as
  an interchangeable ballot option. This is what the TUI's `l` key writes.
- **`priority`** — your modules, most important first. Used as the primary
  sort key for the ballot's snake ordering: every module's best remaining
  option is offered before any module's second-best. Within a module,
  columns are ordered Tutorial, Sectional, Recitation, Laboratory.
- **`preferences.earliest_start` / `latest_end`** — your preferred class
  window. Campus class time outside this window is penalised via the
  `time_window` criterion (online classes are exempt — see the FAQ).
- **`preferences.max_difficulty_per_day`** — the cap the `tough_days`
  criterion measures against; days whose difficulty total exceeds this are
  penalised in proportion to the overage.
- **`preferences.lunch_window` + `lunch_minutes`** — a free block at least
  `lunch_minutes` long must fit somewhere inside `lunch_window` on a given
  day, or that day counts against the `lunch` criterion.
- **`preferences.weights`** — how much each criterion counts toward the
  total score. Setting a weight to `0` disables that criterion completely —
  no score effect, and no warnings for it either. The six criteria, with the
  exact wording kairos itself uses to describe them:

  | Criterion | What it measures | Default weight |
  |---|---|---|
  | `free_days` | whole free weekdays (more = better) | 4 |
  | `gaps` | idle hours between classes (fewer = better) | 1 |
  | `lunch` | days with no lunch break (fewer = better) | 3 |
  | `same_day_pairing` | tutorials/labs sharing a day with their lecture (more = better) | 2 |
  | `time_window` | class-hours outside your preferred window (fewer = better) | 3 |
  | `tough_days` | difficulty piled past your daily cap (less = better) | 5 |

- **`alternatives_per_module`** — how many backup choices to guarantee per
  balloted group before kairos starts filling the rest of the 20 slots with
  whichever group's next option scores best.
- **`top_n`** — how many top-scoring timetables `kairos run` prints in full.
  CLI only; it doesn't affect the TUI's list.
- **`max_arrangements`** — caps how many arrangements the TUI's Timetables
  pane lists. TUI only; it doesn't change what the CLI searches, prints, or
  how many timetables it evaluates.

## Running it: kairos run

    .venv/bin/kairos run

The first line tells you how big the search space was:

    evaluated 363 clash-free timetable shapes (363 distinct arrangements)

"Shapes" is the number of distinct clash-free combinations of classes kairos
found. Classes that are outright identical in time — two lab sections at the
same day, time, and teaching weeks, differing only by venue — are merged
*before* this count, so they never inflate it (this run has several such
pairs, like CS2030S LAB 10A/10B, which is why the ballot later says
"interchangeable with"). "Distinct arrangements" is the shape count after one
further merge: shapes that differ only by *week-based* twins — the same slot
on the same day and time, but running on alternating teaching weeks — are
collapsed into a single arrangement with multiple valid class numbers, since
your week looks the same either way. The two numbers match in this run
because this module combination has no week-based twins to collapse; when
they differ, the second number is the one that answers "how many genuinely
different timetables do I have."

Next, `top_n` timetables print in full, best first. Each one has a score
breakdown, a week grid, and a ready-to-open NUSMods link:

    === timetable #1 ===
    score: -14.00
        free_days          raw    +1.00   weighted    +5.00   — whole free weekdays (more = better)
        gaps               raw    -6.00   weighted    -0.00   — idle hours between classes (fewer = better)
        lunch              raw    -2.00   weighted   -14.00   — days with no lunch break (fewer = better)
        same_day_pairing   raw    +1.00   weighted    +0.00   — tutorials/labs sharing a day with their lecture (more = better)
        time_window        raw    -1.00   weighted    -5.00   — class-hours outside your preferred window (fewer = better)
        tough_days         raw    +0.00   weighted    +0.00   — difficulty piled past your daily cap (less = better)
         0800    0900    1000    1100    1200    1300    1400    1500    1600    1700    1800    1900    2000
    Mon                  MA1521  MA1521  CS2030S CS2030S                 MA1522  MA1522
           1000-1200 MA1521 LEC[1] @UT-AUD1
           1200-1400 CS2030S LEC[1] @I3-LT38
           1600-1800 MA1522 LEC[2] @UT-AUD2
    ...
    https://nusmods.com/timetable/sem-1/share?CS1231S=LEC:2,TUT:07A&CS2030S=LAB:10A,LEC:1,REC:01&MA1521=LEC:1&MA1522=LEC:2&UTW1001X=SEC:2

Each `raw` value is that criterion's unweighted measurement (e.g. `lunch`
raw `-2.00` means two weekdays have no long-enough lunch break); `weighted`
is `raw × preferences.weights.<criterion>`, and the total `score` is the sum
of the weighted column. The week grid marks which module occupies each hour;
a `~` prefix on a cell or agenda line means that session is online. The
NUSMods link opens exactly this timetable in the browser.

After the top timetables comes a section listing every balloted group's
viable options, lettered, best first:

    === backup choices per balloted group ===
    CS2030S LAB:
        A. [10A] Thu 1000-1200   best score -14.00  (interchangeable with 10B)
        B. [14A] Thu 1400-1600   best score -14.00  (interchangeable with 14B)
        C. [16A] Thu 1600-1800   best score -14.00  (interchangeable with 16B)
        D. [10B] Thu 1000-1200   best score -14.00  (interchangeable with 10A)

Finally, the ballot itself — up to 20 entries in snake order, each annotated
with two extra numbers beyond raw score:

    === ballot ranking (snake order, cap 20) ===
    best    = ceiling: the best timetable containing this class
    typical = median of the 363 clash-free timetables containing it

     1. CS2030S REC[05]   choice A  Wed 1400-1500  best #1 (-14.0)  typical #3 (-19.0)
     2. CS2030S LAB[10A]  choice A  Thu 1000-1200  best #1 (-14.0)  typical #3 (-19.0)
                            ↳ interchangeable with 10B
     3. CS1231S TUT[07A]  choice A  Tue 1000-1200  best #1 (-14.0)  typical #1 (-14.0)
                            ↳ interchangeable with 07B, 07C

`best` is the highest score of any clash-free timetable that contains this
class, with its rank (`#1`, `#2`, ...) among all distinct scores seen —
useful because ties are common, so the raw score alone doesn't tell you how
many other options share that ceiling. `typical` is the median score across
every clash-free timetable containing this class, with its own rank. A class
whose `typical` is close to its `best` mostly shows up in good timetables;
one where they're far apart is only good in a lucky combination with
everything else.

If kairos can't fill all 20 slots — because fewer than 20 genuinely distinct
clash-free options exist across your balloted groups — it says so instead of
padding with duplicates:

    warning: ballot uses only N of 20 slots — no further clash-free options exist.
    NUS notes a shorter list may mean not getting a tutorial allocated at all.

That's not a bug to fix in your config; it means your module combination
genuinely has fewer than 20 workable arrangements, and you should register
the ballot as-is rather than manufacture extra rows.

## The TUI

    .venv/bin/kairos tui "https://nusmods.com/timetable/sem-1/share?CS1231S=TUT:07A,LEC:2&..."
    # or, to resume from a saved config.yaml:
    .venv/bin/kairos tui

Pass a share URL to start fresh (this builds a config the same way `kairos
init` does, but skips the interactive prompts — difficulties default to 3
and priority to URL order, both editable live in the app). Omit it to resume
tuning whatever's already in `config.yaml`.

**Pane tour.** The left side has four tabs: **1 Weights**, **2 Difficulty**,
**3 Times**, **4 Priority** (press the number to jump to a tab). The right
side has **Timetables** (top-scoring arrangements), **Warnings** (what's
wrong with the selected one), **Classes** and **Timeslots** (drill into any
group's options), and a detail pane showing the selected timetable's score
breakdown, week grid, and share link.

**Sliders** (Weights, Difficulty, Times tabs): ←/→ adjusts the value and
re-ranks the whole timetable list live; ↑/↓ moves focus between sliders in
the same tab.

**Classes pane**: lists every group with more than one distinct timeslot —
including lectures, since some modules run alternative lecture sections (a
different time, or the same time online). Press → to open that group's
Timeslots pane; a `~` marks an online option; press `l` to lock or unlock the
highlighted timeslot.

Locking pins the *timeslot*, not the class number — the same slot-signature
semantics as the `locked` config key, so venue/week twins at that slot stay
available for the ballot. If locking would leave no clash-free timetable at
all, kairos refuses and shows a toast instead of applying it.

Other keys: `[` / `]` move the highlighted module up/down the priority list
(Priority tab); `b` toggles the ballot view, highlighting the classes that
belong to the currently-selected timetable; `s` saves the current tuning back
to your config file; `e` exports the ballot to `ballot.txt` next to it; `c`
copies the selected timetable's NUSMods share link to your OS clipboard
(falling back to an OSC-52 terminal escape, useful over SSH, if the OS
clipboard command isn't available); `q` quits.

Full keybinding table:

| Key | Action |
|---|---|
| `1` / `2` / `3` / `4` | switch to Weights / Difficulty / Times / Priority tab |
| ← / → (on a slider) | adjust the highlighted value |
| ↑ / ↓ (on a slider) | move between sliders in the tab |
| → | focus the Timeslots pane for the highlighted class |
| ← / Esc | back to the Classes pane |
| `l` | lock/unlock the highlighted timeslot |
| `[` / `]` | move the highlighted module up/down in priority |
| `b` | toggle the ballot view |
| `s` | save config.yaml |
| `e` | export ballot.txt |
| `c` | copy the selected timetable's NUSMods link |
| `q` | quit |

## CourseReg advisor (`kairos advise`)

`kairos advise` is a completely separate tool from everything above — it has
its own config file, its own data source, and targets a different NUS system
entirely. **CourseReg** is how you get a seat in a module in the first
place, weeks before the tutorial ballot this guide otherwise covers even
opens. Each round, every applicant for a course is scored by three factors,
in order: **A** (a priority tier NUS assigns from your programme/curriculum
requirements), **B** (a random tiebreak within that tier), and **C** — the
rank, 1 through 8, that *you* personally give the course in your own ranked
wishlist. A and B are entirely outside your control; **C is the only lever
you have**, and it's exactly what `kairos advise` helps you place well,
using five academic years' worth (ten semesters) of round-by-round
demand-vs-vacancy history scraped from the (now-archived) CourseRekt
project.

### coursereg.yaml reference

`kairos advise` reads `coursereg.yaml` (not `config.yaml`) from the current
directory by default. You don't have to write it by hand: run
`kairos advise <nusmods-share-url>` and it is generated for you (see
"Running it" below). If the file is missing and no link is given, the
command exits with an error that pastes this exact template so you can
copy it straight in:

```yaml
seniority: 2            # your year of study, 1-4
semester: 1             # semester you are planning (1 or 2)
round: 2                # CourseReg round being planned (2 or 3)
candidates:
  CS2109S: major        # course code: your requirement tier (core | major | ue)
  GEH1049: ue
```

- **`seniority`** — your year of study (1–4). Only affects UE-tier courses:
  seniority 3 or 4 cancels out the usual UE-tier penalty (back to the raw
  historical trend); seniority 1 leaves the default UE penalty as-is — it's
  already at the toughest nudge the model applies, so there's no further
  penalty for being a freshman specifically.
- **`semester`** — 1 or 2. Demand for the same course differs systematically
  between semesters, so only same-semester history ever feeds a verdict.
- **`round`** — 2 or 3; this tool models CourseReg rounds 2 and 3 only.
  Toggle it live in the TUI with `r`.
- **`candidates`** — your course code, followed by its requirement tier:
  `core`, `major`, or `ue`. The tier nudges the verdict one notch friendlier
  (`core`) or tougher (`ue`) than the raw historical trend alone would say —
  `major` gets no nudge.
- **`ranked`** — not something you write by hand; the TUI adds it (`true`)
  the first time you save, along with whatever order you left the ranking
  pane in.

### Running it

    # first time: generate coursereg.yaml from an NUSMods share link
    .venv/bin/kairos advise 'https://nusmods.com/timetable/sem-1/share?...'
    # after that (or with a hand-written coursereg.yaml):
    .venv/bin/kairos advise
    # or, to use a different file/cache location:
    .venv/bin/kairos advise --config coursereg.yaml --cache-dir data/coursereg
    # if you suspect the cached demand data is stale or broken:
    .venv/bin/kairos advise --refetch

With a link, the semester and course codes come from the link itself (the
lesson picks in it are ignored) and you're asked for everything else: your
year of study `[2]`, the round `[2]`, and each course's tier
(`core`/`major`/`ue`, default `major`, shorthands `c`/`m`/`u`). The file is
written and the TUI opens immediately with your fresh profile. If
`coursereg.yaml` already exists you're asked before it's overwritten
(this discards any saved ranking); special-term links (`sem-3`/`sem-4`)
are rejected before any prompt since the advisor models semesters 1 and 2
only.

The first run fetches and permanently caches ten semesters of demand history
(AY2021/2022 through AY2025/2026, both semesters) under `data/coursereg/`;
every run after that is cache-only and needs no network at all.

### The TUI walkthrough

The screen has three panes. **Ranking** (left) lists every course in your
`candidates`, in your current rank order — a rank number (or `--` once
you're past position 8, since only your first 8 ranks count for anything),
the course code, its standing, and its tier. **Dossier** (right) shows the
highlighted course's full history — the years matching your planned
semester in full, other-semester years dimmed as background context only —
followed by a one-line explanation of why it got the standing it did.
**Notes** (bottom) lists up to three "leverage warnings" — see below. The
header bar permanently reminds you of the biggest caveat: *"assumes
independent per-course queues"*.

| Key | Action |
|---|---|
| `j` / `k` | move the highlighted row down / up |
| `J` / `K` | move the highlighted *course* down / up in your ranking |
| `a` | reset to the advisor's suggested order |
| `t` | cycle the highlighted course's tier (`core` → `major` → `ue` → `core`) |
| `r` | toggle between planning for round 2 and round 3 |
| `s` | save your current ranking back to `coursereg.yaml` |
| `q` | quit |

**Standings, in plain language:**

- **SAFE** — recent same-semester rounds were comfortably under-subscribed
  (demand well below the number of seats). Should get in at almost any rank.
- **LIKELY** — one notch off the raw historical trend because of your
  profile: either a `CONTESTED` trend softened by your `core`-tier nudge, or
  a `SAFE` trend hardened by your `ue`-tier nudge.
- **CONTESTED** — demand and vacancy have been roughly even lately. This is
  where your rank genuinely decides the outcome.
- **TOUGH** — the mirror case: either a `CONTESTED` trend hardened by your
  `ue`-tier nudge, or a `LONG_SHOT` trend softened by your `core`-tier nudge
  to merely `TOUGH`.
- **LONG_SHOT** — recent rounds were consistently and heavily
  oversubscribed. Expect to miss it most cycles, whatever rank you give it.
- **NO_DATA** — no history exists for this exact semester+round combination
  (a new or renamed course, most likely). The advisor has nothing to tell
  you — place it deliberately.

Pressing `a` restores the advisor's own suggested order, which puts
`CONTESTED`/`TOUGH` courses first (your rank has the most leverage there),
then `LIKELY`, then `NO_DATA` (so you consciously decide where it goes
rather than defaulting it), then `LONG_SHOT`, with `SAFE` courses last —
they'll come through no matter where you rank them, so they shouldn't
occupy a valuable top slot. The **Notes** pane's leverage warnings catch the
opposite mistakes: a `SAFE` course sitting in your top 3 ranks (wasted
leverage — something contested could use that slot instead), a
`TOUGH`/`CONTESTED`/`LIKELY` course sitting past rank 8 (i.e. not on your
actual ranked list at all), or any `NO_DATA` course, so you notice it and
place it on purpose rather than by accident.

### Three things this tool can't know

- **It assumes each course allocates independently.** Missing your rank-1
  choice is assumed to cost you nothing on rank-2's chances. NUS has never
  published the real CourseReg algorithm, and there's a hint — the
  "unmet minimum workload" tie-breaker in NUS's own rules — that something
  more holistic might happen near the unit cap. Treat every verdict as a
  caveated estimate, not a guarantee.
- **Verdicts are historical trends, frozen at AY2025/2026 — they cannot see
  the round you're actually in.** The CourseRekt project this data comes
  from was archived on 2026-01-10 and will never be updated again. A
  verdict tells you what a course's demand *used to* look like across past
  years, not what it looks like right now; a course that was `SAFE` for
  years can flip without any warning from this tool.
- **Only history from your own semester counts.** Semester 1 and Semester 2
  demand for the same course differ systematically, so a course's Semester 1
  history never factors into a Semester 2 verdict, or vice versa — set
  `semester` correctly in `coursereg.yaml`, since a wrong value silently
  looks at the wrong half of the data.

### If the cache is missing and the site is down

If `courserekt.vercel.app` is unreachable *and* you have no local cache yet
(first run, on a machine with no `data/coursereg/` folder), `kairos advise`
exits with:

    error: courserekt.vercel.app unreachable and no cached data in
    data/coursereg — copy a friend's cache there (the data is frozen and
    identical for everyone): <network error detail>

That's a genuine fix, not a workaround: since the underlying dataset is
permanently frozen, any two students' caches are byte-identical. Ask a
friend who's already run `kairos advise` successfully to send you their
`data/coursereg/*.json` files, drop them into your own `data/coursereg/`
directory, and re-run.

## FAQ / gotchas

- **Online classes** (venue starting with `E-Learn`) don't count against your
  time window or lunch-break check, but they *do* count toward daily
  difficulty — a fully-online day can still trip the `tough_days` criterion.
  They're marked with `~` throughout the CLI and TUI output.
- **Lectures are never balloted** by default (`balloted_types` doesn't
  include `LEC`), so they never appear in `ballot.txt`. If you have a
  lecture with more than one section, lock the one you want in the TUI and
  register it directly — it's not part of the ranked ballot process.
- **Saturday only shows up when it's used.** The week grid always prints
  Monday–Friday; a Saturday row is added only for timetables that actually
  have a class scheduled that day.
- **Module data is cached for 24 hours** under `data/cache/`. If NUSMods data
  changed and you want a fresh pull, delete the relevant cache file (or wait
  for it to expire). If the API is unreachable and a cache file exists,
  kairos falls back to it with a `warning: API unreachable for <code>, using
  stale cache` message rather than failing outright.
- **"no clash-free timetable" errors name the two groups at fault** — the
  message reads `error: no clash-free timetable — every <module> <type>
  clashes with every <module> <type>`, telling you exactly which pair of
  classes can never coexist so you know what to fix (an alternative pick, a
  different priority, or accepting the clash is unavoidable).
- **A weight of `0` fully disables that criterion** — no contribution to the
  score, and no warnings generated for it either. It's not just "very low
  priority," it's off.
