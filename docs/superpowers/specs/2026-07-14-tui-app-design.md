# NUS Course Optimiser — Live TUI App Design Spec

**Date:** 2026-07-14
**Status:** Draft for review
**Depends on:** the existing optimiser core (`config.py`, `api.py`, `search.py`,
`scoring.py`, `ballot.py`, `output.py`), shipped in the 2026-07-13 build.

## Purpose

A full-screen Textual TUI that turns the optimiser into an interactive app: load
your modules, tune scoring weights, difficulty ratings, time preferences, and
module priority with on-screen controls, and watch the ranked timetables and the
snake-order ballot re-rank live as you adjust. Export the tuned config, the
ballot list, and share links when satisfied.

It sits on top of the existing pure-logic core and adds a new presentation layer;
it does not change how scoring, search, or ballot generation work.

## Non-goals

- No change to `init` / `run` — they stay for scripted/non-interactive use.
- No new scoring criteria; the app only tunes existing knobs.
- No mouse-drag pixel sliders required; arrow-key adjustment is the contract
  (mouse works where Textual provides it, but is not required).
- No web/browser mode.

## Key architectural idea: enumerate once, rank many

Tuning a weight, difficulty, time preference, or priority changes only how
timetables are **scored/ordered**, never the **set** of clash-free timetables
(the search space depends solely on day/time/weeks/online, none of which the
controls touch). So the app enumerates the clash-free timetable set **once** at
startup, then re-scores and re-sorts that fixed set on every control change.
For ~5 modules the set is a few hundred entries; re-ranking is sub-millisecond,
giving instant live feedback without ever re-searching.

## Core refactor (`optimiser/search.py`)

Split the current `search()` into two, joined by a small value object:

- `EnumeratedSpace` — a frozen dataclass holding `combos: list[tuple[Choice, ...]]`
  (every clash-free combination of footprint representatives, one representative
  per footprint per group) and `members: dict[(module, lesson_type)][footprint]
  -> list[Choice]` (the footprint→choices map, config-independent). Both are what
  `rank` needs; neither depends on config.
- `enumerate_clashfree(groups: list[ChoiceGroup]) -> EnumeratedSpace` — the DFS
  enumeration with clash pruning and footprint dedup plus the members map. Run
  once.
- `rank(space: EnumeratedSpace, config: Config) -> SearchResult` — scores
  `space.combos` with the given config, builds the top-N heap, `best_by_footprint`,
  carries `space.members` and `evaluated`. Called on every live change.
- `search(groups, config)` becomes `rank(enumerate_clashfree(groups), config)`,
  preserving its current signature, return type, and behavior.

`SearchResult` is unchanged. All existing search/ballot/output tests continue to
pass without modification.

## New package: `optimiser/tui/`

```
optimiser/tui/
  __init__.py
  startup.py    resolve modules (URL or config.yaml) → fetch → build → prepare
                → enumerate_clashfree once → return AppState
  state.py      AppState (pure, no Textual): holds the enumerated set, live Config,
                and module groups; produces fresh SearchResults on retune
  widgets.py    Slider (custom, arrow-key adjustable, value-clamped) and small
                display widgets
  app.py        OptimiserApp: Textual layout, key bindings, wires control changes
                → AppState → re-render, and the export actions
```

`state.py` is the testable heart and has no Textual dependency.

### `startup.py`

- `build_state(share_url: str | None, config_path: Path, cache_dir: Path) -> AppState`
  - If `share_url` given: `parse_share_url` (reuse `cli.parse_share_url`), guess
    or accept acad year, fetch each module, `build_groups`, and construct a
    starting `Config` with difficulties defaulting to 3 and `DEFAULT_PREFERENCES`,
    fixed lectures taken from the URL (reuse the `cmd_init` fixed-detection rule).
  - Else if `config_path` exists: `load_config`, then fetch/build for its modules.
  - Else: `raise SystemExit` telling the user to pass a share URL.
  - Then `prepare_groups(groups, config)` and `enumerate_clashfree(prepared)` →
    the `EnumeratedSpace` stored on `AppState`.
  - Returns an `AppState` (or raises `SystemExit` on unreachable API with no cache,
    matching core behavior).

### `state.py`

```
class AppState:
    config: Config
    groups: list[ChoiceGroup]          # prepared groups (post-fixed)
    space: EnumeratedSpace             # combos + members, enumerated once
    result: SearchResult               # current ranking (cache of last retune)

    def retune(self) -> SearchResult   # rank(space, config); updates .result
    def reprioritise(self) -> None     # rebuild ballot only (priority changed)
    def is_empty(self) -> bool         # no clash-free timetables
    def irreconcilable(self)           # find_irreconcilable(groups) or None
    # mutation helpers used by the UI:
    def set_weight(name, value); set_difficulty(module, abbrev, value)
    def set_pref(name, value);   move_priority(module, delta)
    def to_config_yaml(self) -> dict   # same shape init writes
```

Ballot is produced via `ballot.ranked_options(result, config)` and
`ballot.snake(...)`; `reprioritise` re-runs only those (priority does not affect
timetable scores).

## Screen layout & interaction

Left panel: controls in a `TabbedContent` with four tabs — **Weights**,
**Difficulty**, **Times**, **Priority** — so only one group shows at a time.
Right panel: results, always visible so re-ranking is watched live. Footer shows
key bindings. Target width ~100 cols; Textual reflows narrower.

```
 OPTIMISER ─────────────────────────────────────────────────────────────
┌ Controls ──────────────────────┐┌ Timetables ── 252 shapes ───────────┐
│ [Weights] Diff  Times  Priority ││  #1  -19.0   ← selected             │
│ free_days       ══●═════  4     ││  #2  -19.0                          │
│ gaps            ●═══════  1     ││  #3  -20.0                          │
│ ...                             │├─ #1 breakdown ──────────────────────┤
│ ↑/↓ pick  ←/→ adjust            ││ free_days  +1 → +4  ...             │
│                                 │├─ #1 week ───────────────────────────┤
│                                 ││ Mon  MA1521 CS2030S      MA1522     │
│                                 ││ Tue  CS1231S     UTW1001X           │
└─────────────────────────────────┘└─────────────────────────────────────┘
 s save config   e export ballot   c copy link   b ballot   q quit
```

- `Tab`/click switches control group. `↑/↓` moves between controls in the tab;
  `←/→` adjusts the focused control (weights by 1; difficulty 1–5; time prefs by
  15 min for times, 1 for counts). Every adjustment triggers `retune()` and
  re-renders the right panel.
- **Weights** tab: six sliders (`free_days`, `gaps`, `lunch`,
  `same_day_pairing`, `time_window`, `tough_days`).
- **Difficulty** tab: one 1–5 slider per (module, lesson-type), listed and
  scrollable.
- **Times** tab: `earliest_start`, `latest_end`, `lunch_start`, `lunch_end`,
  `lunch_minutes`, `max_difficulty_per_day`.
- **Priority** tab: reorderable module list; `[` / `]` (or `←`/`→`) moves the
  focused module up/down; calls `reprioritise()`.
- Timetables list: `↑/↓` selects; selection drives the breakdown + week grid
  panes (via `output.render_breakdown` / `output.render_week`). Online lessons
  marked `~`, as in the existing renderer.
- `b` toggles the right panel between the timetables view and the **ballot view**
  (the snake list via `output.render_snake`), so you can review EduRec entries.

## Export actions

- `s` — write the current config to `config.yaml` (path from `--config`) via
  `yaml.safe_dump`, in the same shape `init` produces. Confirmation toast.
- `e` — write the snake ballot (`output.render_snake`) to `ballot.txt` (next to
  the config). Confirmation toast with the path.
- `c` — copy the selected timetable's NUSMods share URL (`output.share_url`) to
  the clipboard via Textual's built-in OSC-52 (`App.copy_to_clipboard`).
  Confirmation toast.

## CLI

Add a third subcommand to `optimiser/cli.py`:

- `optimiser tui [share_url] [--acad-year] [--config] [--cache-dir]`
  - With `share_url`: start fresh from the URL.
  - Without: load `config.yaml`.
  - Builds the `AppState` via `startup.build_state`, then runs `OptimiserApp`.
- `init` and `run` are unchanged.

## Dependencies

Adds `textual` (which pulls in `rich`) to runtime dependencies. No `pyperclip`
(clipboard via Textual OSC-52), no `textual-slider` (custom Slider widget).
Python ≥ 3.11 unchanged.

## Error handling

- API unreachable with no cache → `SystemExit` before the TUI launches (core
  behavior), or an in-app error screen if it happens mid-startup.
- No clash-free timetable → the app shows an error screen naming the
  irreconcilable group pair (`find_irreconcilable`) instead of the tuning view.
- No share URL and no `config.yaml` → clean `SystemExit` with guidance.
- A control tab with no items (e.g. no balloted difficulty rows) renders empty.
- Terminal narrower than target → Textual reflows; no hard failure.

## Testing

- **`search.py` refactor:** `search(groups, config)` equals
  `rank(enumerate_clashfree(groups), config)`; re-ranking one `EnumeratedSpace`
  with two different weight configs yields correctly different orderings; existing
  search tests stay green.
- **`state.py`:** `retune()` reorders top-N after a weight change; a difficulty
  bump changes `tough_days` and ranking; `reprioritise()` changes the ballot but
  not timetable scores; URL-seeded vs config-loaded state are equivalent;
  `to_config_yaml()` round-trips through `load_config`.
- **`startup.py`:** both entry paths with monkeypatched `fetch_module`; the
  empty-set / irreconcilable path raises/surfaces the right error.
- **`widgets.py`:** Slider value clamping and step logic (bounds, step size)
  without mounting an app.
- **`app.py`:** a few Textual `Pilot` tests (`app.run_test()`): adjusting a
  focused weight slider re-orders the timetables list; `b` shows the ballot view;
  `c` triggers the clipboard call. Wiring only — logic is covered above.

## Module structure summary

```
optimiser/
  search.py         refactored: enumerate_clashfree + rank; search() = wrapper
  tui/
    __init__.py
    startup.py
    state.py
    widgets.py
    app.py
  cli.py            + `tui` subcommand
tests/
  test_search.py    + enumerate/rank split tests
  test_tui_state.py
  test_tui_startup.py
  test_tui_widgets.py
  test_tui_app.py
```
