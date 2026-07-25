# Design: `kairos advise <nusmods-link>` — generate coursereg.yaml interactively

Date: 2026-07-25
Status: approved

## Goal

Let a user go from an NUSMods share link to the CourseReg advisor in one
command. `kairos advise <link>` parses the link, asks a short series of
questions for everything the link can't tell us, writes `coursereg.yaml`,
and launches the advisor TUI immediately with the fresh profile.

`kairos advise` with no link is completely unchanged.

## What the link provides vs. what we ask

| Field | Source |
|---|---|
| `semester` | from the link path (`/timetable/sem-N/share`) — never prompted |
| `candidates` (course codes, in link order) | query-string keys — lesson picks are ignored |
| `seniority` | prompt: `year of study (1-4) [2]:` |
| `round` | prompt: `round (2/3) [2]:` |
| tier per course | prompt per course: `tier for CS2109S (core/major/ue) [major]:` |

Tier prompts accept the full words and `c`/`m`/`u` shorthands; Enter takes
the `major` default; invalid input reprompts. Seniority/round prompts use
validation loops in the existing `_prompt_difficulty` style.

## CLI surface

- The `advise` subparser gains an optional positional `share_url`
  (`nargs="?"`, same shape as `tui`'s).
- With a link: setup Q&A → write `coursereg.yaml` → print
  `wrote coursereg.yaml` → launch the advisor TUI.
- Without a link: `load_profile` as today.

## Flow

New `_advise_setup(url, config_path)` helper in `kairos/cli.py` (all I/O
stays in the CLI layer; `coursereg/model` stays pure):

1. If `config_path` exists → `coursereg.yaml already exists — overwrite?
   [y/N]`; anything but `y` raises `SystemExit("aborted")`, matching
   `cmd_init`. Overwriting discards any saved ranking.
2. `parse_share_url(url)` (existing) → `(semester, selections)`. If the
   semester is not 1 or 2 (special-term links, `sem-3`/`sem-4`), exit
   immediately — *before any prompts* — with
   `error: kairos advise models semesters 1 and 2 only — this link is for a
   special term`.
3. Prompt seniority, round, then tier per course in link order.
4. Assemble `{seniority, semester, round, candidates}` and pass through the
   existing pure `profile_from_dict` (free validation; `ranked` stays
   false), serialize with `profile_to_yaml`, write to `config_path`.
5. Return the `Profile`.

`cmd_advise` becomes: profile = `_advise_setup(...)` if a link was given
else `load_profile(...)`; then load history and run the TUI, unchanged.

## Error handling

No new error machinery. Malformed URLs and empty-module links reuse
`parse_share_url`'s existing `SystemExit` errors; field validation reuses
`profile_from_dict`'s. Ctrl-C / EOF during prompts behaves the same as
`kairos init` (no special handling).

## Testing

New tests in `tests/test_coursereg_cli.py`, following the monkeypatched
`builtins.input` precedent in `test_cli_init.py`:

- happy path: scripted answers → written YAML has expected semester,
  seniority, round, tiers, link-order candidates, `ranked: false`; the TUI
  is launched with the resulting profile (TUI monkeypatched out)
- all-defaults path: bare Enter everywhere → seniority 2, round 2, all
  `major`
- shorthand tiers: `c`/`m`/`u` map to `core`/`major`/`ue`
- invalid tier input reprompts, then accepts a valid answer
- existing file + declined overwrite → `SystemExit("aborted")`, file
  untouched
- special-term link (`sem-3`) fails before any prompt is issued
- no-link invocation unchanged (still routes through `load_profile`)

## Docs

- user-guide: advisor section — "Running it" gains the from-link flow;
  the `coursereg.yaml` reference notes the file can now be generated.
- CLAUDE.md: `advise` command line mentions the optional link.
- architecture.md: touch only if it enumerates CLI entry points.

## Decisions log

- Launch TUI immediately after writing the file (vs. init-style
  write-and-exit) — one command from link to advice.
- Per-course tier prompt with `major` default (vs. no default, or
  defaulting everything silently).
- Existing file → confirm overwrite (vs. merge or refuse); merge rejected
  as extra logic for a rare mid-semester case.
- Prompt seniority and round with defaults (vs. flags or omitting round);
  round stays togglable in the TUI with `r`.
- Approach: prompts in `cli.py` + existing pure builders (vs. a Textual
  first-run wizard, or a separate `advise-init` subcommand).
