from __future__ import annotations

from .model import DAYS, LESSON_ABBREV, fmt_time
from .scoring import COMPONENT_LEGEND, _merged_intervals, pairing_impossibility, tough_day_peaks

WEEKDAYS = DAYS[:5]
GRID_HOURS = range(8, 21)
CELL = 8


def _render_days(assignment: dict, extra_days: set | None = None) -> list:
    """Days to draw in a week grid: always Mon-Fri, plus any later day in DAYS
    (i.e. Saturday) that actually has a session in this assignment (or in
    extra_days, e.g. a TUI preview)."""
    present = {s.day for choice in assignment.values() for s in choice.sessions}
    if extra_days:
        present = present | set(extra_days)
    return WEEKDAYS + [d for d in DAYS[5:] if d in present]


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
    for day in _render_days(assignment):
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


def class_warnings(assignment: dict, config, space=None, unpairable_slots=None) -> list[str]:
    """Human-readable warnings for classes/days that fail the user's criteria in
    this timetable. Each check mirrors scoring.score_assignment so warnings and
    score never disagree. free_days (a bonus) and gaps (an aggregate) produce no
    per-class warning. A component whose weight is 0 is disabled: it produces no
    warnings. When `space` is given, same_day_pairing warnings are suppressed for
    slots that can never share a lecture day (the pairing is impossible, not a
    fixable problem); callers with a cached result may instead pass
    `unpairable_slots` directly (the TUI does, from its space-scoped cache).
    Returns [] when nothing is violated."""
    prefs = config.preferences
    weights = prefs.weights
    warnings: list[str] = []

    # time_window: campus sessions starting early / ending late (online excluded)
    if weights.get("time_window", 0) != 0:
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

    # tough_days: days whose week-aware PEAK difficulty exceeds the cap. Uses the
    # same tough_day_peaks helper as scoring, so a day is warned iff it is
    # penalised; the reported number is the peak single-week load, not the naive
    # all-session sum. All sessions count, including online.
    if weights.get("tough_days", 0) != 0:
        peaks = tough_day_peaks(assignment.values(), config)
        for day in sorted(peaks, key=DAYS.index):
            warnings.append(
                f"⚠ {day} exceeds max difficulty ({peaks[day]} > {prefs.max_difficulty_per_day})"
            )

    # same_day_pairing: mirror scoring's per-MODULE bonus (capped 1/module). A
    # module with a campus lecture earns the bonus if ANY of its non-lecture
    # classes shares a lecture day, so warn only for modules that earn ZERO
    # pairing — where moving any non-lecture class to a lecture day would
    # actually raise the score. Modules with no campus lecture can't pair
    # (not a violation). Slots that can never share a lecture day given the
    # offered schedule (unpairable_slots) are impossible, not fixable — skip them.
    if weights.get("same_day_pairing", 0) != 0:
        if unpairable_slots is None:
            unpairable_slots = frozenset()
            if space is not None:
                _unpair_mods, unpairable_slots = pairing_impossibility(space.members)
        lecture_days: dict = {}
        for choice in assignment.values():
            if choice.lesson_type == "Lecture":
                lecture_days.setdefault(choice.module, set()).update(
                    s.day for s in choice.sessions if not s.online
                )
        nonlecture_by_module: dict = {}
        for (module, lesson_type), choice in assignment.items():
            if lesson_type == "Lecture":
                continue
            nonlecture_by_module.setdefault(module, []).append((lesson_type, choice))
        unpaired = []
        for module, classes in nonlecture_by_module.items():
            days = lecture_days.get(module)
            if not days:
                continue
            if any(s.day in days for _, choice in classes for s in choice.sessions):
                continue  # module already earns its pairing bonus; score is maxed
            for lesson_type, _ in classes:
                if (module, lesson_type) in unpairable_slots:
                    continue  # pairing impossible: no penalty, no warning
                abbrev = LESSON_ABBREV.get(lesson_type, lesson_type)
                unpaired.append((module, abbrev))
        for module, abbrev in sorted(unpaired):
            warnings.append(f"⚠ {module} {abbrev} not same-day as its lecture")

    # lunch: per day with no free block >= lunch_minutes in the lunch window
    # (campus sessions only; identical arithmetic to scoring's lunchless count)
    if weights.get("lunch", 0) != 0:
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


def snake_legend(provenance) -> list:
    """The two explanatory lines printed above the ballot table."""
    return [
        "best    = ceiling: the best timetable containing this class",
        f"typical = median of the {provenance.total} clash-free timetables containing it",
    ]


def snake_rows(entries: list, provenance) -> list:
    """One `(entry, line, continuation)` triple per ballot entry, in ballot
    order, with columns aligned across the whole ballot. `continuation` is the
    interchangeable-twins line, or None when the entry has no twins.

    Split out of render_snake so a caller needing per-entry rows -- the TUI's
    ballot ListView, which needs one widget per entry -- gets them directly
    rather than rendering text and parsing entry boundaries back out of it.

    Unlike render_snake, `provenance` must not be None: the best/typical
    columns are computed from it unconditionally for every entry."""
    if not entries:
        return []
    cells = []
    for position, option in enumerate(entries, 1):
        abbrev = LESSON_ABBREV.get(option.lesson_type, option.lesson_type)
        stats = provenance.cluster_stats(
            {
                (option.module, option.lesson_type, class_no)
                for class_no in [option.class_no, *option.tied_with]
            }
        )
        best = "" if stats is None else f"best #{stats.ceiling_tier} ({stats.ceiling:+.1f})"
        typical = (
            "" if stats is None else f"typical #{stats.median_tier} ({stats.median:+.1f})"
        )
        cells.append((
            option,
            f"{position:2}. {option.module} {abbrev}[{option.class_no}]",
            f"choice {option.letter}",
            _when(option.sessions),
            best,
            typical,
        ))

    widths = [max(len(cell[i]) for cell in cells) for i in range(1, 6)]
    rows = []
    for option, label, choice, when, best, typical in cells:
        line = (
            f"{label:<{widths[0]}}  {choice:<{widths[1]}}  {when:<{widths[2]}}  "
            f"{best:<{widths[3]}}  {typical}"
        ).rstrip()
        continuation = (
            f"{'':<{widths[0]}}    ↳ interchangeable with {', '.join(option.tied_with)}"
            if option.tied_with
            else None
        )
        rows.append((option, line, continuation))
    return rows


def render_snake(entries: list, provenance=None) -> str:
    """The ballot, in submission order.

    With `provenance`, each row carries the ceiling and median score of the
    arrangements containing it, as `#tier (score)`. The raw score is shown
    alongside the tier because it is directly comparable to the `score:` line on
    each displayed timetable -- that comparability is the point of the
    annotation. Both columns render unconditionally so the layout is stable
    across runs; `best` is frequently constant, which is accepted."""
    if not entries:
        return ""
    if provenance is None:
        lines = []
        for position, option in enumerate(entries, 1):
            tie = (
                f"  (interchangeable with {', '.join(option.tied_with)})"
                if option.tied_with
                else ""
            )
            lines.append(
                f"{position:2}. {option.module} "
                f"{LESSON_ABBREV.get(option.lesson_type, option.lesson_type)}"
                f"[{option.class_no}]  choice {option.letter}  "
                f"{_when(option.sessions)}{tie}"
            )
        return "\n".join(lines)

    lines = [*snake_legend(provenance), ""]
    for _option, line, continuation in snake_rows(entries, provenance):
        lines.append(line)
        if continuation is not None:
            lines.append(continuation)
    return "\n".join(lines)
