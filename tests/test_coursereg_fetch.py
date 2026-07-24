from pathlib import Path

from kairos.coursereg.model import UNLIMITED, DemandRecord

SAMPLE = (Path(__file__).parent / "data" / "courserekt_sample.html").read_text()


def by_key(records):
    return {(r.course, r.round): r for r in records}


def test_parse_merges_class_rows_per_course_round():
    from kairos.coursereg.fetch import parse_history_html

    recs = by_key(parse_history_html(SAMPLE, "2526", 1))
    # L1 207/200 + L2 50/100 summed
    assert recs[("CS2109S", 1)] == DemandRecord("CS2109S", "2526", 1, 1, 257, 300)
    # L2 round-2 cell is N/A: skipped, not zeroed
    assert recs[("CS2109S", 2)] == DemandRecord("CS2109S", "2526", 1, 2, 17, 13)
    assert recs[("CS2109S", 3)] == DemandRecord("CS2109S", "2526", 1, 3, 8, 10)


def test_parse_unlimited_vacancy_sentinel():
    from kairos.coursereg.fetch import parse_history_html

    recs = by_key(parse_history_html(SAMPLE, "2526", 1))
    assert recs[("GEQ1000", 1)].vacancy == UNLIMITED
    assert recs[("GEQ1000", 1)].demand == 108
    assert recs[("GEQ1000", 2)].vacancy == UNLIMITED


def test_parse_all_na_yields_no_record():
    from kairos.coursereg.fetch import parse_history_html

    recs = by_key(parse_history_html(SAMPLE, "2526", 1))
    assert ("GEQ1000", 3) not in recs
    assert not any(course == "XX1000" for course, _ in recs)


def test_parse_records_carry_year_and_semester():
    from kairos.coursereg.fetch import parse_history_html

    recs = parse_history_html(SAMPLE, "2324", 2)
    assert all(r.acad_year == "2324" and r.semester == 2 for r in recs)


def test_parse_unrecognisable_structure_raises():
    import pytest

    from kairos.coursereg.fetch import parse_history_html

    with pytest.raises(SystemExit) as exc:
        parse_history_html("<html><body>maintenance</body></html>", "2526", 1)
    assert "error:" in str(exc.value)
