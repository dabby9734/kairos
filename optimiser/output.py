from __future__ import annotations

from .model import DAYS, LESSON_ABBREV, fmt_time
from .scoring import COMPONENT_LEGEND, _merged_intervals

WEEKDAYS = DAYS[:5]
GRID_HOURS = range(8, 21)
CELL = 8


def share_url(assignment: dict, semester: int) -> str:
    by_module: dict = {}
    for (module, lesson_type), choice in assignment.items():
        by_module.setdefault(module, []).append(
            f"{LESSON_ABBREV.get(lesson_type, lesson_type)}:{choice.class_no}"
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
                        f"{module} {LESSON_ABBREV.get(lesson_type, lesson_type)}[{choice.class_no}] "
                        f"@{session.venue}{online_note}",
                    )
                )
        lines.append(f"{day[:3]:5}" + "".join(cells[hour] for hour in GRID_HOURS))
        lines.extend(text for _, text in sorted(agenda))
    return "\n".join(lines)


def render_breakdown(total: float, breakdown: dict) -> str:
    lines = [f"score: {total:+.2f}"]
    for name, (raw, weighted) in sorted(breakdown.items()):
        desc = COMPONENT_LEGEND.get(name)
        suffix = f"   — {desc}" if desc else ""
        lines.append(f"    {name:18} raw {raw:+8.2f}   weighted {weighted:+8.2f}{suffix}")
    return "\n".join(lines)


def class_warnings(assignment: dict, config) -> list[str]:
    """Human-readable warnings for classes/days that fail the user's criteria in
    this timetable. Each check mirrors scoring.score_assignment so warnings and
    score never disagree. free_days (a bonus) and gaps (an aggregate) produce no
    per-class warning. Returns [] when nothing is violated."""
    prefs = config.preferences
    warnings: list[str] = []

    # time_window: campus sessions starting early / ending late (online excluded)
    tw = []
    for (module, lesson_type), choice in assignment.items():
        abbrev = LESSON_ABBREV.get(lesson_type, lesson_type)
        for s in choice.sessions:
            if s.online:
                continue
            if s.start < prefs.earliest_start:
                tw.append((DAYS.index(s.day), s.start,
                    f"⚠ {module} {abbrev} {s.day[:3]} {fmt_time(s.start)} "
                    f"starts before your earliest {fmt_time(prefs.earliest_start)}"))
            if s.end > prefs.latest_end:
                tw.append((DAYS.index(s.day), s.start,
                    f"⚠ {module} {abbrev} {s.day[:3]} {fmt_time(s.end)} "
                    f"ends after your latest {fmt_time(prefs.latest_end)}"))
    warnings.extend(text for _, _, text in sorted(tw))

    # tough_days: per day whose total difficulty (all sessions incl. online) > cap
    tough: dict = {}
    for choice in assignment.values():
        difficulty = config.difficulty(choice.module, choice.lesson_type)
        for s in choice.sessions:
            tough[s.day] = tough.get(s.day, 0) + difficulty
    for day in sorted(tough, key=DAYS.index):
        if tough[day] > prefs.max_difficulty_per_day:
            warnings.append(
                f"⚠ {day} exceeds max difficulty ({tough[day]} > {prefs.max_difficulty_per_day})"
            )

    # same_day_pairing: non-lecture class whose module has a campus lecture but
    # sits on none of that lecture's days. No campus lecture -> pairing is
    # impossible, so not a violation.
    lecture_days: dict = {}
    for choice in assignment.values():
        if choice.lesson_type == "Lecture":
            lecture_days.setdefault(choice.module, set()).update(
                s.day for s in choice.sessions if not s.online
            )
    unpaired = []
    for (module, lesson_type), choice in assignment.items():
        if lesson_type == "Lecture":
            continue
        days = lecture_days.get(module)
        if not days:
            continue
        if not any(s.day in days for s in choice.sessions):
            abbrev = LESSON_ABBREV.get(lesson_type, lesson_type)
            unpaired.append((module, abbrev))
    for module, abbrev in sorted(unpaired):
        warnings.append(f"⚠ {module} {abbrev} not same-day as its lecture")

    # lunch: per day with no free block >= lunch_minutes in the lunch window
    # (campus sessions only; identical arithmetic to scoring's lunchless count)
    by_day: dict = {}
    for choice in assignment.values():
        for s in choice.sessions:
            if not s.online:
                by_day.setdefault(s.day, []).append(s)
    for day in sorted(by_day, key=DAYS.index):
        merged = _merged_intervals(by_day[day])
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
            warnings.append(f"⚠ {day} has no lunch break")

    return warnings


def _when(sessions) -> str:
    return "; ".join(
        f"{s.day[:3]} {fmt_time(s.start)}-{fmt_time(s.end)}" for s in sessions
    )


def render_options(options_by_group: dict) -> str:
    lines = []
    for (module, lesson_type), options in options_by_group.items():
        lines.append(f"{module} {LESSON_ABBREV.get(lesson_type, lesson_type)}:")
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
            f"{position:2}. {option.module} {LESSON_ABBREV.get(option.lesson_type, option.lesson_type)}"
            f"[{option.class_no}]  choice {option.letter}  {_when(option.sessions)}{tie}"
        )
    return "\n".join(lines)
