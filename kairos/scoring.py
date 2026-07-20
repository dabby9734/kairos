from __future__ import annotations

from typing import NamedTuple

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


class _Fragment(NamedTuple):
    """Everything derivable from a SINGLE choice under a fixed config. Combos
    reuse the same handful of Choice objects, so building this once per distinct
    choice per scoring pass (see search.score_raw) keeps the per-choice work out
    of the ~60K-iteration combo loop."""

    module: str
    is_lecture: bool
    time_window: int      # un-negated, un-divided campus minute penalty (see _combine)
    campus_by_day: dict   # day -> list[Session]  (campus/non-online sessions only)
    pairing_days: frozenset  # days of ALL sessions incl. online (non-lecture pairing test)
    naive_by_day: dict    # day -> summed difficulty (ALL sessions; tough_days fast-path input)
    tough_by_day: dict    # day -> list[(difficulty, weeks)] (ALL sessions)


def _fragment(c, config) -> _Fragment:
    prefs = config.preferences
    campus_by_day: dict = {}
    time_window = 0
    for s in c.sessions:
        if s.online:
            continue
        campus_by_day.setdefault(s.day, []).append(s)
        time_window += (
            max(0, min(s.end, prefs.earliest_start) - s.start)
            + max(0, s.end - max(s.start, prefs.latest_end))
        )
    # tough_days counts ALL sessions, online included; difficulty looked up once.
    difficulty = config.difficulty(c.module, c.lesson_type)
    naive_by_day: dict = {}
    tough_by_day: dict = {}
    for s in c.sessions:
        naive_by_day[s.day] = naive_by_day.get(s.day, 0) + difficulty
        tough_by_day.setdefault(s.day, []).append((difficulty, s.weeks))
    return _Fragment(
        module=c.module,
        is_lecture=c.lesson_type == "Lecture",
        time_window=time_window,
        campus_by_day=campus_by_day,
        pairing_days=frozenset(s.day for s in c.sessions),
        naive_by_day=naive_by_day,
        tough_by_day=tough_by_day,
    )


def tough_day_peaks(choices, config) -> dict:
    """{day: peak_weekly_difficulty} for days whose week-aware peak exceeds
    max_difficulty_per_day. The peak is the largest, over all teaching weeks, of
    the summed difficulty of the sessions active that week — so alternating-week
    sessions on the same day (e.g. a lab and tutorial that never co-occur) are
    not double-counted. All sessions count, including online, as tough_days
    always has. Fast path: the naive all-session daily sum is an upper bound on
    the peak, so days whose naive sum is already <= cap cannot exceed it and skip
    the per-week recount."""
    naive_by_day, tough_by_day = _merge_tough(_fragment(c, config) for c in choices)
    return _tough_peaks(naive_by_day, tough_by_day, config.preferences.max_difficulty_per_day)


def _merge_tough(fragments):
    """Sum the per-choice tough_days inputs across fragments."""
    naive_by_day: dict = {}
    tough_by_day: dict = {}
    for f in fragments:
        for day, difficulty in f.naive_by_day.items():
            naive_by_day[day] = naive_by_day.get(day, 0) + difficulty
        for day, entries in f.tough_by_day.items():
            tough_by_day.setdefault(day, []).extend(entries)
    return naive_by_day, tough_by_day


def _tough_peaks(naive_by_day, tough_by_day, cap) -> dict:
    """{day: peak} for days whose week-aware peak exceeds cap. Fast path: the
    naive all-session sum bounds the peak, so days already <= cap are skipped."""
    peaks: dict = {}
    for day, total in naive_by_day.items():
        if total <= cap:
            continue
        by_week: dict = {}
        for difficulty, weeks in tough_by_day[day]:
            for w in weeks:
                by_week[w] = by_week.get(w, 0) + difficulty
        peak = max(by_week.values(), default=0)
        if peak > cap:
            peaks[day] = peak
    return peaks


def pairing_impossibility(members):
    """From space.members ((module, lesson_type) -> {footprint: [Choice]}),
    find pairings that can never occur because the offered slots share no campus
    day. Returns (unpairable_modules, unpairable_slots):
      - unpairable_modules: modules WITH a campus lecture whose non-lecture slots
        can NONE fall on a lecture day -> scoring counts them as satisfied.
      - unpairable_slots: {(module, lesson_type)} non-lecture slots that can never
        reach a lecture day -> their same-day warning is suppressed.
    Days are taken over offered campus (non-online) sessions, matching the
    same_day_pairing criterion (which ignores online lectures)."""
    lec_days: dict = {}   # module -> set of campus days its lecture is offered on
    slot_days: dict = {}  # (module, lesson_type) -> set of campus days offered
    for (module, lesson_type), by_fp in members.items():
        days = {
            s.day
            for choices in by_fp.values()
            for c in choices
            for s in c.sessions
            if not s.online
        }
        if lesson_type == "Lecture":
            lec_days.setdefault(module, set()).update(days)
        else:
            slot_days.setdefault((module, lesson_type), set()).update(days)

    unpairable_slots = set()
    pairable_by_module: dict = {}  # module -> any non-lecture slot pairable?
    for (module, lesson_type), days in slot_days.items():
        ld = lec_days.get(module)
        pairable = bool(ld) and bool(days & ld)
        if ld and not pairable:
            unpairable_slots.add((module, lesson_type))
        if ld:
            pairable_by_module[module] = pairable_by_module.get(module, False) or pairable

    unpairable_modules = frozenset(
        module for module, pairable in pairable_by_module.items() if not pairable
    )
    return unpairable_modules, frozenset(unpairable_slots)


def _combine(fragments, config, unpairable_modules=frozenset()) -> dict:
    """Merge per-choice fragments into the raw criteria dict. This is the single
    place every criterion is computed; compute_raw and search.score_raw both
    funnel through it. Key order matches the original compute_raw so weight_raw's
    breakdown and float summation stay bit-identical."""
    prefs = config.preferences
    fragments = list(fragments)

    by_day: dict = {}
    for f in fragments:
        for day, sessions in f.campus_by_day.items():
            by_day.setdefault(day, []).extend(sessions)

    raw = {}

    # Negate and divide ONCE on the integer total (not per choice) so the float
    # result is bit-identical to the original single -sum(...) / 60.
    raw["time_window"] = -sum(f.time_window for f in fragments) / 60

    naive_by_day, tough_by_day = _merge_tough(fragments)
    raw["tough_days"] = -sum(
        peak - prefs.max_difficulty_per_day
        for peak in _tough_peaks(naive_by_day, tough_by_day, prefs.max_difficulty_per_day).values()
    )

    # A lecture contributes only its CAMPUS days; a non-lecture pairs if ANY of
    # its sessions (online included) lands on one of them — matching the original.
    lecture_days: dict = {}
    for f in fragments:
        if f.is_lecture:
            lecture_days.setdefault(f.module, set()).update(f.campus_by_day)
    paired_modules = {
        f.module
        for f in fragments
        if not f.is_lecture and (f.pairing_days & lecture_days.get(f.module, frozenset()))
    }
    raw["same_day_pairing"] = len(paired_modules | unpairable_modules)

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


def compute_raw(choices, config, unpairable_modules=frozenset()) -> dict:
    return _combine([_fragment(c, config) for c in choices], config, unpairable_modules)


def weight_raw(raw, config):
    weights = config.preferences.weights
    breakdown = {name: (value, weights[name] * value) for name, value in raw.items()}
    total = sum(weighted for _, weighted in breakdown.values())
    return total, breakdown


def score_assignment(choices, config):
    return weight_raw(compute_raw(choices, config), config)
