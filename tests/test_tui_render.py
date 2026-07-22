from rich.console import Console

from kairos.model import Choice, Session
from kairos.tui.render import module_colours, render_week_rich

ALL_WEEKS = frozenset(range(1, 14))


def _choice(module, ltype, class_no, day, start, end, venue="COM1"):
    return Choice(module, ltype, class_no, (Session(day, start, end, ALL_WEEKS, venue),))


def _plain(renderable, width=200):
    console = Console(width=width)
    with console.capture() as cap:
        console.print(renderable)
    return cap.get()


def test_module_colours_distinct_and_stable():
    colours = module_colours(["CS1231S", "CS2030S", "MA1521"])
    assert len(set(colours.values())) == 3  # distinct pairs
    assert module_colours(["CS1231S", "CS2030S", "MA1521"]) == colours  # stable


def test_wide_block_shows_class_type():
    # 2-hour lab (1400-1600) leaves room for "[LAB]"
    assignment = {("CS2030S", "Laboratory"): _choice("CS2030S", "Laboratory", "14B", "Monday", 840, 960)}
    text = _plain(render_week_rich(assignment, module_colours(["CS2030S"])))
    assert "CS2030S [LAB]" in text


def test_narrow_block_shows_module_only():
    # 1-hour tutorial: "CS2030S [TUT]" (13 chars) won't fit an 8-wide strip
    assignment = {("CS2030S", "Tutorial"): _choice("CS2030S", "Tutorial", "01", "Monday", 840, 900)}
    text = _plain(render_week_rich(assignment, module_colours(["CS2030S"])))
    assert "CS2030S" in text
    assert "CS2030S [TUT]" not in text


def test_online_marked_and_agenda_present():
    assignment = {
        ("CS1231S", "Lecture"): _choice("CS1231S", "Lecture", "2", "Thursday", 720, 840, "E-Learn_C")
    }
    text = _plain(render_week_rich(assignment, module_colours(["CS1231S"])))
    assert "~CS1231S" in text  # online marker in the strip
    assert "(online)" in text  # agenda note
    assert "@E-Learn_C" in text  # agenda venue


def _day_row(text, day3):
    return next(line for line in text.splitlines() if line.startswith(day3))


def test_saturday_class_gets_grid_row_and_agenda():
    assignment = {("AAA", "Lecture"): _choice("AAA", "Lecture", "1", "Saturday", 600, 720)}
    text = _plain(render_week_rich(assignment, module_colours(["AAA"])))
    assert "AAA" in _day_row(text, "Sat")
    assert "1000-1200 AAA LEC[1]" in text


def test_saturday_preview_creates_saturday_row():
    assignment = {("BBB", "Tutorial"): _choice("BBB", "Tutorial", "01", "Monday", 840, 900)}
    sig = frozenset({("Saturday", 600, 720, False)})
    colours = module_colours(["AAA", "BBB"])
    text = _plain(render_week_rich(assignment, colours, preview=("AAA", "Lecture", sig)))
    assert any(line.startswith("Sat") for line in text.splitlines())
    assert "1000-1200 AAA LEC (preview)" in text


def test_back_to_back_halfhour_classes_do_not_drift():
    # Two clash-free, non-hour-aligned back-to-back classes plus a third.
    # Rounded hour spans overlap; the row must still not overflow the grid
    # (a drift bug glues blocks and pushes the row past the header width).
    assignment = {
        ("AAA", "Lecture"): _choice("AAA", "Lecture", "1", "Monday", 720, 810),      # 12:00-13:30
        ("BBB", "Tutorial"): _choice("BBB", "Tutorial", "1", "Monday", 810, 900),    # 13:30-15:00
        ("CCC", "Laboratory"): _choice("CCC", "Laboratory", "1", "Monday", 900, 960),  # 15:00-16:00
    }
    text = _plain(render_week_rich(assignment, module_colours(["AAA", "BBB", "CCC"])))
    header = next(line for line in text.splitlines() if line.strip().startswith("0800"))
    row = _day_row(text, "Mon")
    assert len(row.rstrip()) <= len(header.rstrip())  # no sideways drift / overflow
    for mod in ("AAA", "BBB", "CCC"):
        assert mod in row  # every class still shown


def test_gap_between_separated_classes_is_preserved():
    assignment = {
        ("AAA", "Lecture"): _choice("AAA", "Lecture", "1", "Monday", 600, 660),   # 10:00-11:00
        ("BBB", "Tutorial"): _choice("BBB", "Tutorial", "1", "Monday", 840, 900),  # 14:00-15:00
    }
    text = _plain(render_week_rich(assignment, module_colours(["AAA", "BBB"])))
    row = _day_row(text, "Mon")
    # a real 3-hour gap → blank run between the two labels
    between = row[row.index("AAA") + 3 : row.index("BBB")]
    assert between.strip() == ""
    assert len(between) >= 8  # at least one empty hour cell of separation


def test_subhour_classes_both_listed_in_agenda():
    # Two clash-free classes packed into one clock hour: one strip may be
    # undrawable, but neither may vanish from the (authoritative) agenda.
    assignment = {
        ("AAA", "Lecture"): _choice("AAA", "Lecture", "1", "Monday", 720, 750),   # 12:00-12:30
        ("BBB", "Tutorial"): _choice("BBB", "Tutorial", "1", "Monday", 750, 780),  # 12:30-13:00
    }
    text = _plain(render_week_rich(assignment, module_colours(["AAA", "BBB"])))
    assert "1200-1230 AAA LEC[1]" in text
    assert "1230-1300 BBB TUT[1]" in text  # must not be swallowed


def test_out_of_grid_class_listed_in_agenda():
    # 07:00-08:00 is before the 08:00 grid start: no strip, but still agenda'd.
    assignment = {("AAA", "Lecture"): _choice("AAA", "Lecture", "1", "Monday", 420, 480)}
    text = _plain(render_week_rich(assignment, module_colours(["AAA"])))
    assert "0700-0800 AAA LEC[1]" in text


def test_render_applies_module_background_style():
    assignment = {("CS2030S", "Laboratory"): _choice("CS2030S", "Laboratory", "14B", "Monday", 840, 960)}
    console = Console(width=200, force_terminal=True, color_system="standard")
    with console.capture() as cap:
        console.print(render_week_rich(assignment, {"CS2030S": ("green", "black")}))
    # ANSI output should contain a background colour escape (not plain text)
    assert "\x1b[" in cap.get()


def test_overlapping_classes_get_separate_lanes():
    # A 14:00-17:00 lab (odd weeks) and a 15:00-17:00 tutorial (even weeks) share
    # the 15:00-17:00 cells but never clash -> each gets its own lane/bar.
    w_odd = frozenset({1, 3, 5})
    w_even = frozenset({2, 4, 6})
    assignment = {
        ("CS2040", "Laboratory"): Choice(
            "CS2040", "Laboratory", "L1", (Session("Monday", 840, 1020, w_odd, "COM1"),)
        ),
        ("MA1521", "Tutorial"): Choice(
            "MA1521", "Tutorial", "T1", (Session("Monday", 900, 1020, w_even, "COM2"),)
        ),
    }
    text = _plain(render_week_rich(assignment, module_colours(["CS2040", "MA1521"])))
    lines = text.splitlines()
    mon = next(i for i, l in enumerate(lines) if l.startswith("Mon"))
    assert "CS2040 [LAB]" in lines[mon]           # first lane keeps the day gutter
    assert "MA1521 [TUT]" in lines[mon + 1]       # second class gets its own lane
    assert lines[mon + 1].startswith("     ")     # extra lane has a blank 5-char gutter
    assert not lines[mon + 1][:5].strip()         # gutter is blank, not a day name
    # both classes still listed in the agenda
    assert "1400-1700 CS2040 LAB[L1]" in text
    assert "1500-1700 MA1521 TUT[T1]" in text


def test_non_overlapping_day_uses_single_lane():
    # Two sequential classes (10:00-12:00, 13:00-14:00) do NOT overlap -> one lane
    # row holding both, immediately followed by the agenda (no second lane).
    assignment = {
        ("AAA", "Lecture"): _choice("AAA", "Lecture", "1", "Monday", 600, 720),
        ("BBB", "Tutorial"): _choice("BBB", "Tutorial", "1", "Monday", 780, 840),
    }
    text = _plain(render_week_rich(assignment, module_colours(["AAA", "BBB"])))
    lines = text.splitlines()
    mon = next(i for i, l in enumerate(lines) if l.startswith("Mon"))
    assert "AAA" in lines[mon] and "BBB" in lines[mon]   # both share the single lane
    assert lines[mon + 1].startswith("       ")          # next line is agenda (7 spaces), not a 2nd lane


def test_preview_bar_is_inverted_and_shows_both():
    # Class currently on Monday; preview a candidate Tuesday slot for the SAME class.
    assignment = {("CS2030S", "Tutorial"): _choice("CS2030S", "Tutorial", "01", "Monday", 840, 900)}
    sig = frozenset({("Tuesday", 540, 600, False)})
    colours = module_colours(["CS2030S"])
    # plain text: current Monday strip stays; a Tuesday (preview) agenda line appears
    text = _plain(render_week_rich(assignment, colours, preview=("CS2030S", "Tutorial", sig)))
    mon = _day_row(text, "Mon")
    assert "CS2030S" in mon                       # current strip still shown (show-both)
    assert "0900-1000 CS2030S TUT (preview)" in text  # candidate agenda'd on Tuesday
    # ANSI: the preview bar carries reverse (SGR 7), combined with the module's
    # own colour SGR (additive style: fg on bg + reverse), so a future
    # colour-stripping regression is caught alongside the reverse check.
    console = Console(width=200, force_terminal=True, color_system="standard")
    with console.capture() as cap:
        console.print(render_week_rich(assignment, colours, preview=("CS2030S", "Tutorial", sig)))
    ansi = cap.get()
    assert "\x1b[7;" in ansi or ";7;" in ansi  # reverse SGR, combined with the colour pair
    assert "30;42m" in ansi  # CS2030S keeps its colour (black on green) under the reverse
    assert "\x1b[5m" not in ansi and ";5m" not in ansi and "\x1b[5;" not in ansi  # no blink


def test_preview_none_unchanged():
    assignment = {("CS2030S", "Tutorial"): _choice("CS2030S", "Tutorial", "01", "Monday", 840, 900)}
    colours = module_colours(["CS2030S"])
    assert _plain(render_week_rich(assignment, colours)) == _plain(
        render_week_rich(assignment, colours, preview=None)
    )


def test_previewing_current_slot_draws_no_duplicate_bar():
    # Highlighting the slot the class already occupies must add nothing at all:
    # no second lane, no "(preview)" agenda line. Flash mode changes only style,
    # so the plain text must be byte-identical to rendering with no preview.
    assignment = {("CS2030S", "Tutorial"): _choice("CS2030S", "Tutorial", "01", "Monday", 840, 900)}
    sig = frozenset({("Monday", 840, 900, False)})
    colours = module_colours(["CS2030S"])
    flashed = _plain(render_week_rich(assignment, colours, preview=("CS2030S", "Tutorial", sig)))
    assert flashed == _plain(render_week_rich(assignment, colours))
    assert "(preview)" not in flashed


def test_flashed_slot_inverts_strip_only():
    # The strip carries reverse (SGR 7) over CS2030S's own colour pair
    # (black on green -> 30;42). Blink is deliberately absent everywhere:
    # Apple Terminal.app ignores SGR 5, and flash mode draws no duplicate bar
    # and no extra agenda line, so blink alone would leave it with no signal.
    # The agenda line is unstyled — the inverted bar is the whole cue.
    assignment = {("CS2030S", "Tutorial"): _choice("CS2030S", "Tutorial", "01", "Monday", 840, 900)}
    sig = frozenset({("Monday", 840, 900, False)})
    colours = module_colours(["CS2030S"])
    console = Console(width=200, force_terminal=True, color_system="standard")
    with console.capture() as cap:
        console.print(render_week_rich(assignment, colours, preview=("CS2030S", "Tutorial", sig)))
    ansi = cap.get()
    lines = ansi.splitlines()
    strip = next(line for line in lines if line.startswith("Mon"))
    agenda = next(line for line in lines if "TUT[01]" in line)
    assert "\x1b[7;" in strip or ";7;" in strip  # inverted, combined with the colour pair
    assert "30;42" in strip
    assert "\x1b[" not in agenda  # agenda line carries no styling at all
    assert "\x1b[5m" not in ansi and ";5m" not in ansi and "\x1b[5;" not in ansi  # no blink
