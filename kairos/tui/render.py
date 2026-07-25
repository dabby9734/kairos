from __future__ import annotations

from rich.console import Group
from rich.text import Text

from ..model import LESSON_ABBREV, fmt_time
from ..output import CELL, GRID_HOURS, _render_days

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


def render_week_rich(assignment: dict, colours: dict, preview=None, agenda=True) -> Group:
    """A Rich renderable of the week grid. Each class is a coloured strip spanning
    its hours, labelled `MODULE [TYPE]` (or just `MODULE` when the strip is too
    narrow), with an agenda of times/venues below each day. Classes whose times
    overlap (non-clashing alternating-week pairs sharing a slot) are stacked on
    separate lanes so every class gets a visible bar; when the agenda is
    rendered (see `agenda` below) it always lists every class, even one whose
    strip is undrawable -- with `agenda=False` an undrawable strip vanishes
    with no feedback at all.

    `preview` is an optional `(module, lesson_type, slot_sig)` triple for the
    timeslot the user is currently highlighting. If that class is already on this
    exact slot, its existing strip is inverted in place and nothing is added.
    Otherwise the candidate is drawn as an extra inverted strip plus a
    `(preview)` agenda line, alongside the class's current slot.

    `agenda=False` drops the per-day times/venues lines, leaving strips only.
    The TUI's ballot view pins the grid above a scrolling list, where the full
    agenda would consume the whole pane."""
    hours = list(GRID_HOURS)
    first_hour = hours[0]
    last_hour = hours[-1]

    header = Text("     ")
    for hour in hours:
        header.append(f"{hour:02d}00".ljust(CELL))
    rows: list = [header]

    # Flash mode: the previewed slot is exactly the one this class already
    # occupies. Nothing new gets drawn — the real strips invert in place,
    # rather than a phantom block opening a redundant second lane.
    flash_key = None
    preview_days = None
    if preview is not None:
        p_module, p_lesson_type, p_sig = preview
        current = assignment.get((p_module, p_lesson_type))
        if current is not None and current.slot_sig == p_sig:
            flash_key = (p_module, p_lesson_type)
        else:
            # Force a day row for a candidate landing on an otherwise-empty day.
            # Unnecessary in flash mode: every matched day already has the class.
            preview_days = {p_day for p_day, _start, _end, _online in p_sig}

    for day in _render_days(assignment, extra_days=preview_days):
        # block = (start, end, start_h, end_h, module, abbrev, class_no, venue, online, mode)
        blocks = []
        for (module, lesson_type), choice in sorted(assignment.items()):
            abbrev = LESSON_ABBREV.get(lesson_type, lesson_type)
            mode = "flash" if (module, lesson_type) == flash_key else ""
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
                    mode,
                ))
        blocks.sort()

        if preview is not None and flash_key is None:
            p_abbrev = LESSON_ABBREV.get(p_lesson_type, p_lesson_type)
            for p_day, p_start, p_end, p_online in p_sig:
                if p_day != day:
                    continue
                blocks.append((
                    p_start, p_end, p_start // 60, (p_end + 59) // 60,
                    p_module, p_abbrev, "", "", p_online, "preview",
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
            for start, end, start_h, end_h, module, abbrev, class_no, venue, online, mode in lane:
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
                bg, fg = colours.get(module, ("white", "black"))
                # Both highlight modes invert the bar. Deliberately not blink:
                # Apple Terminal.app ignores SGR 5, which would leave flash mode
                # (it adds no duplicate bar and no agenda line) with no signal
                # at all there.
                highlight = " reverse" if mode else ""
                style = f"{fg} on {bg}" + (" dim" if online else "") + highlight
                row.append(label, style=style)
                cursor = span_end
            rows.append(row)

        if agenda:
            # Agenda: every block for the day, sorted by start time.
            for start, end, _sh, _eh, module, abbrev, class_no, venue, online, mode in sorted(blocks):
                if mode == "preview":
                    rows.append(Text(f"       {fmt_time(start)}-{fmt_time(end)} {module} {abbrev} (preview)"))
                    continue
                note = " (online)" if online else ""
                rows.append(Text(
                    f"       {fmt_time(start)}-{fmt_time(end)} {module} "
                    f"{abbrev}[{class_no}] @{venue}{note}",
                ))

    return Group(*rows)
