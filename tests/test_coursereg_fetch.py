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


def test_parse_tolerates_orphan_td_outside_rows():
    from kairos.coursereg.fetch import parse_history_html

    html = SAMPLE.replace("<tbody>", "<tbody><td>ORPHAN</td>", 1)
    recs = by_key(parse_history_html(html, "2526", 1))
    assert ("CS2109S", 1) in recs  # real rows still parse; orphan ignored


def _fake_fetch_factory(calls):
    def fake_fetch(acad_year, semester):
        calls.append((acad_year, semester))
        return SAMPLE  # every semester serves the fixture page
    return fake_fetch


def test_load_history_fetches_all_semesters_and_caches(tmp_path, monkeypatch):
    from kairos.coursereg import fetch

    calls = []
    monkeypatch.setattr(fetch, "fetch_semester", _fake_fetch_factory(calls))
    records = fetch.load_history(tmp_path)
    assert len(calls) == 10  # 5 years x 2 semesters
    assert len(list(tmp_path.glob("*.json"))) == 10
    # 3 fixture courses with data x 10 semesters... CS2109S has 3 rounds,
    # GEQ1000 has 2, XX1000 none -> 5 records per semester
    assert len(records) == 50

    # Second call: pure cache, no fetches — the source is frozen, no TTL.
    calls.clear()
    again = fetch.load_history(tmp_path)
    assert calls == [] and again == records


def test_load_history_refetch_forces_network(tmp_path, monkeypatch):
    from kairos.coursereg import fetch

    calls = []
    monkeypatch.setattr(fetch, "fetch_semester", _fake_fetch_factory(calls))
    fetch.load_history(tmp_path)
    calls.clear()
    fetch.load_history(tmp_path, refetch=True)
    assert len(calls) == 10


def test_load_history_unreachable_without_cache_exits(tmp_path, monkeypatch):
    import pytest
    import requests

    from kairos.coursereg import fetch

    def down(acad_year, semester):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(fetch, "fetch_semester", down)
    with pytest.raises(SystemExit) as exc:
        fetch.load_history(tmp_path)
    message = str(exc.value)
    assert "error:" in message and str(tmp_path) in message


def test_load_history_corrupt_cache_exits_with_refetch_hint(tmp_path, monkeypatch):
    import pytest

    from kairos.coursereg import fetch

    monkeypatch.setattr(fetch, "fetch_semester", _fake_fetch_factory([]))
    fetch.load_history(tmp_path)
    (tmp_path / "2122-1.json").write_text("[{\"cours")  # truncated write
    with pytest.raises(SystemExit) as exc:
        fetch.load_history(tmp_path)
    assert "error:" in str(exc.value) and "--refetch" in str(exc.value)
