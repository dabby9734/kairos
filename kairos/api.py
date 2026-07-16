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
