# Distinct Arrangements & Interchangeable Bids Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse look-alike timetables that differ only by an interchangeable same-slot week-twin (e.g. EG1311 LAB[03] odd / LAB[04] even) into one "distinct arrangement" that lists all its class numbers to bid, and show all distinct arrangements instead of a fixed top 5.

**Architecture:** Enumeration stays footprint-exact (twins clash differently, so collapsing before clash-checking would be unsound). All collapsing is presentation-layer, over already-validated clash-free combos. A new `rank_arrangements` in `search.py` groups combos by slot-layout key, guards against entangled cross-slot twins, and yields ranked `Arrangement`s. The TUI lists arrangements and shows a per-slot "Bids" block; the ballot view is made consistent by grouping twins by slot signature.

**Tech Stack:** Python ≥3.11, Textual, Rich, pytest. No new dependencies.

## Global Constraints

- **Enumeration unchanged.** Do NOT modify `enumerate_clashfree` or clash logic. Collapsing happens only over `space.combos` (already clash-free).
- **Soundness — entanglement guard:** within a slot-layout group, twins are collapsed into one arrangement with independent per-slot bids ONLY IF the number of clash-free combos equals the product of per-slot option counts. Otherwise (rare cross-module same-slot odd/even case) each combo stays its own arrangement. Every listed per-slot bid must appear in a genuinely clash-free timetable.
- **Each arrangement's `score`/`breakdown`/`assignment` is its BEST-scoring variant** (ties broken by smallest sorted class-number tuple, deterministically).
- **Bids list every BALLOTED slot** (`LESSON_ABBREV.get(lesson_type) in config.balloted_types`), each with its interchangeable `(class_no, week_label)` options; non-balloted/fixed slots are omitted from the Bids block.
- `week_label`: `""` for the full 13-week run, `"even wks"`/`"odd wks"` for pure even/odd sets, else compact `"wks 2,4,6"`.
- Show all arrangements by default; `config.top_n` becomes an optional cap (`0`/falsy → all).
- The week grid, warnings, and share URL continue to use the arrangement's representative assignment — those features must keep working unchanged.

---

### Task 1: `week_label` helper

**Files:**
- Modify: `optimiser/model.py` (add `week_label`)
- Test: `tests/test_model.py`

**Interfaces:**
- Produces: `week_label(weeks) -> str`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_model.py`:

```python
def test_week_label():
    from optimiser.model import week_label

    assert week_label(frozenset(range(1, 14))) == ""          # full run -> no label
    assert week_label(frozenset({2, 4, 6, 8, 10, 12})) == "even wks"
    assert week_label(frozenset({1, 3, 5, 7, 9, 11, 13})) == "odd wks"
    assert week_label(frozenset({1, 2, 5})) == "wks 1,2,5"    # irregular -> compact list
    assert week_label(frozenset()) == ""                      # empty -> no label
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_model.py::test_week_label -v`
Expected: FAIL with `ImportError: cannot import name 'week_label'`

- [ ] **Step 3: Implement `week_label`**

Add to `optimiser/model.py` (after `fmt_time`):

```python
def week_label(weeks) -> str:
    """Short human label for a session's teaching weeks: '' for the full 13-week
    run (or empty), 'even wks'/'odd wks' for pure even/odd sets, else a compact
    'wks 2,4,6'."""
    weeks = frozenset(weeks)
    if not weeks or weeks == frozenset(range(1, 14)):
        return ""
    ordered = sorted(weeks)
    if all(w % 2 == 0 for w in ordered):
        return "even wks"
    if all(w % 2 == 1 for w in ordered):
        return "odd wks"
    return "wks " + ",".join(str(w) for w in ordered)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/pytest tests/test_model.py::test_week_label -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add optimiser/model.py tests/test_model.py
git commit -m "feat: week_label helper for teaching-week patterns"
```

---

### Task 2: `rank_arrangements` grouping

**Files:**
- Modify: `optimiser/search.py` (add `SlotBid`, `Arrangement`, `_arrangement_key`, `_make_arrangement`, `rank_arrangements`)
- Test: `tests/test_search.py`

**Interfaces:**
- Consumes: `model.week_label` (Task 1), `EnumeratedSpace.combos`, `score_assignment`, `config.balloted_types`, `config.top_n`.
- Produces:
  - `SlotBid(module: str, lesson_type: str, options: tuple)` — `options` is a tuple of `(class_no, week_label)`.
  - `Arrangement(score: float, breakdown: dict, assignment: dict, bids: list, variant_count: int)`.
  - `rank_arrangements(space, config, limit=None) -> list[Arrangement]` sorted best-first.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_search.py` (imports `pytest`; add `Choice`, `Session` from `optimiser.model`, `EnumeratedSpace` and `rank_arrangements` from `optimiser.search`; the `config` fixture comes from `conftest.py`):

```python
from optimiser.model import Choice, Session
from optimiser.search import EnumeratedSpace, rank_arrangements

ALL_WEEKS = frozenset(range(1, 14))


def _space(*combos):
    return EnumeratedSpace(combos=tuple(combos), members={})


def test_rank_arrangements_collapses_week_twins(config):
    # ALPHA Tutorial twin at Mon 1400-1500: 01 odd weeks, 02 even weeks -> one
    # arrangement offering both class numbers with week labels.
    odd = frozenset({1, 3, 5})
    even = frozenset({2, 4, 6})
    lec = Choice("ALPHA", "Lecture", "1", (Session("Monday", 600, 720, ALL_WEEKS, "COM1"),))
    tut_odd = Choice("ALPHA", "Tutorial", "01", (Session("Monday", 840, 900, odd, "COM1"),))
    tut_even = Choice("ALPHA", "Tutorial", "02", (Session("Monday", 840, 900, even, "COM1"),))
    arrs = rank_arrangements(_space((lec, tut_odd), (lec, tut_even)), config)
    assert len(arrs) == 1
    a = arrs[0]
    assert a.variant_count == 2
    tut_bid = next(b for b in a.bids if b.lesson_type == "Tutorial")
    assert dict(tut_bid.options) == {"01": "odd wks", "02": "even wks"}
    # Lecture is not a balloted type -> not in the bids block
    assert all(b.lesson_type != "Lecture" for b in a.bids)


def test_rank_arrangements_keeps_entangled_variants_separate(config):
    # ALPHA Tutorial and BETA Laboratory BOTH at Mon 1400-1500 with odd/even
    # splits: only the opposite-week pairings are clash-free, so picking one twin
    # forces the other -> must NOT collapse into free per-slot bids.
    odd = frozenset({1, 3, 5})
    even = frozenset({2, 4, 6})
    a_odd = Choice("ALPHA", "Tutorial", "01", (Session("Monday", 840, 900, odd, "COM1"),))
    a_even = Choice("ALPHA", "Tutorial", "02", (Session("Monday", 840, 900, even, "COM1"),))
    b_odd = Choice("BETA", "Laboratory", "L1", (Session("Monday", 840, 900, odd, "COM2"),))
    b_even = Choice("BETA", "Laboratory", "L2", (Session("Monday", 840, 900, even, "COM2"),))
    arrs = rank_arrangements(_space((a_odd, b_even), (a_even, b_odd)), config)
    assert len(arrs) == 2  # entangled -> not collapsed
    assert all(a.variant_count == 1 for a in arrs)


def test_rank_arrangements_ranks_by_best_and_limits(config):
    # Two genuinely different arrangements (different tutorial days); the higher
    # scorer comes first; limit truncates.
    lec = Choice("ALPHA", "Lecture", "1", (Session("Monday", 600, 720, ALL_WEEKS, "COM1"),))
    tut_mon = Choice("ALPHA", "Tutorial", "01", (Session("Monday", 780, 840, ALL_WEEKS, "COM1"),))
    tut_fri = Choice("ALPHA", "Tutorial", "05", (Session("Friday", 780, 840, ALL_WEEKS, "COM1"),))
    arrs = rank_arrangements(_space((lec, tut_mon), (lec, tut_fri)), config)
    assert len(arrs) == 2
    assert arrs[0].score >= arrs[1].score          # best-first
    assert len(rank_arrangements(_space((lec, tut_mon), (lec, tut_fri)), config, limit=1)) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_search.py -k rank_arrangements -v`
Expected: FAIL with `ImportError: cannot import name 'rank_arrangements'`

- [ ] **Step 3: Implement the grouping in `search.py`**

Add to `optimiser/search.py`. First extend the model import (currently `from .model import LESSON_ABBREV, ChoiceGroup`) to include `week_label`:

```python
from .model import LESSON_ABBREV, ChoiceGroup, week_label
```

Then add these definitions (after `rank`):

```python
@dataclass(frozen=True)
class SlotBid:
    module: str
    lesson_type: str
    options: tuple  # ((class_no, week_label), ...), interchangeable twins at this slot


@dataclass
class Arrangement:
    score: float
    breakdown: dict
    assignment: dict       # representative (best variant) {(module, lesson_type): Choice}
    bids: list             # list[SlotBid], balloted slots only, sorted by (module, lesson_type)
    variant_count: int


def _arrangement_key(combo) -> frozenset:
    # Slot layout, ignoring class number AND weeks: two combos share a key iff
    # they occupy the same (module, type, day, start, end, online) slots.
    return frozenset(
        (c.module, c.lesson_type, s.day, s.start, s.end, s.online)
        for c in combo
        for s in c.sessions
    )


def _make_arrangement(entry, slot_opts, config, variant_count) -> "Arrangement":
    total, breakdown, assignment, _combo = entry
    bids = []
    for (module, lesson_type), by_no in slot_opts.items():
        if LESSON_ABBREV.get(lesson_type, lesson_type) not in config.balloted_types:
            continue
        options = tuple(
            (class_no, week_label(weeks)) for class_no, weeks in sorted(by_no.items())
        )
        bids.append(SlotBid(module, lesson_type, options))
    bids.sort(key=lambda b: (b.module, b.lesson_type))
    return Arrangement(
        score=total, breakdown=breakdown, assignment=assignment,
        bids=bids, variant_count=variant_count,
    )


def rank_arrangements(space, config, limit=None) -> list:
    """Collapse clash-free timetables that share a slot layout (differing only by
    interchangeable same-slot week-twins) into ranked Arrangements. Twins are
    offered as free per-slot bids only when the group's clash-free combos form a
    full Cartesian product; otherwise the combos are kept as separate
    arrangements (soundness — see design doc)."""
    scored = []  # (total, breakdown, assignment, combo)
    for combo in space.combos:
        total, breakdown = score_assignment(list(combo), config)
        assignment = {(c.module, c.lesson_type): c for c in combo}
        scored.append((total, breakdown, assignment, combo))

    groups: dict = {}
    for entry in scored:
        groups.setdefault(_arrangement_key(entry[3]), []).append(entry)

    arrangements = []
    for entries in groups.values():
        slot_opts: dict = {}  # (module, lesson_type) -> {class_no: weeks}
        for _t, _b, _a, combo in entries:
            for c in combo:
                slot_opts.setdefault((c.module, c.lesson_type), {})[c.class_no] = c.sessions[0].weeks
        product = 1
        for by_no in slot_opts.values():
            product *= len(by_no)
        if product == len(entries):  # independent -> collapse
            best = min(entries, key=lambda e: (-e[0], tuple(sorted(c.class_no for c in e[3]))))
            arrangements.append(_make_arrangement(best, slot_opts, config, len(entries)))
        else:  # entangled -> keep each combo as its own arrangement
            for entry in entries:
                single = {
                    (c.module, c.lesson_type): {c.class_no: c.sessions[0].weeks}
                    for c in entry[3]
                }
                arrangements.append(_make_arrangement(entry, single, config, 1))

    arrangements.sort(key=lambda a: -a.score)
    return arrangements[:limit] if limit else arrangements
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_search.py -k rank_arrangements -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Run the search suite**

Run: `.venv/bin/pytest tests/test_search.py -v`
Expected: PASS — existing search tests unaffected.

- [ ] **Step 6: Commit**

```bash
git add optimiser/search.py tests/test_search.py
git commit -m "feat: rank_arrangements collapses interchangeable week-twins"
```

---

### Task 3: Show arrangements + Bids block in the TUI

**Files:**
- Modify: `optimiser/tui/state.py` (add `top_arrangements`)
- Modify: `optimiser/tui/app.py` (list + detail + copy-link use arrangements; render Bids)
- Test: `tests/test_tui_app.py`, `tests/test_tui_state.py`

**Interfaces:**
- Consumes: `search.rank_arrangements` (Task 2), `Arrangement` fields.
- Produces: `AppState.top_arrangements() -> list[Arrangement]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tui_state.py` (it builds an `AppState` via the same pattern as `test_tui_app.py`; if it lacks a `state` fixture, construct with `AppState.from_parts(copy.deepcopy(config), groups)` using `build_groups`/`semester_timetable` as in `test_tui_app.py`):

```python
def test_top_arrangements_returns_arrangements(state):
    from optimiser.search import Arrangement

    arrs = state.top_arrangements()
    assert arrs and all(isinstance(a, Arrangement) for a in arrs)
    assert all(hasattr(a, "bids") and hasattr(a, "variant_count") for a in arrs)
```

Add to `tests/test_tui_app.py` (imports already include `Static`, `Console` locally per earlier tasks):

```python
async def test_detail_shows_bids_block(state, tmp_path):
    from rich.console import Console
    from textual.widgets import Static

    app = OptimiserApp(state, tmp_path / "config.yaml")
    async with app.run_test() as pilot:
        detail = app.query_one("#detail", Static)
        console = Console()
        with console.capture() as cap:
            console.print(detail._Static__content)  # textual 8.2.8: read raw stored content
        assert "Bids" in cap.get()  # the interchangeable-bids block is present
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_tui_state.py -k top_arrangements tests/test_tui_app.py -k bids -v`
Expected: FAIL — `AttributeError: 'AppState' object has no attribute 'top_arrangements'` and no "Bids" in the detail.

- [ ] **Step 3: Add cached `top_arrangements` to `AppState`**

In `optimiser/tui/state.py`, extend the search import (currently `from ..search import (EnumeratedSpace, enumerate_clashfree, find_irreconcilable, prepare_groups, rank)`) to also import `rank_arrangements`. Add an `arrangements` field to the `AppState` dataclass (next to `result: object = None`):

```python
    arrangements: list = None
```

Compute it in `retune` (so it's cached once per slider change, not re-scored on every detail refresh), alongside `result` which `ballot_options` still needs:

```python
    def retune(self):
        self.result = rank(self.space, self.config)
        self.arrangements = rank_arrangements(
            self.space, self.config, limit=self.config.top_n or None
        )
        return self.result
```

And add the accessor next to `top_timetables`:

```python
    def top_arrangements(self) -> list:
        return self.arrangements
```

- [ ] **Step 4: Render the Bids block in `app.py`**

In `optimiser/tui/app.py`, add a module-level helper (after the imports, before `OptimiserApp`):

```python
def _render_bids(arrangement) -> Text:
    """A 'Bids' block listing each balloted slot's interchangeable class numbers
    (with week labels) for the selected arrangement."""
    if not arrangement.bids:
        return Text("")
    lines = ["Bids (interchangeable per slot):"]
    for bid in arrangement.bids:
        abbrev = LESSON_ABBREV.get(bid.lesson_type, bid.lesson_type)
        opts = " / ".join(
            f"{class_no} ({label})" if label else class_no
            for class_no, label in bid.options
        )
        lines.append(f"  {bid.module} {abbrev}  →  {opts}")
    return Text("\n".join(lines), style="dim")
```

Add `LESSON_ABBREV` to the model import at the top of `app.py` if not present (currently `app.py` imports from `..output` and `.render`; add `from ..model import LESSON_ABBREV`).

Then rewire `_refresh_results` and `_refresh_detail`. Replace the body of `_refresh_results` (which iterates `self.state.top_timetables()`):

```python
    def _refresh_results(self) -> None:
        tt_list = self.query_one("#tt-list", ListView)
        tt_list.clear()
        top = self.state.top_arrangements()
        for i, arr in enumerate(top):
            variants = f"  ({arr.variant_count} variants)" if arr.variant_count > 1 else ""
            tt_list.append(ListItem(Label(f"#{i + 1}  {arr.score:+.1f}{variants}")))
        if self.selected >= len(top):
            self.selected = 0
        if top:
            tt_list.index = min(self.selected, len(top) - 1)
        self._refresh_detail()
```

Replace the timetable-mode tail of `_refresh_detail` (the `total, breakdown, assignment = top[self.selected]` block) with:

```python
        arr = top[self.selected]
        warnings = class_warnings(arr.assignment, self.state.config)
        if warnings:
            warning_block = Text("\n".join(warnings), style="dim yellow")
        else:
            warning_block = Text("✓ all criteria met", style="dim green")
        detail.update(
            Group(
                Text(render_breakdown(arr.score, arr.breakdown)),
                Text(""),
                render_week_rich(arr.assignment, self.colours),
                Text(""),
                warning_block,
                Text(""),
                _render_bids(arr),
                Text(""),
                Text(share_url(arr.assignment, self.state.config.semester)),
            )
        )
```

(The `top = self.state.top_arrangements()` call and the `if not top:` guard at the start of `_refresh_detail` replace the old `top_timetables()` call — update that line too.)

Finally, in `action_copy_link`, change the assignment source from `top_timetables()` to arrangements:

```python
    def action_copy_link(self) -> None:
        top = self.state.top_arrangements()
        if not top:
            return
        url = share_url(top[self.selected].assignment, self.state.config.semester)
        self.copy_to_clipboard(url)  # OSC-52 best-effort (SSH / capable terminals)
        if _os_clipboard_copy(url):
            self.notify("copied share link to clipboard")
        else:
            self.notify(f"copy unavailable — link: {url}", timeout=15)
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `.venv/bin/pytest tests/test_tui_state.py -k top_arrangements tests/test_tui_app.py -k bids -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS — the ballot view and other TUI tests still pass (ballot uses `result`, untouched).

- [ ] **Step 7: Commit**

```bash
git add optimiser/tui/state.py optimiser/tui/app.py tests/test_tui_state.py tests/test_tui_app.py
git commit -m "feat: TUI lists distinct arrangements with an interchangeable-bids block"
```

---

### Task 4: Ballot view groups twins by slot signature

**Files:**
- Modify: `optimiser/ballot.py` (`ranked_options` groups by slot signature, annotates week labels)
- Test: `tests/test_ballot.py`

**Interfaces:**
- Consumes: `model.week_label` (Task 1), `result.members` (footprint-keyed), `result.best_by_footprint`.

- [ ] **Step 1: Write the failing test**

Inspect `tests/test_ballot.py` for its existing fixtures/helpers first. Add a test that two same-slot different-week footprints for one group collapse into a single ballot option whose `tied_with` includes the twin's class number. Use the module's existing helper style; concretely:

```python
def test_ranked_options_groups_week_twins(config):
    from optimiser.model import Choice, Session
    from optimiser.search import SearchResult
    from optimiser.ballot import ranked_options

    odd = frozenset({1, 3, 5})
    even = frozenset({2, 4, 6})
    c_odd = Choice("ALPHA", "Tutorial", "01", (Session("Monday", 840, 900, odd, "COM1"),))
    c_even = Choice("ALPHA", "Tutorial", "02", (Session("Monday", 840, 900, even, "COM1"),))
    members = {
        ("ALPHA", "Tutorial"): {c_odd.footprint: [c_odd], c_even.footprint: [c_even]}
    }
    best = {
        ("ALPHA", "Tutorial", c_odd.footprint): 5.0,
        ("ALPHA", "Tutorial", c_even.footprint): 5.0,
    }
    result = SearchResult(top=[], best_by_footprint=best, members=members, evaluated=2)
    options = ranked_options(result, config)[("ALPHA", "Tutorial")]
    # 01 and 02 are the same slot (Mon 1400-1500), different weeks -> interchangeable
    first = options[0]
    assert "02" in first.tied_with or "01" in first.tied_with
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_ballot.py -k week_twins -v`
Expected: FAIL — current `ranked_options` keys on exact footprint, so 01 and 02 are separate options and neither is in the other's `tied_with`.

- [ ] **Step 3: Group by slot signature in `ranked_options`**

In `optimiser/ballot.py`, extend the import (currently `from .model import LESSON_ABBREV`) to `from .model import LESSON_ABBREV, week_label`. Replace the per-footprint aggregation loop in `ranked_options` (the `scored = []` / `for fp, choices in fp_members.items()` block) with a slot-signature grouping that merges footprints sharing `(day, start, end, online)`:

```python
        # Merge footprints that share a slot signature (day/time/online), so
        # same-slot week-twins are interchangeable in the ballot too.
        by_slot: dict = {}
        for fp, choices in fp_members.items():
            best = result.best_by_footprint.get((module, lesson_type, fp))
            if best is None:
                continue  # never part of any clash-free timetable
            sig = frozenset((s.day, s.start, s.end, s.online) for s in choices[0].sessions)
            slot = by_slot.setdefault(sig, {"best": best, "choices": []})
            slot["best"] = max(slot["best"], best)
            slot["choices"].extend(choices)
        scored = [(slot["best"], slot["choices"]) for slot in by_slot.values()]
        scored.sort(key=lambda item: (-item[0], item[1][0].class_no))
```

The existing option-building loop below (`for best, choices in scored:` … `class_nos = [c.class_no for c in choices]` … `tied_with=[n for n in class_nos if n != c.class_no]`) is unchanged and now naturally lists twins as interchangeable. Optionally, annotate the week pattern by extending the emitted option — but keep `BallotOption`'s shape; week labels surface via the arrangement Bids block (Task 3), so no `BallotOption` change is required here.

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/pytest tests/test_ballot.py -k week_twins -v`
Expected: PASS.

- [ ] **Step 5: Run the ballot + full suite**

Run: `.venv/bin/pytest tests/test_ballot.py -v && .venv/bin/pytest -q`
Expected: PASS — existing ballot tests still green (same-footprint tie-grouping is a subset of slot-signature grouping).

- [ ] **Step 6: Commit**

```bash
git add optimiser/ballot.py tests/test_ballot.py
git commit -m "feat: ballot groups interchangeable same-slot week-twins"
```

---

## Self-review

- **Coverage:** slot-layout grouping + entanglement guard + best-variant ranking (Task 2); `week_label` (Task 1); show-all + Bids block + list variants suffix (Task 3); ballot twin-grouping (Task 4). Each spec section maps to a task.
- **Placeholders:** none — full code for every code step (Task 4 Step 1 references reading the existing test file first, but supplies a complete concrete test).
- **Type/name consistency:** `Arrangement`/`SlotBid` fields used in Task 3 match Task 2's definitions; `rank_arrangements(space, config, limit=None)` signature consistent across `state.py` and tests; `week_label` used in Tasks 2 and 4 matches Task 1.
