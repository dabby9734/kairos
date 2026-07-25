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
  | `free_days` | whole free weekdays (more = better) | 6 |
  | `gaps` | idle hours between classes (fewer = better) | 1 |
  | `lunch` | days with no lunch break (fewer = better) | 7 |
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
(Priority tab); `b` toggles the ballot view, which pins a compact week grid above the ballot
list: arrow down the list and the grid highlights the timeslot that ballot
position bids for, either inverting the class's existing strip or drawing the
candidate strip beside it. A `●` in the left gutter marks the rows belonging to
the currently-selected timetable. Esc returns to the timetable view.; `s` saves the current tuning back
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
| ← / Esc | back to the Classes pane (or out of the ballot view) |
| `l` | lock/unlock the highlighted timeslot |
| `[` / `]` | move the highlighted module up/down in priority |
| `b` | toggle the ballot view |
| ↑ / ↓ (in the ballot view) | move the ballot cursor; the grid previews that slot |
| `s` | save config.yaml |
| `e` | export ballot.txt |
| `c` | copy the selected timetable's NUSMods link |
| `q` | quit |

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
