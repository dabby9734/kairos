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


def render_week_rich(assignment: dict, colours: dict, preview=None) -> Group:
    """A Rich renderable of the week grid. Each class is a coloured strip spanning
    its hours, labelled `MODULE [TYPE]` (or just `MODULE` when the strip is too
    narrow), with an agenda of times/venues below each day. Classes whose times
    overlap (non-clashing alternating-week pairs sharing a slot) are stacked on
    separate lanes so every class gets a visible bar; the agenda below always
    lists every class, even one whose strip is undrawable."""
    hours = list(GRID_HOURS)
    first_hour = hours[0]
    last_hour = hours[-1]

    header = Text("     ")
    for hour in hours:
        header.append(f"{hour:02d}00".ljust(CELL))
    rows: list = [header]

    for day in WEEKDAYS:
        # block = (start, end, start_h, end_h, module, abbrev, class_no, venue, online)
        blocks = []
        for (module, lesson_type), choice in sorted(assignment.items()):
            abbrev = LESSON_ABBREV.get(lesson_type, lesson_type)
            for session in choice.sessions:
                if session.day != day:
                    continue
                blocks.append((
                    session.start,
                    session.end,
                    session.start // 60,
                    (session.end + 59) // 60,
                    module,
                    abbrev,
                    choice.class_no,
                    session.venue,
                    session.online,
                    False,  # blink
                ))
        blocks.sort()

        if preview is not None:
            p_module, p_lesson_type, p_sig = preview
            p_abbrev = LESSON_ABBREV.get(p_lesson_type, p_lesson_type)
            for p_day, p_start, p_end, p_online in p_sig:
                if p_day != day:
                    continue
                blocks.append((
                    p_start, p_end, p_start // 60, (p_end + 59) // 60,
                    p_module, p_abbrev, "", "", p_online, True,  # blink
                ))
            blocks.sort()

        # Lane assignment by real time-interval overlap: a block joins the first
        # lane whose last-placed session ends at or before this block starts
        # (blocks are start-sorted, so that means no time overlap). Back-to-back
        # classes stay in one lane; genuinely overlapping classes open a new one.
        lanes: list = []
        lane_end: list = []  # latest end-minute placed in each lane
        for block in blocks:
            start, end = block[0], block[1]
            for i, last_end in enumerate(lane_end):
                if last_end <= start:
                    lanes[i].append(block)
                    lane_end[i] = end
                    break
            else:
                lanes.append([block])
                lane_end.append(end)

        # Render one strip row per lane; a day with no classes still gets one row.
        for li, lane in enumerate(lanes or [[]]):
            row = Text(f"{day[:3]:5}" if li == 0 else "     ")
            cursor = first_hour
            for start, end, start_h, end_h, module, abbrev, class_no, venue, online, blink in lane:
                span_start = max(start_h, first_hour, cursor)
                span_end = min(end_h, last_hour + 1)
                if span_end <= span_start:
                    continue  # undrawable (out of range / cell already used); agenda keeps it
                if span_start > cursor:
                    row.append(" " * ((span_start - cursor) * CELL))
                width = (span_end - span_start) * CELL
                mark = "~" if online else ""
                full = f"{mark}{module} [{abbrev}]"
                label = (full if len(full) <= width else f"{mark}{module}")[:width].ljust(width)
                if blink:
                    style = "blink"
                else:
                    bg, fg = colours.get(module, ("white", "black"))
                    style = f"{fg} on {bg}" + (" dim" if online else "")
                row.append(label, style=style)
                cursor = span_end
            rows.append(row)

        # Agenda: every block for the day, sorted by start time.
        for start, end, _sh, _eh, module, abbrev, class_no, venue, online, blink in sorted(blocks):
            if blink:
                rows.append(Text(f"       {fmt_time(start)}-{fmt_time(end)} {module} {abbrev} (preview)"))
                continue
            note = " (online)" if online else ""
            rows.append(Text(
                f"       {fmt_time(start)}-{fmt_time(end)} {module} "
                f"{abbrev}[{class_no}] @{venue}{note}"
            ))

    return Group(*rows)
