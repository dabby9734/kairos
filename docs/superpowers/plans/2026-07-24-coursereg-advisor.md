# CourseReg Advisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `kairos advise` what-if TUI that turns CourseRekt's frozen demand
history into per-course standings and a leverage-ordered Rank 1–8 suggestion
for NUS CourseReg Rounds 2/3.

**Architecture:** New subsystem `kairos/coursereg/` mirroring the house stance:
pure core (`model.py`, `advisor.py`), one network edge (`fetch.py`, permanent
cache — the source is archived and frozen), and a Textual TUI split into a
Textual-free `AdvisorState` plus an `AdvisorApp`. Spec:
`docs/superpowers/specs/2026-07-24-coursereg-advisor-design.md`.

**Tech Stack:** Python 3.11+, stdlib `html.parser` (no new dependencies),
requests (already a dep), PyYAML, Textual, pytest (+pytest-asyncio,
`asyncio_mode = "auto"` — async tests need no marker).

## Global Constraints

- Pure core: `coursereg/model.py` and `coursereg/advisor.py` do no I/O of any
  kind. `coursereg/tui/state.py` imports no Textual.
- Every sort has an explicit deterministic tiebreak (course code here).
- User-facing errors: `raise SystemExit("error: ...")`.
- No terminal blink (SGR 5); selection affordances use reverse video.
- No new dependencies — HTML parsing uses stdlib `html.parser`.
- No changes to the existing timetable core
  (`kairos/{model,scoring,search,ballot,provenance}.py`) or its tests.
- Commit prefixes `feat:`/`test:`/`docs:`; every commit ends with trailer
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Run the focused test while iterating; the full suite
  (`.venv/bin/pytest -q`, 260 passing before this plan) once before each
  commit.
- Two spec clarifications locked here (both consistent with the spec's
  intent): (1) `coursereg.yaml` carries a `semester:` key — the advisor needs
  to know which semester is being planned for the same-semester rule; (2) a
  `ranked: true` flag is written on save, so a saved ranking is honoured on
  relaunch while a fresh config opens in the advisor's suggested order.

## Verified source facts (fetched 2026-07-24 — do not re-derive)

- `POST https://courserekt.vercel.app/` with form fields
  `year=2526&semester=1&type=ug` returns a ~2.8 MB HTML page containing
  `<table id="table-data">` covering every UG course for that semester.
- `<thead>` row: `Code`, `Name`, `Class`, then one `th.table-round` per round,
  each containing `<a ...>Round N</a>` (years before AY24/25 include Round 0).
- `<tbody>` rows are per **class group** (`L1`, `L2`, …), not per course:
  `td[0]` course code, `td[1]` name link, `td[2]` class, then one td per
  round whose text is `x / y` followed by `<span class='vacancy-data'>(z)</span>`.
  `x` = demand, `y` = vacancy per the CourseReg PDF; `z` (the Vacancy-PDF
  figure) is ignored. Sentinels: `N/A` (td has class `no-data`) and `∞`
  (unlimited vacancy).
- Available data: years `2122 2223 2324 2425 2526` × semesters 1–2, UG.
  Frozen forever (upstream archived 2026-01-10).

---

### Task 1: `coursereg/model.py` — records, profile, config round-trip

**Files:**
- Create: `kairos/coursereg/__init__.py` (empty)
- Create: `kairos/coursereg/model.py`
- Test: `tests/test_coursereg_model.py`

**Interfaces:**
- Produces (used by every later task):
  - `UNLIMITED: int = 2_147_483_647` (vacancy sentinel, mirrors upstream)
  - `RANK_CAP: int = 8`; `TIERS: tuple = ("core", "major", "ue")`
  - `DemandRecord(course: str, acad_year: str, semester: int, round: int,
    demand: int | None, vacancy: int | None)` — frozen dataclass;
    `acad_year` is the short form `"2526"`.
  - `Profile(seniority: int, semester: int, round: int,
    tiers: dict[str, str], order: list[str], ranked: bool)` — mutable
    dataclass (the TUI edits round/tiers/order).
  - `profile_from_dict(data, source: str = "coursereg.yaml") -> Profile`
  - `load_profile(path: Path) -> Profile`
  - `profile_to_yaml(profile: Profile) -> str` (exact inverse of the loader;
    key order of `candidates` = `profile.order`)
  - `TEMPLATE: str` — the example config printed on missing file

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_coursereg_model.py
import pytest
import yaml


def make_profile_dict():
    return {
        "seniority": 2,
        "semester": 1,
        "round": 2,
        "candidates": {"CS2109S": "major", "GEH1049": "ue", "IS2218": "ue"},
    }


def test_profile_from_dict_parses_fields():
    from kairos.coursereg.model import profile_from_dict

    p = profile_from_dict(make_profile_dict())
    assert (p.seniority, p.semester, p.round) == (2, 1, 2)
    assert p.tiers == {"CS2109S": "major", "GEH1049": "ue", "IS2218": "ue"}
    assert p.order == ["CS2109S", "GEH1049", "IS2218"]  # mapping order = rank order
    assert p.ranked is False


def test_profile_from_dict_uppercases_course_codes():
    from kairos.coursereg.model import profile_from_dict

    d = make_profile_dict()
    d["candidates"] = {"cs2109s": "major"}
    p = profile_from_dict(d)
    assert p.order == ["CS2109S"] and "CS2109S" in p.tiers


@pytest.mark.parametrize(
    "key,value,fragment",
    [
        ("seniority", 5, "seniority"),
        ("seniority", 0, "seniority"),
        ("semester", 3, "semester"),
        ("round", 1, "round"),
        ("round", 4, "round"),
    ],
)
def test_profile_from_dict_rejects_out_of_range(key, value, fragment):
    from kairos.coursereg.model import profile_from_dict

    d = make_profile_dict()
    d[key] = value
    with pytest.raises(SystemExit) as exc:
        profile_from_dict(d)
    assert fragment in str(exc.value)


def test_profile_from_dict_rejects_bad_tier_and_empty_candidates():
    from kairos.coursereg.model import profile_from_dict

    d = make_profile_dict()
    d["candidates"] = {"CS2109S": "corr"}
    with pytest.raises(SystemExit):
        profile_from_dict(d)
    d["candidates"] = {}
    with pytest.raises(SystemExit):
        profile_from_dict(d)


def test_load_profile_missing_file_prints_template(tmp_path):
    from kairos.coursereg.model import TEMPLATE, load_profile

    with pytest.raises(SystemExit) as exc:
        load_profile(tmp_path / "coursereg.yaml")
    assert "error:" in str(exc.value) and TEMPLATE in str(exc.value)


def test_yaml_round_trip_preserves_order_and_ranked(tmp_path):
    from kairos.coursereg.model import load_profile, profile_from_dict, profile_to_yaml

    p = profile_from_dict(make_profile_dict())
    p.order = ["IS2218", "CS2109S", "GEH1049"]  # user reordered
    p.ranked = True
    path = tmp_path / "coursereg.yaml"
    path.write_text(profile_to_yaml(p))
    again = load_profile(path)
    assert again.order == ["IS2218", "CS2109S", "GEH1049"]
    assert again.ranked is True and again.tiers == p.tiers


def test_template_is_loadable_yaml():
    from kairos.coursereg.model import TEMPLATE, profile_from_dict

    p = profile_from_dict(yaml.safe_load(TEMPLATE))
    assert p.order  # template parses into a valid profile
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_coursereg_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kairos.coursereg'`

- [ ] **Step 3: Implement**

Create empty `kairos/coursereg/__init__.py`, then:

```python
# kairos/coursereg/model.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# Mirrors upstream CourseRekt's INF sentinel for unlimited-vacancy rows.
UNLIMITED = 2_147_483_647
# CourseReg's C tier has exactly 8 rank preferences.
RANK_CAP = 8
TIERS = ("core", "major", "ue")

TEMPLATE = """\
seniority: 2            # your year of study, 1-4
semester: 1             # semester you are planning (1 or 2)
round: 2                # CourseReg round being planned (2 or 3)
candidates:
  CS2109S: major        # course code: your requirement tier (core | major | ue)
  GEH1049: ue
"""


@dataclass(frozen=True)
class DemandRecord:
    course: str
    acad_year: str  # short form, e.g. "2526"
    semester: int
    round: int
    demand: int | None
    vacancy: int | None  # UNLIMITED for unlimited-vacancy rows


@dataclass
class Profile:
    # Deliberately NOT frozen: the TUI mutates round, tiers, and order.
    seniority: int
    semester: int
    round: int
    tiers: dict  # course -> "core" | "major" | "ue"
    order: list  # current rank order; first RANK_CAP entries get ranks
    ranked: bool = False  # True once the TUI has saved a ranking


def profile_from_dict(data, source: str = "coursereg.yaml") -> Profile:
    if not isinstance(data, dict):
        raise SystemExit(f"error: {source} is empty or not a YAML mapping")
    for key in ("seniority", "semester", "round", "candidates"):
        if key not in data:
            raise SystemExit(f"error: {source} is missing required key '{key}'")
    seniority = int(data["seniority"])
    if not 1 <= seniority <= 4:
        raise SystemExit(f"error: seniority must be 1-4, got {seniority}")
    semester = int(data["semester"])
    if semester not in (1, 2):
        raise SystemExit(f"error: semester must be 1 or 2, got {semester}")
    rnd = int(data["round"])
    if rnd not in (2, 3):
        raise SystemExit(f"error: round must be 2 or 3, got {rnd}")
    raw = data["candidates"]
    if not isinstance(raw, dict) or not raw:
        raise SystemExit(f"error: {source} needs a non-empty 'candidates' mapping")
    tiers = {}
    for code, tier in raw.items():
        if tier not in TIERS:
            raise SystemExit(
                f"error: tier for {code} must be one of {', '.join(TIERS)}, got {tier!r}"
            )
        tiers[str(code).upper()] = tier
    return Profile(
        seniority=seniority,
        semester=semester,
        round=rnd,
        tiers=tiers,
        order=list(tiers),
        ranked=bool(data.get("ranked", False)),
    )


def load_profile(path: Path) -> Profile:
    if not path.exists():
        raise SystemExit(
            f"error: {path} not found — create it, for example:\n\n{TEMPLATE}"
        )
    return profile_from_dict(yaml.safe_load(path.read_text()), str(path))


def profile_to_yaml(profile: Profile) -> str:
    data = {
        "seniority": profile.seniority,
        "semester": profile.semester,
        "round": profile.round,
        "ranked": profile.ranked,
        "candidates": {code: profile.tiers[code] for code in profile.order},
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_coursereg_model.py -v`
Expected: all PASS. Then `.venv/bin/pytest -q` — 260 + new all passing.

- [ ] **Step 5: Commit**

```bash
git add kairos/coursereg/__init__.py kairos/coursereg/model.py tests/test_coursereg_model.py
git commit -m "feat: add coursereg records and profile config round-trip

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `coursereg/fetch.py` parser — CourseRekt HTML → DemandRecords

**Files:**
- Create: `kairos/coursereg/fetch.py` (parser half only; Task 3 adds fetching)
- Create: `tests/data/courserekt_sample.html`
- Test: `tests/test_coursereg_fetch.py`

**Interfaces:**
- Consumes: `DemandRecord`, `UNLIMITED` from `kairos.coursereg.model` (Task 1).
- Produces: `parse_history_html(html: str, acad_year: str, semester: int) ->
  list[DemandRecord]` — one record per (course, round) with class rows merged;
  (course, round) pairs whose cells are all `N/A` yield **no** record.

- [ ] **Step 1: Create the golden fixture**

`tests/data/courserekt_sample.html` — a trimmed excerpt matching the real
page structure (verified 2026-07-24; whitespace and the surrounding
boilerplate are irrelevant to the parser):

```html
<!DOCTYPE html>
<html lang="en">
<head><title>CourseRekt</title></head>
<body>
<div class="table-container">
<table id="table-data">
  <thead>
    <tr>
      <th class="table-code">Code</th>
      <th class="table-name">Name</th>
      <th class="table-class">Class</th>
      <th class='table-round'>
        <a href="/pdfs/2526/1/ug/round_1.pdf" target="_blank">Round 1</a>
      </th>
      <th class='table-round'>
        <a href="/pdfs/2526/1/ug/round_2.pdf" target="_blank">Round 2</a>
      </th>
      <th class='table-round'>
        <a href="/pdfs/2526/1/ug/round_3.pdf" target="_blank">Round 3</a>
      </th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>CS2109S</td>
      <td>
        <a href="https://nusmods.com/courses/CS2109S">Introduction to AI and Machine Learning</a>
      </td>
      <td>L1</td>
      <td class="more-demand">
        207 / 200
        <span class='vacancy-data'>(200)</span>
      </td>
      <td class="more-demand">
        17 / 13
        <span class='vacancy-data'>(4)</span>
      </td>
      <td class="more-demand">
        5 / 0
        <span class='vacancy-data'>(0)</span>
      </td>
    </tr>
    <tr>
      <td>CS2109S</td>
      <td><a href="https://nusmods.com/courses/CS2109S">Introduction to AI and Machine Learning</a></td>
      <td>L2</td>
      <td class="less-demand">
        50 / 100
        <span class='vacancy-data'>(80)</span>
      </td>
      <td class="no-data">
        N/A
      </td>
      <td class="less-demand">
        3 / 10
        <span class='vacancy-data'>(7)</span>
      </td>
    </tr>
    <tr>
      <td>GEQ1000</td>
      <td><a href="https://nusmods.com/courses/GEQ1000">Asking Questions</a></td>
      <td>L1</td>
      <td class="less-demand">
        108 / ∞
        <span class='vacancy-data'>(∞)</span>
      </td>
      <td class="less-demand">
        1 / ∞
        <span class='vacancy-data'>(∞)</span>
      </td>
      <td class="no-data">
        N/A
      </td>
    </tr>
    <tr>
      <td>XX1000</td>
      <td><a href="https://nusmods.com/courses/XX1000">Ghost Course</a></td>
      <td>L1</td>
      <td class="no-data">N/A</td>
      <td class="no-data">N/A</td>
      <td class="no-data">N/A</td>
    </tr>
  </tbody>
</table>
</div>
</body>
</html>
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_coursereg_fetch.py
from pathlib import Path

from kairos.coursereg.model import UNLIMITED, DemandRecord

SAMPLE = (Path(__file__).parent / "data" / "courserekt_sample.html").read_text()


def by_key(records):
    return {(r.course, r.round): r for r in records}


def test_parse_merges_class_rows_per_course_round():
    from kairos.coursereg.fetch import parse_history_html

    recs = by_key(parse_history_html(SAMPLE, "2526", 1))
    # L1 207/200 + L2 50/100 summed
    assert recs[("CS2109S", 1)] == DemandRecord("CS2109S", "2526", 1, 1, 257, 300)
    # L2 round-2 cell is N/A: skipped, not zeroed
    assert recs[("CS2109S", 2)] == DemandRecord("CS2109S", "2526", 1, 2, 17, 13)
    assert recs[("CS2109S", 3)] == DemandRecord("CS2109S", "2526", 1, 3, 8, 10)


def test_parse_unlimited_vacancy_sentinel():
    from kairos.coursereg.fetch import parse_history_html

    recs = by_key(parse_history_html(SAMPLE, "2526", 1))
    assert recs[("GEQ1000", 1)].vacancy == UNLIMITED
    assert recs[("GEQ1000", 1)].demand == 108
    assert recs[("GEQ1000", 2)].vacancy == UNLIMITED


def test_parse_all_na_yields_no_record():
    from kairos.coursereg.fetch import parse_history_html

    recs = by_key(parse_history_html(SAMPLE, "2526", 1))
    assert ("GEQ1000", 3) not in recs
    assert not any(course == "XX1000" for course, _ in recs)


def test_parse_records_carry_year_and_semester():
    from kairos.coursereg.fetch import parse_history_html

    recs = parse_history_html(SAMPLE, "2324", 2)
    assert all(r.acad_year == "2324" and r.semester == 2 for r in recs)


def test_parse_unrecognisable_structure_raises():
    import pytest

    from kairos.coursereg.fetch import parse_history_html

    with pytest.raises(SystemExit) as exc:
        parse_history_html("<html><body>maintenance</body></html>", "2526", 1)
    assert "error:" in str(exc.value)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_coursereg_fetch.py -v`
Expected: FAIL — `No module named 'kairos.coursereg.fetch'`

- [ ] **Step 4: Implement the parser**

```python
# kairos/coursereg/fetch.py
from __future__ import annotations

import re
from html.parser import HTMLParser

from .model import UNLIMITED, DemandRecord

# First "x / y" in a round cell; the trailing "(z)" span (Vacancy-PDF figure)
# is deliberately not captured.
_CELL_RE = re.compile(r"(\d+|∞)\s*/\s*(\d+|∞)")
_ROUND_RE = re.compile(r"Round\s+(\d)")


class _TableParser(HTMLParser):
    """Collects the round numbers from <th class='table-round'> headers and the
    raw text of every <td> per <tbody> row of table#table-data."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_table = False
        self.in_round_th = False
        self.in_td = False
        self.rounds: list[int] = []
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table" and attrs.get("id") == "table-data":
            self.in_table = True
        elif self.in_table and tag == "th" and "table-round" in (attrs.get("class") or ""):
            self.in_round_th = True
            self._text = []
        elif self.in_table and tag == "tr":
            self._row = []
        elif self.in_table and tag == "td":
            self.in_td = True
            self._text = []

    def handle_endtag(self, tag):
        if tag == "table":
            self.in_table = False
        elif tag == "th" and self.in_round_th:
            self.in_round_th = False
            match = _ROUND_RE.search(" ".join(self._text))
            if match:
                self.rounds.append(int(match.group(1)))
        elif tag == "td" and self.in_td:
            self.in_td = False
            assert self._row is not None
            self._row.append(" ".join(self._text))
        elif tag == "tr" and self._row:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self.in_round_th or self.in_td:
            self._text.append(data.strip())


def _cell_values(text: str) -> tuple[int | None, int | None]:
    match = _CELL_RE.search(text)
    if not match:  # N/A or empty
        return None, None
    demand_raw, vacancy_raw = match.groups()
    # A literal ∞ demand does not occur in the data; treat it as missing.
    demand = None if demand_raw == "∞" else int(demand_raw)
    vacancy = UNLIMITED if vacancy_raw == "∞" else int(vacancy_raw)
    return demand, vacancy


def parse_history_html(html: str, acad_year: str, semester: int) -> list[DemandRecord]:
    parser = _TableParser()
    parser.feed(html)
    if not parser.rounds or not parser.rows:
        raise SystemExit(
            "error: courserekt page has no recognisable history table — "
            "the site may have changed; try --refetch"
        )
    # (course, round) -> [demand_sum, vacancy_sum, any_unlimited, any_numeric]
    merged: dict = {}
    for row in parser.rows:
        if len(row) < 3 + len(parser.rounds):
            continue  # defensive: malformed row
        course = row[0].strip().upper()
        for offset, rnd in enumerate(parser.rounds):
            demand, vacancy = _cell_values(row[3 + offset])
            if demand is None and vacancy is None:
                continue  # N/A cell: skipped, never imputed
            slot = merged.setdefault((course, rnd), [0, 0, False, False])
            slot[3] = True
            if demand is not None:
                slot[0] += demand
            if vacancy == UNLIMITED:
                slot[2] = True
            elif vacancy is not None:
                slot[1] += vacancy
    records = [
        DemandRecord(
            course=course,
            acad_year=acad_year,
            semester=semester,
            round=rnd,
            demand=demand_sum,
            vacancy=UNLIMITED if any_unlimited else vacancy_sum,
        )
        for (course, rnd), (demand_sum, vacancy_sum, any_unlimited, has_data) in merged.items()
        if has_data
    ]
    # Deterministic output order: course code, then round.
    return sorted(records, key=lambda r: (r.course, r.round))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_coursereg_fetch.py -v`
Expected: all PASS. Then `.venv/bin/pytest -q` — all passing.

- [ ] **Step 6: Commit**

```bash
git add kairos/coursereg/fetch.py tests/data/courserekt_sample.html tests/test_coursereg_fetch.py
git commit -m "feat: parse courserekt history tables into demand records

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `coursereg/fetch.py` — fetch, permanent cache, `load_history`

**Files:**
- Modify: `kairos/coursereg/fetch.py` (append; parser from Task 2 unchanged)
- Test: `tests/test_coursereg_fetch.py` (append)

**Interfaces:**
- Consumes: `parse_history_html` (Task 2), `DemandRecord` (Task 1).
- Produces:
  - `COURSEREKT_URL = "https://courserekt.vercel.app/"`
  - `YEARS: tuple = ("2122", "2223", "2324", "2425", "2526")`
  - `fetch_semester(acad_year: str, semester: int) -> str` (raw HTML;
    raises `requests.RequestException` upward)
  - `load_history(cache_dir: Path, refetch: bool = False) ->
    list[DemandRecord]` — all 10 semesters, cache-first, **no TTL**.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_coursereg_fetch.py`:

```python
def _fake_fetch_factory(calls):
    def fake_fetch(acad_year, semester):
        calls.append((acad_year, semester))
        return SAMPLE  # every semester serves the fixture page
    return fake_fetch


def test_load_history_fetches_all_semesters_and_caches(tmp_path, monkeypatch):
    from kairos.coursereg import fetch

    calls = []
    monkeypatch.setattr(fetch, "fetch_semester", _fake_fetch_factory(calls))
    records = fetch.load_history(tmp_path)
    assert len(calls) == 10  # 5 years x 2 semesters
    assert len(list(tmp_path.glob("*.json"))) == 10
    # 3 fixture courses with data x 10 semesters... CS2109S has 3 rounds,
    # GEQ1000 has 2, XX1000 none -> 5 records per semester
    assert len(records) == 50

    # Second call: pure cache, no fetches — the source is frozen, no TTL.
    calls.clear()
    again = fetch.load_history(tmp_path)
    assert calls == [] and again == records


def test_load_history_refetch_forces_network(tmp_path, monkeypatch):
    from kairos.coursereg import fetch

    calls = []
    monkeypatch.setattr(fetch, "fetch_semester", _fake_fetch_factory(calls))
    fetch.load_history(tmp_path)
    calls.clear()
    fetch.load_history(tmp_path, refetch=True)
    assert len(calls) == 10


def test_load_history_unreachable_without_cache_exits(tmp_path, monkeypatch):
    import pytest
    import requests

    from kairos.coursereg import fetch

    def down(acad_year, semester):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(fetch, "fetch_semester", down)
    with pytest.raises(SystemExit) as exc:
        fetch.load_history(tmp_path)
    message = str(exc.value)
    assert "error:" in message and str(tmp_path) in message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_coursereg_fetch.py -v -k load_history`
Expected: FAIL — `module 'kairos.coursereg.fetch' has no attribute 'load_history'`

- [ ] **Step 3: Implement**

Append to `kairos/coursereg/fetch.py` (add `import json`, `from dataclasses
import asdict`, `from pathlib import Path`, `import requests` to the imports):

```python
COURSEREKT_URL = "https://courserekt.vercel.app/"
YEARS = ("2122", "2223", "2324", "2425", "2526")


def fetch_semester(acad_year: str, semester: int) -> str:
    resp = requests.post(
        COURSEREKT_URL,
        data={"year": acad_year, "semester": str(semester), "type": "ug"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.text


def load_history(cache_dir: Path, refetch: bool = False) -> list[DemandRecord]:
    """All UG demand records across every archived semester. Cache-first with
    NO TTL: the upstream project is archived and its data frozen, so a cache
    hit is always valid. `refetch` exists only as a repair hatch."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    records: list[DemandRecord] = []
    for acad_year in YEARS:
        for semester in (1, 2):
            cache_file = cache_dir / f"{acad_year}-{semester}.json"
            if cache_file.exists() and not refetch:
                rows = json.loads(cache_file.read_text())
                records.extend(DemandRecord(**row) for row in rows)
                continue
            try:
                html = fetch_semester(acad_year, semester)
            except requests.RequestException as exc:
                raise SystemExit(
                    f"error: courserekt.vercel.app unreachable and no cached data in "
                    f"{cache_dir} — copy a friend's cache there (the data is frozen "
                    f"and identical for everyone): {exc}"
                )
            parsed = parse_history_html(html, acad_year, semester)
            cache_file.write_text(json.dumps([asdict(r) for r in parsed]))
            records.extend(parsed)
    return records
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_coursereg_fetch.py -v`
Expected: all PASS. Then `.venv/bin/pytest -q` — all passing.

- [ ] **Step 5: Commit**

```bash
git add kairos/coursereg/fetch.py tests/test_coursereg_fetch.py
git commit -m "feat: fetch and permanently cache courserekt demand history

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `coursereg/advisor.py` — verdicts, nudges, suggested order, warnings

**Files:**
- Create: `kairos/coursereg/advisor.py`
- Test: `tests/test_coursereg_advisor.py`

**Interfaces:**
- Consumes: `DemandRecord`, `Profile`, `UNLIMITED`, `RANK_CAP` (Task 1).
- Produces (Task 5's `AdvisorState` calls exactly these):
  - Standing strings `SAFE, LIKELY, CONTESTED, TOUGH, LONG_SHOT, NO_DATA`
    and `BANDS = [SAFE, LIKELY, CONTESTED, TOUGH, LONG_SHOT]`
  - Constants `RECENT_YEARS = 3`, `SAFE_MEDIAN_MAX = 0.85`,
    `LONG_SHOT_MEDIAN_MIN = 1.5`, `TOP_RANKS = 3`
  - `Verdict(course: str, standing: str, reasoning: str)` — frozen dataclass
  - `ratio(demand, vacancy) -> float | None`
  - `same_sem_ratios(records, course, semester, rnd) ->
    list[tuple[str, float]]` (year-ascending, `None` ratios dropped)
  - `base_verdict(ratios: list[tuple[str, float]]) -> str`
  - `nudge_steps(tier: str, seniority: int) -> int` (clamped to −1..+1)
  - `verdict(records, course, profile) -> Verdict`
  - `suggested_order(standings: dict[str, str]) -> list[str]`
  - `leverage_warnings(order: list[str], standings: dict[str, str]) ->
    list[str]`
  - `dossier_rows(records, course, rnd, semester) ->
    tuple[list[DemandRecord], list[DemandRecord]]` (same-sem, other-sem;
    each year-descending)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_coursereg_advisor.py
import math

from kairos.coursereg.model import UNLIMITED, DemandRecord, Profile


def rec(course, year, sem, rnd, demand, vacancy):
    return DemandRecord(course, year, sem, rnd, demand, vacancy)


def profile(**kw):
    base = dict(seniority=2, semester=1, round=2,
                tiers={"AAA1000": "major"}, order=["AAA1000"], ranked=False)
    base.update(kw)
    return Profile(**base)


def history(course, ratios_by_year, sem=1, rnd=2):
    """ratios expressed as (demand, vacancy) pairs keyed by year."""
    return [rec(course, year, sem, rnd, d, v) for year, (d, v) in ratios_by_year.items()]


def test_ratio_edge_cases():
    from kairos.coursereg.advisor import ratio

    assert ratio(50, 100) == 0.5
    assert ratio(None, 100) is None and ratio(50, None) is None
    assert ratio(108, UNLIMITED) == 0.0
    assert ratio(5, 0) == math.inf
    assert ratio(0, 0) is None


def test_base_verdict_bands():
    from kairos.coursereg.advisor import (
        CONTESTED, LONG_SHOT, NO_DATA, SAFE, base_verdict, same_sem_ratios,
    )

    safe = history("AAA1000", {"2324": (40, 100), "2425": (50, 100), "2526": (60, 100)})
    contested = history("AAA1000", {"2324": (90, 100), "2425": (110, 100), "2526": (95, 100)})
    long_shot = history("AAA1000", {"2324": (200, 100), "2425": (180, 100), "2526": (210, 100)})

    assert base_verdict(same_sem_ratios(safe, "AAA1000", 1, 2)) == SAFE
    assert base_verdict(same_sem_ratios(contested, "AAA1000", 1, 2)) == CONTESTED
    assert base_verdict(same_sem_ratios(long_shot, "AAA1000", 1, 2)) == LONG_SHOT
    assert base_verdict([]) == NO_DATA


def test_base_verdict_uses_only_recent_years():
    from kairos.coursereg.advisor import SAFE, base_verdict, same_sem_ratios

    # Ancient oversubscription beyond RECENT_YEARS=3 must not spoil SAFE.
    records = history("AAA1000", {
        "2122": (300, 100),
        "2324": (40, 100), "2425": (50, 100), "2526": (60, 100),
    })
    assert base_verdict(same_sem_ratios(records, "AAA1000", 1, 2)) == SAFE


def test_same_sem_ratios_filters_semester_and_round():
    from kairos.coursereg.advisor import same_sem_ratios

    records = [
        rec("AAA1000", "2526", 1, 2, 50, 100),
        rec("AAA1000", "2526", 2, 2, 999, 100),  # other semester
        rec("AAA1000", "2526", 1, 3, 999, 100),  # other round
        rec("BBB1000", "2526", 1, 2, 999, 100),  # other course
    ]
    assert same_sem_ratios(records, "AAA1000", 1, 2) == [("2526", 0.5)]


def test_nudge_steps_table():
    from kairos.coursereg.advisor import nudge_steps

    assert nudge_steps("core", 2) == -1   # toward safe
    assert nudge_steps("major", 2) == 0
    assert nudge_steps("ue", 2) == 1      # toward long-shot
    assert nudge_steps("ue", 4) == 0      # Y3/Y4 seniority cancels the UE hit
    assert nudge_steps("ue", 1) == 1      # Y1 + ue clamped at +1, never +2
    assert nudge_steps("core", 1) == -1   # seniority only applies to ue tier


def test_verdict_five_bands_and_reasoning():
    from kairos.coursereg.advisor import CONTESTED, LIKELY, TOUGH, verdict

    contested = history("AAA1000", {"2324": (90, 100), "2425": (110, 100), "2526": (95, 100)})
    v_major = verdict(contested, "AAA1000", profile(tiers={"AAA1000": "major"}))
    v_core = verdict(contested, "AAA1000", profile(tiers={"AAA1000": "core"}))
    v_ue = verdict(contested, "AAA1000", profile(tiers={"AAA1000": "ue"}))
    assert v_major.standing == CONTESTED
    assert v_core.standing == LIKELY
    assert v_ue.standing == TOUGH
    assert "oversubscribed" in v_major.reasoning


def test_verdict_no_data_for_unknown_course():
    from kairos.coursereg.advisor import NO_DATA, verdict

    v = verdict([], "ZZZ9999", profile(tiers={"ZZZ9999": "ue"}))
    assert v.standing == NO_DATA and "no" in v.reasoning.lower()


def test_suggested_order_leverage_and_tiebreak():
    from kairos.coursereg.advisor import (
        CONTESTED, LIKELY, LONG_SHOT, NO_DATA, SAFE, TOUGH, suggested_order,
    )

    standings = {
        "SAFE1": SAFE, "TOUGH1": TOUGH, "LIKELY1": LIKELY,
        "NEW1": NO_DATA, "LONG1": LONG_SHOT,
        "CONT2": CONTESTED, "CONT1": CONTESTED,
    }
    assert suggested_order(standings) == [
        "TOUGH1", "CONT1", "CONT2", "LIKELY1", "NEW1", "LONG1", "SAFE1",
    ]


def test_leverage_warnings():
    from kairos.coursereg.advisor import CONTESTED, NO_DATA, SAFE, leverage_warnings

    # 9 candidates: a SAFE in rank 1, a CONTESTED pushed past RANK_CAP=8.
    order = ["SAFE1", "B", "C", "D", "E", "F", "G", "NEW1", "CONT1"]
    standings = {c: SAFE for c in order}
    standings["CONT1"] = CONTESTED
    standings["NEW1"] = NO_DATA
    messages = " ".join(leverage_warnings(order, standings))
    assert "SAFE1" in messages          # wasted top rank
    assert "CONT1" in messages          # contested unranked
    assert "NEW1" in messages           # no-data note


def test_dossier_rows_split_and_sorted():
    from kairos.coursereg.advisor import dossier_rows

    records = [
        rec("AAA1000", "2425", 1, 2, 1, 2),
        rec("AAA1000", "2526", 1, 2, 3, 4),
        rec("AAA1000", "2526", 2, 2, 5, 6),
        rec("AAA1000", "2526", 1, 3, 7, 8),  # other round: excluded
    ]
    same, other = dossier_rows(records, "AAA1000", 2, 1)
    assert [r.acad_year for r in same] == ["2526", "2425"]  # year-descending
    assert [r.acad_year for r in other] == ["2526"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_coursereg_advisor.py -v`
Expected: FAIL — `No module named 'kairos.coursereg.advisor'`

- [ ] **Step 3: Implement**

```python
# kairos/coursereg/advisor.py
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from .model import RANK_CAP, UNLIMITED, DemandRecord, Profile

SAFE = "SAFE"
LIKELY = "LIKELY"
CONTESTED = "CONTESTED"
TOUGH = "TOUGH"
LONG_SHOT = "LONG_SHOT"
NO_DATA = "NO_DATA"
# Ordinal ladder, safest first. Base verdicts land on SAFE/CONTESTED/LONG_SHOT
# (indices 0/2/4); profile nudges move at most one index either way.
BANDS = [SAFE, LIKELY, CONTESTED, TOUGH, LONG_SHOT]

# Verdict thresholds. RECENT_YEARS bounds how far back "current character"
# reaches; the medians define "comfortably under" and "wide margin" — chosen
# so a course must be clearly, repeatedly one-sided to leave CONTESTED.
RECENT_YEARS = 3
SAFE_MEDIAN_MAX = 0.85
LONG_SHOT_MEDIAN_MIN = 1.5
# A SAFE course sitting in ranks 1..TOP_RANKS is flagged as wasted leverage.
TOP_RANKS = 3

# Leverage order for suggested ranking: courses where C plausibly flips the
# outcome first; NO_DATA before the hopeless/sure things so the user places
# it deliberately; SAFE last (wins at any rank).
_LEVERAGE = {TOUGH: 0, CONTESTED: 1, LIKELY: 2, NO_DATA: 3, LONG_SHOT: 4, SAFE: 5}

_NUDGE_NOTES = {
    "core": "core-tier A beats the UE crowd in this queue",
    "ue": "UE-tier A sits at the bottom of this queue",
}


@dataclass(frozen=True)
class Verdict:
    course: str
    standing: str
    reasoning: str


def ratio(demand, vacancy) -> float | None:
    if demand is None or vacancy is None:
        return None
    if vacancy == UNLIMITED:
        return 0.0
    if vacancy == 0:
        return math.inf if demand > 0 else None
    return demand / vacancy


def same_sem_ratios(records, course, semester, rnd) -> list:
    pairs = [
        (r.acad_year, ratio(r.demand, r.vacancy))
        for r in records
        if r.course == course and r.semester == semester and r.round == rnd
    ]
    return sorted(
        [(year, value) for year, value in pairs if value is not None],
        key=lambda pair: pair[0],
    )


def base_verdict(ratios) -> str:
    recent = [value for _, value in ratios][-RECENT_YEARS:]
    if not recent:
        return NO_DATA
    median = statistics.median(recent)
    if median <= SAFE_MEDIAN_MAX and all(value <= 1 for value in recent):
        return SAFE
    if median >= LONG_SHOT_MEDIAN_MIN and all(value > 1 for value in recent):
        return LONG_SHOT
    return CONTESTED


def nudge_steps(tier: str, seniority: int) -> int:
    # Negative = toward SAFE. Seniority only matters on GE/UE queues, where
    # everyone's A is bottom-tier and B decides.
    step = {"core": -1, "major": 0, "ue": 1}[tier]
    if tier == "ue":
        if seniority >= 3:
            step -= 1
        elif seniority == 1:
            step += 1
    return max(-1, min(1, step))


def verdict(records, course, profile: Profile) -> Verdict:
    ratios = same_sem_ratios(records, course, profile.semester, profile.round)
    base = base_verdict(ratios)
    if base == NO_DATA:
        return Verdict(
            course, NO_DATA,
            f"no S{profile.semester} round-{profile.round} history — new or renamed course?",
        )
    recent = [value for _, value in ratios][-RECENT_YEARS:]
    over = sum(1 for value in recent if value > 1)
    median = statistics.median(recent)
    median_text = "∞" if math.isinf(median) else f"{median:.2f}"
    parts = [
        f"oversubscribed {over} of {len(recent)} recent S{profile.semester} "
        f"runs at round {profile.round} (median ratio {median_text})"
    ]
    tier = profile.tiers[course]
    steps = nudge_steps(tier, profile.seniority)
    if tier in _NUDGE_NOTES:
        parts.append(_NUDGE_NOTES[tier])
    if tier == "ue" and profile.seniority >= 3:
        parts.append("Y3/Y4 seniority helps on GE/UE")
    elif tier == "ue" and profile.seniority == 1:
        parts.append("Y1 seniority hurts on GE/UE")
    final = BANDS[max(0, min(len(BANDS) - 1, BANDS.index(base) + steps))]
    return Verdict(course, final, "; ".join(parts))


def suggested_order(standings: dict) -> list:
    return sorted(standings, key=lambda course: (_LEVERAGE[standings[course]], course))


def leverage_warnings(order, standings) -> list:
    warnings = []
    for position, course in enumerate(order, 1):
        standing = standings[course]
        if standing == SAFE and position <= TOP_RANKS:
            warnings.append(f"rank {position} holds {course} (SAFE) — wasted leverage")
        if standing in (TOUGH, CONTESTED, LIKELY) and position > RANK_CAP:
            warnings.append(f"{course} ({standing}) has no rank — contested courses need one")
        if standing == NO_DATA:
            warnings.append(f"{course} has no history — place it deliberately")
    return warnings


def dossier_rows(records, course, rnd, semester):
    rows = [r for r in records if r.course == course and r.round == rnd]
    same = sorted((r for r in rows if r.semester == semester),
                  key=lambda r: r.acad_year, reverse=True)
    other = sorted((r for r in rows if r.semester != semester),
                   key=lambda r: r.acad_year, reverse=True)
    return same, other
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_coursereg_advisor.py -v`
Expected: all PASS. Then `.venv/bin/pytest -q` — all passing.

- [ ] **Step 5: Commit**

```bash
git add kairos/coursereg/advisor.py tests/test_coursereg_advisor.py
git commit -m "feat: add coursereg verdicts, profile nudges, and leverage ranking

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `coursereg/tui/state.py` — `AdvisorState`

**Files:**
- Create: `kairos/coursereg/tui/__init__.py` (empty)
- Create: `kairos/coursereg/tui/state.py`
- Test: `tests/test_coursereg_tui_state.py`

**Interfaces:**
- Consumes: everything Task 4 produces; `Profile`, `RANK_CAP`, `TIERS`,
  `profile_to_yaml` (Task 1).
- Produces (Task 6's `AdvisorApp` calls exactly these):
  - `AdvisorState(profile: Profile, records: list[DemandRecord])` —
    **no Textual imports in this module**
  - `.order: list[str]`; `.verdicts: dict[str, Verdict]`;
    `.suggested: list[str]`
  - `.rows() -> list[tuple[int | None, str, str, str]]`
    (rank-or-None, course, standing, tier)
  - `.move(index: int, delta: int) -> int` (returns new index; clamps)
  - `.cycle_tier(course: str) -> None` (core → major → ue → core; recomputes)
  - `.toggle_round() -> None` (2 ↔ 3 on the profile; recomputes)
  - `.restore_suggested() -> None`
  - `.warnings() -> list[str]`
  - `.dossier(course) -> tuple[list[DemandRecord], list[DemandRecord]]`
  - `.to_yaml() -> str` (sets `ranked=True`, order = current order)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_coursereg_tui_state.py
import yaml

from kairos.coursereg.model import DemandRecord, Profile


def rec(course, year, sem, rnd, demand, vacancy):
    return DemandRecord(course, year, sem, rnd, demand, vacancy)


def make_records():
    # AAA1000 contested, BBB1000 safe, CCC1000 long shot; all S1 round 2.
    out = []
    for year, (a, b, c) in {
        "2324": (90, 40, 200), "2425": (110, 50, 180), "2526": (95, 60, 210),
    }.items():
        out += [
            rec("AAA1000", year, 1, 2, a, 100),
            rec("BBB1000", year, 1, 2, b, 100),
            rec("CCC1000", year, 1, 2, c, 100),
        ]
    return out


def make_profile(ranked=False, order=None):
    tiers = {"AAA1000": "major", "BBB1000": "major", "CCC1000": "major"}
    return Profile(seniority=2, semester=1, round=2, tiers=tiers,
                   order=order or list(tiers), ranked=ranked)


def make_state(**kw):
    from kairos.coursereg.tui.state import AdvisorState

    return AdvisorState(make_profile(**kw), make_records())


def test_fresh_profile_opens_in_suggested_order():
    state = make_state()
    # leverage order: CONTESTED (AAA) then LONG_SHOT (CCC) then SAFE (BBB)
    assert state.order == ["AAA1000", "CCC1000", "BBB1000"]
    assert state.order == state.suggested


def test_ranked_profile_keeps_saved_order():
    state = make_state(ranked=True, order=["BBB1000", "AAA1000", "CCC1000"])
    assert state.order == ["BBB1000", "AAA1000", "CCC1000"]


def test_rows_carry_rank_standing_tier():
    state = make_state()
    rows = state.rows()
    assert rows[0] == (1, "AAA1000", "CONTESTED", "major")
    assert [row[0] for row in rows] == [1, 2, 3]  # all within RANK_CAP


def test_move_reorders_and_clamps():
    state = make_state()
    new_index = state.move(0, 1)
    assert new_index == 1 and state.order[1] == "AAA1000"
    assert state.move(0, -1) == 0  # clamped at the top


def test_cycle_tier_recomputes_verdicts():
    state = make_state()
    assert state.verdicts["AAA1000"].standing == "CONTESTED"
    state.cycle_tier("AAA1000")  # major -> ue
    assert state.profile.tiers["AAA1000"] == "ue"
    assert state.verdicts["AAA1000"].standing == "TOUGH"


def test_toggle_round_recomputes():
    state = make_state()
    state.toggle_round()
    assert state.profile.round == 3
    # No round-3 records exist -> everything becomes NO_DATA.
    assert all(v.standing == "NO_DATA" for v in state.verdicts.values())
    state.toggle_round()
    assert state.profile.round == 2


def test_restore_suggested_after_manual_moves():
    state = make_state()
    state.move(0, 2)
    assert state.order != state.suggested
    state.restore_suggested()
    assert state.order == state.suggested


def test_warnings_flag_safe_in_top_ranks():
    state = make_state(ranked=True, order=["BBB1000", "AAA1000", "CCC1000"])
    assert any("BBB1000" in w for w in state.warnings())


def test_to_yaml_round_trips_with_ranked_flag():
    from kairos.coursereg.model import profile_from_dict

    state = make_state()
    state.move(0, 1)
    data = yaml.safe_load(state.to_yaml())
    again = profile_from_dict(data)
    assert again.ranked is True
    assert again.order == state.order
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_coursereg_tui_state.py -v`
Expected: FAIL — `No module named 'kairos.coursereg.tui'`

- [ ] **Step 3: Implement**

Create empty `kairos/coursereg/tui/__init__.py`, then:

```python
# kairos/coursereg/tui/state.py
from __future__ import annotations

from ..advisor import dossier_rows, leverage_warnings, suggested_order, verdict
from ..model import RANK_CAP, TIERS, DemandRecord, Profile, profile_to_yaml


class AdvisorState:
    """Mutable session object behind the advisor TUI. Pure-python (no Textual
    imports) so every interaction is testable without a terminal — mirrors the
    timetable TUI's AppState/App split."""

    def __init__(self, profile: Profile, records: list):
        self.profile = profile
        self.records = records
        self.verdicts: dict = {}
        self.suggested: list = []
        self.recompute()
        # A fresh config opens in the advisor's suggested order; a config the
        # TUI has saved (ranked: true) keeps the user's own order.
        self.order = list(profile.order) if profile.ranked else list(self.suggested)

    def recompute(self) -> None:
        self.verdicts = {
            course: verdict(self.records, course, self.profile)
            for course in self.profile.tiers
        }
        standings = {course: v.standing for course, v in self.verdicts.items()}
        self.suggested = suggested_order(standings)

    def rows(self) -> list:
        return [
            (
                position if position <= RANK_CAP else None,
                course,
                self.verdicts[course].standing,
                self.profile.tiers[course],
            )
            for position, course in enumerate(self.order, 1)
        ]

    def move(self, index: int, delta: int) -> int:
        target = index + delta
        if not (0 <= index < len(self.order)) or not (0 <= target < len(self.order)):
            return index
        self.order[index], self.order[target] = self.order[target], self.order[index]
        return target

    def cycle_tier(self, course: str) -> None:
        current = TIERS.index(self.profile.tiers[course])
        self.profile.tiers[course] = TIERS[(current + 1) % len(TIERS)]
        self.recompute()

    def toggle_round(self) -> None:
        self.profile.round = 5 - self.profile.round  # 2 <-> 3
        self.recompute()

    def restore_suggested(self) -> None:
        self.order = list(self.suggested)

    def warnings(self) -> list:
        standings = {course: v.standing for course, v in self.verdicts.items()}
        return leverage_warnings(self.order, standings)

    def dossier(self, course: str) -> tuple:
        return dossier_rows(
            self.records, course, self.profile.round, self.profile.semester
        )

    def to_yaml(self) -> str:
        self.profile.order = list(self.order)
        self.profile.ranked = True
        return profile_to_yaml(self.profile)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_coursereg_tui_state.py -v`
Expected: all PASS. Then `.venv/bin/pytest -q` — all passing.

- [ ] **Step 5: Commit**

```bash
git add kairos/coursereg/tui/__init__.py kairos/coursereg/tui/state.py tests/test_coursereg_tui_state.py
git commit -m "feat: add AdvisorState session object for the coursereg TUI

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: `coursereg/tui/app.py` + `kairos advise` CLI wiring

**Files:**
- Create: `kairos/coursereg/tui/app.py`
- Modify: `kairos/cli.py` (add `advise` subparser + `cmd_advise`; the
  existing dest-prefix merge in `main()` handles the new defaults because
  they are non-None strings)
- Test: `tests/test_coursereg_tui_app.py` (create),
  `tests/test_coursereg_cli.py` (create)

**Interfaces:**
- Consumes: `AdvisorState` (Task 5), `load_profile` (Task 1),
  `load_history` (Task 3).
- Produces: `AdvisorApp(state, config_path)`, `run_advisor(state,
  config_path)`; CLI `kairos advise [--config coursereg.yaml]
  [--cache-dir data/coursereg] [--refetch]`.

- [ ] **Step 1: Write the failing TUI tests**

```python
# tests/test_coursereg_tui_app.py
import yaml
from textual.widgets import ListView, Static

from kairos.coursereg.model import DemandRecord, Profile
from kairos.coursereg.tui.app import AdvisorApp
from kairos.coursereg.tui.state import AdvisorState


def rec(course, year, sem, rnd, demand, vacancy):
    return DemandRecord(course, year, sem, rnd, demand, vacancy)


def make_state():
    records = []
    for year, (a, b, c) in {
        "2324": (90, 40, 200), "2425": (110, 50, 180), "2526": (95, 60, 210),
    }.items():
        records += [
            rec("AAA1000", year, 1, 2, a, 100),
            rec("BBB1000", year, 1, 2, b, 100),
            rec("CCC1000", year, 1, 2, c, 100),
        ]
    tiers = {"AAA1000": "major", "BBB1000": "major", "CCC1000": "major"}
    profile = Profile(seniority=2, semester=1, round=2, tiers=tiers,
                      order=list(tiers), ranked=False)
    return AdvisorState(profile, records)


async def test_opens_in_suggested_order_with_dossier(tmp_path):
    app = AdvisorApp(make_state(), tmp_path / "coursereg.yaml")
    async with app.run_test() as pilot:
        await pilot.pause()
        ranking = app.query_one("#ranking", ListView)
        assert ranking.index == 0
        detail = app.query_one("#dossier", Static)
        text = str(detail.renderable)
        assert "AAA1000" in text and "CONTESTED" in text
        assert "25/26" in text  # dossier shows per-year rows


async def test_shift_j_moves_course_down(tmp_path):
    state = make_state()
    app = AdvisorApp(state, tmp_path / "coursereg.yaml")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("J")
        await pilot.pause()
        assert state.order[1] == "AAA1000"
        assert app.query_one("#ranking", ListView).index == 1


async def test_t_cycles_tier_and_recomputes(tmp_path):
    state = make_state()
    app = AdvisorApp(state, tmp_path / "coursereg.yaml")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("t")  # AAA1000 major -> ue
        await pilot.pause()
        assert state.profile.tiers["AAA1000"] == "ue"
        assert state.verdicts["AAA1000"].standing == "TOUGH"


async def test_r_toggles_round(tmp_path):
    state = make_state()
    app = AdvisorApp(state, tmp_path / "coursereg.yaml")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        assert state.profile.round == 3


async def test_a_restores_suggested_order(tmp_path):
    state = make_state()
    app = AdvisorApp(state, tmp_path / "coursereg.yaml")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("J")
        await pilot.press("a")
        await pilot.pause()
        assert state.order == state.suggested


async def test_s_saves_ranking_to_yaml(tmp_path):
    state = make_state()
    path = tmp_path / "coursereg.yaml"
    app = AdvisorApp(state, path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("J")
        await pilot.press("s")
        await pilot.pause()
    data = yaml.safe_load(path.read_text())
    assert data["ranked"] is True
    assert list(data["candidates"]) == state.order


async def test_warnings_strip_flags_safe_in_top_rank(tmp_path):
    state = make_state()
    state.order = ["BBB1000", "AAA1000", "CCC1000"]  # SAFE first
    app = AdvisorApp(state, tmp_path / "coursereg.yaml")
    async with app.run_test() as pilot:
        await pilot.pause()
        summary = app.query_one("#summary", Static)
        assert "BBB1000" in str(summary.renderable)
```

And the CLI test:

```python
# tests/test_coursereg_cli.py
import pytest

from kairos.cli import main


def test_advise_missing_config_prints_template(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["advise"])
    message = str(exc.value)
    assert "error:" in message and "candidates:" in message


def test_advise_uses_own_config_and_cache_defaults():
    # The parser must default advise's config to coursereg.yaml (not the
    # global config.yaml) and its cache dir to data/coursereg.
    from kairos import cli

    captured = {}

    def fake_cmd_advise(args):
        captured["config"] = args.config
        captured["cache_dir"] = args.cache_dir

    original = cli.cmd_advise
    cli.cmd_advise = fake_cmd_advise
    try:
        cli.main(["advise"])
    finally:
        cli.cmd_advise = original
    assert captured == {"config": "coursereg.yaml", "cache_dir": "data/coursereg"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_coursereg_tui_app.py tests/test_coursereg_cli.py -v`
Expected: FAIL — `No module named 'kairos.coursereg.tui.app'` and
`main(["advise"])` exiting with argparse error (unknown command).

- [ ] **Step 3: Implement the app**

```python
# kairos/coursereg/tui/app.py
from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from ..advisor import NO_DATA, ratio
from ..model import UNLIMITED

_TIER_ABBREV = {"core": "core", "major": "maj", "ue": "ue"}


def _fmt_year(short: str) -> str:
    return f"AY{short[:2]}/{short[2:]}"


def _fmt_count(value) -> str:
    if value is None:
        return "?"
    if value == UNLIMITED:
        return "∞"
    return str(value)


def _history_lines(rows, dim: bool) -> list[Text]:
    lines = []
    for record in rows:
        r = ratio(record.demand, record.vacancy)
        ratio_text = "" if r is None else ("∞" if r == float("inf") else f"{r:.2f}")
        over = "  over" if r is not None and r > 1 else ""
        line = Text(
            f"  {_fmt_year(record.acad_year)}  "
            f"{_fmt_count(record.demand)} / {_fmt_count(record.vacancy)}"
            f"  {ratio_text}{over}"
        )
        if dim:
            line.stylize("dim")
        lines.append(line)
    return lines


class AdvisorApp(App):
    CSS = """
    #ranking { width: 44; border: round $panel; border-title-color: $text; }
    #dossier { width: 1fr; border: round $panel; border-title-color: $text; }
    #summary { height: 4; border: round $panel; border-title-color: $text; }
    """

    BINDINGS = [
        ("j", "cursor_down", "down"),
        ("k", "cursor_up", "up"),
        ("J", "move_down", "move down"),
        ("K", "move_up", "move up"),
        ("a", "advisor_order", "advisor order"),
        ("t", "cycle_tier", "tier"),
        ("r", "toggle_round", "round 2/3"),
        ("s", "save", "save"),
        ("q", "quit", "quit"),
    ]

    def __init__(self, state, config_path: Path) -> None:
        super().__init__()
        self.state = state
        self.config_path = Path(config_path)

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            with Horizontal():
                yield ListView(id="ranking")
                yield Static(id="dossier")
            yield Static(id="summary")
        yield Footer()

    def on_mount(self) -> None:
        # Assumption surfaced per spec: stated in the header bar, always visible.
        self.sub_title = "assumes independent per-course queues"
        self.query_one("#ranking", ListView).border_title = "Ranking"
        self.query_one("#dossier", Static).border_title = "Dossier"
        self.query_one("#summary", Static).border_title = "Notes"
        self._refresh_ranking(keep_index=0)

    # ------------------------------------------------------------- rendering

    def _refresh_ranking(self, keep_index: int) -> None:
        ranking = self.query_one("#ranking", ListView)
        ranking.clear()
        for rank, course, standing, tier in self.state.rows():
            rank_text = f"{rank:>2}" if rank is not None else "--"
            label = f"{rank_text}  {course:<10} {standing:<9} {_TIER_ABBREV[tier]}"
            ranking.append(ListItem(Label(label)))
        ranking.index = min(keep_index, len(self.state.order) - 1)
        self._refresh_detail()
        self._refresh_summary()

    def _selected_course(self) -> str:
        index = self.query_one("#ranking", ListView).index or 0
        return self.state.order[index]

    def _refresh_detail(self) -> None:
        course = self._selected_course()
        v = self.state.verdicts[course]
        same, other = self.state.dossier(course)
        parts = [Text(f"{course} — {v.standing}", style="bold")]
        parts.append(
            Text(f"round {self.state.profile.round}, "
                 f"S{self.state.profile.semester} history:")
        )
        if same:
            parts.extend(_history_lines(same, dim=False))
        elif v.standing == NO_DATA:
            parts.append(Text("  (none)", style="dim"))
        if other:
            parts.append(Text("other semester (context only):", style="dim"))
            parts.extend(_history_lines(other, dim=True))
        parts.append(Text(f"reasoning: {v.reasoning}"))
        self.query_one("#dossier", Static).update(Text("\n").join(parts))

    def _refresh_summary(self) -> None:
        notes = self.state.warnings()
        text = "\n".join(notes[:3]) if notes else "no leverage warnings"
        self.query_one("#summary", Static).update(text)

    # --------------------------------------------------------------- actions

    def action_cursor_down(self) -> None:
        self.query_one("#ranking", ListView).action_cursor_down()
        self._refresh_detail()

    def action_cursor_up(self) -> None:
        self.query_one("#ranking", ListView).action_cursor_up()
        self._refresh_detail()

    def action_move_down(self) -> None:
        index = self.query_one("#ranking", ListView).index or 0
        self._refresh_ranking(keep_index=self.state.move(index, 1))

    def action_move_up(self) -> None:
        index = self.query_one("#ranking", ListView).index or 0
        self._refresh_ranking(keep_index=self.state.move(index, -1))

    def action_advisor_order(self) -> None:
        self.state.restore_suggested()
        self._refresh_ranking(keep_index=0)

    def action_cycle_tier(self) -> None:
        index = self.query_one("#ranking", ListView).index or 0
        self.state.cycle_tier(self._selected_course())
        self._refresh_ranking(keep_index=index)

    def action_toggle_round(self) -> None:
        index = self.query_one("#ranking", ListView).index or 0
        self.state.toggle_round()
        self._refresh_ranking(keep_index=index)

    def action_save(self) -> None:
        self.config_path.write_text(self.state.to_yaml())
        self.notify(f"saved {self.config_path}")


def run_advisor(state, config_path: Path) -> None:
    AdvisorApp(state, config_path).run()
```

- [ ] **Step 4: Wire the CLI**

In `kairos/cli.py`:

Add `cmd_advise` after `cmd_tui` (lazy imports, mirroring the existing
lazy-import comment style — here it simply keeps coursereg out of the
timetable paths' import cost):

```python
def cmd_advise(args) -> None:
    from .coursereg.fetch import load_history
    from .coursereg.model import load_profile
    from .coursereg.tui.app import run_advisor
    from .coursereg.tui.state import AdvisorState

    profile = load_profile(Path(args.config))
    records = load_history(Path(args.cache_dir), refetch=args.refetch)
    run_advisor(AdvisorState(profile, records), Path(args.config))
```

In `main()`, after the `tui` subparser block, add:

```python
    advise_parser = subparsers.add_parser(
        "advise", help="CourseReg R2/R3 ranking advisor (what-if TUI)"
    )
    # advise has its OWN config/cache defaults (coursereg.yaml, data/coursereg)
    # rather than _add_common_flags: the generic merge in main() would fall
    # back to the timetable's config.yaml/data/cache for absent values, and
    # these non-None defaults keep the merge from ever falling through.
    advise_parser.add_argument(
        "--config", dest="advise_config", default="coursereg.yaml",
        help="path to coursereg.yaml",
    )
    advise_parser.add_argument(
        "--cache-dir", dest="advise_cache_dir", default="data/coursereg",
        help="demand-history cache directory",
    )
    advise_parser.add_argument(
        "--refetch", action="store_true",
        help="re-scrape courserekt even if cached (repair hatch)",
    )
```

And extend the dispatch at the bottom of `main()`:

```python
    if args.command == "init":
        cmd_init(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "advise":
        cmd_advise(args)
    else:
        cmd_tui(args)
```

(No other change: the existing
`args.config = getattr(args, f"{args.command}_config", None) or args.config`
merge resolves `advise_config`'s non-None default before the global default.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_coursereg_tui_app.py tests/test_coursereg_cli.py -v`
Expected: all PASS. Then `.venv/bin/pytest -q` — all passing.

- [ ] **Step 6: Manual smoke test**

Create a real `coursereg.yaml` in the repo root from `TEMPLATE` (do not
commit it), then: `.venv/bin/kairos advise`. Expected: first run fetches 10
semesters (visible pause), the TUI opens in suggested order, `J`/`K`/`t`/`r`
respond, `s` writes the file, `q` exits cleanly. Delete the scratch
`coursereg.yaml` afterwards. Record what you saw in the report.

- [ ] **Step 7: Commit**

```bash
git add kairos/coursereg/tui/app.py kairos/cli.py tests/test_coursereg_tui_app.py tests/test_coursereg_cli.py
git commit -m "feat: add kairos advise what-if TUI and CLI wiring

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Docs upkeep

**Files:**
- Modify: `docs/user-guide.md`, `docs/architecture.md`, `docs/development.md`,
  `CLAUDE.md`

**Interfaces:**
- Consumes: the shipped behavior of Tasks 1–6 — every claim verified against
  the merged code, not this plan (source wins; note discrepancies in the
  report).

Required content (accuracy rule: run every command you document; read every
file you cite):

- [ ] **Step 1: `docs/user-guide.md`** — new top-level section "CourseReg
  advisor (`kairos advise`)" after the TUI section: what CourseReg is vs
  tutorial balloting (one paragraph, A×B×C with C as the only lever),
  `coursereg.yaml` reference (paste the real TEMPLATE), the TUI walkthrough
  (panes, keys, standings explained in plain language), the three stated
  assumptions in user terms (especially: verdicts are historical trends
  frozen at AY25/26 — they cannot see the current cycle), and the
  cache-copy recovery note. Update the user-guide TOC.

- [ ] **Step 2: `docs/architecture.md`** — add `kairos/coursereg/` to the
  module map (per-module paragraphs in the existing style: responsibility,
  key symbols, imports clause) and one paragraph in the design-stance
  section: second subsystem, same pure-core rule, permanent cache rationale.
  Update the mermaid data-flow diagram with the advise path.

- [ ] **Step 3: `docs/development.md`** — add the five new test files to the
  test-map table; note the golden fixture `tests/data/courserekt_sample.html`
  and that fetch tests monkeypatch `fetch_semester` (no network in tests).

- [ ] **Step 4: `CLAUDE.md`** — add `advise: .venv/bin/kairos advise` to
  Commands; extend the pure-core hard rule with `coursereg/{model,advisor}`.
  Keep it under ~40 lines total.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/pytest -q` (all passing) and the repo link check:
`grep -Roh 'docs/[a-z-]*\.md\|CLAUDE.md' README.md CLAUDE.md docs/*.md | sort -u | while read f; do [ -f "$f" ] || echo "BROKEN: $f"; done`
Expected: no BROKEN lines.

```bash
git add docs/user-guide.md docs/architecture.md docs/development.md CLAUDE.md
git commit -m "docs: document the coursereg advisor across all pages

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
