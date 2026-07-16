import json

import pytest

from kairos.api import build_groups, fetch_module, normalise_weeks, semester_timetable


def test_normalise_weeks():
    assert normalise_weeks([1, 3, 5]) == frozenset({1, 3, 5})
    assert normalise_weeks({"start": "2026-08-10", "end": "2026-11-13"}) == frozenset(range(1, 14))


def test_semester_timetable_missing_semester(alpha_json):
    with pytest.raises(SystemExit):
        semester_timetable(alpha_json, 2)


def test_build_groups_bundles_and_groups(alpha_json):
    groups = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    by_type = {g.lesson_type: g for g in groups}
    assert set(by_type) == {"Lecture", "Tutorial"}
    lec = by_type["Lecture"]
    assert len(lec.choices) == 1
    assert len(lec.choices[0].sessions) == 2  # Mon + Wed bundle
    tut = by_type["Tutorial"]
    assert sorted(c.class_no for c in tut.choices) == ["01", "02", "03"]


def test_fetch_module_uses_fresh_cache(tmp_path):
    cache_file = tmp_path / "2026-2027-ALPHA.json"
    cache_file.write_text(json.dumps({"moduleCode": "ALPHA"}))
    # fresh cache -> no network call attempted
    assert fetch_module("2026-2027", "ALPHA", tmp_path) == {"moduleCode": "ALPHA"}


def test_fetch_module_stale_cache_fallback(tmp_path, monkeypatch):
    import os
    import requests as requests_lib

    cache_file = tmp_path / "2026-2027-ALPHA.json"
    cache_file.write_text(json.dumps({"moduleCode": "ALPHA"}))
    os.utime(cache_file, (0, 0))  # make cache stale

    def boom(*args, **kwargs):
        raise requests_lib.ConnectionError("offline")

    monkeypatch.setattr(requests_lib, "get", boom)
    assert fetch_module("2026-2027", "ALPHA", tmp_path) == {"moduleCode": "ALPHA"}


def test_fetch_module_no_cache_no_network(tmp_path, monkeypatch):
    import requests as requests_lib

    def boom(*args, **kwargs):
        raise requests_lib.ConnectionError("offline")

    monkeypatch.setattr(requests_lib, "get", boom)
    with pytest.raises(SystemExit):
        fetch_module("2026-2027", "NOPE", tmp_path)
