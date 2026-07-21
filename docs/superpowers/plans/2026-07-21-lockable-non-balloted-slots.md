# Lockable Non-Balloted Slots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make lecture groups that offer more than one class visible and lockable in the TUI, without letting lectures leak into the ballot output.

**Architecture:** The Classes pane stops reading `arr.bids` (a ballot concept) and reads a new `AppState.selectable_groups()` built from `base_groups`. Share-URL picks are written to `locked` instead of `fixed`, and pre-existing non-balloted `fixed` pins are migrated to `locked` on TUI load so the existing locking machinery (already lesson-type agnostic) can drive them.

**Tech Stack:** Python 3.13, Textual (TUI), Rich (rendering), pytest + `pytest-asyncio` (Textual `Pilot` tests), PyYAML.

## Global Constraints

- Run everything through the venv: `.venv/bin/python -m pytest`.
- `SlotBid`, `_make_arrangement` (`kairos/search.py:245`) and `ballot.ranked_options` (`kairos/ballot.py:45`) keep their `balloted_types` filters. Lectures must never reach `arr.bids`, the snake ranking, or `ballot.txt`.
- `kairos run` behaviour must not change: migration happens in `build_state` only, never in `load_config` or `cmd_run`.
- `fixed` retains its meaning of "hard pin to exactly one class" and continues to beat `locked` in `prepare_groups`.
- Slot counts for pane membership come from `base_groups` (full offered set), never from prepared groups.
- Existing list rebuilds are wrapped in `with self.prevent(ListView.Highlighted)`; preserve that in any rebuild you touch.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `kairos/tui/state.py` | `SelectableGroup` dataclass + `AppState.selectable_groups()` | Modify |
| `kairos/tui/startup.py` | Write `locked` from share URLs; migrate `fixed` on load | Modify |
| `kairos/cli.py` | `cmd_init` writes `locked` for non-balloted picks | Modify |
| `kairos/tui/app.py` | Classes pane reads the new model; timeslot labels gain venue/online; CSS heights | Modify |
| `tests/conftest.py` | `gamma_json` fixture — two lectures at identical times, one online | Modify |
| `tests/test_tui_state.py` | `selectable_groups()` unit tests | Modify |
| `tests/test_tui_startup.py` | migration tests | Modify |
| `tests/test_cli_init.py` | `cmd_init` writes `locked` | Modify |
| `tests/test_tui_app.py` | Pilot tests: lock a lecture, ballot isolation, label disambiguation | Modify |

---

### Task 1: `selectable_groups()` on AppState

The Classes pane needs a model that is independent of the ballot. This task adds it as a pure, directly-testable state method; nothing consumes it yet.

**Files:**
- Modify: `kairos/tui/state.py` (add dataclass near the top, method on `AppState`)
- Test: `tests/test_tui_state.py`

**Interfaces:**
- Consumes: `AppState.base_groups`, `AppState.is_locked`, `Choice.slot_sig`, `LESSON_ABBREV` — all existing.
- Produces: `SelectableGroup(module: str, lesson_type: str, abbrev: str, balloted: bool, current_class_no: str, locked: bool)` (frozen dataclass) and `AppState.selectable_groups(assignment: dict) -> list[SelectableGroup]`, sorted by `(module, lesson_type)`. Task 3 consumes both.

Reference data: with the `alpha_json` + `beta_json` + `config` fixtures, the expected rows are exactly `ALPHA Tutorial`, `BETA Laboratory`, `BETA Lecture`. `ALPHA Lecture` is excluded — it has a single class (`1`, a Mon+Wed bundle), so one `slot_sig`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tui_state.py`:

```python
def test_selectable_groups_lists_multi_slot_groups_including_lectures(state):
    arr = state.top_arrangements()[0]
    rows = state.selectable_groups(arr.assignment)
    keys = [(r.module, r.abbrev) for r in rows]
    # BETA LEC has two classes (Fri online / Thu physical) -> selectable
    assert ("BETA", "LEC") in keys
    # ALPHA LEC has a single class (one Mon+Wed bundle) -> nothing to choose
    assert ("ALPHA", "LEC") not in keys
    assert keys == sorted(keys)  # stable (module, lesson_type) ordering


def test_selectable_groups_marks_balloted_and_current_class(state):
    arr = state.top_arrangements()[0]
    rows = {(r.module, r.abbrev): r for r in state.selectable_groups(arr.assignment)}
    assert rows[("ALPHA", "TUT")].balloted is True
    assert rows[("BETA", "LEC")].balloted is False
    # current class number is read off the selected arrangement's assignment
    expected = arr.assignment[("BETA", "Lecture")].class_no
    assert rows[("BETA", "LEC")].current_class_no == expected


def test_selectable_groups_counts_slots_from_base_groups(state):
    # Locking narrows the PREPARED group to one slot. The row must survive,
    # otherwise the pane row vanishes the instant the user locks it.
    state.config.fixed = {}
    state._rebuild()
    assert state.set_lock("BETA", "LAB", "L1")
    arr = state.top_arrangements()[0]
    rows = {(r.module, r.abbrev): r for r in state.selectable_groups(arr.assignment)}
    assert ("BETA", "LAB") in rows
    assert rows[("BETA", "LAB")].locked is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tui_state.py -k selectable -v`
Expected: FAIL — `AttributeError: 'AppState' object has no attribute 'selectable_groups'`

- [ ] **Step 3: Implement `SelectableGroup` and `selectable_groups()`**

In `kairos/tui/state.py`, add the dataclass immediately after the `_PREF_FIELDS` block (before `normalize_difficulties`):

```python
@dataclass(frozen=True)
class SelectableGroup:
    """A group the user can actually decide between — one row of the Classes pane.

    Deliberately distinct from search.SlotBid: a SlotBid is something you BALLOT
    for and may not be granted, whereas this covers any group offering more than
    one timeslot, including lectures you simply pick. Keeping them separate is
    what stops lectures leaking into the ballot output."""

    module: str
    lesson_type: str      # full name, e.g. "Lecture"
    abbrev: str           # e.g. "LEC"
    balloted: bool
    current_class_no: str
    locked: bool
```

Then add this method to `AppState`, directly after `offered_timeslots` (around `kairos/tui/state.py:210`):

```python
    def selectable_groups(self, assignment: dict) -> list:
        """Rows for the Classes pane: every offered group with more than one
        distinct timeslot, balloted or not.

        Slot counting uses base_groups (the FULL offered set) rather than the
        prepared groups, for the same reason offered_timeslots does — a locked
        group is narrowed to a single slot in the prepared set, so counting there
        would make the row disappear the moment the user locked it."""
        rows = []
        for group in self.base_groups:
            if len({c.slot_sig for c in group.choices}) < 2:
                continue
            abbrev = LESSON_ABBREV.get(group.lesson_type, group.lesson_type)
            choice = assignment.get((group.module, group.lesson_type))
            rows.append(SelectableGroup(
                module=group.module,
                lesson_type=group.lesson_type,
                abbrev=abbrev,
                balloted=abbrev in self.config.balloted_types,
                current_class_no=choice.class_no if choice else "",
                locked=self.is_locked(group.module, abbrev),
            ))
        rows.sort(key=lambda r: (r.module, r.lesson_type))
        return rows
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_tui_state.py -v`
Expected: PASS (all tests in the file, including pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add kairos/tui/state.py tests/test_tui_state.py
git commit -m "feat: AppState.selectable_groups for the Classes pane

Models any group offering >1 timeslot, independent of SlotBid so that
lectures can be listed without reaching the ballot. Slot counts come from
base_groups so a row survives being locked."
```

---

### Task 2: Write `locked` instead of `fixed`, and migrate existing pins

Without this, Task 3's pane would list a lecture whose lock silently does nothing — `fixed` beats `locked` in `prepare_groups`. Ordering matters: this must land before the pane.

**Files:**
- Modify: `kairos/tui/startup.py:12-38` (`_config_from_url`), `kairos/tui/startup.py:50-59` (`build_state`)
- Modify: `kairos/cli.py:72-113` (`cmd_init`)
- Test: `tests/test_tui_startup.py`, `tests/test_cli_init.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `kairos.tui.startup.migrate_fixed_to_locked(config) -> None`, mutating `config.fixed` / `config.locked` in place. No later task calls it directly; Task 3 relies on its effect.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tui_startup.py`:

```python
def test_build_state_migrates_non_balloted_fixed_to_locked(
    tmp_path, monkeypatch, alpha_json, beta_json
):
    import yaml

    _patch_fetch(monkeypatch, alpha_json, beta_json)
    cfg = {
        "acad_year": "2026-2027",
        "semester": 1,
        "modules": {"ALPHA": {"difficulty": 3}, "BETA": {"difficulty": 3}},
        "fixed": {"BETA": {"LEC": "1"}},
        "priority": ["ALPHA", "BETA"],
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    state = build_state(None, path, tmp_path / "cache")
    # the LEC pin moved from fixed to locked, so the TUI can switch it
    assert state.config.locked["BETA"]["LEC"] == "1"
    assert "BETA" not in state.config.fixed
    # and BOTH lecture slots remain offered, so the pane can show them
    lec = next(g for g in state.base_groups if g.module == "BETA" and g.lesson_type == "Lecture")
    assert len(lec.choices) == 2


def test_build_state_leaves_balloted_fixed_alone(
    tmp_path, monkeypatch, alpha_json, beta_json
):
    import yaml

    _patch_fetch(monkeypatch, alpha_json, beta_json)
    cfg = {
        "acad_year": "2026-2027",
        "semester": 1,
        "modules": {"ALPHA": {"difficulty": 3}, "BETA": {"difficulty": 3}},
        "fixed": {"ALPHA": {"TUT": "01"}},  # balloted -> deliberate hand-written pin
        "priority": ["ALPHA", "BETA"],
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    state = build_state(None, path, tmp_path / "cache")
    assert state.config.fixed["ALPHA"]["TUT"] == "01"
    assert "ALPHA" not in state.config.locked


def test_build_state_from_url_writes_locked_not_fixed(
    tmp_path, monkeypatch, alpha_json, beta_json
):
    _patch_fetch(monkeypatch, alpha_json, beta_json)
    state = build_state(SHARE_URL, tmp_path / "config.yaml", tmp_path / "cache", "2026-2027")
    # URL had BETA=LEC:1 — a non-balloted multi-option group
    assert state.config.locked["BETA"]["LEC"] == "1"
    assert not state.config.fixed
```

Add to `tests/test_cli_init.py`:

```python
def test_init_writes_locked_for_non_balloted_picks(tmp_path, monkeypatch, alpha_json, beta_json):
    import yaml

    from kairos.cli import main

    fixtures = {"ALPHA": alpha_json, "BETA": beta_json}
    monkeypatch.setattr("kairos.cli.api.fetch_module", lambda ay, code, cache: fixtures[code])
    monkeypatch.setattr("builtins.input", lambda *a: "")  # accept every default
    config_path = tmp_path / "config.yaml"
    url = "https://nusmods.com/timetable/sem-1/share?ALPHA=TUT:01,LEC:1&BETA=LAB:L2,LEC:1"
    main([
        "--config", str(config_path),
        "--cache-dir", str(tmp_path / "cache"),
        "init", url, "--acad-year", "2026-2027",
    ])
    written = yaml.safe_load(config_path.read_text())
    assert written["locked"] == {"BETA": {"LEC": "1"}}
    assert written["fixed"] == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tui_startup.py tests/test_cli_init.py -v`
Expected: FAIL — migration tests fail on `KeyError: 'BETA'` reading `config.locked`; the init test fails because `written["locked"]` is missing.

- [ ] **Step 3: Implement the migration and switch both writers**

In `kairos/tui/startup.py`, replace `_config_from_url` (lines 12-38) with:

```python
def _config_from_url(share_url: str, cache_dir: Path, acad_year: str | None):
    semester, selections = parse_share_url(share_url)
    acad_year = acad_year or guess_acad_year()
    modules_cfg: dict = {}
    locked: dict = {}
    groups = []
    for code, picks in selections.items():
        data = api.fetch_module(acad_year, code, cache_dir)
        code_groups = api.build_groups(code, api.semester_timetable(data, semester))
        groups.extend(code_groups)
        difficulty: dict = {}
        for group in code_groups:
            abbrev = LESSON_ABBREV.get(group.lesson_type, group.lesson_type)
            difficulty[abbrev] = 3
            if abbrev not in DEFAULT_BALLOTED and len(group.choices) > 1 and abbrev in picks:
                # `locked`, not `fixed`: pins the SLOT while keeping the group
                # switchable from the TUI and keeping venue-twins interchangeable.
                locked.setdefault(code, {})[abbrev] = picks[abbrev]
        modules_cfg[code] = {"difficulty": difficulty}
    data = {
        "acad_year": acad_year,
        "semester": semester,
        "balloted_types": list(DEFAULT_BALLOTED),
        "modules": modules_cfg,
        "fixed": {},
        "locked": locked,
        "priority": list(selections),
        "preferences": DEFAULT_PREFERENCES,
    }
    return config_from_dict(data, "share URL"), groups
```

Add this function immediately after `_config_from_file` in the same file:

```python
def migrate_fixed_to_locked(config) -> None:
    """Convert non-balloted `fixed` pins into `locked` pins, in place.

    Such entries were auto-written from a share URL by earlier versions, and
    `fixed` beats `locked` in prepare_groups — so the group is pinned to one
    class AND unswitchable from the TUI. `locked` pins the same slot while
    leaving the group selectable. Balloted `fixed` entries are hand-written and
    deliberate, so they are left alone.

    TUI-load only: `kairos run` / load_config are untouched, so CLI behaviour
    does not move. The migrated form reaches disk only when the user saves."""
    for code in list(config.fixed):
        slots = config.fixed[code]
        for abbrev in list(slots):
            if abbrev in config.balloted_types:
                continue
            # fixed previously won over locked, so it wins this overwrite too
            config.locked.setdefault(code, {})[abbrev] = str(slots.pop(abbrev))
        if not slots:
            config.fixed.pop(code)
```

Then in `build_state`, call it just before constructing the state:

```python
def build_state(share_url, config_path: Path, cache_dir: Path, acad_year=None) -> AppState:
    if share_url:
        config, groups = _config_from_url(share_url, cache_dir, acad_year)
    elif Path(config_path).exists():
        config, groups = _config_from_file(Path(config_path), cache_dir)
    else:
        raise SystemExit(
            "error: no config.yaml found — start from a share URL: kairos tui <share-url>"
        )
    migrate_fixed_to_locked(config)
    return AppState.from_parts(config, groups)
```

In `kairos/cli.py:cmd_init`, rename the accumulator and emit both keys. Change line 73 from `fixed: dict = {}` to `locked: dict = {}`; change lines 81-84 to:

```python
            if abbrev not in DEFAULT_BALLOTED and len(group.choices) > 1:
                if abbrev in picks:
                    # `locked` pins the slot but stays switchable in the TUI
                    locked.setdefault(code, {})[abbrev] = picks[abbrev]
```

and change the `"fixed": fixed,` entry of the `config` dict (line 105) to:

```python
        "fixed": {},
        "locked": locked,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_tui_startup.py tests/test_cli_init.py tests/test_cli_run.py -v`
Expected: PASS. `test_cli_run.py` is included to confirm `kairos run` behaviour did not move.

- [ ] **Step 5: Commit**

```bash
git add kairos/tui/startup.py kairos/cli.py tests/test_tui_startup.py tests/test_cli_init.py
git commit -m "feat: write locked (not fixed) for share-URL picks, migrate on TUI load

Share-URL picks for non-balloted multi-option groups were written to
fixed, which prepare_groups applies before locked — pinning the group to
one class and making it unswitchable from the TUI. Write locked instead,
and migrate pre-existing non-balloted fixed pins in build_state. Balloted
pins and kairos run are unaffected."
```

---

### Task 3: Classes pane reads the new model; timeslot labels disambiguate

**Files:**
- Modify: `kairos/tui/app.py:73-77` (`_fmt_sessions`), `:196-238` (`_refresh_slots`, `_populate_timeslots`), `:320-335` (`action_toggle_lock`)
- Modify: `tests/conftest.py` (add `gamma_json`)
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Consumes: `AppState.selectable_groups(assignment) -> list[SelectableGroup]` from Task 1, with fields `module`, `lesson_type`, `abbrev`, `balloted`, `current_class_no`, `locked`. The `locked` migration from Task 2 must already be in place.
- Produces: `KairosApp._rows: list[SelectableGroup]` (the Classes pane's backing list) and module-level `_fmt_timeslot(row: dict) -> str`, where `row` is an `offered_timeslots` dict with keys `sig`, `class_nos`, `sessions`, `rep`.

`gamma_json` reproduces the CS1231S shape — two lecture classes at identical times, differing only physical vs. online — which is the case that renders as two indistinguishable rows today. Thursday is free in both `alpha_json` and `beta_json`, so GAMMA never clashes.

- [ ] **Step 1: Add the fixture**

Add to `tests/conftest.py`:

```python
@pytest.fixture
def gamma_json():
    """GAMMA: two lecture classes at IDENTICAL times, one physical one online
    (the CS1231S shape). Their slot_sigs differ only by `online`, so they are
    two distinct rows that a day/time-only label cannot tell apart."""
    return {
        "moduleCode": "GAMMA",
        "semesterData": [
            {
                "semester": 1,
                "timetable": [
                    lesson("1", "Lecture", "Thursday", "1200", "1400", venue="UT-AUD1"),
                    lesson("2", "Lecture", "Thursday", "1200", "1400", venue="E-Learn_C"),
                ],
            }
        ],
    }
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_tui_app.py`:

```python
@pytest.fixture
def gamma_state(alpha_json, gamma_json, config):
    groups = build_groups("ALPHA", semester_timetable(alpha_json, 1)) + build_groups(
        "GAMMA", semester_timetable(gamma_json, 1)
    )
    cfg = copy.deepcopy(config)
    cfg.fixed = {}
    cfg.modules = {"ALPHA": {"LEC": 2, "TUT": 4}, "GAMMA": 3}
    cfg.priority = ["ALPHA", "GAMMA"]
    return AppState.from_parts(cfg, groups)


def test_fmt_timeslot_distinguishes_physical_from_online(gamma_state):
    from kairos.tui.app import _fmt_timeslot

    rows = gamma_state.offered_timeslots("GAMMA", "Lecture")
    assert len(rows) == 2  # same times, different online-ness -> distinct sigs
    labels = [_fmt_timeslot(row) for row in rows]
    assert labels[0] != labels[1]          # the whole point
    assert any("E-Learn_C" in lb for lb in labels)
    assert any(lb.startswith("~") for lb in labels)  # online marker


async def test_lecture_row_appears_and_locks(state, tmp_path):
    state.config.fixed = {}
    state._rebuild()
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        slot_list = app.query_one("#slot-list", ListView)
        keys = [(r.module, r.abbrev) for r in app._rows]
        assert ("BETA", "LEC") in keys  # lecture is now a row

        slot_list.index = keys.index(("BETA", "LEC"))
        app.set_focus(slot_list)
        await pilot.pause()
        tlist = app.query_one("#timeslot-list", ListView)
        assert len(app._timeslots) == 2  # both lecture slots offered

        app.set_focus(tlist)
        tlist.index = 1
        await pilot.press("l")
        await pilot.pause()
        assert app.state.is_locked("BETA", "LEC")


async def test_locked_lecture_never_enters_ballot(state, tmp_path):
    state.config.fixed = {}
    state._rebuild()
    assert state.set_lock("BETA", "LEC", "2")
    app = KairosApp(state, tmp_path / "config.yaml")
    async with app.run_test():
        for arr in app.state.top_arrangements():
            assert all(b.lesson_type != "Lecture" for b in arr.bids)
        assert all(e.lesson_type != "Lecture" for e in app.state.ballot_snake())
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tui_app.py -k "fmt_timeslot or lecture_row or ballot" -v`
Expected: FAIL — `ImportError: cannot import name '_fmt_timeslot'`, and `AttributeError: 'KairosApp' object has no attribute '_rows'`.

- [ ] **Step 4: Replace `_fmt_sessions` with `_fmt_timeslot`**

In `kairos/tui/app.py`, replace the `_fmt_sessions` function (lines 73-77) with:

```python
def _fmt_timeslot(row) -> str:
    """Label one offered_timeslots row. Day/time alone is not enough: two classes
    can share a slot and differ only by venue or physical-vs-online (e.g. CS1231S
    lecture 1 @UT-AUD1 vs 2 @E-Learn_C), which would otherwise render identically.
    Reuses the `~` online marker from tui.render."""
    sessions = row["sessions"]
    times = ", ".join(
        f"{s.day[:3]} {fmt_time(s.start)}-{fmt_time(s.end)}"
        for s in sorted(sessions, key=lambda s: (DAYS.index(s.day), s.start))
    )
    mark = "~" if any(s.online for s in sessions) else " "
    return f"{mark}{times}  @{sessions[0].venue}"
```

- [ ] **Step 5: Rewrite `_refresh_slots` to read `selectable_groups`**

Replace `_refresh_slots` (lines 196-210) with:

```python
    def _refresh_slots(self) -> None:
        slot_list = self.query_one("#slot-list", ListView)
        prev = slot_list.index
        with self.prevent(ListView.Highlighted):
            slot_list.clear()
            self._rows = []
            top = self.state.top_arrangements()
            if top:
                self._rows = self.state.selectable_groups(top[self.selected].assignment)
                for row in self._rows:
                    lock = "🔒 " if row.locked else ""
                    tag = "  ·ballot" if row.balloted else ""
                    slot_list.append(ListItem(Label(
                        f"{lock}{row.module} {row.abbrev} → {row.current_class_no}{tag}"
                    )))
            if slot_list.children and prev is not None:
                slot_list.index = min(prev, len(slot_list.children) - 1)
```

Initialise the backing list in `__init__` (after `self._timeslots = []`, line 117):

```python
        self._rows = []
```

- [ ] **Step 6: Point `_populate_timeslots` and `action_toggle_lock` at `_rows`**

Replace the body of `_populate_timeslots` (lines 212-238) with:

```python
    def _populate_timeslots(self) -> None:
        tlist = self.query_one("#timeslot-list", ListView)
        slot_list = self.query_one("#slot-list", ListView)
        self._timeslots = []
        self._current_class = None
        with self.prevent(ListView.Highlighted):
            tlist.clear()
            tlist.border_title = "Timeslots"
            if slot_list.index is not None and 0 <= slot_list.index < len(self._rows):
                row = self._rows[slot_list.index]
                self._current_class = (row.module, row.lesson_type)
                tlist.border_title = f"Timeslots: {row.module} {row.abbrev}"
                self._timeslots = self.state.offered_timeslots(row.module, row.lesson_type)
                locked = self.state.locked_sig(row.module, row.lesson_type)
                locked_idx = 0
                for i, slot in enumerate(self._timeslots):
                    mark = "🔒 " if slot["sig"] == locked else ""
                    label = f"{mark}{_fmt_timeslot(slot)} ({'/'.join(slot['class_nos'])})"
                    tlist.append(ListItem(Label(label)))
                    if slot["sig"] == locked:
                        locked_idx = i
                if self._timeslots:
                    tlist.index = locked_idx
```

`action_toggle_lock` already derives `(module, lesson_type)` from `self._current_class` and the abbrev via `LESSON_ABBREV`, so it needs no change — verify by reading lines 320-335 and confirming it does not reference `arr.bids`.

`_fmt_sessions` has exactly one caller (the label line in `_populate_timeslots`, replaced above), so removing it leaves nothing dangling. Confirm with `grep -rn "_fmt_sessions" kairos/ tests/` — expect no matches after this step.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_tui_app.py tests/test_tui_state.py -v`
Expected: PASS

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. If `tests/test_output.py` or `tests/test_ballot.py` fail, the `balloted_types` filters in `search.py`/`ballot.py` were touched — revert that; they must stay.

- [ ] **Step 9: Commit**

```bash
git add kairos/tui/app.py tests/conftest.py tests/test_tui_app.py
git commit -m "feat: list every multi-slot group in the Classes pane

The pane read arr.bids, so only balloted types appeared and lecture
groups offering two classes were unreachable. Read selectable_groups
instead, and label timeslots with venue + online marker so classes that
share a slot and differ only by venue or delivery mode can be told apart.
SlotBid stays ballot-only, so lectures never reach ballot.txt."
```

---

### Task 4: Rebalance the results column

**Files:**
- Modify: `kairos/tui/app.py:81-91` (the `CSS` class attribute)
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Consumes: nothing. Produces: nothing. Pure layout.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tui_app.py`:

```python
async def test_week_grid_gets_more_height_than_the_top_row(state, tmp_path):
    app = KairosApp(state, tmp_path / "config.yaml")
    # Size is pinned: the assertion compares integer row counts, so it must not
    # depend on the harness default. At 100x30 the results column is 28 rows —
    # before: top=8 classes=4 detail=16; after: top=5 classes=5 detail=18.
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        top_row = app.query_one("#top-row")
        detail = app.query_one("#detail-scroll")
        # timetables + warnings shrank; the week grid absorbs the remainder
        assert detail.size.height >= 3 * top_row.size.height
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_tui_app.py -k week_grid -v`
Expected: FAIL — `assert 16 >= 24`. (Do not weaken this to `> 2 *`: at 30%/15% the detail pane is already 16 vs. a doubled top row of 16, so a 2x assertion passes before the change and proves nothing.)

- [ ] **Step 3: Adjust the CSS**

In `kairos/tui/app.py`, change these two lines of the `CSS` block:

```css
    #top-row { height: 20%; }
    #classes-row { height: 20%; }
```

(`#top-row` was `30%`; `#classes-row` was `15%` and grows because it now gains lecture rows. `#detail-scroll` stays `height: 1fr` and absorbs the remainder, going from ~55% to ~60%.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_tui_app.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kairos/tui/app.py tests/test_tui_app.py
git commit -m "style: shorten timetables/warnings, grow the week grid"
```

---

### Task 5: Refresh the checked-in config and README

`config.yaml` still carries three auto-written `fixed` LEC pins. Migrating it makes the repo's own config match the new model, and the README's TUI section does not mention that lectures are now selectable.

**Files:**
- Modify: `config.yaml`
- Modify: `README.md:26-36`

**Interfaces:**
- Consumes: `migrate_fixed_to_locked` semantics from Task 2. Produces: nothing.

- [ ] **Step 1: Migrate the checked-in config by hand**

In `config.yaml`, replace:

```yaml
fixed:
  CS1231S:
    LEC: '2'
  MA1521:
    LEC: '1'
  MA1522:
    LEC: '2'
locked: {}
```

with:

```yaml
fixed: {}
locked:
  CS1231S:
    LEC: '2'
  MA1521:
    LEC: '1'
  MA1522:
    LEC: '2'
```

- [ ] **Step 2: Verify the config still loads and produces a timetable**

Run: `.venv/bin/python -c "
from pathlib import Path
from kairos import api, search
from kairos.config import load_config
cfg = load_config(Path('config.yaml'))
groups = []
for code in cfg.modules:
    d = api.fetch_module(cfg.acad_year, code, Path('.cache'))
    groups.extend(api.build_groups(code, api.semester_timetable(d, cfg.semester)))
res = search.search(search.prepare_groups(groups, cfg), cfg)
print('clash-free shapes:', res.evaluated)
"`

Expected: a non-zero count printed, no traceback.

- [ ] **Step 3: Document the behaviour in the README**

In `README.md`, replace the sentence beginning "A full-screen app:" through "`q` to quit." with:

```markdown
A full-screen app: tabs on the left for Weights, Difficulty, Times, and Priority
(adjust with ←/→); the timetables and their score breakdown on the right, re-ranking
live as you tune. The Classes pane lists every group offering more than one
timeslot — including lectures, which some modules run as two alternative classes
(a different time, or the same time online). Press `→` to see that group's
timeslots and `l` to lock one. Locking pins the slot, not the class number, so
interchangeable twins stay available for the ballot; lectures are never balloted
and never appear in `ballot.txt`. Press `b` for the ballot view, `s` to save
config.yaml, `e` to export the ballot to `ballot.txt`, `c` to copy the selected
timetable's NUSMods link, `q` to quit.
```

- [ ] **Step 4: Run the full suite one last time**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config.yaml README.md
git commit -m "docs: migrate checked-in config to locked; document lecture selection"
```

---

## Spec Coverage

| Spec section | Task |
|---|---|
| 1. Classes pane gets its own model | 1, 3 |
| 2. `SlotBid` stays ballot-only | 3 (asserted by `test_locked_lecture_never_enters_ballot`) |
| 3. Stop auto-writing `fixed` | 2 |
| 4. Migrate existing `fixed` pins on TUI load | 2 |
| 5. Disambiguate timeslot labels | 3 |
| 6. No new locking machinery | 3 Step 6 (verification only — no code change) |
| 7. Layout | 4 |
| 8. Testing | tests distributed across 1-4 |
