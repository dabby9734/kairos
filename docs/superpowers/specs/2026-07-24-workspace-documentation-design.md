# Workspace Documentation — Design

**Date:** 2026-07-24
**Status:** Approved for planning

## Goal

Documentation that onboards two audiences with no prior context:

1. **End users** — NUS friends who clone the repo to build their own timetable
   and ballot. They may not know NUS ballot mechanics precisely and are not
   Python developers.
2. **Developers** — anyone (including future maintainers and AI-assisted
   sessions) modifying the codebase: architecture, setup, tests, workflows.

## Structure

Four focused files, one clear audience per page. Plain markdown, readable on
GitHub, no doc-site tooling.

```
README.md                  # slim: what it is, 5-min quickstart, links into docs/
docs/
  user-guide.md            # everything an end user needs
  architecture.md          # how the code is shaped and why
  development.md           # dev setup, tests, workflows
CLAUDE.md                  # AI-session conventions + pointers (repo has none today)
```

Rejected alternatives: a finer-grained `docs/user/` + `docs/dev/` tree
(too much surface for ~2.5k lines of source); README + ARCHITECTURE.md only
(README balloons, dev setup gets squeezed).

## Page contents

### README.md (slimmed)

- What kairos is, in ~3 sentences.
- 5-minute quickstart: venv → `pip install -e .` → `kairos init <share-url>` →
  `kairos run` or `kairos tui`.
- "Where to go next" table linking the three docs pages.
- Content deeper than quickstart (TUI key reference, scoring explanation)
  moves out of the README into the user guide.

### docs/user-guide.md

In reading order:

1. **How NUS tutorial balloting works** — primer: balloted vs. non-balloted
   class types, the 20-slot global budget, why ranking order matters,
   snake/mirror ordering.
2. **Getting your modules in** — the NUSMods share URL, what `kairos init`
   prompts for (per-component difficulty, module priority) and why it matters.
3. **config.yaml reference** — every key: `preferences:` weights and
   thresholds, `balloted_types`, `top_n`, locks. Annotated real example.
4. **Running it** — `kairos run` output walkthrough: top-N arrangements with
   NUSMods links, ranked backups per balloted group, the ballot ranking.
5. **The TUI** — pane tour (Weights/Difficulty/Times/Priority tabs, Classes,
   timetable, ballot view), full key reference, locking semantics (pins the
   timeslot, not the class number; interchangeable twins stay ballotable),
   save/export/copy.
6. **FAQ / gotchas** — online `E-Learn_*` venues, lectures never balloted by
   default, Saturday sessions, resuming the TUI from a saved config.

### docs/architecture.md

1. **Design stance** — pure functional core with I/O at the edges; three
   entrypoints (init / run / tui) over one shared core.
2. **Data-flow diagram** (mermaid) — share URL → `api` (NUSMods fetch) →
   `model` (typed domain objects) → `search` (combination enumeration) →
   `scoring` → `ballot` / `provenance` → `output` or TUI.
3. **Module-by-module** — one paragraph per module (9 core + 4 TUI):
   responsibility, key types/functions, dependencies.
4. **Key invariants and decisions** — lock pins timeslot not class number;
   uncapped-provenance caching; dedupe by slot signature; ballot filled to
   20 entries; snake-order ballot construction.

### docs/development.md

- Dev environment: venv, `pip install -e ".[dev]"`.
- Running the tests; test file ↔ source module map.
- How the Textual pilot tests work (`asyncio_mode = auto`, driving the app
  headless).
- Workflow conventions: `plans/` micro-plans, `docs/superpowers/` specs and
  plans, commit style observed in git history.

### CLAUDE.md

Short. Project one-liner; commands (install / test / run); pointers into the
three docs pages; the conventions an AI session needs up front (pure-core
rule, test expectations, no-blink TUI constraint — Terminal.app ignores
SGR 5, use reverse video). Plus the upkeep rule below.

## Accuracy and verification

- **Source-of-truth rule:** every factual claim is read from the code at
  writing time, never from memory. The implementation plan pairs each doc
  section with the source files it must be checked against (config keys ←
  `config.py` + `config.yaml`; TUI keys ← `BINDINGS` in `kairos/tui/app.py`;
  CLI ← `cli.py`; scoring criteria ← `scoring.py`).
- **Commands are run before being documented:** install, `kairos --help`,
  `pytest`. Output excerpts in the user guide come from a real run against
  checked-in data.
- **Diagrams** are mermaid (renders on GitHub).

## Upkeep

CLAUDE.md instructs future sessions: when a change touches CLI flags, config
keys, TUI bindings, or scoring behavior, update the affected docs page in the
same change.

## Caveat

The working tree has uncommitted changes (`kairos/tui/app.py`,
`tests/test_tui_app.py` — timeslot-lock-picker work). During planning, check
whether that work is complete; document working-tree behavior if it is,
committed behavior only if it is not.

## Out of scope

- Doc-site generation (MkDocs etc.).
- PyPI packaging / release docs.
- CourseReg advisor feature docs (feature not built yet).
