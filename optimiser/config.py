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
    max_arrangements: int = 50

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


def config_from_dict(data, source: str = "config") -> Config:
    if not isinstance(data, dict):
        raise SystemExit(f"error: {source} is empty or not a YAML mapping")
    for key in ("acad_year", "semester"):
        if key not in data:
            raise SystemExit(f"error: {source} is missing required key '{key}'")

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
        raise SystemExit(f"error: no modules in {source}")

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
        max_arrangements=int(data.get("max_arrangements", 50)),
    )


def load_config(path: Path) -> Config:
    if not path.exists():
        raise SystemExit(f"error: {path} not found — run 'optimiser init <share-url>' first")
    data = yaml.safe_load(path.read_text())
    return config_from_dict(data, str(path))
