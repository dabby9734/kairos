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
