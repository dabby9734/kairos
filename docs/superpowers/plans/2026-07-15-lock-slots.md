# Lock Decided Slots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the live-tuning TUI **lock** a decided slot so the search collapses that group to its interchangeable slot-twins, cutting the combo space at its source while still surfacing the twins as ballot options.

**Architecture:** A new `locked` config field (`module → {abbrev: class_no}`) drives a new branch in `prepare_groups` that restricts a group to the choices sharing the locked class's `(day, start, end, online)` slot signature. `AppState` gains `set_lock`/`clear_lock` that re-run the full `prepare → enumerate → retune` rebuild (locking changes enumeration, not just scoring), with an empty-space guard that rolls back. The TUI adds a focusable slot-list and an `l` binding to toggle the lock on the highlighted slot. No ballot code changes — the existing clash-set grouping already lists the surviving twins.

**Tech Stack:** Python 3.13, Textual 8.2.8 (TUI + Pilot tests), PyYAML, pytest.

## Global Constraints

- No new third-party dependencies.
- `fixed` behaviour is unchanged: `fixed` is applied first and always wins over `locked`; a group present in `fixed` is never additionally narrowed by `locked`.
- `locked` values are class-number strings (mirroring how `fixed` stores `class_no`).
- A stale `locked` entry (class number absent from the group) raises `SystemExit`, exactly like `fixed`.
- Locks live in session state; they reach disk only via the existing `s` (save) action.

---

### Task 1: Config field `locked`

**Files:**
- Modify: `optimiser/config.py` (`Config` dataclass ~40-51, imports line 3, `config_from_dict` return ~102-113)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config.locked: dict` (default `{}`), shape `{module: {abbrev: class_no}}`; parsed by `config_from_dict` / `load_config`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py` (after `test_config_from_dict_matches_load`):

```python
def test_load_config_parses_locked(tmp_path):
    cfg = load_config(write(tmp_path, BASE + "\nlocked:\n  ALPHA: {TUT: '02'}\n"))
    assert cfg.locked == {"ALPHA": {"TUT": "02"}}


def test_load_config_defaults_locked_empty(tmp_path):
    cfg = load_config(write(tmp_path, BASE))
    assert cfg.locked == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_config.py::test_load_config_parses_locked tests/test_config.py::test_load_config_defaults_locked_empty -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'locked'`.

- [ ] **Step 3: Add the field and parse it**

In `optimiser/config.py`, change the dataclass import (line 3):

```python
from dataclasses import dataclass, field
```

In the `Config` dataclass, add `locked` after `max_arrangements` (it must follow the other default field):

```python
@dataclass
class Config:
    acad_year: str
    semester: int
    balloted_types: list
    modules: dict  # code -> int | dict[abbrev, int]
    fixed: dict  # code -> dict[abbrev, class_no]
    priority: list
    preferences: Preferences
    alternatives_per_module: int
    top_n: int
    max_arrangements: int = 50
    locked: dict = field(default_factory=dict)  # code -> dict[abbrev, class_no]
```

In `config_from_dict`, add `locked` to the returned `Config(...)` (after the `max_arrangements=...` line):

```python
        max_arrangements=int(data.get("max_arrangements", 50)),
        locked=data.get("locked") or {},
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (all config tests, including the two new ones).

- [ ] **Step 5: Commit**

```bash
git add optimiser/config.py tests/test_config.py
git commit -m "feat: add locked config field for slot locking"
```

---

### Task 2: `prepare_groups` slot-signature locking

**Files:**
- Modify: `optimiser/search.py` (`prepare_groups` 19-38; add `_slot_sig` helper above it)
- Test: `tests/test_search.py`

**Interfaces:**
- Consumes: `Config.locked` from Task 1.
- Produces: `prepare_groups(groups, config)` now restricts a group whose `(module, abbrev)` is in `config.locked` to the choices sharing the locked class's slot signature; raises `SystemExit` on a missing locked class; `fixed` still takes precedence.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_search.py` (after `test_prepare_groups_bad_fixed`):

```python
def test_prepare_groups_locks_to_slot_twins(alpha_json, config):
    config.fixed = {}
    config.locked = {"ALPHA": {"TUT": "02"}}
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    prepared = prepare_groups(gs, config)
    tut = next(g for g in prepared if g.key == ("ALPHA", "Tutorial"))
    # 02 is the Tue 0900 slot; its venue-twin 03 stays, Mon 01 is dropped
    assert sorted(c.class_no for c in tut.choices) == ["02", "03"]


def test_prepare_groups_bad_locked(alpha_json, config):
    config.fixed = {}
    config.locked = {"ALPHA": {"TUT": "99"}}
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    with pytest.raises(SystemExit):
        prepare_groups(gs, config)


def test_prepare_groups_fixed_beats_locked(beta_json, config):
    config.fixed = {"BETA": {"LEC": "1"}}
    config.locked = {"BETA": {"LEC": "2"}}
    gs = build_groups("BETA", semester_timetable(beta_json, 1))
    prepared = prepare_groups(gs, config)
    lec = next(g for g in prepared if g.key == ("BETA", "Lecture"))
    assert [c.class_no for c in lec.choices] == ["1"]  # fixed wins
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_search.py::test_prepare_groups_locks_to_slot_twins tests/test_search.py::test_prepare_groups_bad_locked tests/test_search.py::test_prepare_groups_fixed_beats_locked -v`
Expected: FAIL — `test_prepare_groups_locks_to_slot_twins` keeps all three tutorials (no locking yet); `test_prepare_groups_bad_locked` does not raise.

- [ ] **Step 3: Implement slot-signature locking**

In `optimiser/search.py`, add the helper just above `prepare_groups` (after the imports, before line 19):

```python
def _slot_sig(choice) -> frozenset:
    """Slot signature ignoring class number, venue AND weeks: two choices share
    a signature iff they occupy the same (day, start, end, online) sessions."""
    return frozenset((s.day, s.start, s.end, s.online) for s in choice.sessions)
```

Then rewrite `prepare_groups` to add the `locked` branch after the `fixed` branch (so `fixed` wins) and before the free-group warning:

```python
def prepare_groups(groups: list, config) -> list:
    prepared = []
    for group in groups:
        abbrev = LESSON_ABBREV.get(group.lesson_type, group.lesson_type)
        fixed_no = (config.fixed.get(group.module) or {}).get(abbrev)
        if fixed_no is not None:
            chosen = [c for c in group.choices if c.class_no == str(fixed_no)]
            if not chosen:
                raise SystemExit(
                    f"error: {group.module} {abbrev} class {fixed_no} (config 'fixed') does not exist"
                )
            prepared.append(ChoiceGroup(group.module, group.lesson_type, chosen))
            continue
        locked_no = (config.locked.get(group.module) or {}).get(abbrev)
        if locked_no is not None:
            anchor = next((c for c in group.choices if c.class_no == str(locked_no)), None)
            if anchor is None:
                raise SystemExit(
                    f"error: {group.module} {abbrev} class {locked_no} (config 'locked') does not exist"
                )
            sig = _slot_sig(anchor)
            chosen = [c for c in group.choices if _slot_sig(c) == sig]
            prepared.append(ChoiceGroup(group.module, group.lesson_type, chosen))
            continue
        if len(group.choices) > 1 and abbrev not in config.balloted_types:
            print(
                f"warning: {group.module} {abbrev} has {len(group.choices)} options "
                "and no fixed choice; searching over all of them"
            )
        prepared.append(group)
    return prepared
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_search.py -v`
Expected: PASS (all search tests, including the three new ones).

- [ ] **Step 5: Commit**

```bash
git add optimiser/search.py tests/test_search.py
git commit -m "feat: prepare_groups locks a group to its slot-signature twins"
```

---

### Task 3: `AppState` lock/unlock with rebuild + guard

**Files:**
- Modify: `optimiser/tui/state.py` (`AppState` dataclass 47-62, add methods; `to_config_yaml` 116-139)
- Test: `tests/test_tui_state.py`

**Interfaces:**
- Consumes: `prepare_groups`/`enumerate_clashfree` locking from Task 2.
- Produces:
  - `AppState.base_groups: list` — the raw (pre-`prepare_groups`) groups, retained so re-locking rebuilds from scratch.
  - `AppState._rebuild() -> result` — shared `prepare → normalize → enumerate → retune` sequence.
  - `AppState.set_lock(module, abbrev, class_no) -> bool` — locks a slot; returns `False` and leaves state unchanged if the lock empties the space.
  - `AppState.clear_lock(module, abbrev) -> bool` — removes a lock (always succeeds).
  - `AppState.is_locked(module, abbrev) -> bool`.
  - `to_config_yaml()` now emits `"locked"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tui_state.py` (the file already has the `state` fixture and imports `AppState`):

```python
def test_set_lock_shrinks_and_keeps_twins(state):
    before = len(state.space.combos)
    assert state.set_lock("ALPHA", "TUT", "02") is True
    assert state.is_locked("ALPHA", "TUT")
    assert len(state.space.combos) < before
    # locking the slot keeps its interchangeable twins (02/03) in the ballot
    opts = state.ballot_options()[("ALPHA", "Tutorial")]
    assert {"02", "03"} <= {o.class_no for o in opts}


def test_clear_lock_restores(state):
    before = len(state.space.combos)
    state.set_lock("ALPHA", "TUT", "02")
    assert state.clear_lock("ALPHA", "TUT") is True
    assert not state.is_locked("ALPHA", "TUT")
    assert len(state.space.combos) == before


def test_set_lock_empty_guard_leaves_state_unchanged(config):
    import copy

    from optimiser.model import Choice, ChoiceGroup, Session

    all_weeks = frozenset(range(1, 14))
    tut = ChoiceGroup(
        "ALPHA", "Tutorial",
        [
            Choice("ALPHA", "Tutorial", "T1", (Session("Monday", 540, 600, all_weeks, "COM1"),)),
            Choice("ALPHA", "Tutorial", "T2", (Session("Tuesday", 540, 600, all_weeks, "COM1"),)),
        ],
    )
    lab = ChoiceGroup(
        "BETA", "Laboratory",
        [Choice("BETA", "Laboratory", "L1", (Session("Monday", 540, 600, all_weeks, "COM1"),))],
    )
    cfg = copy.deepcopy(config)
    cfg.fixed, cfg.locked = {}, {}
    cfg.modules = {"ALPHA": {"TUT": 3}, "BETA": {"LAB": 3}}
    state = AppState.from_parts(cfg, [tut, lab])
    before = len(state.space.combos)  # only (T2, L1) is clash-free -> 1
    # locking ALPHA TUT to the Monday slot clashes the only lab -> empty
    assert state.set_lock("ALPHA", "TUT", "T1") is False
    assert not state.is_locked("ALPHA", "TUT")
    assert len(state.space.combos) == before  # rolled back


def test_locked_roundtrips_through_config(tmp_path, state):
    import yaml

    from optimiser.config import load_config
    from optimiser.search import prepare_groups

    state.set_lock("ALPHA", "TUT", "02")
    data = state.to_config_yaml()
    assert data["locked"] == {"ALPHA": {"TUT": "02"}}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    reloaded = load_config(path)
    prepared = prepare_groups(state.base_groups, reloaded)
    tut = next(g for g in prepared if g.key == ("ALPHA", "Tutorial"))
    assert sorted(c.class_no for c in tut.choices) == ["02", "03"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tui_state.py::test_set_lock_shrinks_and_keeps_twins tests/test_tui_state.py::test_clear_lock_restores tests/test_tui_state.py::test_set_lock_empty_guard_leaves_state_unchanged tests/test_tui_state.py::test_locked_roundtrips_through_config -v`
Expected: FAIL — `AppState` has no `set_lock`/`clear_lock`/`is_locked`/`base_groups`.

- [ ] **Step 3: Refactor `from_parts` to keep raw groups and add lock methods**

In `optimiser/tui/state.py`, replace the `AppState` dataclass fields and `from_parts` (lines 47-73) with:

```python
@dataclass
class AppState:
    config: object
    groups: list                       # prepared (post prepare_groups) groups
    space: EnumeratedSpace
    result: object = None
    arrangements: list = None
    base_groups: list = None           # raw groups, for re-locking rebuilds

    @classmethod
    def from_parts(cls, config, groups) -> "AppState":
        state = cls(
            config=config,
            groups=[],
            space=EnumeratedSpace((), {}),
            base_groups=list(groups),
        )
        state._rebuild()
        return state

    def _rebuild(self):
        prepared = prepare_groups(self.base_groups, self.config)
        normalize_difficulties(self.config, prepared)
        self.groups = prepared
        self.space = enumerate_clashfree(prepared)
        return self.retune()

    def retune(self):
        # Score every combo once, then share it with both consumers (M5). The
        # arrangement list is capped at config.max_arrangements (keeps the TUI
        # ListView bounded); top_n only sizes result.top (the raw timetable list).
        scored = _score_combos(self.space, self.config)
        self.result = rank(self.space, self.config, scored=scored)
        self.arrangements = rank_arrangements(
            self.space, self.config, limit=self.config.max_arrangements, scored=scored
        )
        return self.result
```

Then add the lock methods immediately after `set_pref` (after line 93, before `move_priority`):

```python
    def is_locked(self, module: str, abbrev: str) -> bool:
        return abbrev in (self.config.locked.get(module) or {})

    def _apply_locked_change(self, mutate) -> bool:
        """Mutate config.locked, rebuild the space, and commit only if the
        result is non-empty; otherwise roll everything back and return False."""
        snapshot = (
            {m: dict(v) for m, v in self.config.locked.items()},
            self.groups, self.space, self.result, self.arrangements,
        )
        mutate()
        prepared = prepare_groups(self.base_groups, self.config)
        normalize_difficulties(self.config, prepared)
        space = enumerate_clashfree(prepared)
        if not space.combos:
            (self.config.locked, self.groups, self.space,
             self.result, self.arrangements) = snapshot
            return False
        self.groups = prepared
        self.space = space
        self.retune()
        return True

    def set_lock(self, module: str, abbrev: str, class_no: str) -> bool:
        def mutate():
            self.config.locked.setdefault(module, {})[abbrev] = str(class_no)
        return self._apply_locked_change(mutate)

    def clear_lock(self, module: str, abbrev: str) -> bool:
        def mutate():
            slots = self.config.locked.get(module)
            if slots:
                slots.pop(abbrev, None)
                if not slots:
                    self.config.locked.pop(module, None)
        return self._apply_locked_change(mutate)
```

- [ ] **Step 4: Emit `locked` in `to_config_yaml`**

In `optimiser/tui/state.py`, add the `locked` key to the dict returned by `to_config_yaml`, right after the `"fixed"` line:

```python
            "fixed": self.config.fixed,
            "locked": self.config.locked,
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tui_state.py -v`
Expected: PASS (all state tests, including the four new ones — the existing `from_parts`/`retune`/round-trip tests still pass because the rebuild sequence is unchanged in effect).

- [ ] **Step 6: Commit**

```bash
git add optimiser/tui/state.py tests/test_tui_state.py
git commit -m "feat: AppState set_lock/clear_lock with empty-space guard and rebuild"
```

---

### Task 4: TUI slot list + `l` toggle binding

**Files:**
- Modify: `optimiser/tui/app.py` (`CSS` 78-83, `BINDINGS` 85-97, `compose` results `Vertical` 142-144, `_refresh_detail` 165, add `_refresh_slots` + `action_toggle_lock`)
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Consumes: `AppState.set_lock`/`clear_lock`/`is_locked`/`top_arrangements` from Task 3; `Arrangement.bids` (`list[SlotBid]`) and `Arrangement.assignment` (`{(module, lesson_type): Choice}`) from `optimiser/search.py`.
- Produces: a `#slot-list` `ListView` in the results pane (one row per balloted `SlotBid`, `🔒` prefix when locked) and an `l` action toggling the lock on the highlighted row.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tui_app.py` (the file already has the `state` fixture and imports `OptimiserApp`, `ListView`):

```python
def _slot_labels(app):
    from textual.widgets import Label, ListView

    return [str(lbl.renderable) for lbl in app.query_one("#slot-list", ListView).query(Label)]


async def test_slot_list_lists_balloted_slots(state, tmp_path):
    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        labels = _slot_labels(app)
        # ALPHA Tutorial is a balloted slot; BETA Lecture is fixed and excluded
        assert any("ALPHA TUT" in t for t in labels)
        assert not any("LEC" in t for t in labels)


async def test_lock_slot_marks_and_reduces(state, tmp_path):
    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        before = len(app.state.top_arrangements())
        slot_list = app.query_one("#slot-list", ListView)
        app.set_focus(slot_list)
        slot_list.index = 0  # ALPHA Tutorial
        await pilot.press("l")
        assert len(app.state.top_arrangements()) < before
        assert any("🔒" in t for t in _slot_labels(app))


async def test_lock_then_unlock_restores(state, tmp_path):
    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        before = len(app.state.top_arrangements())
        slot_list = app.query_one("#slot-list", ListView)
        app.set_focus(slot_list)
        slot_list.index = 0
        await pilot.press("l")   # lock ALPHA Tutorial
        await pilot.press("l")   # unlock the same row (index 0 restored)
        assert len(app.state.top_arrangements()) == before
        assert not any("🔒" in t for t in _slot_labels(app))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tui_app.py::test_slot_list_lists_balloted_slots tests/test_tui_app.py::test_lock_slot_marks_and_reduces tests/test_tui_app.py::test_lock_then_unlock_restores -v`
Expected: FAIL — no `#slot-list` widget (`query_one` raises), no `l` action.

- [ ] **Step 3: Add the slot list to the layout, CSS, and bindings**

In `optimiser/tui/app.py`, update the `CSS` block (lines 78-83) to make room for the slot list:

```python
    CSS = """
    #controls { width: 42; }
    #results { width: 1fr; }
    #tt-list { height: 30%; }
    #slot-list { height: 20%; }
    #detail { height: 1fr; }
    """
```

Add the `l` binding to `BINDINGS` (after the `"b"` ballot line):

```python
        ("b", "toggle_ballot", "ballot view"),
        ("l", "toggle_lock", "lock slot"),
```

Insert the slot list into the results `Vertical` in `compose` (between `#tt-list` and `#detail`, lines 142-144):

```python
            with Vertical(id="results"):
                yield ListView(id="tt-list")
                yield ListView(id="slot-list")
                yield Static(id="detail")
```

- [ ] **Step 4: Render the slot list on every detail refresh**

In `optimiser/tui/app.py`, add a `_refresh_slots` method (place it just before `_refresh_detail`), and call it at the top of `_refresh_detail`.

Add the method:

```python
    def _refresh_slots(self) -> None:
        slot_list = self.query_one("#slot-list", ListView)
        prev = slot_list.index
        slot_list.clear()
        top = self.state.top_arrangements()
        if top:
            arr = top[self.selected]
            for bid in arr.bids:
                abbrev = LESSON_ABBREV.get(bid.lesson_type, bid.lesson_type)
                class_no = arr.assignment[(bid.module, bid.lesson_type)].class_no
                lock = "🔒 " if self.state.is_locked(bid.module, abbrev) else ""
                slot_list.append(ListItem(Label(f"{lock}{bid.module} {abbrev} → {class_no}")))
        if slot_list.children and prev is not None:
            slot_list.index = min(prev, len(slot_list.children) - 1)
```

Add the call as the first line of `_refresh_detail` (before the `detail = self.query_one(...)` line):

```python
    def _refresh_detail(self) -> None:
        self._refresh_slots()
        detail = self.query_one("#detail", Static)
```

- [ ] **Step 5: Add the `action_toggle_lock` handler**

In `optimiser/tui/app.py`, add this action (place it after `action_toggle_ballot`):

```python
    def action_toggle_lock(self) -> None:
        slot_list = self.query_one("#slot-list", ListView)
        top = self.state.top_arrangements()
        if slot_list.index is None or not top:
            return
        arr = top[self.selected]
        if slot_list.index >= len(arr.bids):
            return
        bid = arr.bids[slot_list.index]
        abbrev = LESSON_ABBREV.get(bid.lesson_type, bid.lesson_type)
        if self.state.is_locked(bid.module, abbrev):
            ok = self.state.clear_lock(bid.module, abbrev)
        else:
            class_no = arr.assignment[(bid.module, bid.lesson_type)].class_no
            ok = self.state.set_lock(bid.module, abbrev, class_no)
        if not ok:
            self.notify(f"locking {bid.module} {abbrev} leaves no clash-free timetable")
            return
        self._refresh_results()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tui_app.py -v`
Expected: PASS (all app tests, including the three new ones).

- [ ] **Step 7: Commit**

```bash
git add optimiser/tui/app.py tests/test_tui_app.py
git commit -m "feat: TUI slot list with 'l' to lock/unlock the highlighted slot"
```

---

### Task 5: Full suite green

**Files:** none (verification task)

- [ ] **Step 1: Run the whole test suite**

Run: `python -m pytest -q`
Expected: PASS — no regressions across config, search, state, app, and the other modules.

- [ ] **Step 2: Sanity-check the live app boots (optional manual smoke)**

Run: `python -m optimiser tui` against an existing `config.yaml`, press `l` on a slot, confirm the 🔒 appears and the arrangement list shrinks, press `l` again to restore, press `s` and confirm `locked:` is written to `config.yaml`.

- [ ] **Step 3: Commit any incidental fixes**

```bash
git add -A
git commit -m "test: full suite green for slot locking"
```

---

## Self-Review

**Spec coverage:**
- §1 Config & data model → Task 1 (field + parse) and Task 2 (`prepare_groups` expansion, missing-class `SystemExit`, `fixed` precedence). ✓
- §2 Search / state rebuild (`set_lock`/`clear_lock`, shared build helper, empty-space guard, `normalize_difficulties` on rebuild) → Task 3. ✓
- §3 TUI interaction (slot list, `🔒` prefix, `l` toggle, notify on guard, save via `s`) → Task 4; save-via-`s` already writes `to_config_yaml()` which now emits `locked` (Task 3 Step 4). ✓
- §4 Ballot / interchangeability (no new code; twins still surfaced) → verified by `test_set_lock_shrinks_and_keeps_twins` (Task 3). ✓
- §5 Testing (prepare_groups unit, state, round-trip, TUI Pilot) → Tasks 2-4. ✓
- Out-of-scope items (raw-value caching, numpy, solvers) → correctly not planned. ✓

**Focus binding note:** The design mentions "a binding to jump focus" to the slot list. The slot list is a `ListView`, which joins Textual's built-in Tab focus chain automatically, and the global `l` binding acts on the highlighted row regardless of focus — so no extra colliding key is introduced. This is a deliberate, minimal reading of that optional detail.

**Type consistency:** `set_lock(module, abbrev, class_no)` / `clear_lock(module, abbrev)` / `is_locked(module, abbrev)` are used identically in Task 3 (definition) and Task 4 (call site). `abbrev` is always the `LESSON_ABBREV`-mapped short form; `class_no` is a string. `arr.bids` (`list[SlotBid]`) and `arr.assignment[(module, lesson_type)].class_no` match `optimiser/search.py`. `_slot_sig` is defined once in Task 2 and reused conceptually by the state layer via `prepare_groups`.

**Placeholder scan:** none — every code and test step is complete.
