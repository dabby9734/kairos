# Developing kairos

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Requires Python 3.11+ (`pyproject.toml` sets `requires-python = ">=3.11"`).
Runtime deps are `requests`, `PyYAML`, and `textual`; the `dev` extra adds
`pytest` and `pytest-asyncio`. The package installs a console script,
`kairos = "kairos.cli:main"`, so once the editable install is done you can
also run `kairos ...` directly instead of `python -m kairos`.

## Running the tests

```bash
.venv/bin/pytest -q                                  # full suite: 260 passed in ~8s
.venv/bin/pytest tests/test_ballot.py -k snake -v     # narrowing example: 2 selected
```

`pyproject.toml` sets `asyncio_mode = "auto"` under `[tool.pytest.ini_options]`,
so async tests (the TUI ones) need no `@pytest.mark.asyncio` marker — any
`async def test_...` just works.

## Test suite layout

| File | Module under test | What it covers |
|---|---|---|
| `test_api.py` | `kairos/api.py` | Week normalisation, missing-semester error, group building from a fetched timetable, and the fetch/cache paths (fresh cache hit, stale-cache-on-network-failure fallback, no-cache-no-network error). |
| `test_ballot.py` | `kairos/ballot.py` | `ranked_options`/`all_options`/`fill_to_cap`/`snake`/`shortfall` — per-module capping, week/venue twin grouping, entangled twins staying separate, the 20-slot fill algorithm (best-remaining-score awarding, exhaustion, no-op cases), and provenance-aware ranking (ceiling/median tie-breaks, twin interleaving). |
| `test_cli_init.py` | `kairos/cli.py` (`init` subcommand) | Share-URL parsing (valid/empty/garbage), acad-year guessing, `cmd_init` writing `config.yaml` from a share URL, overwrite confirmation, and migrating non-balloted picks into `locked`. |
| `test_cli_run.py` | `kairos/cli.py` (`run` subcommand) | End-to-end `run` against a written config, flag placement after the subcommand, an init→run roundtrip, irreconcilable-module reporting, and that CLI-printed timetables match arrangement ranking. |
| `test_cli_tui.py` | `kairos/cli.py` (`tui` subcommand) | That `tui` builds `AppState` and hands off to `run_app`, exits cleanly with no source, and reports irreconcilable modules before launching. |
| `test_config.py` | `kairos/config.py` | `load_config` defaults and difficulty derivation, overrides, bad-difficulty/missing-file/empty-file/missing-key errors, `Config`-from-dict parity, and parsing/defaulting the `locked` key. |
| `test_model.py` | `kairos/model.py` | Time parsing/formatting, `slot_sig` ignoring class_no/venue/weeks, lesson-type abbreviation roundtrip, online detection, clash detection (same-day overlap, different day, back-to-back, disjoint weeks), `Choice` clash/footprint, and week labels. |
| `test_output.py` | `kairos/output.py` | Share-URL rendering, week-grid rendering (Saturday shown/omitted, unmapped lesson types), breakdown legend rendering, the full `class_warnings` rule set (time window, tough days, same-day pairing, lunch, weight-zero suppression, impossible-pairing suppression), and `snake_rows`/`snake_legend` — including that `render_snake`'s own text output is byte-identical to before the split, since it is written to `ballot.txt` and printed by `kairos run`. |
| `test_provenance.py` | `kairos/provenance.py` | `arrangement_provenance` — total/score-descending invariants, dedup of distinct scores, tier lookup for observed vs. interpolated scores, per-class cluster stats, ceiling-never-worse-than-median, agreement between by-arrangement and by-class views, and index alignment with `rank_arrangements` (including under ties). |
| `test_scoring.py` | `kairos/scoring.py` | `compute_raw`/`score_assignment` — a golden scoring matrix, each penalty component in isolation (time window, tough days, same-day pairing, free days, gaps, lunch), weight independence of the raw pass, weighted totals, and the pairing-impossibility helper (disjoint/pairable/mixed/online-ignoring cases). |
| `test_search.py` | `kairos/search.py` | `prepare_groups` (fixed/locked resolution, bad-key errors, migration, slot-twin locking), `search`/`enumerate_clashfree`/`rank_arrangements` (footprint dedup, clash detection, config independence, twin collapsing/entangling), and the `score_raw`/`weight_scored`/arrangement-structure helpers behind the raw-cache split. |
| `test_tui_app.py` | `kairos/tui/app.py` | `KairosApp` end-to-end via Textual's `App.run_test()` pilot: warnings styling, locking/unlocking timeslots, slider-driven reranking, priority reordering, ballot/detail views, config export, ballot export, clipboard copy, tab switching, and timeslot preview/flash rendering. |
| `test_tui_render.py` | `kairos/tui/render.py` | `render_week_rich` — module colour assignment, wide/narrow block labelling, online marking, Saturday handling, sub-hour and back-to-back layout, overlapping-class lanes, and preview/flash bar inversion. Also the `agenda=False` compact mode used by the ballot view. |
| `test_tui_startup.py` | `kairos/tui/startup.py` | `build_state` — building `AppState` from a share URL or a config file, no-source error, migrating non-balloted `fixed` entries to `locked` (including collision handling), and that migrated locks roundtrip through config and `prepare_groups`. |
| `test_tui_state.py` | `kairos/tui/state.py` | `AppState`/`normalize_difficulties` — enumeration/ranking on construction, weight/difficulty/preference changes and reranking, priority reordering without a full rescore, ballot helpers, lock/unlock of timeslots, config-YAML roundtrip, the raw-cache and arrangement-structure reuse/rebuild rules, provenance exposure, and `selectable_groups` filtering (including the "collapses to one slot_sig" exclusion). |
| `test_tui_widgets.py` | `kairos/tui/widgets.py` | `clamp` and `Slider` — value clamping/stepping and that the rendered label contains both name and value. |

(16 test files, one per row above. `ls tests/` also shows two non-test
entries: the `__init__.py` and `conftest.py` support files.)

`tests/conftest.py` defines shared fixtures. Four synthetic NUSMods-shaped
module JSON fixtures each pin one tricky shape, per their own docstrings:

- **`alpha_json`** (ALPHA) — one Mon+Wed lecture bundle plus three tutorials,
  two of which (`02`/`03`) share a footprint.
- **`beta_json`** (BETA) — two lecture groups (group `1` online) and two labs,
  where lab `L1` clashes with ALPHA's tutorial `01`.
- **`gamma_json`** (GAMMA) — two lecture classes at identical times, one
  physical and one online (the CS1231S shape): their `slot_sig`s differ only
  by `online`, so they're two distinct rows a day/time-only label can't tell
  apart.
- **`delta_json`** (DELTA) — one tutorial group with two classes at the same
  day/time/online-ness, differing only by venue; both collapse to a single
  `slot_sig`, the discriminating case for the "excluded from
  `selectable_groups`" filter.

Plus `config` (a full `Config`/`Preferences` fixture with `ALPHA`/`BETA`
modules) and `groups` (prepared `ChoiceGroup`s built from `alpha_json` +
`beta_json` under that config). Reach for these four fixtures before
inventing a new synthetic module — most shape-pinning needs are already
covered by one of them.

## TUI tests

`test_tui_app.py` drives the real `KairosApp` through Textual's pilot, no
terminal needed:

```python
app = KairosApp(state, tmp_path / "config.yaml")
async with app.run_test() as pilot:
    await pilot.pause()
    widget = app.query_one("#warnings-text", Static)
    assert "warn" in widget.classes         # a check is failing in timetable view
    await pilot.press("b")                  # drive the app like a user would
    await pilot.pause()
    assert "warn" not in widget.classes     # entering ballot view clears the styling
```

Build `AppState` from the shared fixtures (`AppState.from_parts(config,
groups)`), open the app under `run_test()`, drive it with `pilot.press(...)`
and `pilot.pause()` to let the event loop settle, then assert on widgets
fetched with `app.query_one(...)`. No `@pytest.mark.asyncio` needed —
`asyncio_mode = "auto"` covers it.

## Conventions

- **Pure core stays pure**: `model.py`, `scoring.py`, `search.py`,
  `ballot.py`, `provenance.py` do no network or file I/O — keep new logic
  there free of it too. (One existing exception: `search.prepare_groups`
  does `print()` a warning and can raise `SystemExit` on a bad config entry.)
- **Determinism**: every sort that could hit a tie gets an explicit
  tiebreak (usually `class_no`), and tests pin the resulting order — don't
  add an unstable sort.
- **User-facing errors**: raise `SystemExit(f"error: ...")` — see
  `kairos/api.py`, `kairos/config.py`, `kairos/cli.py`, `kairos/search.py`,
  `kairos/tui/startup.py` for the existing pattern.
- **Comments explain why, not what** — e.g. the comment at
  `kairos/tui/render.py:136` notes *"Deliberately not blink: Apple
  Terminal.app ignores SGR 5, which would leave flash mode with no signal at
  all there."*
- **Terminal compatibility**: no SGR blink for highlights; use reverse video
  instead (`kairos/output.py`, `kairos/tui/render.py` both do this
  deliberately — Terminal.app silently drops blink).
- **Commits**: conventional prefixes (`feat`/`fix`/`test`/`refactor`/`docs`),
  imperative mood — see `git log --oneline` for examples.

## Workflow artifacts (what the odd directories are)

- **`plans/`** — numbered, single-change micro-plans with a status table
  (`plans/README.md`; the numbered plan files themselves are local
  working-tree artifacts and may not be in a fresh clone); generated by an
  audit pass and executed in numbered
  order unless the README's dependency notes say a pair is independent (most
  are — only plans that touch the same files, like 003/004 there, must run
  sequentially).
- **`docs/superpowers/specs/`** and **`docs/superpowers/plans/`** — design
  specs and implementation plans from the brainstorm → spec → plan → execute
  pipeline this project's features go through before landing.
- **`.superpowers/`, `.cache/`, `data/cache/` (the default `--cache-dir`),
  `kairos.egg-info/`** — generated or scratch; not documentation, safe to
  ignore or delete.

## Docs upkeep

When a change touches CLI flags, config keys, TUI bindings, or scoring
behavior, update the affected page (`user-guide.md` / `architecture.md` /
`development.md`) in the same change.
