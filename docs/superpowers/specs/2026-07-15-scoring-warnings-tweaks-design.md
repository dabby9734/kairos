# Design: scoring & warnings tweaks

Three independent user-requested changes to how the optimiser scores timetables
and surfaces warnings in the TUI. Layered on top of the arrangement-cache work on
`feat/arrangement-cache`.

## Motivation

1. **Warnings clipped in the TUI.** The `#detail` panel is a non-scrolling
   `Static`; the breakdown + week grid eat the vertical space, so only the first
   few warnings are visible and the rest are silently cut off. (There is no count
   cap in code — it is purely a layout artifact.)
2. **Lunch is critical.** A day with no lunch break should hurt more. The current
   raw penalty is −1 per lunchless day; the user wants −2.
3. **Disabling components and impossible pairings.** Setting a weight to 0 already
   removes a component from the score, but its warnings still surface. And
   `same_day_pairing` warns (and effectively penalises) modules whose lecture and
   tutorial/lab are *never offered* on the same day — an unfixable "problem" that
   is noise.

## Feature 1 — Lunch penalty −2 per lunchless day

`optimiser/scoring.py`, `compute_raw`: change

```python
raw["lunch"] = -lunchless          # was
raw["lunch"] = -2 * lunchless      # now
```

The `lunch` weight slider (default 3) remains the tuning knob, so the effective
hit is −2 × weight (−6/day at the default). No config schema change — the −2 is a
fixed raw magnitude, not a new preference. `class_warnings`' lunch check is
binary per day (has-a-break / not) and is unchanged.

## Feature 2 — Dedicated scrollable warnings pane

`optimiser/tui/app.py`. Split the warnings out of the `#detail` `Static` into
their own scrollable pane so all warnings are reachable regardless of count.

Layout (`results` Vertical):

```
tt-list   (ListView)        height 25%
slot-list (ListView)        height 15%
detail    (Static)          height 1fr   breakdown + grid + bids + link
warnings  (VerticalScroll)  height 30%   border-title "Warnings", scrolls
```

- `compose()` adds a `VerticalScroll(id="warnings")` after `#detail`, containing a
  `Static(id="warnings-text")`. Give it a `border_title` of "Warnings".
- `_refresh_detail()` stops embedding `warning_block` in the `#detail` Group.
  Instead it updates `#warnings-text` separately: the joined warnings (dim
  yellow), or `✓ all criteria met` (dim green) when there are none.
- In **ballot mode** the warnings pane is emptied (`""`) — there are no
  per-arrangement warnings in that view, matching how `#detail` already switches
  to `render_snake`.
- `class_warnings` is called with the new `space=` argument (see Feature 3).

CSS: adjust the four `#results` children heights as above (currently `tt-list 30%`,
`slot-list 20%`, `detail 1fr`).

## Feature 3 — Disable via weight 0 + impossible-pairing suppression

### 3a. Weight 0 disables warnings

`optimiser/output.py`, `class_warnings`. Each of the four warning-producing blocks
is gated on its weight being non-zero:

```python
weights = config.preferences.weights
...
if weights.get("time_window", 0) != 0:      # time_window block
if weights.get("tough_days", 0) != 0:        # tough_days block
if weights.get("same_day_pairing", 0) != 0:  # same_day_pairing block
if weights.get("lunch", 0) != 0:             # lunch block
```

A component at weight 0 already contributes 0 to the score; now it also emits no
warnings. (`free_days` and `gaps` produce no warnings, so they need no guard.)
No new UI: the existing 0–10 weight slider is the disable control.

### 3b. Impossible pairings: no penalty, no warning

A **shared helper** keeps scoring and warnings mirrored — a suppressed warning
always corresponds to a scoring change.

`optimiser/scoring.py`:

```python
def pairing_impossibility(members) -> tuple[set, set]:
    """From space.members ((module, lesson_type) -> {footprint: [choices]}),
    find pairings that can never occur because the offered slots share no campus
    day. Returns (unpairable_modules, unpairable_slots):
      - unpairable_modules: modules WITH a lecture whose non-lecture slots can
        NONE fall on a lecture day. They can never earn the pairing bonus, so
        scoring counts them as satisfied (no penalty).
      - unpairable_slots: {(module, lesson_type)} non-lecture slots that can never
        reach a lecture day (covers a module whose TUT can pair but LAB cannot).
        Their same-day warning is suppressed.
    Days are taken over offered (campus, non-online) sessions; online sessions
    are excluded, matching the existing pairing criterion."""
```

Sketch:
- Build `lec_days: module -> set(campus days)` and
  `slot_days: (module, lesson_type) -> set(campus days)` from `members`.
- A non-lecture slot is *pairable* iff its module has a lecture and
  `slot_days ∩ lec_days[module]` is non-empty.
- `unpairable_slots` = non-lecture slots with a lecture but not pairable.
- `unpairable_modules` = modules that have a lecture and whose non-lecture slots
  are *all* unpairable.

**Scoring** — `compute_raw(choices, config, unpairable_modules=frozenset())`:

```python
raw["same_day_pairing"] = len(paired_modules | unpairable_modules)
```

`score_raw(space, config)` computes `unpairable_modules` once via
`pairing_impossibility(space.members)` and passes it to `compute_raw` for every
combo. `score_assignment(choices, config)` keeps the empty default — behaviour
unchanged for its (test-only) callers.

**Warnings** — `class_warnings(assignment, config, space=None)`: when `space` is
given, compute `(unpairable_modules, unpairable_slots)` from `space.members`; in
the `same_day_pairing` block, `continue` past any `(module, lesson_type)` in
`unpairable_slots`. When `space=None`, behaviour is exactly today's (safe default
for any non-TUI caller).

**TUI** — `tui/app.py` passes `space=self.state.space` into `class_warnings`.

### Why offered-days (`space.members`) and not clash-free combos

`members` holds every offered slot post-dedup — cheap (dozens of entries) and
available in both code paths. Using it means "pairable" = "offered on a shared
day". A slot offered on the lecture day but *always clashing* with it would be
called pairable (false positive) and keep its warning — the conservative
direction (we never wrongly suppress a genuinely fixable warning). Deriving from
all ~60k clash-free combos would remove that rare false positive at real cost;
not worth it.

### Ranking impact

An unpairable module contributes the same constant to every arrangement, so this
shifts absolute scores but **does not change arrangement ranking or ballot
order**. Existing tests that assert exact scores are updated where the corrected
behaviour legitimately moves a number, with a comment explaining why.

## Testing

- `test_scoring.py`: lunch penalty is −2/day; `pairing_impossibility` returns the
  right sets for a disjoint-days fixture; `compute_raw` counts an unpairable
  module as satisfied when `unpairable_modules` is passed, and is unchanged with
  the default.
- `test_output.py`: each component's warnings are suppressed at weight 0;
  impossible-pairing slots are suppressed when `space` is passed; a mixed module
  (TUT pairable, LAB not) suppresses only LAB; `space=None` is unchanged.
- `test_tui_app.py` / `test_tui_render.py`: the `#warnings` pane exists, populates
  from `class_warnings`, shows the all-clear message when empty, and is emptied in
  ballot mode.
- Full suite stays green (fixing legitimately-shifted score expectations).

## Out of scope

- No `lunch_penalty` config key (fixed −2).
- No explicit `disabled:` list (weight 0 is the disable mechanism).
- No "(off)" annotation on disabled components in the breakdown.
- No clash-aware (per-combo) pairability; offered-days is sufficient.
