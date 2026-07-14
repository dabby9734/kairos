import pytest

from optimiser.tui.startup import build_state

SHARE_URL = "https://nusmods.com/timetable/sem-1/share?ALPHA=TUT:01,LEC:1&BETA=LAB:L2,LEC:1"


def _patch_fetch(monkeypatch, alpha_json, beta_json):
    fixtures = {"ALPHA": alpha_json, "BETA": beta_json}
    monkeypatch.setattr(
        "optimiser.tui.startup.api.fetch_module", lambda ay, code, cache: fixtures[code]
    )


def test_build_state_from_url(tmp_path, monkeypatch, alpha_json, beta_json):
    _patch_fetch(monkeypatch, alpha_json, beta_json)
    state = build_state(SHARE_URL, tmp_path / "config.yaml", tmp_path / "cache", "2026-2027")
    assert not state.is_empty()
    assert state.config.semester == 1
    # difficulties normalized to per-component dicts defaulting to 3
    assert state.config.modules["ALPHA"]["TUT"] == 3


def test_build_state_from_config(tmp_path, monkeypatch, alpha_json, beta_json):
    import yaml

    _patch_fetch(monkeypatch, alpha_json, beta_json)
    cfg = {
        "acad_year": "2026-2027",
        "semester": 1,
        "modules": {"ALPHA": {"difficulty": {"TUT": 4}}, "BETA": {"difficulty": 3}},
        "fixed": {"BETA": {"LEC": "1"}},
        "priority": ["ALPHA", "BETA"],
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    state = build_state(None, path, tmp_path / "cache")
    assert not state.is_empty()
    assert state.config.modules["ALPHA"]["TUT"] == 4


def test_build_state_no_source(tmp_path):
    with pytest.raises(SystemExit):
        build_state(None, tmp_path / "missing.yaml", tmp_path / "cache")
