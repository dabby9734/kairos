from kairos.ballot import BallotOption
from kairos.model import Choice, Session
from kairos.output import class_warnings, render_breakdown, render_options, render_snake, render_week, share_url

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


def test_render_week_shows_saturday_when_present():
    mon = Choice("ALPHA", "Lecture", "1", (Session("Monday", 540, 600, ALL_WEEKS, "COM1"),))
    sat = Choice("GAMMA", "Lecture", "1", (Session("Saturday", 600, 720, ALL_WEEKS, "COM1"),))
    text = render_week({("ALPHA", "Lecture"): mon, ("GAMMA", "Lecture"): sat})
    lines = text.split("\n")
    assert any(line.startswith("Sat") for line in lines)
    assert "1000-1200 GAMMA LEC[1] @COM1" in text


def test_render_week_omits_saturday_when_absent():
    text = render_week(make_assignment())
    lines = text.split("\n")
    assert not any(line.startswith("Sat") for line in lines)


def test_render_breakdown():
    text = render_breakdown(3.5, {"gaps": (-2.0, -2.0), "free_days": (2, 8.0)})
    assert "score: +3.50" in text
    assert "gaps" in text and "free_days" in text


def test_render_breakdown_includes_legend_descriptions():
    from kairos.scoring import COMPONENT_LEGEND

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


def _choice(module, ltype, class_no, *sessions):
    return Choice(module, ltype, class_no, tuple(sessions))


def _sess(day, start, end, venue="COM1"):
    return Session(day, start, end, ALL_WEEKS, venue)


def test_class_warnings_time_window_before_earliest(config):
    # ALPHA TUT 09:00-11:00, earliest 10:00 -> starts too early.
    a = {("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", _sess("Monday", 540, 660))}
    warnings = class_warnings(a, config)
    assert warnings == ["⚠ ALPHA TUT Mon 0900 starts before your earliest 1000"]


def test_class_warnings_time_window_after_latest(config):
    # ALPHA TUT 17:00-19:00, latest 18:00 -> ends too late.
    a = {("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", _sess("Monday", 1020, 1140))}
    assert class_warnings(a, config) == ["⚠ ALPHA TUT Mon 1900 ends after your latest 1800"]


def test_class_warnings_time_window_ignores_online(config):
    # Online 08:00-10:00 lecture is excluded from the time window, like scoring.
    a = {("ALPHA", "Lecture"): _choice("ALPHA", "Lecture", "1", _sess("Monday", 480, 600, "E-Learn_C"))}
    assert class_warnings(a, config) == []


def test_class_warnings_tough_day_counts_online(config):
    # ALPHA LEC(online) 2 + ALPHA TUT 4 + BETA LAB 3 = 9 > 8, all Monday.
    a = {
        ("ALPHA", "Lecture"): _choice("ALPHA", "Lecture", "1", _sess("Monday", 600, 720, "E-Learn_C")),
        ("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", _sess("Monday", 780, 840)),
        ("BETA", "Laboratory"): _choice("BETA", "Laboratory", "L1", _sess("Monday", 960, 1080)),
    }
    assert "⚠ Monday exceeds max difficulty (9 > 8)" in class_warnings(a, config)


def test_class_warnings_same_day_pairing_unpaired(config):
    # ALPHA lecture Monday (campus), tutorial Tuesday -> not paired.
    a = {
        ("ALPHA", "Lecture"): _choice("ALPHA", "Lecture", "1", _sess("Monday", 600, 720)),
        ("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", _sess("Tuesday", 600, 660)),
    }
    assert "⚠ ALPHA TUT not same-day as its lecture" in class_warnings(a, config)


def test_class_warnings_no_pairing_when_no_campus_lecture(config):
    # Lecture is online-only -> pairing is impossible, so it is NOT a violation.
    a = {
        ("ALPHA", "Lecture"): _choice("ALPHA", "Lecture", "1", _sess("Monday", 600, 720, "E-Learn_C")),
        ("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", _sess("Tuesday", 600, 660)),
    }
    assert not any("same-day" in w for w in class_warnings(a, config))


def test_class_warnings_no_lunch(config):
    # One class spans the whole 11:00-14:00 window -> no lunch block.
    a = {("ALPHA", "Lecture"): _choice("ALPHA", "Lecture", "1", _sess("Monday", 600, 900))}
    assert "⚠ Monday has no lunch break" in class_warnings(a, config)


def test_class_warnings_clean_timetable_is_empty(config):
    # Lecture 10:00-12:00 + tutorial 13:00-14:00, same day: in window, paired,
    # under the difficulty cap, and leaves a 60-min lunch block.
    a = {
        ("ALPHA", "Lecture"): _choice("ALPHA", "Lecture", "1", _sess("Monday", 600, 720)),
        ("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", _sess("Monday", 780, 840)),
    }
    assert class_warnings(a, config) == []


def test_class_warnings_pairing_suppressed_when_module_already_paired(config):
    # ALPHA lecture Mon; tutorial Mon (paired) earns the module's bonus, so the
    # unpaired Tue lab must NOT be flagged — moving it would not change the score.
    a = {
        ("ALPHA", "Lecture"): _choice("ALPHA", "Lecture", "1", _sess("Monday", 600, 720)),
        ("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", _sess("Monday", 780, 840)),
        ("ALPHA", "Laboratory"): _choice("ALPHA", "Laboratory", "L1", _sess("Tuesday", 600, 660)),
    }
    assert not any("same-day" in w for w in class_warnings(a, config))


def test_class_warnings_pairing_flags_all_when_module_fully_unpaired(config):
    # ALPHA lecture Mon; tutorial AND lab both on Tue -> module earns no pairing
    # bonus, so both are flagged (moving either to Mon would raise the score).
    a = {
        ("ALPHA", "Lecture"): _choice("ALPHA", "Lecture", "1", _sess("Monday", 600, 720)),
        ("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", _sess("Tuesday", 600, 660)),
        ("ALPHA", "Laboratory"): _choice("ALPHA", "Laboratory", "L1", _sess("Tuesday", 720, 780)),
    }
    warnings = class_warnings(a, config)
    assert "⚠ ALPHA TUT not same-day as its lecture" in warnings
    assert "⚠ ALPHA LAB not same-day as its lecture" in warnings


def test_class_warnings_tough_day_week_aware_ignores_disjoint_weeks(config):
    # Naive Monday difficulty 10 > cap 8, but the recitation's weeks are disjoint
    # from the other two (peak week load 7) -> no tough-day warning (parity).
    w13 = frozenset({1, 3})
    w24 = frozenset({2, 4})
    a = {
        ("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", Session("Monday", 600, 660, w13, "COM1")),
        ("BETA", "Laboratory"): _choice("BETA", "Laboratory", "L1", Session("Monday", 720, 780, w13, "COM1")),
        ("BETA", "Recitation"): _choice("BETA", "Recitation", "R1", Session("Monday", 840, 900, w24, "COM1")),
    }
    assert not any("exceeds max difficulty" in w for w in class_warnings(a, config))


def test_class_warnings_tough_day_reports_peak_week(config):
    # Overlapping weeks: week 1 load 4+3+3 = 10 -> the warning names the peak (10),
    # not the naive all-session sum (also 10 here, but the message must be the peak).
    w13 = frozenset({1, 3})
    a = {
        ("ALPHA", "Tutorial"): _choice("ALPHA", "Tutorial", "01", Session("Monday", 600, 660, w13, "COM1")),
        ("BETA", "Laboratory"): _choice("BETA", "Laboratory", "L1", Session("Monday", 720, 780, w13, "COM1")),
        ("BETA", "Recitation"): _choice("BETA", "Recitation", "R1", Session("Monday", 840, 900, w13, "COM1")),
    }
    assert "⚠ Monday exceeds max difficulty (10 > 8)" in class_warnings(a, config)


def test_class_warnings_suppressed_when_weight_zero(config):
    import copy

    all_weeks = frozenset(range(1, 14))
    # 11:00-14:00 solid ALPHA lecture -> normally a lunch warning
    a = {("ALPHA", "Lecture"): Choice("ALPHA", "Lecture", "1",
         (Session("Monday", 660, 840, all_weeks, "COM1"),))}
    assert any("lunch" in w for w in class_warnings(a, config))
    off = copy.deepcopy(config)
    off.preferences.weights["lunch"] = 0
    assert not any("lunch" in w for w in class_warnings(a, off))


def test_class_warnings_pairing_suppressed_when_weight_zero(config):
    import copy

    all_weeks = frozenset(range(1, 14))
    a = {
        ("ALPHA", "Lecture"): Choice("ALPHA", "Lecture", "1",
            (Session("Monday", 600, 720, all_weeks, "COM1"),)),
        ("ALPHA", "Tutorial"): Choice("ALPHA", "Tutorial", "01",
            (Session("Tuesday", 540, 600, all_weeks, "COM1"),)),
    }
    assert any("same-day" in w for w in class_warnings(a, config))
    off = copy.deepcopy(config)
    off.preferences.weights["same_day_pairing"] = 0
    assert not any("same-day" in w for w in class_warnings(a, off))


def test_class_warnings_pairing_suppressed_when_impossible(config):
    from kairos.search import EnumeratedSpace

    all_weeks = frozenset(range(1, 14))
    lec = Choice("ALPHA", "Lecture", "1", (Session("Monday", 600, 720, all_weeks, "COM1"),))
    tut = Choice("ALPHA", "Tutorial", "01", (Session("Tuesday", 540, 600, all_weeks, "COM1"),))
    a = {("ALPHA", "Lecture"): lec, ("ALPHA", "Tutorial"): tut}
    # Offered slots: lecture only Monday, tutorial only Tuesday -> pairing impossible.
    members = {
        ("ALPHA", "Lecture"): {lec.footprint: [lec]},
        ("ALPHA", "Tutorial"): {tut.footprint: [tut]},
    }
    space = EnumeratedSpace(combos=(), members=members)
    # Without space: warns as before.
    assert any("same-day" in w for w in class_warnings(a, config))
    # With space: the impossible pairing is suppressed.
    assert not any("same-day" in w for w in class_warnings(a, config, space=space))


def test_class_warnings_unpairable_slots_kwarg_matches_space(config):
    from kairos.scoring import pairing_impossibility
    from kairos.search import EnumeratedSpace

    all_weeks = frozenset(range(1, 14))
    lec = Choice("ALPHA", "Lecture", "1", (Session("Monday", 600, 720, all_weeks, "COM1"),))
    tut = Choice("ALPHA", "Tutorial", "01", (Session("Tuesday", 540, 600, all_weeks, "COM1"),))
    a = {("ALPHA", "Lecture"): lec, ("ALPHA", "Tutorial"): tut}
    members = {
        ("ALPHA", "Lecture"): {lec.footprint: [lec]},
        ("ALPHA", "Tutorial"): {tut.footprint: [tut]},
    }
    space = EnumeratedSpace(combos=(), members=members)
    # The precomputed-kwarg path is behavior-identical to computing from space.
    unpairable = pairing_impossibility(space.members)[1]
    assert class_warnings(a, config, unpairable_slots=unpairable) == class_warnings(a, config, space=space)


def test_render_snake_without_provenance_is_unchanged():
    from kairos.ballot import BallotOption
    from kairos.model import Session

    weeks = frozenset(range(1, 14))
    entry = BallotOption(
        "ALPHA", "Tutorial", "01", "A", 3.0,
        (Session("Monday", 600, 660, weeks, "COM1"),), [],
    )
    assert render_snake([entry]) == render_snake([entry], provenance=None)


def test_render_snake_shows_best_and_typical():
    from kairos.ballot import BallotOption
    from kairos.model import Session
    from kairos.provenance import ClusterStats

    class Prov:
        total = 363

        def cluster_stats(self, keys):
            return ClusterStats(-14.0, -19.0, 29, 1, 3)

    weeks = frozenset(range(1, 14))
    entry = BallotOption(
        "ALPHA", "Tutorial", "01", "A", 3.0,
        (Session("Monday", 600, 660, weeks, "COM1"),), [],
    )
    text = render_snake([entry], provenance=Prov())
    assert "best #1 (-14.0)" in text
    assert "typical #3 (-19.0)" in text
    assert "363" in text


def test_render_snake_moves_interchangeable_to_continuation_line():
    from kairos.ballot import BallotOption
    from kairos.model import Session
    from kairos.provenance import ClusterStats

    class Prov:
        total = 363

        def cluster_stats(self, keys):
            return ClusterStats(-14.0, -14.0, 29, 1, 1)

    weeks = frozenset(range(1, 14))
    entry = BallotOption(
        "ALPHA", "Tutorial", "01", "A", 3.0,
        (Session("Monday", 600, 660, weeks, "COM1"),), ["02", "03"],
    )
    lines = render_snake([entry], provenance=Prov()).splitlines()
    body = [line for line in lines if "ALPHA" in line or "interchangeable" in line]
    assert "interchangeable" not in body[0]
    assert "interchangeable with 02, 03" in body[1]


def test_render_snake_handles_missing_stats():
    from kairos.ballot import BallotOption
    from kairos.model import Session

    class Prov:
        total = 363

        def cluster_stats(self, keys):
            return None

    weeks = frozenset(range(1, 14))
    entry = BallotOption(
        "ALPHA", "Tutorial", "01", "A", 3.0,
        (Session("Monday", 600, 660, weeks, "COM1"),), [],
    )
    text = render_snake([entry], provenance=Prov())
    assert "ALPHA" in text


def test_render_snake_columns_align_across_mixed_widths():
    from kairos.ballot import BallotOption
    from kairos.model import Session
    from kairos.provenance import ClusterStats

    class Prov:
        total = 363

        def cluster_stats(self, keys):
            return ClusterStats(-14.0, -19.0, 29, 1, 3)

    weeks = frozenset(range(1, 14))
    short = BallotOption(
        "A1", "Tutorial", "1", "A", 3.0,
        (Session("Monday", 600, 660, weeks, "COM1"),), [],
    )
    wide = BallotOption(
        "LONGMODULE", "Laboratory", "L12", "B", 3.0,
        (
            Session("Tuesday", 840, 960, weeks, "COM1"),
            Session("Friday", 840, 960, weeks, "COM1"),
        ),
        [],
    )
    lines = [
        line
        for line in render_snake([short, wide], provenance=Prov()).splitlines()
        if "best #" in line
    ]
    assert len(lines) == 2
    assert lines[0].index("best #") == lines[1].index("best #")
    assert lines[0].index("typical #") == lines[1].index("typical #")


def test_render_snake_empty_entries():
    class Prov:
        total = 0

        def cluster_stats(self, keys):
            return None

    assert render_snake([], provenance=Prov()) == ""
    assert render_snake([]) == ""


def test_class_warnings_pairing_mixed_suppresses_only_impossible(config):
    from kairos.search import EnumeratedSpace

    all_weeks = frozenset(range(1, 14))
    lec = Choice("ALPHA", "Lecture", "1", (Session("Monday", 600, 720, all_weeks, "COM1"),))
    # Tutorial offered Monday (pairable) but placed Tuesday here; lab offered only Tuesday.
    tut = Choice("ALPHA", "Tutorial", "01", (Session("Tuesday", 540, 600, all_weeks, "COM1"),))
    tut_mon = Choice("ALPHA", "Tutorial", "02", (Session("Monday", 780, 840, all_weeks, "COM1"),))
    lab = Choice("ALPHA", "Laboratory", "L1", (Session("Tuesday", 780, 840, all_weeks, "COM1"),))
    a = {
        ("ALPHA", "Lecture"): lec,
        ("ALPHA", "Tutorial"): tut,
        ("ALPHA", "Laboratory"): lab,
    }
    members = {
        ("ALPHA", "Lecture"): {lec.footprint: [lec]},
        ("ALPHA", "Tutorial"): {tut.footprint: [tut], tut_mon.footprint: [tut_mon]},
        ("ALPHA", "Laboratory"): {lab.footprint: [lab]},
    }
    space = EnumeratedSpace(combos=(), members=members)
    warnings = class_warnings(a, config, space=space)
    # Tutorial CAN pair (offered Monday) -> still warned; Lab can't -> suppressed.
    assert any("ALPHA TUT" in w and "same-day" in w for w in warnings)
    assert not any("ALPHA LAB" in w and "same-day" in w for w in warnings)


def test_render_snake_rich_reverses_highlighted_rows():
    # Reverse video, NOT blink: Terminal.app ignores SGR 5.
    from kairos.ballot import BallotOption
    from kairos.model import Session
    from kairos.output import render_snake_rich
    from kairos.provenance import ClusterStats

    class Prov:
        total = 10

        def cluster_stats(self, keys):
            return ClusterStats(-14.0, -14.0, 5, 1, 1)

    weeks = frozenset(range(1, 14))
    hit = BallotOption(
        "ALPHA", "Tutorial", "01", "A", 3.0,
        (Session("Monday", 600, 660, weeks, "COM1"),), [],
    )
    miss = BallotOption(
        "BETA", "Laboratory", "L1", "A", 3.0,
        (Session("Tuesday", 600, 660, weeks, "COM1"),), [],
    )
    text = render_snake_rich(
        [hit, miss], Prov(), highlight=frozenset({("ALPHA", "Tutorial", "01")})
    )
    styles = {str(span.style) for span in text.spans}
    assert "reverse" in styles
    assert "blink" not in styles


def test_render_snake_rich_without_highlight_has_no_reverse_spans():
    from kairos.ballot import BallotOption
    from kairos.model import Session
    from kairos.output import render_snake_rich
    from kairos.provenance import ClusterStats

    class Prov:
        total = 10

        def cluster_stats(self, keys):
            return ClusterStats(-14.0, -14.0, 5, 1, 1)

    weeks = frozenset(range(1, 14))
    entry = BallotOption(
        "ALPHA", "Tutorial", "01", "A", 3.0,
        (Session("Monday", 600, 660, weeks, "COM1"),), [],
    )
    text = render_snake_rich([entry], Prov(), highlight=frozenset())
    assert all("reverse" not in str(span.style) for span in text.spans)


def test_render_snake_rich_matches_plain_text():
    from kairos.ballot import BallotOption
    from kairos.model import Session
    from kairos.output import render_snake, render_snake_rich
    from kairos.provenance import ClusterStats

    class Prov:
        total = 10

        def cluster_stats(self, keys):
            return ClusterStats(-14.0, -14.0, 5, 1, 1)

    weeks = frozenset(range(1, 14))
    entry = BallotOption(
        "ALPHA", "Tutorial", "01", "A", 3.0,
        (Session("Monday", 600, 660, weeks, "COM1"),), [],
    )
    prov = Prov()
    assert render_snake_rich([entry], prov).plain == render_snake([entry], provenance=prov)
