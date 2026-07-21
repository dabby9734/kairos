import pytest

from kairos.tui.startup import build_state

SHARE_URL = "https://nusmods.com/timetable/sem-1/share?ALPHA=TUT:01,LEC:1&BETA=LAB:L2,LEC:1"


def _patch_fetch(monkeypatch, alpha_json, beta_json):
    fixtures = {"ALPHA": alpha_json, "BETA": beta_json}
    monkeypatch.setattr(
        "kairos.tui.startup.api.fetch_module", lambda ay, code, cache: fixtures[code]
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


def test_build_state_migrates_non_balloted_fixed_to_locked(
    tmp_path, monkeypatch, alpha_json, beta_json
):
    import yaml

    _patch_fetch(monkeypatch, alpha_json, beta_json)
    cfg = {
        "acad_year": "2026-2027",
        "semester": 1,
        "modules": {"ALPHA": {"difficulty": 3}, "BETA": {"difficulty": 3}},
        "fixed": {"BETA": {"LEC": "1"}},
        "priority": ["ALPHA", "BETA"],
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    state = build_state(None, path, tmp_path / "cache")
    # the LEC pin moved from fixed to locked, so the TUI can switch it
    assert state.config.locked["BETA"]["LEC"] == "1"
    assert "BETA" not in state.config.fixed
    # and BOTH lecture slots remain offered, so the pane can show them
    lec = next(g for g in state.base_groups if g.module == "BETA" and g.lesson_type == "Lecture")
    assert len(lec.choices) == 2


def test_build_state_leaves_balloted_fixed_alone(
    tmp_path, monkeypatch, alpha_json, beta_json
):
    import yaml

    _patch_fetch(monkeypatch, alpha_json, beta_json)
    cfg = {
        "acad_year": "2026-2027",
        "semester": 1,
        "modules": {"ALPHA": {"difficulty": 3}, "BETA": {"difficulty": 3}},
        "fixed": {"ALPHA": {"TUT": "01"}},  # balloted -> deliberate hand-written pin
        "priority": ["ALPHA", "BETA"],
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    state = build_state(None, path, tmp_path / "cache")
    assert state.config.fixed["ALPHA"]["TUT"] == "01"
    assert "ALPHA" not in state.config.locked


def test_build_state_from_url_writes_locked_not_fixed(
    tmp_path, monkeypatch, alpha_json, beta_json
):
    _patch_fetch(monkeypatch, alpha_json, beta_json)
    state = build_state(SHARE_URL, tmp_path / "config.yaml", tmp_path / "cache", "2026-2027")
    # URL had BETA=LEC:1 — a non-balloted multi-option group
    assert state.config.locked["BETA"]["LEC"] == "1"
    assert not state.config.fixed
