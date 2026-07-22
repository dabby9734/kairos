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


def test_migration_overwrites_a_colliding_locked_entry(
    tmp_path, monkeypatch, alpha_json, beta_json
):
    """When one key sits in BOTH `fixed` and `locked`, `fixed` must win.

    prepare_groups reads `fixed` first and short-circuits, so pre-migration the
    file behaved as `fixed`. The migration overwrites rather than skips, keeping
    the effective pin identical. Balloted `fixed` entries stay put regardless.
    """
    import yaml

    _patch_fetch(monkeypatch, alpha_json, beta_json)
    cfg = {
        "acad_year": "2026-2027",
        "semester": 1,
        "modules": {"ALPHA": {"difficulty": 3}, "BETA": {"difficulty": 3}},
        "fixed": {"BETA": {"LEC": "1"}, "ALPHA": {"TUT": "01"}},  # LEC free, TUT balloted
        "locked": {"BETA": {"LEC": "2"}},  # collides with the fixed LEC pin
        "priority": ["ALPHA", "BETA"],
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    state = build_state(None, path, tmp_path / "cache")
    assert state.config.locked["BETA"]["LEC"] == "1"  # fixed won, not "2"
    assert "BETA" not in state.config.fixed
    assert state.config.fixed["ALPHA"]["TUT"] == "01"  # balloted pin untouched
    assert "ALPHA" not in state.config.locked


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


def test_migrated_fixed_roundtrips_through_config_and_prepare_groups(
    tmp_path, monkeypatch
):
    """Design spec section 8: 'the migrated form round-trips through
    to_config_yaml -> load_config -> prepare_groups.' Joins the two halves that
    were separately tested (migration in build_state; a locked round-trip on a
    hand-locked state) so pressing `s` provably does not resurrect `fixed`.

    Uses a purpose-built module (ZETA) whose LEC classes 1 & 2 share a slot_sig
    (same day/time, differ only by venue) so the locked-twin-set narrowing is
    distinguishable from a fixed-style single-class narrowing: class 3 sits on a
    different slot_sig and must be dropped, while both 1 and 2 must survive."""
    import yaml

    from tests.conftest import lesson

    from kairos.config import load_config
    from kairos.search import prepare_groups

    zeta_json = {
        "moduleCode": "ZETA",
        "semesterData": [
            {
                "semester": 1,
                "timetable": [
                    lesson("1", "Lecture", "Monday", "1000", "1200"),
                    lesson("2", "Lecture", "Monday", "1000", "1200", venue="COM1-0202"),
                    lesson("3", "Lecture", "Tuesday", "1400", "1600"),
                ],
            }
        ],
    }
    monkeypatch.setattr(
        "kairos.tui.startup.api.fetch_module", lambda ay, code, cache: zeta_json
    )
    cfg = {
        "acad_year": "2026-2027",
        "semester": 1,
        "modules": {"ZETA": {"difficulty": 3}},
        "fixed": {"ZETA": {"LEC": "1"}},  # non-balloted -> migrates to locked
        "priority": ["ZETA"],
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))

    state = build_state(None, path, tmp_path / "cache")
    assert state.config.locked["ZETA"]["LEC"] == "1"
    assert "ZETA" not in state.config.fixed

    data = state.to_config_yaml()
    assert data["fixed"] == {}
    assert data["locked"] == {"ZETA": {"LEC": "1"}}

    reload_path = tmp_path / "reloaded.yaml"
    reload_path.write_text(yaml.safe_dump(data))
    reloaded = load_config(reload_path)

    prepared = prepare_groups(state.base_groups, reloaded)
    lec = next(g for g in prepared if g.module == "ZETA" and g.lesson_type == "Lecture")
    # narrowed to the locked slot's twin set {1, 2} — not to a single class
    # (that would mean fixed-style behaviour survived) and not left unnarrowed
    # (that would mean the lock never applied): class 3 (different slot_sig)
    # must be gone.
    assert sorted(c.class_no for c in lec.choices) == ["1", "2"]
