import pytest

from optimiser.config import load_config


def write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return p


BASE = """
acad_year: 2026-2027
semester: 1
modules:
  ALPHA:
    difficulty: {LEC: 2, TUT: 4}
  BETA:
    difficulty: 3
fixed:
  BETA: {LEC: "1"}
priority: [BETA]
"""


def test_load_config_defaults_and_difficulty(tmp_path):
    cfg = load_config(write(tmp_path, BASE))
    assert cfg.balloted_types == ["TUT", "LAB", "REC", "SEC"]
    assert cfg.preferences.earliest_start == 600  # default "10:00"
    assert cfg.preferences.lunch_start == 660 and cfg.preferences.lunch_end == 840
    assert cfg.preferences.weights["tough_days"] == 5
    assert cfg.top_n == 5 and cfg.alternatives_per_module == 4
    assert cfg.difficulty("ALPHA", "Tutorial") == 4
    assert cfg.difficulty("ALPHA", "Recitation") == 3  # unspecified component
    assert cfg.difficulty("BETA", "Laboratory") == 3  # shorthand int
    assert cfg.priority == ["BETA", "ALPHA"]  # missing modules appended


def test_load_config_overrides(tmp_path):
    cfg = load_config(
        write(
            tmp_path,
            BASE
            + """
preferences:
  earliest_start: "09:00"
  weights: {gaps: 7}
top_n: 3
""",
        )
    )
    assert cfg.preferences.earliest_start == 540
    assert cfg.preferences.weights["gaps"] == 7
    assert cfg.preferences.weights["lunch"] == 3  # unlisted weights keep defaults
    assert cfg.top_n == 3


def test_load_config_rejects_bad_difficulty(tmp_path):
    with pytest.raises(SystemExit):
        load_config(write(tmp_path, BASE.replace("difficulty: 3", "difficulty: 9")))


def test_load_config_missing_file(tmp_path):
    with pytest.raises(SystemExit):
        load_config(tmp_path / "nope.yaml")
