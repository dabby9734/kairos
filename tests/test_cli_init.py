import datetime

import pytest
import yaml

from kairos.cli import guess_acad_year, main, parse_share_url

SHARE_URL = (
    "https://nusmods.com/timetable/sem-1/share?"
    "ALPHA=TUT:01,LEC:1&BETA=LAB:L2,LEC:1"
)


def test_parse_share_url():
    semester, selections = parse_share_url(SHARE_URL)
    assert semester == 1
    assert selections == {
        "ALPHA": {"TUT": "01", "LEC": "1"},
        "BETA": {"LAB": "L2", "LEC": "1"},
    }


def test_parse_share_url_empty_selection():
    _, selections = parse_share_url("https://nusmods.com/timetable/sem-2/share?ALPHA=")
    assert selections == {"ALPHA": {}}


def test_parse_share_url_rejects_garbage():
    with pytest.raises(SystemExit):
        parse_share_url("https://example.com/nothing")
    with pytest.raises(SystemExit):
        parse_share_url("https://nusmods.com/timetable/sem-1/share?ALPHA=junk")


def test_guess_acad_year():
    assert guess_acad_year(datetime.date(2026, 7, 13)) == "2026-2027"
    assert guess_acad_year(datetime.date(2026, 2, 1)) == "2025-2026"


def test_cmd_init_writes_config(tmp_path, monkeypatch, alpha_json, beta_json):
    fixtures = {"ALPHA": alpha_json, "BETA": beta_json}
    monkeypatch.setattr(
        "kairos.cli.api",
        type(
            "FakeApi",
            (),
            {
                "fetch_module": staticmethod(lambda ay, code, cache: fixtures[code]),
                "semester_timetable": staticmethod(
                    __import__("kairos.api", fromlist=["x"]).semester_timetable
                ),
                "build_groups": staticmethod(
                    __import__("kairos.api", fromlist=["x"]).build_groups
                ),
            },
        ),
    )
    # prompts: ALPHA LEC diff, ALPHA TUT diff, BETA LAB diff, BETA LEC diff, priority
    answers = iter(["2", "4", "", "1", "BETA,ALPHA"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    config_path = tmp_path / "config.yaml"
    main(
        [
            "--config", str(config_path),
            "--cache-dir", str(tmp_path / "cache"),
            "init", SHARE_URL,
            "--acad-year", "2026-2027",
        ]
    )

    written = yaml.safe_load(config_path.read_text())
    assert written["acad_year"] == "2026-2027"
    assert written["semester"] == 1
    assert written["modules"]["ALPHA"]["difficulty"] == {"LEC": 2, "TUT": 4}
    assert written["modules"]["BETA"]["difficulty"] == {"LAB": 3, "LEC": 1}
    # BETA has 2 lecture groups and a URL pick -> fixed; ALPHA has 1 lecture group -> not fixed
    assert written["fixed"] == {"BETA": {"LEC": "1"}}
    assert written["priority"] == ["BETA", "ALPHA"]
    assert written["balloted_types"] == ["TUT", "LAB", "REC", "SEC"]
    assert written["preferences"]["weights"]["free_days"] == 4


def test_cmd_init_refuses_overwrite_without_confirmation(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("existing: true")
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    with pytest.raises(SystemExit):
        main(["--config", str(config_path), "init", SHARE_URL])
    assert config_path.read_text() == "existing: true"
