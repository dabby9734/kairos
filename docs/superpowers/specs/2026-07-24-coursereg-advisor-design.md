# CourseReg Advisor — Design

Date: 2026-07-24. Status: approved by user (section-by-section), pending
written-spec review.

## Problem

NUS CourseReg allocates *courses* by Priority Score = A × B × C, where A
(programme-requirement tier) and B (seniority) are fixed for a student in a
round and C (Rank 1–8) is the only live lever. Rank 1 is a scarce resource
with opportunity cost: spent on a course you would win anyway (undersubscribed)
or lose anyway (hopelessly oversubscribed), some other course ran with a lower
C than it could have. The advisor answers "where do I spend my high ranks" —
for Rounds 2 and 3, where ranking strategy actually matters.

This is a **new subsystem**, parallel to the timetable optimiser / tutorial
ballot. CourseReg (which courses you get) and Tutorial Registration (which
slots inside courses you have) are different NUS systems; nothing in the
existing search/scoring/ballot core is reused, but the architecture stance is:
pure core, I/O at the edges, deterministic everything.

## Decisions locked during brainstorm

| Question | Decision |
|---|---|
| Deadline | None — build it right; not scoped to the current R2 window |
| Deliverable | Interactive what-if TUI, opening with a computed suggested ranking |
| Data source | CourseRekt (courserekt.vercel.app) historical data only — runtime scrape + permanent cache. No NUS current-cycle PDF ingestion (site blocks scripted fetch; explicitly out of scope) |
| User model | Demand verdicts + coarse self-profile (seniority, per-course requirement tier). No full A×B×C simulation — point values are unpublished, everything stays ordinal |
| Rounds | R2 and R3 only |
| Population | Undergraduate (`ug`) data only |

## Stated assumptions (surface these in the TUI help, not just here)

1. **Independent per-course queues**: each course allocates by its own
   score-sorted queue; missing Rank 1 costs nothing on Rank 2. NUS does not
   publish the allocation algorithm; the "unmet minimum workload" tie-breaker
   hints at a workload-aware pass near the unit cap. Treated as a caveat, not
   modelled.
2. **Historical demand predicts this cycle ordinally**: CourseRekt is frozen
   at AY25/26 S2 (upstream archived 2026-01-10; no new scrapes will ever
   come). The advisor's verdicts are trend statements, not probabilities, and
   they can never see the current cycle's numbers.
3. **Same-semester history is the signal**: demand differs systematically
   between S1 and S2; only same-semester years feed verdicts.

## Architecture

```
coursereg.yaml ──┐
                 ├─→ coursereg/model.py    (records, profile — pure)
courserekt ──→ coursereg/fetch.py ──cache──→ coursereg/advisor.py (pure)
  (HTML)         data/coursereg/*.json          │
                                                ├─→ coursereg/tui/  (Textual)
cli.py: `kairos advise` ────────────────────────┘
```

New package `kairos/coursereg/`:

- **`model.py`** — pure. Frozen dataclasses: `DemandRecord(course, acad_year,
  semester, round, demand, vacancy)` (demand/vacancy `int | None`, vacancy may
  be the ∞ sentinel for unlimited); `Profile(seniority, round, tiers)` where
  `tiers: {course_code: "core"|"major"|"ue"}`; `Standing` enum (SAFE, LIKELY,
  CONTESTED, TOUGH, LONG_SHOT, NO_DATA). Config load/validate for
  `coursereg.yaml` (schema errors → `SystemExit`).
- **`fetch.py`** — the only network edge. `fetch_semester(year, sem)` POSTs to
  `courserekt.vercel.app/` (form fields `year`, `semester`, `type=ug`),
  returns raw HTML. `parse_history_html(html) -> list[DemandRecord]` is a
  separate pure function (stdlib `html.parser`; CourseRekt sentinels `NA` →
  `None`, unlimited vacancy → ∞ marker). `load_history(cache_dir,
  refetch=False)` orchestrates: per-semester JSON cache files in
  `data/coursereg/`, **no TTL — the source is frozen, a cache hit is always
  valid**; fetches all 10 semesters (AY21/22 S1 → AY25/26 S2) on first run.
- **`advisor.py`** — pure. Aggregation, verdicts, nudges, suggested ranking,
  reasoning strings, leverage warnings (details below).
- **`tui/`** — `AdvisorState` (mutable session object, no Textual imports) +
  the Textual `App`. Mirrors the existing `tui/state.py` / `tui/app.py`
  split.
- **`cli.py`** — new subparser `advise` with `--config` (default
  `coursereg.yaml`), `--cache-dir` (default `data/coursereg`), `--refetch`.
  Launches the TUI directly; no print mode.

Nothing under the existing `kairos/{model,scoring,search,ballot,provenance}.py`
changes.

## Config: `coursereg.yaml`

```yaml
seniority: 2            # year of study 1-4 (B tier, coarse)
round: 2                # 2 or 3 — the round being planned
candidates:
  CS2109S: major        # course code: requirement tier for YOU
  GEH1049: ue           #   one of: core | major | ue
  IS2218: ue
```

Separate file from the timetable's `config.yaml` — different question,
different lifecycle. More than 8 candidates is allowed; only 8 get ranks.
Missing file → `SystemExit` that prints a filled-in template. No init wizard.

## Core model

**Aggregation.** For target round r, a course's history = subscription ratio
(demand ÷ vacancy) in each past same-semester round-r report. `NA` cells and
absent years are skipped, never imputed. Ratio with zero vacancy and positive
demand is treated as ∞ (maximally oversubscribed); unlimited-vacancy rows as
ratio 0.

**Base verdict** (3 bands) from same-semester ratios, thresholds as named
module constants with justifying comments (single place to tune):

- SAFE — median ratio comfortably < 1 and no oversubscription in recent
  same-semester years ("recent" = the last 3 same-semester years with data,
  itself one of the named constants).
- CONTESTED — ratio around 1, or oversubscribed in some but not all years.
- LONG SHOT — persistently oversubscribed by a wide margin.

**Profile nudges** — ordinal, each ±1 band, total movement capped at one band:

| Signal | Direction |
|---|---|
| tier = core | toward safe (your A beats the UE crowd in this queue) |
| tier = ue | toward long-shot |
| tier = major | neutral |
| seniority Y3/Y4, only on `ue`-tier candidates | toward safe (on GE/UE everyone's A is bottom; B decides) |
| seniority Y1, only on `ue`-tier candidates | toward long-shot |

Result: 5-band `Standing` (SAFE / LIKELY / CONTESTED / TOUGH / LONG_SHOT),
plus NO_DATA when the course has no same-semester round-r history at all
(new courses are normal, not an error). Every standing carries a generated
one-line reasoning string (house style: the exact wording the TUI shows,
defined once, like `COMPONENT_LEGEND`).

**Suggested ranking** (deterministic, assumption 1 above): leverage order —

1. Contested band, most knife-edge first: TOUGH, CONTESTED, LIKELY.
2. NO_DATA (maximum uncertainty; the user must place these deliberately —
   always flagged in the summary strip).
3. LONG_SHOT.
4. SAFE last (they win at any rank).

Ties broken by course code (house rule: every sort has an explicit
deterministic tiebreak). With > 8 candidates the top 8 by this order get
ranks 1–8; the rest are listed unranked.

**Leverage warnings** (recomputed on every change): SAFE course in a top rank
("wasted leverage"), contested-band course unranked or in a bottom rank,
NO_DATA course anywhere (informational).

## TUI

One screen, two panes + summary strip + footer:

```
┌─ Ranking ──────────────────┬─ CS2109S — CONTESTED ────────────────┐
│ 1  CS2109S  CONTESTED  maj │ round 2, S1 history:                 │
│ 2  IS2218   TOUGH      ue  │   AY25/26  231 / 180  1.28  over     │
│ 3  GEH1049  LIKELY     ue  │   AY24/25  190 / 200  0.95           │
│ 4  GESS1025 SAFE       ue  │   AY23/24  210 / 160  1.31  over     │
│ unranked: LAG2201          │   (other semester dimmed, context)   │
│                            │ reasoning: oversubscribed 2 of 3     │
├─ 2 contested in top ranks; │ recent S1s; major-tier A helps       │
│  Rank 4 holds a SAFE course ──────────────────────────────────────┤
│ j/k move · J/K reorder · a advisor order · t tier · r round · s save │
└───────────────────────────────────────────────────────────────────┘
```

- Left: candidates in current rank order (opens in the advisor's suggested
  order) with standing badge and tier. Selection = reverse video; **no blink**
  (Terminal.app ignores SGR 5 — house rule).
- Right: highlighted course's dossier — per-year demand/vacancy/ratio for the
  chosen round, same-semester years prominent, other semester dimmed, then the
  reasoning line.
- Summary strip: leverage warnings.
- Keys: `j/k` navigate · `J/K` move course · `a` restore advisor order ·
  `t` cycle tier of highlighted course (core → major → ue; verdicts and
  warnings recompute live) · `r` toggle round 2/3 (dossier + verdicts + the
  advisor baseline recompute) · `s` save current ranking, tier edits, and the
  currently selected round back to `coursereg.yaml` (rank order = the
  `candidates` mapping's key order, which YAML preserves on load and the
  writer emits unsorted; exact inverse of the loader, like
  `to_config_yaml()`) · `q` quit.
- TUI help/footer surfaces assumption 1's caveat in one line.

## Error handling

- Missing or invalid `coursereg.yaml` → `SystemExit("error: ...")` printing a
  filled-in template.
- Site unreachable with no cache → `SystemExit` naming the cache dir (a copy
  of a friend's `data/coursereg/` works — the data is identical and frozen).
- HTML that doesn't match the expected structure → `SystemExit` saying the
  site may have changed; suggest `--refetch`.
- Candidate with no history → NO_DATA standing, never an error.

## Testing

- **Parser**: golden-file test — trimmed real CourseRekt HTML excerpt as a
  checked-in fixture; `parse_history_html` asserted against known records. No
  network in any test (HTTP call and parse are separate functions).
- **Core**: synthetic histories per band; nudge table (each row, cap at ±1);
  ranking determinism incl. course-code tiebreak; > 8 candidates; NO_DATA
  placement; ratio edge cases (zero vacancy, unlimited vacancy, all-NA).
- **TUI**: Textual pilot tests — J/K reorder, `t` recompute, `r` toggle,
  `a` restore, `s` round-trips `coursereg.yaml`, warnings strip content.
- Existing 260 tests untouched and passing.

## Out of scope (explicit)

- NUS current-cycle demand PDFs (Imperva-blocked for scripts) — revisit only
  if a manual-download flow is ever wanted.
- Round 1 (protected categories) and graduate/CPE populations.
- Probability estimates, expected-value arithmetic, or any pretence of
  computing a real Priority Score (point values unpublished).
- Integration with the timetable optimiser's config or TUI.

## Docs upkeep (binding on implementation)

New CLI subcommand, new config file, new TUI: user-guide, architecture, and
development pages plus CLAUDE.md must be updated in the same change set, per
the repo's docs-upkeep rule.
