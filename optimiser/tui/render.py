from __future__ import annotations

from rich.console import Group
from rich.text import Text

from ..model import LESSON_ABBREV, fmt_time
from ..output import CELL, GRID_HOURS, WEEKDAYS

# Distinct (background, foreground) pairs, assigned to modules in order.
# Chosen for legible contrast on both light and dark terminals.
PALETTE = [
    ("green", "black"),
    ("blue", "white"),
    ("magenta", "white"),
    ("yellow", "black"),
    ("cyan", "black"),
    ("red", "white"),
    ("bright_magenta", "black"),
    ("bright_blue", "black"),
]


def module_colours(modules) -> dict:
    """Map each module code to a stable (background, foreground) pair."""
    return {module: PALETTE[i % len(PALETTE)] for i, module in enumerate(modules)}


def render_week_rich(assignment: dict, colours: dict) -> Group:
    """A Rich renderable of the week grid: each class a coloured strip spanning
    its hours, labelled `MODULE [TYPE]` (or just `MODULE` when the strip is too
    narrow), with an agenda of times/venues below each day."""
    hours = list(GRID_HOURS)
    first_hour = hours[0]
    last_hour = hours[-1]

    header = Text("     ")
    for hour in hours:
        header.append(f"{hour:02d}00".ljust(CELL))
    rows: list = [header]

    for day in WEEKDAYS:
        blocks = []  # (start_h, end_h, module, abbrev, class_no, venue, online, start, end)
        for (module, lesson_type), choice in sorted(assignment.items()):
            abbrev = LESSON_ABBREV.get(lesson_type, lesson_type)
            for session in choice.sessions:
                if session.day != day:
                    continue
                blocks.append(
                    (
                        session.start // 60,
                        (session.end + 59) // 60,
                        module,
                        abbrev,
                        choice.class_no,
                        session.venue,
                        session.online,
                        session.start,
                        session.end,
                    )
                )
        blocks.sort()

        row = Text(f"{day[:3]:5}")
        cursor = first_hour
        agenda = []
        for start_h, end_h, module, abbrev, class_no, venue, online, start, end in blocks:
            # Clamp the start to `cursor` too: hours are floor(start)/ceil(end),
            # so half-hour-boundary back-to-back classes round into overlapping
            # hour cells. Never drawing before where we've already written keeps
            # every strip aligned under the hour header (no sideways drift).
            span_start = max(start_h, first_hour, cursor)
            span_end = min(end_h, last_hour + 1)
            if span_end <= span_start:
                continue
            if span_start > cursor:
                row.append(" " * ((span_start - cursor) * CELL))
            width = (span_end - span_start) * CELL
            mark = "~" if online else ""
            full = f"{mark}{module} [{abbrev}]"
            label = (full if len(full) <= width else f"{mark}{module}")[:width].ljust(width)
            bg, fg = colours.get(module, ("white", "black"))
            style = f"{fg} on {bg}" + (" dim" if online else "")
            row.append(label, style=style)
            cursor = span_end
            note = " (online)" if online else ""
            agenda.append(
                (
                    start,
                    f"       {fmt_time(start)}-{fmt_time(end)} {module} "
                    f"{abbrev}[{class_no}] @{venue}{note}",
                )
            )
        rows.append(row)
        rows.extend(Text(text) for _, text in sorted(agenda))

    return Group(*rows)
