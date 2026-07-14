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
