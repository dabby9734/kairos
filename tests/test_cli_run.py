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


def test_run_accepts_config_flag_after_subcommand(
    tmp_path, config_file, monkeypatch, capsys, alpha_json, beta_json
):
    # Regression: --config/--cache-dir used to live only on the parent parser,
    # so `optimiser run --config X` (flag after the subcommand) failed even
    # though `optimiser --config X run` (flag before) worked.
    monkeypatch.setattr(
        "optimiser.cli.api.fetch_module",
        lambda ay, code, cache: {"ALPHA": alpha_json, "BETA": beta_json}[code],
    )
    main(["run", "--config", str(config_file), "--cache-dir", str(tmp_path / "cache")])
    out = capsys.readouterr().out
    assert "timetable #1" in out


def test_init_then_run_roundtrip(tmp_path, monkeypatch, capsys, alpha_json, beta_json):
    # Whole-system round trip: `init` writes config.yaml from a share URL and
    # interactive prompts, then `run` reads that exact file back and produces
    # a ranked ballot. alpha_json/beta_json don't have two balloted lesson
    # types on the same module, so we add a synthetic GAMMA module with both
    # a Recitation and a Laboratory group to exercise the snake's
    # within-module REC-before-LAB ordering through search -> ranked_options
    # -> snake on data that actually flowed through init's config.yaml.
    from tests.conftest import lesson

    gamma_json = {
        "moduleCode": "GAMMA",
        "semesterData": [
            {
                "semester": 1,
                "timetable": [
                    lesson("R1", "Recitation", "Wednesday", "1400", "1500"),
                    lesson("R2", "Recitation", "Thursday", "1400", "1500"),
                    lesson("G1", "Laboratory", "Tuesday", "1400", "1600"),
                    lesson("G2", "Laboratory", "Wednesday", "1600", "1800"),
                ],
            }
        ],
    }
    fixtures = {"ALPHA": alpha_json, "BETA": beta_json, "GAMMA": gamma_json}
    monkeypatch.setattr("optimiser.cli.api.fetch_module", lambda ay, code, cache: fixtures[code])

    # BETA gets a LEC pick (2 lecture groups) so it's fixed; ALPHA has only 1
    # LEC group so it's never fixed regardless of the pick; GAMMA's REC/LAB
    # are balloted types so they're never fixed even though unpicked.
    share_url = (
        "https://nusmods.com/timetable/sem-1/share?"
        "ALPHA=TUT:01,LEC:1&BETA=LAB:L2,LEC:1&GAMMA="
    )

    config_path = tmp_path / "config.yaml"
    cache_dir = tmp_path / "cache"

    # Difficulty prompts fire in lesson_type-sorted order per module:
    #   ALPHA: Lecture, Tutorial
    #   BETA:  Laboratory, Lecture
    #   GAMMA: Laboratory, Recitation
    # followed by one priority-order prompt. Blank answers take the defaults.
    answers = iter(["", "", "", "", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    main(
        [
            "--config", str(config_path),
            "--cache-dir", str(cache_dir),
            "init", share_url,
            "--acad-year", "2026-2027",
        ]
    )
    capsys.readouterr()  # discard init's own output

    written = yaml.safe_load(config_path.read_text())
    assert written["fixed"] == {"BETA": {"LEC": "1"}}

    main(["run", "--config", str(config_path), "--cache-dir", str(cache_dir)])
    out = capsys.readouterr().out

    assert "timetable #1" in out
    assert "https://nusmods.com/timetable/sem-1/share?" in out
    assert "ballot ranking" in out

    snake_section = out.split("=== ballot ranking")[1]
    rec_pos = snake_section.index("GAMMA REC[")
    lab_pos = snake_section.index("GAMMA LAB[")
    assert rec_pos < lab_pos, "GAMMA REC choice A must come before GAMMA LAB choice A in the snake"


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
