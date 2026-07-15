from __future__ import annotations

from .model import DAYS

WEEKDAYS = DAYS[:5]

COMPONENT_LEGEND = {
    "free_days": "whole free weekdays (more = better)",
    "gaps": "idle hours between classes (fewer = better)",
    "lunch": "days with no lunch break (fewer = better)",
    "same_day_pairing": "tutorials/labs sharing a day with their lecture (more = better)",
    "time_window": "class-hours outside your preferred window (fewer = better)",
    "tough_days": "difficulty piled past your daily cap (less = better)",
}


def _merged_intervals(sessions) -> list:
    intervals = sorted((s.start, s.end) for s in sessions)
    merged = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def tough_day_peaks(choices, config) -> dict:
    """{day: peak_weekly_difficulty} for days whose week-aware peak exceeds
    max_difficulty_per_day. The peak is the largest, over all teaching weeks, of
    the summed difficulty of the sessions active that week — so alternating-week
    sessions on the same day (e.g. a lab and tutorial that never co-occur) are
    not double-counted. All sessions count, including online, as tough_days
    always has. Fast path: the naive all-session daily sum is an upper bound on
    the peak, so days whose naive sum is already <= cap cannot exceed it and skip
    the per-week recount."""
    cap = config.preferences.max_difficulty_per_day
    naive: dict = {}
    per_day: dict = {}
    for c in choices:
        difficulty = config.difficulty(c.module, c.lesson_type)
        for s in c.sessions:
            naive[s.day] = naive.get(s.day, 0) + difficulty
            per_day.setdefault(s.day, []).append((difficulty, s.weeks))
    peaks: dict = {}
    for day, total in naive.items():
        if total <= cap:
            continue
        by_week: dict = {}
        for difficulty, weeks in per_day[day]:
            for w in weeks:
                by_week[w] = by_week.get(w, 0) + difficulty
        peak = max(by_week.values(), default=0)
        if peak > cap:
            peaks[day] = peak
    return peaks


def compute_raw(choices, config) -> dict:
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

    raw["tough_days"] = -sum(
        peak - prefs.max_difficulty_per_day
        for peak in tough_day_peaks(choices, config).values()
    )

    lecture_days: dict = {}
    for c in choices:
        if c.lesson_type == "Lecture":
            lecture_days.setdefault(c.module, set()).update(
                s.day for s in c.sessions if not s.online
            )
    paired_modules = {
        c.module
        for c in choices
        if c.lesson_type != "Lecture"
        and any(s.day in lecture_days.get(c.module, ()) for s in c.sessions)
    }
    raw["same_day_pairing"] = len(paired_modules)

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
    raw["lunch"] = -2 * lunchless

    return raw


def weight_raw(raw, config):
    weights = config.preferences.weights
    breakdown = {name: (value, weights[name] * value) for name, value in raw.items()}
    total = sum(weighted for _, weighted in breakdown.values())
    return total, breakdown


def score_assignment(choices, config):
    return weight_raw(compute_raw(choices, config), config)
