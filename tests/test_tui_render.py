from rich.console import Console

from optimiser.model import Choice, Session
from optimiser.tui.render import module_colours, render_week_rich

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


def test_render_applies_module_background_style():
    assignment = {("CS2030S", "Laboratory"): _choice("CS2030S", "Laboratory", "14B", "Monday", 840, 960)}
    console = Console(width=200, force_terminal=True, color_system="standard")
    with console.capture() as cap:
        console.print(render_week_rich(assignment, {"CS2030S": ("green", "black")}))
    # ANSI output should contain a background colour escape (not plain text)
    assert "\x1b[" in cap.get()
