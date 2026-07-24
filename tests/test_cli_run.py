import pytest
import yaml

from kairos.cli import main


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
        "kairos.cli.api.fetch_module", lambda ay, code, cache: fixtures[code]
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
    # only 5 viable options exist across ALPHA TUT + BETA LAB, so the ballot
    # falls short of the 20-slot cap and the CLI must warn about it
    assert (
        "warning: ballot uses only 5 of 20 slots — no further clash-free "
        "options exist. NUS notes a shorter list may mean not getting a "
        "tutorial allocated at all."
    ) in out


def test_run_accepts_config_flag_after_subcommand(
    tmp_path, config_file, monkeypatch, capsys, alpha_json, beta_json
):
    # Regression: --config/--cache-dir used to live only on the parent parser,
    # so `kairos run --config X` (flag after the subcommand) failed even
    # though `kairos --config X run` (flag before) worked.
    monkeypatch.setattr(
        "kairos.cli.api.fetch_module",
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
    monkeypatch.setattr("kairos.cli.api.fetch_module", lambda ay, code, cache: fixtures[code])

    # BETA gets a LEC pick (2 lecture groups) so it's locked; ALPHA has only 1
    # LEC group so it's never locked regardless of the pick; GAMMA's REC/LAB
    # are balloted types so they're never locked even though unpicked.
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
    assert written["fixed"] == {}
    assert written["locked"] == {"BETA": {"LEC": "1"}}

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
        "kairos.cli.api.fetch_module",
        lambda ay, code, cache: {"ALPHA": clash_a, "BETA": clash_b}[code],
    )
    with pytest.raises(SystemExit) as exc:
        main(["--config", str(config_file), "run"])
    assert "no clash-free timetable" in str(exc.value)


def test_run_reports_both_counts_and_annotates_ballot(
    tmp_path, config_file, monkeypatch, capsys, alpha_json, beta_json
):
    # The header must state the arrangement total, because the ballot's
    # annotation denominators count arrangements while `evaluated` counts combos.
    import re

    out = run_cli(
        tmp_path, config_file, monkeypatch, capsys,
        {"ALPHA": alpha_json, "BETA": beta_json},
    )
    assert re.search(
        r"evaluated \d+ clash-free timetable shapes \(\d+ distinct arrangements\)", out
    )
    assert "best #" in out
    assert "typical #" in out


def test_cli_timetables_are_arrangement_ranked(
    tmp_path, config_file, monkeypatch, capsys, alpha_json, beta_json
):
    # Cross-surface agreement: the CLI's "timetable #1" must be the first
    # ARRANGEMENT, so a ballot row's "best #t" is comparable against it.
    from kairos.api import build_groups, semester_timetable
    from kairos.config import load_config
    from kairos.search import enumerate_clashfree, prepare_groups, rank_arrangements

    out = run_cli(
        tmp_path, config_file, monkeypatch, capsys,
        {"ALPHA": alpha_json, "BETA": beta_json},
    )
    cfg = load_config(config_file)
    groups = prepare_groups(
        build_groups("ALPHA", semester_timetable(alpha_json, 1))
        + build_groups("BETA", semester_timetable(beta_json, 1)),
        cfg,
    )
    arrangements = rank_arrangements(enumerate_clashfree(groups), cfg, limit=cfg.top_n)
    assert f"score: {arrangements[0].score:+.2f}" in out
