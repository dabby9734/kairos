# User-Selected Acceptable Timeslots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user restrict each balloted group to a chosen set of timeslots, so the ballot and the timetable search draw only from slots they've said yes to.

**Architecture:** A new `accept` config key generalises `locked` from one timeslot to a set. `search.prepare_groups` gains a branch between `locked` and the unrestricted fallback, so the restriction lands at space construction and every consumer — search, scoring, provenance, ballot, TUI — inherits it. `ballot.py` is not touched. The TUI's Timeslots pane gains an `a` toggle routed through the existing lock-rollback guard.

**Tech Stack:** Python 3.11+, Textual, PyYAML, pytest (async tests need no marker).

## Global Constraints

Copied verbatim from `CLAUDE.md`; every task's requirements implicitly include these.

- `model/scoring/search/ballot/provenance` stay pure — no I/O in the core (exception: `search.prepare_groups` warns/exits on bad config).
- Every sort needs an explicit deterministic tiebreak (usually `class_no`).
- User-facing errors: `raise SystemExit("error: ...")`.
- No terminal blink (SGR 5); use reverse video — Terminal.app ignores blink.
- `BALLOT_CAP` (`kairos/ballot.py`) is the single source for the 20-slot budget.
- Comments state constraints the code can't show, not narration.
- Changing CLI flags, config keys, TUI bindings, or scoring? Update the affected docs page in the same change (Task 4 does this).
- All tests must pass: `.venv/bin/pytest -q`.

Design spec: `docs/superpowers/specs/2026-07-25-accepted-timeslots-design.md`.

**This feature deliberately does NOT deconflict the ballot.** Two accepted slots from different groups may clash, and the ballot may list both. That is the user's call. Do not add clash filtering anywhere.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `kairos/config.py` | `Config.accept` field + parsing | 1 |
| `kairos/tui/state.py` | `to_config_yaml` persists `accept`; accept toggle API | 1, 3 |
| `kairos/search.py` | `prepare_groups` accept branch | 2 |
| `kairos/tui/app.py` | `a` binding, Timeslots marker, shortfall wording | 3 |
| `kairos/cli.py` | shortfall wording | 3 |
| `tests/test_config.py`, `test_search.py`, `test_tui_state.py`, `test_tui_app.py` | coverage | 1-3 |
| `docs/user-guide.md`, `architecture.md`, `development.md` | documentation | 4 |

---

### Task 1: `accept` config key

**Files:**
- Modify: `kairos/config.py:52` (Config fields), `:118` (`config_from_dict` return)
- Modify: `kairos/tui/state.py:319` (`to_config_yaml`)
- Test: `tests/test_config.py`, `tests/test_tui_state.py`

**Interfaces:**
- Produces: `Config.accept: dict` — `code -> dict[abbrev, list[class_no]]`, defaulting to `{}`. Parsed from the `accept` YAML key. Persisted by `to_config_yaml` under `"accept"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py` (the `load_config`, `write` and `BASE` helpers already exist there — see `test_load_config_parses_locked` at line 96 for the exact idiom):

```python
def test_load_config_parses_accept(tmp_path):
    cfg = load_config(write(tmp_path, BASE + "\naccept:\n  ALPHA: {TUT: ['02', '03']}\n"))
    assert cfg.accept == {"ALPHA": {"TUT": ["02", "03"]}}


def test_load_config_defaults_accept_empty(tmp_path):
    cfg = load_config(write(tmp_path, BASE))
    assert cfg.accept == {}
```

Add to `tests/test_tui_state.py` (mirroring `test_locked_roundtrips_through_config` at line 179):

```python
def test_accept_roundtrips_through_config(tmp_path, state):
    from kairos.config import config_from_dict

    state.config.accept = {"ALPHA": {"TUT": ["02", "03"]}}
    data = state.to_config_yaml()
    assert data["accept"] == {"ALPHA": {"TUT": ["02", "03"]}}
    assert config_from_dict(data).accept == {"ALPHA": {"TUT": ["02", "03"]}}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py tests/test_tui_state.py -k accept -q`

Expected: FAIL with `AttributeError: 'Config' object has no attribute 'accept'`.

- [ ] **Step 3: Add the field**

In `kairos/config.py`, add immediately after the `locked` field (line 52):

```python
    # code -> dict[abbrev, list[class_no]]. Each class number designates its
    # TIMESLOT, like `locked`; an absent or empty entry means every slot is
    # acceptable, so a forgotten group can never submit nothing.
    accept: dict = field(default_factory=dict)
```

Place it before `migrated_from_fixed` so the existing comment on that field still reads against it.

- [ ] **Step 4: Parse it**

In `kairos/config.py`'s `config_from_dict` return (line 118), add beside `locked`:

```python
        accept=data.get("accept") or {},
```

- [ ] **Step 5: Persist it**

In `kairos/tui/state.py`'s `to_config_yaml` (line 319), add after the `"locked"` entry:

```python
            "accept": self.config.accept,
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/pytest tests/test_config.py tests/test_tui_state.py -q`

Expected: PASS, including the pre-existing config round-trip tests.

- [ ] **Step 7: Commit**

```bash
git add kairos/config.py kairos/tui/state.py tests/test_config.py tests/test_tui_state.py
git commit -m "feat: add the accept config key"
```

---

### Task 2: `prepare_groups` restricts to accepted timeslots

**Files:**
- Modify: `kairos/search.py:19-58` (`prepare_groups`)
- Test: `tests/test_search.py`

**Interfaces:**
- Consumes: `Config.accept` (Task 1).
- Produces: no signature change. `prepare_groups(groups, config)` now restricts a group to every choice whose `slot_sig` matches one named in `config.accept`, when that group has a non-empty accept list and is not already covered by `fixed` or `locked`.

Fixture facts you can rely on (see `tests/test_search.py:57-64`): `ALPHA` `Tutorial` has class `01` on Monday and classes `02`/`03` sharing the Tuesday 0900 slot.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_search.py` (`prepare_groups`, `build_groups`, `semester_timetable`, `pytest` and the `config`/`alpha_json`/`beta_json` fixtures are already imported there):

```python
def test_prepare_groups_accept_restricts_to_named_slots(alpha_json, config):
    config.fixed = {}
    config.accept = {"ALPHA": {"TUT": ["01"]}}
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    prepared = prepare_groups(gs, config)
    tut = next(g for g in prepared if g.key == ("ALPHA", "Tutorial"))
    assert [c.class_no for c in tut.choices] == ["01"]  # Tue slot dropped


def test_prepare_groups_accept_keeps_slot_twins(alpha_json, config):
    # 02 designates the Tue 0900 SLOT, so its twin 03 comes along uninvited-but-correct
    config.fixed = {}
    config.accept = {"ALPHA": {"TUT": ["02"]}}
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    prepared = prepare_groups(gs, config)
    tut = next(g for g in prepared if g.key == ("ALPHA", "Tutorial"))
    assert sorted(c.class_no for c in tut.choices) == ["02", "03"]


def test_prepare_groups_accept_unions_multiple_slots(alpha_json, config):
    config.fixed = {}
    config.accept = {"ALPHA": {"TUT": ["01", "02"]}}
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    prepared = prepare_groups(gs, config)
    tut = next(g for g in prepared if g.key == ("ALPHA", "Tutorial"))
    assert sorted(c.class_no for c in tut.choices) == ["01", "02", "03"]


def test_prepare_groups_bad_accept_names_accept(alpha_json, config):
    config.fixed = {}
    config.accept = {"ALPHA": {"TUT": ["99"]}}
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    with pytest.raises(SystemExit, match="config 'accept'"):
        prepare_groups(gs, config)


def test_prepare_groups_empty_accept_means_all(alpha_json, config):
    # An empty list is "no restriction", NOT "accept nothing" — a stray `TUT: []`
    # must never empty the space.
    config.fixed = {}
    config.accept = {"ALPHA": {"TUT": []}}
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    prepared = prepare_groups(gs, config)
    tut = next(g for g in prepared if g.key == ("ALPHA", "Tutorial"))
    assert sorted(c.class_no for c in tut.choices) == ["01", "02", "03"]


def test_prepare_groups_locked_beats_accept(alpha_json, config):
    config.fixed = {}
    config.locked = {"ALPHA": {"TUT": "02"}}
    config.accept = {"ALPHA": {"TUT": ["01"]}}
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    prepared = prepare_groups(gs, config)
    tut = next(g for g in prepared if g.key == ("ALPHA", "Tutorial"))
    assert sorted(c.class_no for c in tut.choices) == ["02", "03"]  # locked wins
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_search.py -k accept -q`

Expected: FAIL — `AttributeError` on `config.accept` is already gone after Task 1, so these fail on the assertions instead (the accept lists are currently ignored, so every group keeps all three classes).

- [ ] **Step 3: Add the branch**

In `kairos/search.py`, insert between the `locked` branch's `continue` (line 51) and the balloted-types warning (line 52):

```python
        accepted = (config.accept.get(group.module) or {}).get(abbrev)
        if accepted:
            # Each number designates its SLOT, as `locked` does, so venue/week
            # twins at an accepted slot stay available for the ballot. Resolved
            # one number at a time rather than by set membership: an unknown
            # number must raise, not silently narrow the space differently than
            # the user asked.
            sigs = set()
            for number in accepted:
                anchor = next(
                    (c for c in group.choices if c.class_no == str(number)), None
                )
                if anchor is None:
                    raise SystemExit(
                        f"error: {group.module} {abbrev} class {number} "
                        "(config 'accept') does not exist"
                    )
                sigs.add(anchor.slot_sig)
            chosen = [c for c in group.choices if c.slot_sig in sigs]
            prepared.append(ChoiceGroup(group.module, group.lesson_type, chosen))
            continue
```

The `if accepted:` guard makes an empty list equivalent to an absent key.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/test_search.py -q`

Expected: PASS, including every existing `fixed`/`locked` precedence test.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`

Expected: PASS. `accept` defaults to `{}` everywhere, so no existing behaviour moves.

- [ ] **Step 6: Commit**

```bash
git add kairos/search.py tests/test_search.py
git commit -m "feat: prepare_groups restricts balloted groups to accepted timeslots"
```

---

### Task 3: TUI accept toggle

**Files:**
- Modify: `kairos/tui/state.py` (accept API, near the lock methods at 168-207)
- Modify: `kairos/tui/app.py` (BINDINGS ~116-132, `_populate_timeslots` ~238-260, new action, shortfall wording ~475)
- Modify: `kairos/cli.py:169-175` (shortfall wording)
- Test: `tests/test_tui_state.py`, `tests/test_tui_app.py`

**Interfaces:**
- Consumes: `Config.accept` (Task 1), `prepare_groups`' accept branch (Task 2), `state._apply_locked_change(mutate) -> bool` (`state.py:171`, snapshots/rebuilds/rolls back on empty), `state.offered_timeslots(module, lesson_type)` returning rows with keys `sig`/`class_nos`/`sessions`/`rep`/`venues`.
- Produces:
  - `state.accepted_sigs(module, lesson_type) -> frozenset | None` — the accepted `slot_sig`s, or `None` when the group is unrestricted.
  - `state.toggle_accept(module, abbrev, lesson_type, class_no) -> bool` — flips one timeslot's membership, rebuilds, rolls back and returns `False` if the result has no clash-free timetable.

**Toggle semantics (important — read before implementing).** An unrestricted group means *every* slot is acceptable. So the first `a` press must **remove** the highlighted slot, materialising "all slots except this one" — not restrict the group to the single highlighted slot, which would silently behave like a lock. Subsequent presses add or remove individual slots.

- [ ] **Step 1: Write the failing state tests**

Add to `tests/test_tui_state.py` (the `state` and `config` fixtures already exist; see `test_set_lock_shrinks_and_keeps_twins` at line 131 for the idiom):

```python
def test_first_toggle_accept_removes_only_that_slot(state):
    # Unrestricted means all-acceptable, so the first press REJECTS one slot
    # rather than restricting to it.
    assert state.accepted_sigs("ALPHA", "Tutorial") is None
    assert state.toggle_accept("ALPHA", "TUT", "Tutorial", "01") is True
    accepted = state.accepted_sigs("ALPHA", "Tutorial")
    assert accepted is not None
    assert state.config.accept["ALPHA"]["TUT"] == ["02"]  # 01 gone, Tue slot kept


def test_toggle_accept_is_reversible(state):
    before = len(state.space.combos)
    state.toggle_accept("ALPHA", "TUT", "Tutorial", "01")
    assert len(state.space.combos) < before
    state.toggle_accept("ALPHA", "TUT", "Tutorial", "01")   # put it back
    assert state.accepted_sigs("ALPHA", "Tutorial") is None
    assert len(state.space.combos) == before


def test_toggle_accept_rejecting_everything_rolls_back(state):
    state.toggle_accept("ALPHA", "TUT", "Tutorial", "01")
    before = len(state.space.combos)
    snapshot = {m: dict(v) for m, v in state.config.accept.items()}
    # rejecting the last remaining slot would empty the space
    assert state.toggle_accept("ALPHA", "TUT", "Tutorial", "02") is False
    assert state.config.accept == snapshot       # config restored
    assert len(state.space.combos) == before     # space restored
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_tui_state.py -k accept -q`

Expected: FAIL with `AttributeError: 'AppState' object has no attribute 'accepted_sigs'`.

- [ ] **Step 3: Implement the state API**

In `kairos/tui/state.py`, add after `clear_lock` (which ends at line 207):

```python
    def accepted_sigs(self, module: str, lesson_type: str):
        """The slot_sigs this group is restricted to, or None when unrestricted.

        None and "every slot listed" are behaviourally identical; None is the
        unrestricted representation, so a group the user never touched carries
        no config entry."""
        abbrev = LESSON_ABBREV.get(lesson_type, lesson_type)
        numbers = (self.config.accept.get(module) or {}).get(abbrev)
        if not numbers:
            return None
        wanted = {str(n) for n in numbers}
        return frozenset(
            row["sig"]
            for row in self.offered_timeslots(module, lesson_type)
            if wanted & set(row["class_nos"])
        )

    def toggle_accept(self, module: str, abbrev: str, lesson_type: str, class_no: str) -> bool:
        """Flip one timeslot's membership of the accepted set, rebuilding the
        space and rolling back if nothing clash-free survives.

        An unrestricted group is materialised as every slot MINUS this one: the
        first press rejects, because "unrestricted" already means everything is
        acceptable and restricting to the highlighted slot would silently
        duplicate `l`."""
        rows = self.offered_timeslots(module, lesson_type)
        target = next((r for r in rows if class_no in r["class_nos"]), None)
        if target is None:
            return False
        current = (self.config.accept.get(module) or {}).get(abbrev)
        if current:
            wanted = {str(n) for n in current}
            keep = [r for r in rows if wanted & set(r["class_nos"])]
        else:
            keep = list(rows)
        if any(r["sig"] == target["sig"] for r in keep):
            keep = [r for r in keep if r["sig"] != target["sig"]]
        else:
            keep.append(target)
        # One representative class_no per kept slot; sorted for a deterministic
        # config file (M4: every ordering needs an explicit tiebreak).
        numbers = sorted(min(r["class_nos"]) for r in keep)

        def mutate():
            if numbers and len(numbers) < len(rows):
                self.config.accept.setdefault(module, {})[abbrev] = numbers
            else:
                slots = self.config.accept.get(module)
                if slots is not None:
                    slots.pop(abbrev, None)
                    if not slots:
                        self.config.accept.pop(module, None)

        return self._apply_accept_change(mutate)
```

Note `numbers and len(numbers) < len(rows)`: keeping every slot is written back as
*unrestricted* (entry removed), so accepting everything and never touching the
group produce the same config.

- [ ] **Step 4: Add the rollback guard**

`_apply_locked_change` (`state.py:171-193`) snapshots `config.locked` only. Read it, then add a sibling `_apply_accept_change` that snapshots `config.accept` the same way and is otherwise identical (same rebuild, same commit-or-restore of `(groups, space, result, provenance, arrangements, unpairable_slots)` — copy whatever tuple that method actually restores; do not guess).

If the two methods end up differing only in which config dict they snapshot, factor the shared body into one helper taking the dict name, rather than duplicating it.

- [ ] **Step 5: Run the state tests**

Run: `.venv/bin/pytest tests/test_tui_state.py -q`

Expected: PASS, including every existing lock test.

- [ ] **Step 6: Write the failing app test**

Add to `tests/test_tui_app.py` (the `state` fixture and `ListView` import already exist):

```python
async def test_accept_toggle_marks_timeslot_and_shrinks_space(state, tmp_path):
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#slot-list", ListView).index = 0
        await pilot.pause()
        await pilot.press("right")            # focus the Timeslots pane
        await pilot.pause()
        before = len(app.state.space.combos)
        await pilot.press("a")
        await pilot.pause()
        assert len(app.state.space.combos) < before
        labels = [
            str(item.query_one("Label").content)
            for item in app.query_one("#timeslot-list", ListView).children
        ]
        assert any(line.startswith("✗") for line in labels)   # rejected slot marked
```

- [ ] **Step 7: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_tui_app.py -k accept -q`

Expected: FAIL — `a` is unbound, so the space is unchanged.

- [ ] **Step 8: Bind `a` and mark rejected rows**

In `kairos/tui/app.py`:

1. Add to `BINDINGS`, after the `("l", "toggle_lock", "lock slot")` entry:

```python
        ("a", "toggle_accept", "accept slot"),
```

2. Add the action, next to `action_toggle_lock`:

```python
    def action_toggle_accept(self) -> None:
        tlist = self.query_one("#timeslot-list", ListView)
        if (self._current_class is None or tlist.index is None
                or not (0 <= tlist.index < len(self._timeslots))):
            return
        module, lesson_type = self._current_class
        abbrev = LESSON_ABBREV.get(lesson_type, lesson_type)
        row = self._timeslots[tlist.index]
        if not self.state.toggle_accept(module, abbrev, lesson_type, row["rep"].class_no):
            self.notify(f"rejecting {module} {abbrev} at that slot leaves no clash-free timetable")
            return
        self._refresh_results()
```

3. In `_populate_timeslots`, mark rejected rows. It currently builds `mark` from
the locked sig; extend it so a row excluded by a non-`None` `accepted_sigs`
carries `✗`. Lock and reject are mutually exclusive in practice (a locked group
takes precedence in `prepare_groups`), so one marker column suffices:

```python
                accepted = self.state.accepted_sigs(row.module, row.lesson_type)
                ...
                for i, slot in enumerate(self._timeslots):
                    if slot["sig"] == locked:
                        mark = "🔒 "
                    elif accepted is not None and slot["sig"] not in accepted:
                        mark = "✗ "
                    else:
                        mark = ""
```

Re-locate the surrounding loop by content — line numbers will have shifted.

- [ ] **Step 9: Fix the shortfall wording**

Both messages currently assert the cause is exhaustion, which is wrong when the
user narrowed the pool themselves.

`kairos/cli.py:170-175` — replace `"no further clash-free options exist. "` with:

```python
            "no further clash-free options exist (or your `accept` lists exclude them). "
```

`kairos/tui/app.py` `action_export_ballot` — replace the
`"(no further clash-free options)"` tail with:

```python
                "(no further clash-free options, or narrowed by your accepted slots)",
```

- [ ] **Step 10: Run the full suite**

Run: `.venv/bin/pytest -q`

Expected: PASS.

- [ ] **Step 11: Drive it headlessly**

The plan's author verified the previous feature this way; do the same here.
Write a throwaway test that presses `right` then `a`, prints the Timeslots
labels and `len(state.space.combos)` before/after, run it with `-s`, confirm the
`✗` appears and the space shrinks, then **delete the file** (do not commit it).

- [ ] **Step 12: Commit**

```bash
git add kairos/tui/state.py kairos/tui/app.py kairos/cli.py tests/test_tui_state.py tests/test_tui_app.py
git commit -m "feat: toggle accepted timeslots from the TUI"
```

---

### Task 4: Documentation

Required by the docs-upkeep rule in `CLAUDE.md`: a config key and a TUI binding changed.

**Files:**
- Modify: `docs/user-guide.md` (config reference ~97-219, TUI section ~330-366)
- Modify: `docs/architecture.md` (the `search.py` / `prepare_groups` description)
- Modify: `docs/development.md` (test-layout table)

**Interfaces:** Consumes everything from Tasks 1-3. Produces no code.

- [ ] **Step 1: Document the config key**

In `docs/user-guide.md`'s `config.yaml` reference, add an `accept` entry beside
`locked`. It must state:

- shape: `accept: {MODULE: {ABBREV: [class_no, ...]}}`
- each class number designates its **timeslot**, so venue/week twins come along
- absent or empty means **every slot is acceptable**, never "none"
- precedence: `fixed` > `locked` > `accept` > all
- it narrows the **timetable search too**, not only the ballot
- **it does not deconflict**: two accepted slots in different modules can still
  overlap, and the ballot may list both — resolving that is the user's call

- [ ] **Step 2: Document the binding**

In `docs/user-guide.md`'s TUI section, describe `a` in the Timeslots pane
(toggle whether a slot is acceptable; `✗` marks rejected ones; the first press
on an untouched group rejects that one slot rather than restricting to it), and
that kairos refuses a toggle leaving no clash-free timetable. Add to the
keybinding table, after the `l` row:

```
| `a` | accept/reject the highlighted timeslot |
```

- [ ] **Step 3: Update architecture.md**

Find the `prepare_groups` description and update the precedence cascade to four
tiers (`fixed` > `locked` > `accept` > all), noting that because the restriction
lands at space construction, every downstream consumer inherits it and
`ballot.py` needs no knowledge of the feature.

- [ ] **Step 4: Update development.md**

Add the new coverage to the `test_search.py` and `test_tui_state.py` rows:
accept slot-union/twin semantics, the unknown-number error, empty-list-means-all,
`locked`-beats-`accept` precedence, and the accept rollback guard.

- [ ] **Step 5: Verify docs match code**

Run: `grep -rn "accept" docs/user-guide.md docs/architecture.md docs/development.md`

Confirm every claim matches what shipped — in particular the precedence order
and the first-press-rejects semantics.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add docs/user-guide.md docs/architecture.md docs/development.md
git commit -m "docs: document accepted timeslots"
```

---

## Self-Review

**Spec coverage.** Config key → Task 1. `prepare_groups` branch, twin semantics,
unknown-number error, empty-means-all, `locked` precedence → Task 2. TUI toggle,
rollback on over-restriction, marker, `to_config_yaml` persistence → Tasks 1 and 3.
Shortfall wording → Task 3 Step 9. Docs → Task 4. The spec's explicit non-goals
(no deconfliction, no overlap warning) have no task, as intended, and are called
out in Global Constraints so no implementer adds them opportunistically.

**Placeholder scan.** No TBDs. Every code step carries real code; every test step
a real test body; every run step an exact command and expected result. Two steps
(Task 3 Steps 4 and 8.3) deliberately instruct the implementer to read the
surrounding code rather than transcribe — both touch methods whose exact bodies
depend on state I could not verify without inventing them, and both say so
explicitly rather than guessing.

**Type consistency.** `Config.accept` is `dict[str, dict[str, list[str]]]` at
definition (Task 1 Step 3), parse (Step 4), persistence (Step 5), and every
read: `prepare_groups` (Task 2 Step 3), `accepted_sigs` and `toggle_accept`
(Task 3 Step 3). `accepted_sigs` returns `frozenset | None` and is consumed as
such in `_populate_timeslots` (Task 3 Step 8). `toggle_accept` returns `bool`
and is branched on in `action_toggle_accept`. `offered_timeslots` rows are read
by the keys they are documented to carry (`sig`, `class_nos`, `rep`) at every
site.

**One design decision worth the user's attention.** The spec says "select
acceptable timeslots" without fixing what the first keypress does. This plan makes
it **reject** — an untouched group is already fully acceptable, so a first press
that restricted the group to the highlighted slot would silently duplicate `l`
(lock). The config still records what is *kept*, matching the spec's `accept`
key. Consequence worth knowing: rejecting one slot writes out every other slot
explicitly, so slots that appear later (after a data refresh) would not be
included automatically. A `reject` key would invert that trade; the spec chose
`accept`.
