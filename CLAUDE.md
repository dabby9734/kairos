# CLAUDE.md

Kairos — NUS timetable optimiser and tutorial-ballot ranker. Python 3.11+,
Textual TUI, pure-functional core.

## Commands
- install: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`
- test: `.venv/bin/pytest -q` (all tests must pass; async tests need no marker)
- run: `.venv/bin/kairos run` | TUI: `.venv/bin/kairos tui`

## Read first
- docs/architecture.md — data flow, module map, invariants (slot_sig vs
  footprint, locked vs fixed, two-pass scoring, uncapped provenance)
- docs/development.md — test layout, fixtures, conventions
- docs/user-guide.md — what users see; NUS ballot mechanics

## Hard rules
- model/scoring/search/ballot/provenance stay pure — no I/O in the core
  (exception: `search.prepare_groups` warns/exits on bad config)
- every sort needs an explicit deterministic tiebreak (usually class_no)
- user-facing errors: `raise SystemExit("error: ...")`
- no terminal blink (SGR 5); use reverse video — Terminal.app ignores blink
- BALLOT_CAP (kairos/ballot.py) is the single source for the 20-slot budget
- comments state constraints the code can't show, not narration

## Docs upkeep
Changing CLI flags, config keys, TUI bindings, or scoring? Update the affected
docs page (user-guide / architecture / development) in the same change.
