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
