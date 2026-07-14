import pytest
import yaml

from optimiser.cli import main


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "acad_year": "2026-2027",
                "semester": 1,
                "modules": {
                    "ALPHA": {"difficulty": {"LEC": 2, "TUT": 4}},
                    "BETA": {"difficulty": 3},
                },
                "fixed": {"BETA": {"LEC": "1"}},
                "priority": ["ALPHA", "BETA"],
                "top_n": 2,
            }
        )
    )
    return path


def run_cli(tmp_path, config_file, monkeypatch, capsys, fixtures):
    monkeypatch.setattr(
        "optimiser.cli.api.fetch_module", lambda ay, code, cache: fixtures[code]
    )
    main(["--config", str(config_file), "--cache-dir", str(tmp_path / "cache"), "run"])
    return capsys.readouterr().out


def test_run_end_to_end(tmp_path, config_file, monkeypatch, capsys, alpha_json, beta_json):
    out = run_cli(
        tmp_path, config_file, monkeypatch, capsys, {"ALPHA": alpha_json, "BETA": beta_json}
    )
    assert "timetable #1" in out
    assert "https://nusmods.com/timetable/sem-1/share?" in out
    assert "score:" in out
    assert "ballot ranking" in out
    # BETA lecture is fixed to the online group 1, so it appears with LEC:1
    assert "BETA=LAB:" in out and "LEC:1" in out
    # backup section lists ALPHA tutorials with interchangeable pair 02/03
    assert "interchangeable" in out


def test_run_reports_irreconcilable(tmp_path, config_file, monkeypatch, capsys):
    from tests.conftest import lesson

    clash_a = {
        "moduleCode": "ALPHA",
        "semesterData": [{"semester": 1, "timetable": [
            lesson("1", "Lecture", "Monday", "1000", "1200"),
            lesson("01", "Tutorial", "Monday", "1300", "1400"),
        ]}],
    }
    clash_b = {
        "moduleCode": "BETA",
        "semesterData": [{"semester": 1, "timetable": [
            lesson("1", "Lecture", "Monday", "1100", "1300"),
            lesson("L1", "Laboratory", "Monday", "1300", "1500"),
        ]}],
    }
    monkeypatch.setattr(
        "optimiser.cli.api.fetch_module",
        lambda ay, code, cache: {"ALPHA": clash_a, "BETA": clash_b}[code],
    )
    with pytest.raises(SystemExit) as exc:
        main(["--config", str(config_file), "run"])
    assert "no clash-free timetable" in str(exc.value)
