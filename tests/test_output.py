from optimiser.ballot import BallotOption
from optimiser.model import Choice, Session
from optimiser.output import render_breakdown, render_options, render_snake, render_week, share_url

ALL_WEEKS = frozenset(range(1, 14))


def make_assignment():
    lec = Choice("ALPHA", "Lecture", "2", (Session("Monday", 600, 720, ALL_WEEKS, "E-Learn_C"),))
    tut = Choice("ALPHA", "Tutorial", "07A", (Session("Monday", 840, 900, ALL_WEEKS, "COM1-0201"),))
    lab = Choice("BETA", "Laboratory", "14B", (Session("Friday", 600, 720, ALL_WEEKS, "COM4"),))
    return {
        ("ALPHA", "Lecture"): lec,
        ("ALPHA", "Tutorial"): tut,
        ("BETA", "Laboratory"): lab,
    }


def test_share_url():
    url = share_url(make_assignment(), 1)
    assert url == "https://nusmods.com/timetable/sem-1/share?ALPHA=LEC:2,TUT:07A&BETA=LAB:14B"


def test_render_week_contains_sessions_and_online_mark():
    text = render_week(make_assignment())
    assert "1400-1500 ALPHA TUT[07A] @COM1-0201" in text
    assert "1000-1200 ALPHA LEC[2] @E-Learn_C (online)" in text
    assert "~ALPHA" in text  # online marker in the grid row
    assert "Mon" in text and "Fri" in text


def test_render_breakdown():
    text = render_breakdown(3.5, {"gaps": (-2.0, -2.0), "free_days": (2, 8.0)})
    assert "score: +3.50" in text
    assert "gaps" in text and "free_days" in text


def test_render_breakdown_includes_legend_descriptions():
    from optimiser.scoring import COMPONENT_LEGEND

    text = render_breakdown(3.5, {"gaps": (-2.0, -2.0), "free_days": (2, 8.0)})
    assert COMPONENT_LEGEND["gaps"] in text
    assert COMPONENT_LEGEND["free_days"] in text


def test_render_breakdown_unknown_component_has_no_description():
    # A component with no legend entry must still render (no trailing dash).
    text = render_breakdown(1.0, {"mystery": (1.0, 1.0)})
    assert "mystery" in text
    assert "—" not in text


def test_render_handles_unmapped_lesson_type():
    unmapped = "Tutorial Type 3"
    choice = Choice(
        "ALPHA", unmapped, "09", (Session("Monday", 840, 900, ALL_WEEKS, "COM1-0201"),)
    )
    assignment = {("ALPHA", unmapped): choice}

    assert unmapped in share_url(assignment, 1)
    assert unmapped in render_week(assignment)

    entry = BallotOption(
        "ALPHA", unmapped, "09", "A", 10.0,
        (Session("Monday", 840, 900, ALL_WEEKS, "COM1-0201"),), [],
    )
    assert unmapped in render_snake([entry])


def test_render_options_and_snake():
    entry = BallotOption(
        "ALPHA", "Tutorial", "01", "A", 10.0,
        (Session("Monday", 840, 900, ALL_WEEKS, "COM1"),), ["02"],
    )
    options_text = render_options({("ALPHA", "Tutorial"): [entry]})
    assert "ALPHA TUT" in options_text and "01" in options_text
    snake_text = render_snake([entry])
    assert snake_text.startswith(" 1. ALPHA TUT[01]")
    assert "choice A" in snake_text
    assert "Mon 1400-1500" in snake_text
    assert "interchangeable with 02" in snake_text
