# NUS Course Optimiser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python CLI that searches all valid NUS timetable combinations for a set of modules and emits top-N scored timetables, per-group backup choices, and a snake-order ballot ranking for tutorial registration.

**Architecture:** Small package `optimiser/` — API fetch+cache → lesson `ChoiceGroup`s → DFS enumeration with clash pruning and footprint dedup → weighted scoring → top-N heap + per-footprint conditional bests → ballot alternatives + snake order → terminal rendering with NUSMods share links.

**Tech Stack:** Python ≥ 3.11, `requests`, `PyYAML`, `pytest`. No other dependencies.

**Spec:** `docs/superpowers/specs/2026-07-13-course-optimiser-design.md`

## Global Constraints

- Python ≥ 3.11; runtime deps exactly `requests` and `PyYAML`; dev dep `pytest`.
- Times are minutes-since-midnight `int` internally; API times are `"HHMM"` strings; config times are `"HH:MM"` strings.
- A lesson is **online** iff its venue starts with `E-Learn`.
- Two sessions clash iff same day AND time ranges overlap AND week sets intersect.
- Online lessons are excluded from time_window / free_days / gaps / lunch, **included** in tough_days.
- Lesson type names: API full names (`Lecture`, `Tutorial`, `Recitation`, `Laboratory`, `Sectional Teaching`); share URLs/config use abbreviations (`LEC`, `TUT`, `REC`, `LAB`, `SEC`). Internal code uses **full names**; config/URLs use abbreviations.
- Ballot list capped at 20 entries. Default `balloted_types: [TUT, LAB, REC, SEC]`.
- Difficulty is an int 1–5 per (module, lesson type); bare int in config = all components; unspecified defaults to 3.
- All commands below run from the repo root; use `.venv/bin/pytest`, `.venv/bin/python` etc.

---

### Task 1: Scaffolding + core model

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `optimiser/__init__.py`, `optimiser/model.py`
- Test: `tests/test_model.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces (used by every later task):
  - `optimiser.model.DAYS: list[str]` — `["Monday", ..., "Saturday"]`
  - `optimiser.model.LESSON_ABBREV: dict[str, str]` (full → abbrev), `LESSON_FULL: dict[str, str]` (abbrev → full)
  - `parse_time("0930") -> 570`, `parse_clock("09:30") -> 570`, `fmt_time(570) -> "0930"`
  - `Session(day: str, start: int, end: int, weeks: frozenset[int], venue: str)` — frozen dataclass, `.online: bool`, `.clashes(other: Session) -> bool`
  - `Choice(module: str, lesson_type: str, class_no: str, sessions: tuple[Session, ...])` — frozen dataclass, `.footprint -> frozenset`, `.clashes(other: Choice) -> bool`
  - `ChoiceGroup(module: str, lesson_type: str, choices: list[Choice])` — dataclass, `.key -> tuple[str, str]`

- [ ] **Step 1: Create project scaffolding**

`pyproject.toml`:

```toml
[project]
name = "optimiser"
version = "0.1.0"
description = "NUS timetable optimiser and ballot ranker"
requires-python = ">=3.11"
dependencies = ["requests", "PyYAML"]

[project.optional-dependencies]
dev = ["pytest"]

[project.scripts]
optimiser = "optimiser.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["optimiser*"]
```

`.gitignore`:

```
.venv/
__pycache__/
*.egg-info/
data/cache/
```

`optimiser/__init__.py` and `tests/__init__.py`: empty files (the latter lets tests import
shared helpers via `from tests.conftest import lesson`).

Then:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Expected: install succeeds.

- [ ] **Step 2: Write the failing tests**

`tests/test_model.py`:

```python
from optimiser.model import (
    LESSON_ABBREV,
    LESSON_FULL,
    Choice,
    Session,
    fmt_time,
    parse_clock,
    parse_time,
)

ALL_WEEKS = frozenset(range(1, 14))


def sess(day="Monday", start=600, end=720, weeks=ALL_WEEKS, venue="COM1"):
    return Session(day, start, end, weeks, venue)


def test_time_parsing():
    assert parse_time("0930") == 570
    assert parse_clock("09:30") == 570
    assert fmt_time(570) == "0930"


def test_lesson_type_maps_roundtrip():
    assert LESSON_ABBREV["Tutorial"] == "TUT"
    assert LESSON_FULL["SEC"] == "Sectional Teaching"
    for full, ab in LESSON_ABBREV.items():
        assert LESSON_FULL[ab] == full


def test_online_detection():
    assert sess(venue="E-Learn_C").online
    assert not sess(venue="LT11").online


def test_clash_same_day_overlap():
    assert sess(start=600, end=720).clashes(sess(start=660, end=780))


def test_no_clash_different_day():
    assert not sess(day="Monday").clashes(sess(day="Tuesday"))


def test_no_clash_back_to_back():
    assert not sess(start=600, end=720).clashes(sess(start=720, end=840))


def test_no_clash_disjoint_weeks():
    odd = sess(weeks=frozenset({1, 3, 5}))
    even = sess(weeks=frozenset({2, 4, 6}))
    assert not odd.clashes(even)
    assert odd.clashes(sess(weeks=frozenset({5, 7})))


def test_choice_clash_and_footprint():
    a = Choice("ALPHA", "Tutorial", "01", (sess(),))
    b = Choice("BETA", "Laboratory", "L1", (sess(start=660, end=780),))
    assert a.clashes(b)
    # same schedule, different venue -> same footprint
    c = Choice("ALPHA", "Tutorial", "02", (sess(venue="COM2"),))
    assert a.footprint == c.footprint
    d = Choice("ALPHA", "Tutorial", "03", (sess(day="Friday"),))
    assert a.footprint != d.footprint
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_model.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'optimiser.model'`

- [ ] **Step 4: Implement `optimiser/model.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

LESSON_ABBREV = {
    "Lecture": "LEC",
    "Tutorial": "TUT",
    "Recitation": "REC",
    "Laboratory": "LAB",
    "Sectional Teaching": "SEC",
    "Workshop": "WS",
    "Seminar-Style Module Class": "SEM",
    "Packaged Lecture": "PLEC",
    "Packaged Tutorial": "PTUT",
    "Design Lecture": "DLEC",
    "Tutorial Type 2": "TUT2",
}
LESSON_FULL = {ab: full for full, ab in LESSON_ABBREV.items()}


def parse_time(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[2:])


def parse_clock(hh_mm: str) -> int:
    hours, minutes = hh_mm.split(":")
    return int(hours) * 60 + int(minutes)


def fmt_time(minutes: int) -> str:
    return f"{minutes // 60:02d}{minutes % 60:02d}"


@dataclass(frozen=True)
class Session:
    day: str
    start: int
    end: int
    weeks: frozenset
    venue: str

    @property
    def online(self) -> bool:
        return self.venue.startswith("E-Learn")

    def clashes(self, other: "Session") -> bool:
        return (
            self.day == other.day
            and self.start < other.end
            and other.start < self.end
            and bool(self.weeks & other.weeks)
        )


@dataclass(frozen=True)
class Choice:
    module: str
    lesson_type: str  # full name, e.g. "Tutorial"
    class_no: str
    sessions: tuple

    @property
    def footprint(self) -> frozenset:
        return frozenset((s.day, s.start, s.end, s.weeks) for s in self.sessions)

    def clashes(self, other: "Choice") -> bool:
        return any(a.clashes(b) for a in self.sessions for b in other.sessions)


@dataclass
class ChoiceGroup:
    module: str
    lesson_type: str
    choices: list

    @property
    def key(self) -> tuple:
        return (self.module, self.lesson_type)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_model.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore optimiser tests
git commit -m "feat: project scaffolding and core timetable model"
```

---

### Task 2: NUSMods API client and group building

**Files:**
- Create: `optimiser/api.py`, `tests/conftest.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `model.Session/Choice/ChoiceGroup/parse_time`.
- Produces:
  - `api.fetch_module(acad_year: str, code: str, cache_dir: Path, ttl_hours: float = 24.0) -> dict` — cached GET of `https://api.nusmods.com/v2/{acadYear}/modules/{code}.json`; on network error falls back to stale cache with a warning, else `SystemExit`.
  - `api.semester_timetable(module_json: dict, semester: int) -> list[dict]` — raises `SystemExit` if module not offered that semester.
  - `api.build_groups(code: str, timetable: list[dict]) -> list[ChoiceGroup]` — groups by lessonType, bundles multi-session classNos.
  - `api.normalise_weeks(weeks) -> frozenset[int]` — list passes through; dict-style week ranges become weeks 1–13.
  - Test fixtures `alpha_json`, `beta_json` and helper `lesson(...)` in `tests/conftest.py`, reused by later tasks.

- [ ] **Step 1: Write shared fixtures**

`tests/conftest.py`:

```python
import pytest


def lesson(class_no, lesson_type, day, start, end, weeks=None, venue="COM1-0201"):
    return {
        "classNo": class_no,
        "lessonType": lesson_type,
        "day": day,
        "startTime": start,
        "endTime": end,
        "weeks": weeks if weeks is not None else list(range(1, 14)),
        "venue": venue,
    }


@pytest.fixture
def alpha_json():
    """ALPHA: one Mon+Wed lecture bundle; 3 tutorials, of which 02/03 share a footprint."""
    return {
        "moduleCode": "ALPHA",
        "semesterData": [
            {
                "semester": 1,
                "timetable": [
                    lesson("1", "Lecture", "Monday", "1000", "1200"),
                    lesson("1", "Lecture", "Wednesday", "1000", "1100"),
                    lesson("01", "Tutorial", "Monday", "1400", "1500"),
                    lesson("02", "Tutorial", "Tuesday", "0900", "1000"),
                    lesson("03", "Tutorial", "Tuesday", "0900", "1000", venue="COM1-0202"),
                ],
            }
        ],
    }


@pytest.fixture
def beta_json():
    """BETA: two lecture groups (group 1 online); two labs (L1 clashes ALPHA TUT 01)."""
    return {
        "moduleCode": "BETA",
        "semesterData": [
            {
                "semester": 1,
                "timetable": [
                    lesson("1", "Lecture", "Friday", "0800", "1000", venue="E-Learn_C"),
                    lesson("2", "Lecture", "Thursday", "1600", "1800"),
                    lesson("L1", "Laboratory", "Monday", "1400", "1600"),
                    lesson("L2", "Laboratory", "Friday", "1000", "1200"),
                ],
            }
        ],
    }
```

- [ ] **Step 2: Write the failing tests**

`tests/test_api.py`:

```python
import json

import pytest

from optimiser.api import build_groups, fetch_module, normalise_weeks, semester_timetable


def test_normalise_weeks():
    assert normalise_weeks([1, 3, 5]) == frozenset({1, 3, 5})
    assert normalise_weeks({"start": "2026-08-10", "end": "2026-11-13"}) == frozenset(range(1, 14))


def test_semester_timetable_missing_semester(alpha_json):
    with pytest.raises(SystemExit):
        semester_timetable(alpha_json, 2)


def test_build_groups_bundles_and_groups(alpha_json):
    groups = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    by_type = {g.lesson_type: g for g in groups}
    assert set(by_type) == {"Lecture", "Tutorial"}
    lec = by_type["Lecture"]
    assert len(lec.choices) == 1
    assert len(lec.choices[0].sessions) == 2  # Mon + Wed bundle
    tut = by_type["Tutorial"]
    assert sorted(c.class_no for c in tut.choices) == ["01", "02", "03"]


def test_fetch_module_uses_fresh_cache(tmp_path):
    cache_file = tmp_path / "2026-2027-ALPHA.json"
    cache_file.write_text(json.dumps({"moduleCode": "ALPHA"}))
    # fresh cache -> no network call attempted
    assert fetch_module("2026-2027", "ALPHA", tmp_path) == {"moduleCode": "ALPHA"}


def test_fetch_module_stale_cache_fallback(tmp_path, monkeypatch):
    import os
    import requests as requests_lib

    cache_file = tmp_path / "2026-2027-ALPHA.json"
    cache_file.write_text(json.dumps({"moduleCode": "ALPHA"}))
    os.utime(cache_file, (0, 0))  # make cache stale

    def boom(*args, **kwargs):
        raise requests_lib.ConnectionError("offline")

    monkeypatch.setattr(requests_lib, "get", boom)
    assert fetch_module("2026-2027", "ALPHA", tmp_path) == {"moduleCode": "ALPHA"}


def test_fetch_module_no_cache_no_network(tmp_path, monkeypatch):
    import requests as requests_lib

    def boom(*args, **kwargs):
        raise requests_lib.ConnectionError("offline")

    monkeypatch.setattr(requests_lib, "get", boom)
    with pytest.raises(SystemExit):
        fetch_module("2026-2027", "NOPE", tmp_path)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_api.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'optimiser.api'`

- [ ] **Step 4: Implement `optimiser/api.py`**

```python
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from .model import Choice, ChoiceGroup, Session, parse_time

API_BASE = "https://api.nusmods.com/v2"


def normalise_weeks(weeks) -> frozenset:
    if isinstance(weeks, list):
        return frozenset(weeks)
    # date-ranged weeks (irregular modules): assume every teaching week
    return frozenset(range(1, 14))


def fetch_module(acad_year: str, code: str, cache_dir: Path, ttl_hours: float = 24.0) -> dict:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{acad_year}-{code}.json"
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < ttl_hours * 3600:
        return json.loads(cache_file.read_text())
    url = f"{API_BASE}/{acad_year}/modules/{code}.json"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        if cache_file.exists():
            print(f"warning: API unreachable for {code}, using stale cache ({exc})")
            return json.loads(cache_file.read_text())
        raise SystemExit(f"error: cannot fetch {code} and no cache exists: {exc}")
    cache_file.write_text(resp.text)
    return resp.json()


def semester_timetable(module_json: dict, semester: int) -> list:
    for sem in module_json.get("semesterData", []):
        if sem["semester"] == semester:
            return sem["timetable"]
    code = module_json.get("moduleCode", "?")
    raise SystemExit(f"error: {code} is not offered in semester {semester}")


def build_groups(code: str, timetable: list) -> list:
    by_type: dict = {}
    for entry in timetable:
        by_type.setdefault(entry["lessonType"], {}).setdefault(entry["classNo"], []).append(entry)
    groups = []
    for lesson_type, by_class in sorted(by_type.items()):
        choices = []
        for class_no, entries in sorted(by_class.items()):
            sessions = tuple(
                Session(
                    day=e["day"],
                    start=parse_time(e["startTime"]),
                    end=parse_time(e["endTime"]),
                    weeks=normalise_weeks(e["weeks"]),
                    venue=e.get("venue", ""),
                )
                for e in entries
            )
            choices.append(Choice(code, lesson_type, class_no, sessions))
        groups.append(ChoiceGroup(code, lesson_type, choices))
    return groups
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add optimiser/api.py tests/conftest.py tests/test_api.py
git commit -m "feat: NUSMods API client with caching and lesson group building"
```

---

### Task 3: Config loading

**Files:**
- Create: `optimiser/config.py`
- Modify: `tests/conftest.py` (append `config` fixture)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `model.LESSON_ABBREV`, `model.parse_clock`.
- Produces:
  - `config.DEFAULT_BALLOTED = ["TUT", "LAB", "REC", "SEC"]`
  - `config.DEFAULT_PREFERENCES: dict` — YAML-shaped defaults (times as `"HH:MM"` strings) used by `init` and merged during load.
  - `Preferences(earliest_start: int, latest_end: int, max_difficulty_per_day: int, lunch_start: int, lunch_end: int, lunch_minutes: int, weights: dict[str, float])`
  - `Config(acad_year: str, semester: int, balloted_types: list[str], modules: dict, fixed: dict, priority: list[str], preferences: Preferences, alternatives_per_module: int, top_n: int)` with method `difficulty(module: str, lesson_type_full: str) -> int`
  - `load_config(path: Path) -> Config` — merges preference defaults, validates difficulty 1–5, extends `priority` with missing modules.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:

```python
import pytest

from optimiser.config import load_config


def write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return p


BASE = """
acad_year: 2026-2027
semester: 1
modules:
  ALPHA:
    difficulty: {LEC: 2, TUT: 4}
  BETA:
    difficulty: 3
fixed:
  BETA: {LEC: "1"}
priority: [BETA]
"""


def test_load_config_defaults_and_difficulty(tmp_path):
    cfg = load_config(write(tmp_path, BASE))
    assert cfg.balloted_types == ["TUT", "LAB", "REC", "SEC"]
    assert cfg.preferences.earliest_start == 600  # default "10:00"
    assert cfg.preferences.lunch_start == 660 and cfg.preferences.lunch_end == 840
    assert cfg.preferences.weights["tough_days"] == 5
    assert cfg.top_n == 5 and cfg.alternatives_per_module == 4
    assert cfg.difficulty("ALPHA", "Tutorial") == 4
    assert cfg.difficulty("ALPHA", "Recitation") == 3  # unspecified component
    assert cfg.difficulty("BETA", "Laboratory") == 3  # shorthand int
    assert cfg.priority == ["BETA", "ALPHA"]  # missing modules appended


def test_load_config_overrides(tmp_path):
    cfg = load_config(
        write(
            tmp_path,
            BASE
            + """
preferences:
  earliest_start: "09:00"
  weights: {gaps: 7}
top_n: 3
""",
        )
    )
    assert cfg.preferences.earliest_start == 540
    assert cfg.preferences.weights["gaps"] == 7
    assert cfg.preferences.weights["lunch"] == 3  # unlisted weights keep defaults
    assert cfg.top_n == 3


def test_load_config_rejects_bad_difficulty(tmp_path):
    with pytest.raises(SystemExit):
        load_config(write(tmp_path, BASE.replace("difficulty: 3", "difficulty: 9")))


def test_load_config_missing_file(tmp_path):
    with pytest.raises(SystemExit):
        load_config(tmp_path / "nope.yaml")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'optimiser.config'`

- [ ] **Step 3: Implement `optimiser/config.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .model import LESSON_ABBREV, parse_clock

DEFAULT_BALLOTED = ["TUT", "LAB", "REC", "SEC"]

DEFAULT_PREFERENCES = {
    "earliest_start": "10:00",
    "latest_end": "18:00",
    "max_difficulty_per_day": 8,
    "lunch_window": ["11:00", "14:00"],
    "lunch_minutes": 60,
    "weights": {
        "time_window": 3,
        "tough_days": 5,
        "same_day_pairing": 2,
        "free_days": 4,
        "gaps": 1,
        "lunch": 3,
    },
}


@dataclass
class Preferences:
    earliest_start: int
    latest_end: int
    max_difficulty_per_day: int
    lunch_start: int
    lunch_end: int
    lunch_minutes: int
    weights: dict


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

    def difficulty(self, module: str, lesson_type_full: str) -> int:
        spec = self.modules.get(module, 3)
        if isinstance(spec, int):
            return spec
        return spec.get(LESSON_ABBREV.get(lesson_type_full, ""), 3)


def _validate_difficulty(code: str, value) -> None:
    values = [value] if isinstance(value, int) else list(value.values())
    for v in values:
        if not isinstance(v, int) or not 1 <= v <= 5:
            raise SystemExit(f"error: difficulty for {code} must be an int 1-5, got {v!r}")


def load_config(path: Path) -> Config:
    if not path.exists():
        raise SystemExit(f"error: {path} not found — run 'optimiser init <share-url>' first")
    data = yaml.safe_load(path.read_text())

    prefs_raw = {**DEFAULT_PREFERENCES, **(data.get("preferences") or {})}
    weights = {**DEFAULT_PREFERENCES["weights"], **(prefs_raw.get("weights") or {})}
    preferences = Preferences(
        earliest_start=parse_clock(prefs_raw["earliest_start"]),
        latest_end=parse_clock(prefs_raw["latest_end"]),
        max_difficulty_per_day=int(prefs_raw["max_difficulty_per_day"]),
        lunch_start=parse_clock(prefs_raw["lunch_window"][0]),
        lunch_end=parse_clock(prefs_raw["lunch_window"][1]),
        lunch_minutes=int(prefs_raw["lunch_minutes"]),
        weights=weights,
    )

    modules = {}
    for code, spec in (data.get("modules") or {}).items():
        value = spec.get("difficulty", 3) if isinstance(spec, dict) else spec
        _validate_difficulty(code, value)
        modules[code] = value
    if not modules:
        raise SystemExit(f"error: no modules in {path}")

    priority = list(data.get("priority") or [])
    for code in priority:
        if code not in modules:
            raise SystemExit(f"error: priority lists unknown module {code}")
    for code in modules:
        if code not in priority:
            priority.append(code)

    return Config(
        acad_year=str(data["acad_year"]),
        semester=int(data["semester"]),
        balloted_types=list(data.get("balloted_types") or DEFAULT_BALLOTED),
        modules=modules,
        fixed=data.get("fixed") or {},
        priority=priority,
        preferences=preferences,
        alternatives_per_module=int(data.get("alternatives_per_module", 4)),
        top_n=int(data.get("top_n", 5)),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -q`
Expected: all PASS

- [ ] **Step 5: Append shared `config` fixture**

Append to `tests/conftest.py`:

```python
@pytest.fixture
def config():
    from optimiser.config import DEFAULT_PREFERENCES, Config, Preferences

    return Config(
        acad_year="2026-2027",
        semester=1,
        balloted_types=["TUT", "LAB", "REC", "SEC"],
        modules={"ALPHA": {"LEC": 2, "TUT": 4}, "BETA": 3},
        fixed={"BETA": {"LEC": "1"}},
        priority=["ALPHA", "BETA"],
        preferences=Preferences(
            earliest_start=600,
            latest_end=1080,
            max_difficulty_per_day=8,
            lunch_start=660,
            lunch_end=840,
            lunch_minutes=60,
            weights=dict(DEFAULT_PREFERENCES["weights"]),
        ),
        alternatives_per_module=4,
        top_n=5,
    )
```

Run: `.venv/bin/pytest -q` — Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add optimiser/config.py tests/test_config.py tests/conftest.py
git commit -m "feat: config loading with defaults, validation, difficulty resolution"
```

---

### Task 4: Scoring

**Files:**
- Create: `optimiser/scoring.py`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Consumes: `model.Choice/Session/DAYS`, `Config.difficulty`, `Config.preferences`.
- Produces:
  - `scoring.score_assignment(choices: list[Choice], config: Config) -> tuple[float, dict[str, tuple[float, float]]]` — returns `(total, breakdown)` where `breakdown[name] = (raw, weighted)` and `total == sum(weighted)`. Component names exactly: `time_window`, `tough_days`, `same_day_pairing`, `free_days`, `gaps`, `lunch`.

Raw component definitions (penalties negative, bonuses positive):
- `time_window`: −(on-campus class minutes before `earliest_start` or after `latest_end`) / 60
- `tough_days`: −Σ over days of `max(0, Σ session difficulties that day − max_difficulty_per_day)`; online sessions **count**; each session of a bundle counts its choice's difficulty.
- `same_day_pairing`: +1 per non-Lecture choice with a session on a day where its module has an on-campus Lecture session.
- `free_days`: +1 per Mon–Fri day with no on-campus sessions.
- `gaps`: −(idle minutes between merged on-campus intervals per day) / 60
- `lunch`: −1 per day that has on-campus sessions but no free block ≥ `lunch_minutes` within the lunch window.

- [ ] **Step 1: Write the failing tests**

`tests/test_scoring.py`:

```python
import pytest

from optimiser.model import Choice, Session
from optimiser.scoring import score_assignment

ALL_WEEKS = frozenset(range(1, 14))


def choice(module, ltype, class_no, *sessions):
    return Choice(module, ltype, class_no, tuple(sessions))


def sess(day, start, end, venue="COM1"):
    return Session(day, start, end, ALL_WEEKS, venue)


def raw(choices, config, name):
    _, breakdown = score_assignment(choices, config)
    return breakdown[name][0]


def test_time_window_penalty(config):
    # 09:00-11:00 class with earliest 10:00 -> 60 min outside -> raw -1.0
    c = choice("ALPHA", "Tutorial", "01", sess("Monday", 540, 660))
    assert raw([c], config, "time_window") == pytest.approx(-1.0)


def test_time_window_ignores_online(config):
    c = choice("ALPHA", "Lecture", "1", sess("Monday", 480, 600, venue="E-Learn_C"))
    assert raw([c], config, "time_window") == 0


def test_tough_days_counts_online(config):
    # ALPHA LEC diff 2 (online) + ALPHA TUT diff 4 + BETA LAB diff 3 = 9 > 8 -> raw -1
    cs = [
        choice("ALPHA", "Lecture", "1", sess("Monday", 600, 720, venue="E-Learn_C")),
        choice("ALPHA", "Tutorial", "01", sess("Monday", 840, 900)),
        choice("BETA", "Laboratory", "L1", sess("Monday", 960, 1080)),
    ]
    assert raw(cs, config, "tough_days") == pytest.approx(-1)


def test_same_day_pairing_requires_oncampus_lecture(config):
    lec = choice("ALPHA", "Lecture", "1", sess("Monday", 600, 720))
    tut = choice("ALPHA", "Tutorial", "01", sess("Monday", 840, 900))
    assert raw([lec, tut], config, "same_day_pairing") == 1
    online_lec = choice("ALPHA", "Lecture", "1", sess("Monday", 600, 720, venue="E-Learn_C"))
    assert raw([online_lec, tut], config, "same_day_pairing") == 0


def test_free_days_ignores_online(config):
    # one on-campus Monday class + one online Friday lecture -> Tue/Wed/Thu/Fri free
    cs = [
        choice("ALPHA", "Tutorial", "01", sess("Monday", 600, 720)),
        choice("BETA", "Lecture", "1", sess("Friday", 480, 600, venue="E-Learn_C")),
    ]
    assert raw(cs, config, "free_days") == 4


def test_gaps(config):
    # 10:00-12:00 then 14:00-15:00 -> 120 min gap -> raw -2.0
    cs = [
        choice("ALPHA", "Lecture", "1", sess("Monday", 600, 720)),
        choice("ALPHA", "Tutorial", "01", sess("Monday", 840, 900)),
    ]
    assert raw(cs, config, "gaps") == pytest.approx(-2.0)


def test_lunch_penalty(config):
    # 11:00-14:00 solid class -> no lunch block -> raw -1
    blocked = [choice("ALPHA", "Lecture", "1", sess("Monday", 660, 840))]
    assert raw(blocked, config, "lunch") == -1
    # 11:00-12:00 class leaves 12:00-14:00 free -> ok
    fine = [choice("ALPHA", "Lecture", "1", sess("Monday", 660, 720))]
    assert raw(fine, config, "lunch") == 0


def test_total_is_weighted_sum(config):
    cs = [choice("ALPHA", "Tutorial", "01", sess("Monday", 540, 660))]
    total, breakdown = score_assignment(cs, config)
    assert total == pytest.approx(sum(w for _, w in breakdown.values()))
    assert breakdown["free_days"][1] == pytest.approx(4 * config.preferences.weights["free_days"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_scoring.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'optimiser.scoring'`

- [ ] **Step 3: Implement `optimiser/scoring.py`**

```python
from __future__ import annotations

from .model import DAYS

WEEKDAYS = DAYS[:5]


def _merged_intervals(sessions) -> list:
    intervals = sorted((s.start, s.end) for s in sessions)
    merged = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def score_assignment(choices, config):
    prefs = config.preferences
    campus = [s for c in choices for s in c.sessions if not s.online]
    by_day: dict = {}
    for s in campus:
        by_day.setdefault(s.day, []).append(s)

    raw = {}

    raw["time_window"] = (
        -sum(
            max(0, min(s.end, prefs.earliest_start) - s.start)
            + max(0, s.end - max(s.start, prefs.latest_end))
            for s in campus
        )
        / 60
    )

    tough: dict = {}
    for c in choices:
        difficulty = config.difficulty(c.module, c.lesson_type)
        for s in c.sessions:
            tough[s.day] = tough.get(s.day, 0) + difficulty
    raw["tough_days"] = -sum(
        max(0, total - prefs.max_difficulty_per_day) for total in tough.values()
    )

    lecture_days: dict = {}
    for c in choices:
        if c.lesson_type == "Lecture":
            lecture_days.setdefault(c.module, set()).update(
                s.day for s in c.sessions if not s.online
            )
    raw["same_day_pairing"] = sum(
        1
        for c in choices
        if c.lesson_type != "Lecture"
        and any(s.day in lecture_days.get(c.module, ()) for s in c.sessions)
    )

    raw["free_days"] = sum(1 for day in WEEKDAYS if day not in by_day)

    gap_minutes = 0
    lunchless = 0
    for sessions in by_day.values():
        merged = _merged_intervals(sessions)
        gap_minutes += sum(b[0] - a[1] for a, b in zip(merged, merged[1:]))

        free_blocks = []
        cursor = prefs.lunch_start
        for start, end in merged:
            if end <= prefs.lunch_start or start >= prefs.lunch_end:
                continue
            if start > cursor:
                free_blocks.append(start - cursor)
            cursor = max(cursor, end)
        if prefs.lunch_end > cursor:
            free_blocks.append(prefs.lunch_end - cursor)
        if max(free_blocks, default=0) < prefs.lunch_minutes:
            lunchless += 1
    raw["gaps"] = -gap_minutes / 60
    raw["lunch"] = -lunchless

    breakdown = {name: (value, prefs.weights[name] * value) for name, value in raw.items()}
    total = sum(weighted for _, weighted in breakdown.values())
    return total, breakdown
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_scoring.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add optimiser/scoring.py tests/test_scoring.py
git commit -m "feat: weighted timetable scoring with online-lesson handling"
```

---

### Task 5: Search

**Files:**
- Create: `optimiser/search.py`
- Test: `tests/test_search.py`

**Interfaces:**
- Consumes: `model.ChoiceGroup/Choice`, `scoring.score_assignment`, `Config` (`fixed`, `balloted_types`, `top_n`), `model.LESSON_ABBREV`.
- Produces:
  - `search.prepare_groups(groups: list[ChoiceGroup], config: Config) -> list[ChoiceGroup]` — applies `config.fixed` restrictions (SystemExit if a fixed classNo doesn't exist); warns (prints) for multi-option non-balloted groups without a fixed choice.
  - `search.search(groups: list[ChoiceGroup], config: Config) -> SearchResult`
  - `SearchResult` dataclass:
    - `top: list[tuple[float, dict, dict]]` — `(total, breakdown, assignment)` best-first; `assignment` maps `(module, lesson_type_full) -> Choice` (footprint representatives).
    - `best_by_footprint: dict[tuple[str, str, frozenset], float]` — `(module, lesson_type, footprint) -> best total achievable using it`.
    - `members: dict[tuple[str, str], dict[frozenset, list[Choice]]]` — per group: footprint → choices sharing it, sorted by class_no.
    - `evaluated: int` — number of clash-free footprint-level timetables scored.
  - `search.find_irreconcilable(groups) -> tuple[ChoiceGroup, ChoiceGroup] | None` — first pair of groups where every choice pair clashes.

- [ ] **Step 1: Write the failing tests**

`tests/test_search.py`:

```python
import itertools

import pytest

from optimiser.api import build_groups, semester_timetable
from optimiser.model import ChoiceGroup
from optimiser.scoring import score_assignment
from optimiser.search import find_irreconcilable, prepare_groups, search


@pytest.fixture
def groups(alpha_json, beta_json, config):
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1)) + build_groups(
        "BETA", semester_timetable(beta_json, 1)
    )
    return prepare_groups(gs, config)


def test_prepare_groups_applies_fixed(groups):
    beta_lec = next(g for g in groups if g.key == ("BETA", "Lecture"))
    assert [c.class_no for c in beta_lec.choices] == ["1"]  # config.fixed pins it


def test_prepare_groups_bad_fixed(alpha_json, config):
    config.fixed = {"ALPHA": {"LEC": "99"}}
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    with pytest.raises(SystemExit):
        prepare_groups(gs, config)


def test_search_footprint_dedup_and_clash(groups, config):
    result = search(groups, config)
    # ALPHA TUT footprints: {Mon}, {Tue} (02+03 collapse). BETA LAB: L1, L2.
    # L1 clashes ALPHA TUT 01 -> clash-free footprint combos = 2*2 - 1 = 3
    assert result.evaluated == 3
    tut_members = result.members[("ALPHA", "Tutorial")]
    assert sorted(len(v) for v in tut_members.values()) == [1, 2]


def test_search_top_sorted_and_assignment_shape(groups, config):
    result = search(groups, config)
    totals = [t for t, _, _ in result.top]
    assert totals == sorted(totals, reverse=True)
    _, _, assignment = result.top[0]
    assert set(assignment) == {
        ("ALPHA", "Lecture"),
        ("ALPHA", "Tutorial"),
        ("BETA", "Lecture"),
        ("BETA", "Laboratory"),
    }


def test_best_by_footprint_matches_bruteforce(groups, config):
    result = search(groups, config)
    best = {}
    for combo in itertools.product(*(g.choices for g in groups)):
        if any(a.clashes(b) for a, b in itertools.combinations(combo, 2)):
            continue
        total, _ = score_assignment(list(combo), config)
        for c in combo:
            key = (c.module, c.lesson_type, c.footprint)
            best[key] = max(best.get(key, float("-inf")), total)
    assert result.best_by_footprint == pytest.approx(best)


def test_find_irreconcilable(config):
    from tests.conftest import lesson
    from optimiser.api import build_groups as bg

    a = bg("A", [lesson("1", "Tutorial", "Monday", "1000", "1200")])
    b = bg("B", [lesson("1", "Tutorial", "Monday", "1100", "1300")])
    pair = find_irreconcilable(a + b)
    assert pair is not None
    assert {pair[0].module, pair[1].module} == {"A", "B"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_search.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'optimiser.search'`

- [ ] **Step 3: Implement `optimiser/search.py`**

```python
from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field

from .model import LESSON_ABBREV, ChoiceGroup
from .scoring import score_assignment


@dataclass
class SearchResult:
    top: list
    best_by_footprint: dict
    members: dict
    evaluated: int = 0


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
        if len(group.choices) > 1 and abbrev not in config.balloted_types:
            print(
                f"warning: {group.module} {abbrev} has {len(group.choices)} options "
                "and no fixed choice; searching over all of them"
            )
        prepared.append(group)
    return prepared


def find_irreconcilable(groups: list):
    for a, b in itertools.combinations(groups, 2):
        if all(ca.clashes(cb) for ca in a.choices for cb in b.choices):
            return a, b
    return None


def search(groups: list, config) -> SearchResult:
    deduped = []  # (group, reps, members)
    for group in groups:
        members: dict = {}
        for c in group.choices:
            members.setdefault(c.footprint, []).append(c)
        reps = [choices[0] for choices in members.values()]
        deduped.append((group, reps, members))
    deduped.sort(key=lambda item: len(item[1]))

    heap: list = []
    best_fp: dict = {}
    chosen: list = []
    state = {"evaluated": 0, "seq": 0}

    def recurse(depth: int) -> None:
        if depth == len(deduped):
            total, breakdown = score_assignment(chosen, config)
            state["evaluated"] += 1
            for c in chosen:
                key = (c.module, c.lesson_type, c.footprint)
                if total > best_fp.get(key, float("-inf")):
                    best_fp[key] = total
            assignment = {(c.module, c.lesson_type): c for c in chosen}
            state["seq"] += 1
            item = (total, state["seq"], breakdown, assignment)
            if len(heap) < config.top_n:
                heapq.heappush(heap, item)
            else:
                heapq.heappushpop(heap, item)
            return
        for choice in deduped[depth][1]:
            if any(choice.clashes(existing) for existing in chosen):
                continue
            chosen.append(choice)
            recurse(depth + 1)
            chosen.pop()

    recurse(0)

    top = [
        (total, breakdown, assignment)
        for total, _, breakdown, assignment in sorted(heap, key=lambda item: -item[0])
    ]
    members_out = {
        (group.module, group.lesson_type): {
            fp: sorted(choices, key=lambda c: c.class_no) for fp, choices in members.items()
        }
        for group, _, members in deduped
    }
    return SearchResult(top, best_fp, members_out, state["evaluated"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_search.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add optimiser/search.py tests/test_search.py
git commit -m "feat: DFS timetable search with clash pruning, footprint dedup, top-N"
```

---

### Task 6: Ballot generation

**Files:**
- Create: `optimiser/ballot.py`
- Test: `tests/test_ballot.py`

**Interfaces:**
- Consumes: `SearchResult.best_by_footprint`, `SearchResult.members`, `Config` (`balloted_types`, `alternatives_per_module`, `priority`), `model.LESSON_ABBREV`.
- Produces:
  - `ballot.BALLOT_TYPE_ORDER = ["Tutorial", "Sectional Teaching", "Recitation", "Laboratory"]` — within-module column order.
  - `BallotOption(module: str, lesson_type: str, class_no: str, letter: str, best_score: float, sessions: tuple, tied_with: list[str])` — `letter` is "A", "B", ... rank within its group; `tied_with` lists other classNos sharing the footprint (interchangeable).
  - `ballot.ranked_options(result: SearchResult, config: Config) -> dict[tuple[str, str], list[BallotOption]]` — per balloted group, up to `alternatives_per_module` options, best first; footprints never in a clash-free timetable are excluded.
  - `ballot.snake(options_by_group: dict, config: Config, cap: int = 20) -> list[BallotOption]` — columns ordered by module priority then `BALLOT_TYPE_ORDER`; round 0 forward, round 1 reversed, alternating; exhausted columns skipped; capped.

- [ ] **Step 1: Write the failing tests**

`tests/test_ballot.py`:

```python
import pytest

from optimiser.ballot import BallotOption, ranked_options, snake
from optimiser.model import Session
from optimiser.search import SearchResult

ALL_WEEKS = frozenset(range(1, 14))


def sess(day="Monday", start=600, end=660):
    return Session(day, start, end, ALL_WEEKS, "COM1")


def opt(module, ltype, class_no, letter):
    return BallotOption(module, ltype, class_no, letter, 0.0, (sess(),), [])


def fake_result(config):
    """ALPHA Tutorial: fp1 {01,02} score 10, fp2 {03} score 8, fp3 {04} never viable.
    BETA Laboratory: fpA {L1} score 9, fpB {L2} score 7."""
    from optimiser.model import Choice

    def ch(module, ltype, no, day):
        return Choice(module, ltype, no, (sess(day),))

    a1, a2 = ch("ALPHA", "Tutorial", "01", "Monday"), ch("ALPHA", "Tutorial", "02", "Monday")
    a3 = ch("ALPHA", "Tutorial", "03", "Tuesday")
    a4 = ch("ALPHA", "Tutorial", "04", "Friday")
    b1, b2 = ch("BETA", "Laboratory", "L1", "Wednesday"), ch("BETA", "Laboratory", "L2", "Thursday")
    members = {
        ("ALPHA", "Tutorial"): {
            a1.footprint: [a1, a2],
            a3.footprint: [a3],
            a4.footprint: [a4],
        },
        ("BETA", "Laboratory"): {b1.footprint: [b1], b2.footprint: [b2]},
        ("ALPHA", "Lecture"): {ch("ALPHA", "Lecture", "1", "Monday").footprint: [ch("ALPHA", "Lecture", "1", "Monday")]},
    }
    best = {
        ("ALPHA", "Tutorial", a1.footprint): 10.0,
        ("ALPHA", "Tutorial", a3.footprint): 8.0,
        # a4 footprint absent: never part of a clash-free timetable
        ("BETA", "Laboratory", b1.footprint): 9.0,
        ("BETA", "Laboratory", b2.footprint): 7.0,
    }
    return SearchResult(top=[], best_by_footprint=best, members=members, evaluated=3)


def test_ranked_options(config):
    options = ranked_options(fake_result(config), config)
    assert set(options) == {("ALPHA", "Tutorial"), ("BETA", "Laboratory")}  # LEC not balloted
    tut = options[("ALPHA", "Tutorial")]
    assert [o.class_no for o in tut] == ["01", "02", "03"]  # 04 excluded (never viable)
    assert [o.letter for o in tut] == ["A", "B", "C"]
    assert tut[0].tied_with == ["02"] and tut[2].tied_with == []
    assert tut[0].best_score == pytest.approx(10.0)


def test_ranked_options_caps_alternatives(config):
    config.alternatives_per_module = 2
    tut = ranked_options(fake_result(config), config)[("ALPHA", "Tutorial")]
    assert [o.class_no for o in tut] == ["01", "02"]


def test_snake_order(config):
    options = {
        ("ALPHA", "Tutorial"): [opt("ALPHA", "Tutorial", n, l) for n, l in [("01", "A"), ("02", "B"), ("03", "C")]],
        ("ALPHA", "Laboratory"): [opt("ALPHA", "Laboratory", n, l) for n, l in [("L1", "A"), ("L2", "B")]],
        ("BETA", "Sectional Teaching"): [opt("BETA", "Sectional Teaching", n, l) for n, l in [("S1", "A")]],
    }
    entries = snake(options, config)  # priority ALPHA, BETA; TUT before LAB
    labels = [(e.module, e.class_no) for e in entries]
    assert labels == [
        ("ALPHA", "01"), ("ALPHA", "L1"), ("BETA", "S1"),  # round A forward
        ("ALPHA", "L2"), ("ALPHA", "02"),                   # round B reversed, BETA exhausted
        ("ALPHA", "03"),                                    # round C forward
    ]


def test_snake_cap(config):
    options = {
        ("ALPHA", "Tutorial"): [opt("ALPHA", "Tutorial", f"{i:02d}", "A") for i in range(30)],
    }
    assert len(snake(options, config)) == 20
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ballot.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'optimiser.ballot'`

- [ ] **Step 3: Implement `optimiser/ballot.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

from .model import LESSON_ABBREV

BALLOT_TYPE_ORDER = ["Tutorial", "Sectional Teaching", "Recitation", "Laboratory"]


@dataclass
class BallotOption:
    module: str
    lesson_type: str
    class_no: str
    letter: str
    best_score: float
    sessions: tuple
    tied_with: list


def ranked_options(result, config) -> dict:
    options_by_group: dict = {}
    for (module, lesson_type), fp_members in result.members.items():
        if LESSON_ABBREV.get(lesson_type) not in config.balloted_types:
            continue
        scored = []
        for fp, choices in fp_members.items():
            best = result.best_by_footprint.get((module, lesson_type, fp))
            if best is None:
                continue  # never part of any clash-free timetable
            scored.append((best, choices))
        scored.sort(key=lambda item: (-item[0], item[1][0].class_no))

        options = []
        for best, choices in scored:
            class_nos = [c.class_no for c in choices]
            for c in choices:
                if len(options) >= config.alternatives_per_module:
                    break
                options.append(
                    BallotOption(
                        module=module,
                        lesson_type=lesson_type,
                        class_no=c.class_no,
                        letter=chr(ord("A") + len(options)),
                        best_score=best,
                        sessions=c.sessions,
                        tied_with=[n for n in class_nos if n != c.class_no],
                    )
                )
        if options:
            options_by_group[(module, lesson_type)] = options
    return options_by_group


def snake(options_by_group: dict, config, cap: int = 20) -> list:
    def column_key(key):
        module, lesson_type = key
        module_rank = (
            config.priority.index(module) if module in config.priority else len(config.priority)
        )
        type_rank = (
            BALLOT_TYPE_ORDER.index(lesson_type)
            if lesson_type in BALLOT_TYPE_ORDER
            else len(BALLOT_TYPE_ORDER)
        )
        return (module_rank, type_rank)

    columns = [options_by_group[key] for key in sorted(options_by_group, key=column_key)]
    entries = []
    depth = max((len(col) for col in columns), default=0)
    for round_no in range(depth):
        row = [col[round_no] for col in columns if len(col) > round_no]
        if round_no % 2 == 1:
            row.reverse()
        entries.extend(row)
    return entries[:cap]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ballot.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add optimiser/ballot.py tests/test_ballot.py
git commit -m "feat: ballot alternatives ranking and snake-order generation"
```

---

### Task 7: Output rendering

**Files:**
- Create: `optimiser/output.py`
- Test: `tests/test_output.py`

**Interfaces:**
- Consumes: `assignment: dict[(module, lesson_type_full), Choice]`, `(total, breakdown)` from scoring, `BallotOption` lists from ballot.
- Produces:
  - `output.share_url(assignment: dict, semester: int) -> str` — `https://nusmods.com/timetable/sem-{semester}/share?CODE=TYPE:NO,...` with modules and their type entries sorted.
  - `output.render_week(assignment: dict) -> str` — per-weekday hour-grid row (08:00–20:00 cells showing module code, `~` prefix when online) plus indented `HHMM-HHMM MODULE TYPE[NO] @venue` agenda lines.
  - `output.render_breakdown(total: float, breakdown: dict) -> str`
  - `output.render_options(options_by_group: dict) -> str`
  - `output.render_snake(entries: list[BallotOption]) -> str` — numbered entries with day/time and interchangeability notes.

- [ ] **Step 1: Write the failing tests**

`tests/test_output.py`:

```python
from optimiser.ballot import BallotOption
from optimiser.model import Choice, Session
from optimiser.output import render_breakdown, render_options, render_snake, render_week, share_url

ALL_WEEKS = frozenset(range(1, 14))


def make_assignment():
    lec = Choice("ALPHA", "Lecture", "2", (Session("Monday", 600, 720, ALL_WEEKS, "E-Learn_C"),))
    tut = Choice("ALPHA", "Tutorial", "07A", (Session("Monday", 840, 900, ALL_WEEKS, "COM1-0201"),))
    lab = Choice("BETA", "Laboratory", "14B", (Session("Friday", 600, 720, ALL_WEEKS, "COM4"),))
    return {
        ("ALPHA", "Lecture"): lec,
        ("ALPHA", "Tutorial"): tut,
        ("BETA", "Laboratory"): lab,
    }


def test_share_url():
    url = share_url(make_assignment(), 1)
    assert url == "https://nusmods.com/timetable/sem-1/share?ALPHA=LEC:2,TUT:07A&BETA=LAB:14B"


def test_render_week_contains_sessions_and_online_mark():
    text = render_week(make_assignment())
    assert "1400-1500 ALPHA TUT[07A] @COM1-0201" in text
    assert "1000-1200 ALPHA LEC[2] @E-Learn_C (online)" in text
    assert "~ALPHA" in text  # online marker in the grid row
    assert "Mon" in text and "Fri" in text


def test_render_breakdown():
    text = render_breakdown(3.5, {"gaps": (-2.0, -2.0), "free_days": (2, 8.0)})
    assert "score: +3.50" in text
    assert "gaps" in text and "free_days" in text


def test_render_options_and_snake():
    entry = BallotOption(
        "ALPHA", "Tutorial", "01", "A", 10.0,
        (Session("Monday", 840, 900, ALL_WEEKS, "COM1"),), ["02"],
    )
    options_text = render_options({("ALPHA", "Tutorial"): [entry]})
    assert "ALPHA TUT" in options_text and "01" in options_text
    snake_text = render_snake([entry])
    assert snake_text.startswith(" 1. ALPHA TUT[01]")
    assert "choice A" in snake_text
    assert "Mon 1400-1500" in snake_text
    assert "interchangeable with 02" in snake_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_output.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'optimiser.output'`

- [ ] **Step 3: Implement `optimiser/output.py`**

```python
from __future__ import annotations

from .model import DAYS, LESSON_ABBREV, fmt_time

WEEKDAYS = DAYS[:5]
GRID_HOURS = range(8, 21)
CELL = 8


def share_url(assignment: dict, semester: int) -> str:
    by_module: dict = {}
    for (module, lesson_type), choice in assignment.items():
        by_module.setdefault(module, []).append(
            f"{LESSON_ABBREV[lesson_type]}:{choice.class_no}"
        )
    parts = [f"{module}={','.join(sorted(entries))}" for module, entries in sorted(by_module.items())]
    return f"https://nusmods.com/timetable/sem-{semester}/share?" + "&".join(parts)


def render_week(assignment: dict) -> str:
    lines = ["     " + "".join(f"{hour:02d}00".ljust(CELL) for hour in GRID_HOURS)]
    for day in WEEKDAYS:
        cells = {hour: " " * CELL for hour in GRID_HOURS}
        agenda = []
        for (module, lesson_type), choice in sorted(assignment.items()):
            for session in choice.sessions:
                if session.day != day:
                    continue
                mark = "~" if session.online else ""
                label = f"{mark}{module}"[: CELL - 1].ljust(CELL)
                for hour in range(session.start // 60, (session.end + 59) // 60):
                    if hour in cells:
                        cells[hour] = label
                online_note = " (online)" if session.online else ""
                agenda.append(
                    (
                        session.start,
                        f"       {fmt_time(session.start)}-{fmt_time(session.end)} "
                        f"{module} {LESSON_ABBREV[lesson_type]}[{choice.class_no}] "
                        f"@{session.venue}{online_note}",
                    )
                )
        lines.append(f"{day[:3]:5}" + "".join(cells[hour] for hour in GRID_HOURS))
        lines.extend(text for _, text in sorted(agenda))
    return "\n".join(lines)


def render_breakdown(total: float, breakdown: dict) -> str:
    lines = [f"score: {total:+.2f}"]
    for name, (raw, weighted) in sorted(breakdown.items()):
        lines.append(f"    {name:18} raw {raw:+8.2f}   weighted {weighted:+8.2f}")
    return "\n".join(lines)


def _when(sessions) -> str:
    return "; ".join(
        f"{s.day[:3]} {fmt_time(s.start)}-{fmt_time(s.end)}" for s in sessions
    )


def render_options(options_by_group: dict) -> str:
    lines = []
    for (module, lesson_type), options in options_by_group.items():
        lines.append(f"{module} {LESSON_ABBREV[lesson_type]}:")
        for option in options:
            tie = (
                f"  (interchangeable with {', '.join(option.tied_with)})"
                if option.tied_with
                else ""
            )
            lines.append(
                f"    {option.letter}. [{option.class_no}] {_when(option.sessions)}"
                f"   best score {option.best_score:+.2f}{tie}"
            )
    return "\n".join(lines)


def render_snake(entries: list) -> str:
    lines = []
    for position, option in enumerate(entries, 1):
        tie = (
            f"  (interchangeable with {', '.join(option.tied_with)})"
            if option.tied_with
            else ""
        )
        lines.append(
            f"{position:2}. {option.module} {LESSON_ABBREV[option.lesson_type]}"
            f"[{option.class_no}]  choice {option.letter}  {_when(option.sessions)}{tie}"
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_output.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add optimiser/output.py tests/test_output.py
git commit -m "feat: terminal week view, share URLs, ballot rendering"
```

---

### Task 8: CLI `init`

**Files:**
- Create: `optimiser/cli.py`, `optimiser/__main__.py`
- Test: `tests/test_cli_init.py`

**Interfaces:**
- Consumes: `api.fetch_module/semester_timetable/build_groups`, `config.DEFAULT_BALLOTED/DEFAULT_PREFERENCES`, `model.LESSON_ABBREV`.
- Produces:
  - `cli.parse_share_url(url: str) -> tuple[int, dict[str, dict[str, str]]]` — `(semester, {module: {abbrev: class_no}})`; modules with no selections map to `{}`; `SystemExit` on malformed URL/fragment.
  - `cli.guess_acad_year(today: datetime.date | None = None) -> str` — June onwards → `"{Y}-{Y+1}"`, else `"{Y-1}-{Y}"`.
  - `cli.cmd_init(args)` — interactive; writes YAML config.
  - `cli.main(argv: list[str] | None = None)` — argparse with global `--config` (default `config.yaml`) and `--cache-dir` (default `data/cache`); subcommands `init <share_url> [--acad-year]` and `run`.
  - `optimiser/__main__.py` delegating to `cli.main()`.
  - `cmd_run` is a stub in this task (`raise SystemExit("run: not implemented yet")`); Task 9 replaces it.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli_init.py`:

```python
import datetime

import pytest
import yaml

from optimiser.cli import guess_acad_year, main, parse_share_url

SHARE_URL = (
    "https://nusmods.com/timetable/sem-1/share?"
    "ALPHA=TUT:01,LEC:1&BETA=LAB:L2,LEC:1"
)


def test_parse_share_url():
    semester, selections = parse_share_url(SHARE_URL)
    assert semester == 1
    assert selections == {
        "ALPHA": {"TUT": "01", "LEC": "1"},
        "BETA": {"LAB": "L2", "LEC": "1"},
    }


def test_parse_share_url_empty_selection():
    _, selections = parse_share_url("https://nusmods.com/timetable/sem-2/share?ALPHA=")
    assert selections == {"ALPHA": {}}


def test_parse_share_url_rejects_garbage():
    with pytest.raises(SystemExit):
        parse_share_url("https://example.com/nothing")
    with pytest.raises(SystemExit):
        parse_share_url("https://nusmods.com/timetable/sem-1/share?ALPHA=junk")


def test_guess_acad_year():
    assert guess_acad_year(datetime.date(2026, 7, 13)) == "2026-2027"
    assert guess_acad_year(datetime.date(2026, 2, 1)) == "2025-2026"


def test_cmd_init_writes_config(tmp_path, monkeypatch, alpha_json, beta_json):
    fixtures = {"ALPHA": alpha_json, "BETA": beta_json}
    monkeypatch.setattr(
        "optimiser.cli.api",
        type(
            "FakeApi",
            (),
            {
                "fetch_module": staticmethod(lambda ay, code, cache: fixtures[code]),
                "semester_timetable": staticmethod(
                    __import__("optimiser.api", fromlist=["x"]).semester_timetable
                ),
                "build_groups": staticmethod(
                    __import__("optimiser.api", fromlist=["x"]).build_groups
                ),
            },
        ),
    )
    # prompts: ALPHA LEC diff, ALPHA TUT diff, BETA LAB diff, BETA LEC diff, priority
    answers = iter(["2", "4", "", "1", "BETA,ALPHA"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    config_path = tmp_path / "config.yaml"
    main(
        [
            "--config", str(config_path),
            "--cache-dir", str(tmp_path / "cache"),
            "init", SHARE_URL,
            "--acad-year", "2026-2027",
        ]
    )

    written = yaml.safe_load(config_path.read_text())
    assert written["acad_year"] == "2026-2027"
    assert written["semester"] == 1
    assert written["modules"]["ALPHA"]["difficulty"] == {"LEC": 2, "TUT": 4}
    assert written["modules"]["BETA"]["difficulty"] == {"LAB": 3, "LEC": 1}
    # BETA has 2 lecture groups and a URL pick -> fixed; ALPHA has 1 lecture group -> not fixed
    assert written["fixed"] == {"BETA": {"LEC": "1"}}
    assert written["priority"] == ["BETA", "ALPHA"]
    assert written["balloted_types"] == ["TUT", "LAB", "REC", "SEC"]
    assert written["preferences"]["weights"]["free_days"] == 4


def test_cmd_init_refuses_overwrite_without_confirmation(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("existing: true")
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    with pytest.raises(SystemExit):
        main(["--config", str(config_path), "init", SHARE_URL])
    assert config_path.read_text() == "existing: true"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli_init.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'optimiser.cli'`

- [ ] **Step 3: Implement `optimiser/cli.py` (init + run stub) and `optimiser/__main__.py`**

`optimiser/cli.py`:

```python
from __future__ import annotations

import argparse
import datetime
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

from . import api
from .config import DEFAULT_BALLOTED, DEFAULT_PREFERENCES
from .model import LESSON_ABBREV


def parse_share_url(url: str):
    parsed = urlparse(url)
    match = re.search(r"/timetable/sem-(\d)/share", parsed.path)
    if not match:
        raise SystemExit(f"error: not an NUSMods share URL: {url}")
    semester = int(match.group(1))
    selections: dict = {}
    for code, values in parse_qs(parsed.query, keep_blank_values=True).items():
        picks: dict = {}
        for fragment in values[0].split(","):
            if not fragment:
                continue
            if ":" not in fragment:
                raise SystemExit(f"error: cannot parse '{fragment}' in share URL ({code})")
            abbrev, class_no = fragment.split(":", 1)
            picks[abbrev] = class_no
        selections[code.upper()] = picks
    if not selections:
        raise SystemExit("error: share URL contains no modules")
    return semester, selections


def guess_acad_year(today: datetime.date | None = None) -> str:
    today = today or datetime.date.today()
    if today.month >= 6:
        return f"{today.year}-{today.year + 1}"
    return f"{today.year - 1}-{today.year}"


def _prompt_difficulty(code: str, abbrev: str) -> int:
    while True:
        answer = input(f"difficulty for {code} {abbrev} (1-5) [3]: ").strip()
        if not answer:
            return 3
        if answer.isdigit() and 1 <= int(answer) <= 5:
            return int(answer)
        print("please enter a number from 1 to 5")


def cmd_init(args) -> None:
    config_path = Path(args.config)
    if config_path.exists():
        answer = input(f"{config_path} already exists — overwrite? [y/N] ").strip().lower()
        if answer != "y":
            raise SystemExit("aborted")

    semester, selections = parse_share_url(args.share_url)
    acad_year = args.acad_year or guess_acad_year()
    cache_dir = Path(args.cache_dir)

    modules_cfg: dict = {}
    fixed: dict = {}
    for code, picks in selections.items():
        data = api.fetch_module(acad_year, code, cache_dir)
        groups = api.build_groups(code, api.semester_timetable(data, semester))
        difficulty: dict = {}
        for group in sorted(groups, key=lambda g: g.lesson_type):
            abbrev = LESSON_ABBREV.get(group.lesson_type, group.lesson_type)
            difficulty[abbrev] = _prompt_difficulty(code, abbrev)
            if abbrev not in DEFAULT_BALLOTED and len(group.choices) > 1:
                if abbrev in picks:
                    fixed.setdefault(code, {})[abbrev] = picks[abbrev]
                else:
                    print(
                        f"note: {code} {abbrev} has {len(group.choices)} options and no pick "
                        "in the URL; it will be searched over"
                    )
        modules_cfg[code] = {"difficulty": difficulty}

    default_order = ",".join(selections)
    answer = input(f"priority order, most important first [{default_order}]: ").strip()
    priority = (
        [code.strip().upper() for code in answer.split(",")] if answer else list(selections)
    )
    unknown = [code for code in priority if code not in selections]
    if unknown:
        raise SystemExit(f"error: priority lists unknown module(s): {', '.join(unknown)}")

    config = {
        "acad_year": acad_year,
        "semester": semester,
        "balloted_types": list(DEFAULT_BALLOTED),
        "modules": modules_cfg,
        "fixed": fixed,
        "priority": priority,
        "preferences": DEFAULT_PREFERENCES,
        "alternatives_per_module": 4,
        "top_n": 5,
    }
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    print(f"wrote {config_path} — tweak preferences there, then: optimiser run")


def cmd_run(args) -> None:
    raise SystemExit("run: not implemented yet")


def main(argv: list | None = None) -> None:
    parser = argparse.ArgumentParser(prog="optimiser", description="NUS timetable optimiser")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--cache-dir", default="data/cache", help="API cache directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="generate config.yaml from a share URL")
    init_parser.add_argument("share_url", help="NUSMods share URL with your current picks")
    init_parser.add_argument("--acad-year", help="e.g. 2026-2027 (default: guessed from date)")

    subparsers.add_parser("run", help="search timetables and print ballot ranking")

    args = parser.parse_args(argv)
    if args.command == "init":
        cmd_init(args)
    else:
        cmd_run(args)
```

`optimiser/__main__.py`:

```python
from .cli import main

main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli_init.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add optimiser/cli.py optimiser/__main__.py tests/test_cli_init.py
git commit -m "feat: CLI init — share URL parsing, interactive config generation"
```

---

### Task 9: CLI `run`, end-to-end test, README

**Files:**
- Create: `README.md`
- Modify: `optimiser/cli.py` (replace `cmd_run` stub, extend imports)
- Test: `tests/test_cli_run.py`

**Interfaces:**
- Consumes: everything from Tasks 2–7.
- Produces: `cli.cmd_run(args)` — full pipeline: load config → fetch/build groups → `prepare_groups` → `search` → print top-N (breakdown, week view, share URL), backup options, snake ballot. `SystemExit` with irreconcilable-pair message when no clash-free timetable exists.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli_run.py`:

```python
import pytest
import yaml

from optimiser.cli import main


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "acad_year": "2026-2027",
                "semester": 1,
                "modules": {
                    "ALPHA": {"difficulty": {"LEC": 2, "TUT": 4}},
                    "BETA": {"difficulty": 3},
                },
                "fixed": {"BETA": {"LEC": "1"}},
                "priority": ["ALPHA", "BETA"],
                "top_n": 2,
            }
        )
    )
    return path


def run_cli(tmp_path, config_file, monkeypatch, capsys, fixtures):
    monkeypatch.setattr(
        "optimiser.cli.api.fetch_module", lambda ay, code, cache: fixtures[code]
    )
    main(["--config", str(config_file), "--cache-dir", str(tmp_path / "cache"), "run"])
    return capsys.readouterr().out


def test_run_end_to_end(tmp_path, config_file, monkeypatch, capsys, alpha_json, beta_json):
    out = run_cli(
        tmp_path, config_file, monkeypatch, capsys, {"ALPHA": alpha_json, "BETA": beta_json}
    )
    assert "timetable #1" in out
    assert "https://nusmods.com/timetable/sem-1/share?" in out
    assert "score:" in out
    assert "ballot ranking" in out
    # BETA lecture is fixed to the online group 1, so it appears with LEC:1
    assert "BETA=LAB:" in out and "LEC:1" in out
    # backup section lists ALPHA tutorials with interchangeable pair 02/03
    assert "interchangeable" in out


def test_run_reports_irreconcilable(tmp_path, config_file, monkeypatch, capsys):
    from tests.conftest import lesson

    clash_a = {
        "moduleCode": "ALPHA",
        "semesterData": [{"semester": 1, "timetable": [
            lesson("1", "Lecture", "Monday", "1000", "1200"),
            lesson("01", "Tutorial", "Monday", "1300", "1400"),
        ]}],
    }
    clash_b = {
        "moduleCode": "BETA",
        "semesterData": [{"semester": 1, "timetable": [
            lesson("1", "Lecture", "Monday", "1100", "1300"),
            lesson("L1", "Laboratory", "Monday", "1300", "1500"),
        ]}],
    }
    monkeypatch.setattr(
        "optimiser.cli.api.fetch_module",
        lambda ay, code, cache: {"ALPHA": clash_a, "BETA": clash_b}[code],
    )
    with pytest.raises(SystemExit) as exc:
        main(["--config", str(config_file), "run"])
    assert "no clash-free timetable" in str(exc.value)
```

Note: `config_file` fixture omits BETA's `fixed` pick in the irreconcilable test path — BETA has one lecture group there, so `fixed: {BETA: {LEC: "1"}}` still resolves (classNo "1" exists in both fixtures).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli_run.py -q`
Expected: FAIL with `SystemExit: run: not implemented yet`

- [ ] **Step 3: Implement `cmd_run`**

In `optimiser/cli.py`, extend the imports:

```python
from . import api, ballot, output, search
from .config import DEFAULT_BALLOTED, DEFAULT_PREFERENCES, load_config
```

Replace the `cmd_run` stub with:

```python
def cmd_run(args) -> None:
    config = load_config(Path(args.config))
    cache_dir = Path(args.cache_dir)

    groups = []
    for code in config.modules:
        data = api.fetch_module(config.acad_year, code, cache_dir)
        groups.extend(api.build_groups(code, api.semester_timetable(data, config.semester)))
    groups = search.prepare_groups(groups, config)

    result = search.search(groups, config)
    if not result.top:
        pair = search.find_irreconcilable(groups)
        if pair:
            first, second = pair
            raise SystemExit(
                "error: no clash-free timetable — every "
                f"{first.module} {first.lesson_type} clashes with every "
                f"{second.module} {second.lesson_type}"
            )
        raise SystemExit("error: no clash-free timetable found")

    print(f"evaluated {result.evaluated} clash-free timetables\n")
    for rank, (total, breakdown, assignment) in enumerate(result.top, 1):
        print(f"=== timetable #{rank} ===")
        print(output.render_breakdown(total, breakdown))
        print(output.render_week(assignment))
        print(output.share_url(assignment, config.semester))
        print()

    options = ballot.ranked_options(result, config)
    print("=== backup choices per balloted group ===")
    print(output.render_options(options))
    print("\n=== ballot ranking (snake order, cap 20) ===")
    print(output.render_snake(ballot.snake(options, config)))
```

- [ ] **Step 4: Run the full test suite**

Run: `.venv/bin/pytest -q`
Expected: all PASS

- [ ] **Step 5: Write `README.md`**

```markdown
# NUS Course Optimiser

Searches every valid combination of your modules' tutorial/lab/recitation/sectional
slots, scores them against your preferences, and prints:

1. the top-N timetables (with NUSMods share links),
2. ranked backup choices per balloted group, and
3. a snake-order ballot ranking (max 20 entries) ready for tutorial registration.

## Setup

    python3 -m venv .venv
    .venv/bin/pip install -e .

## Usage

Generate a config from your NUSMods share URL (prompts for per-component
difficulty ratings and module priority):

    .venv/bin/optimiser init "https://nusmods.com/timetable/sem-1/share?CS1231S=TUT:07A,LEC:2&..."

Tweak `config.yaml` (preferences, weights, balloted types), then:

    .venv/bin/optimiser run

## How scoring works

Weighted sum of: class time outside your preferred window, per-day difficulty
overload, lecture+tutorial same-day pairing, free days, gaps between classes,
and lunch-break availability. Online lessons (venue `E-Learn_*`) don't count
against physical-presence criteria but do count toward daily difficulty.

Weights and thresholds live under `preferences:` in `config.yaml`.
```

- [ ] **Step 6: Smoke-test against the real API**

```bash
.venv/bin/python -m optimiser --config /tmp/smoke.yaml init \
  "https://nusmods.com/timetable/sem-1/share?CS1231S=TUT:07A,LEC:2&CS2030S=REC:06,LAB:14B,LEC:1&MA1521=LEC:1&MA1522=LEC:2&UTW1001X=SEC:2" \
  --acad-year 2026-2027
.venv/bin/python -m optimiser --config /tmp/smoke.yaml run
```

(Accept difficulty defaults at the prompts.) Expected: config written; `run` prints timetables, backups, and a ballot list without traceback. Note MA1521/MA1522 tutorials may not be published yet — the run should still succeed with whatever groups exist.

- [ ] **Step 7: Commit**

```bash
git add optimiser/cli.py tests/test_cli_run.py README.md
git commit -m "feat: CLI run pipeline, end-to-end tests, README"
```
