import pytest

from optimiser.cli import main


def test_tui_builds_state_and_runs(tmp_path, monkeypatch, alpha_json, beta_json):
    fixtures = {"ALPHA": alpha_json, "BETA": beta_json}
    monkeypatch.setattr(
        "optimiser.tui.startup.api.fetch_module", lambda ay, code, cache: fixtures[code]
    )
    ran = {}
    monkeypatch.setattr(
        "optimiser.cli.run_app", lambda state, path: ran.setdefault("state", state)
    )
    url = "https://nusmods.com/timetable/sem-1/share?ALPHA=TUT:01,LEC:1&BETA=LAB:L2,LEC:1"
    main(
        [
            "--config", str(tmp_path / "config.yaml"),
            "--cache-dir", str(tmp_path / "cache"),
            "tui", url, "--acad-year", "2026-2027",
        ]
    )
    assert "state" in ran  # app was launched with a built state
    assert not ran["state"].is_empty()


def test_tui_no_source_exits(tmp_path, monkeypatch):
    monkeypatch.setattr("optimiser.cli.run_app", lambda state, path: None)
    with pytest.raises(SystemExit):
        main(["--config", str(tmp_path / "missing.yaml"), "tui"])


def test_tui_reports_irreconcilable(tmp_path, monkeypatch):
    from tests.conftest import lesson

    # Every ALPHA lesson clashes with every BETA lesson (same Monday slot).
    clash_a = {
        "moduleCode": "ALPHA",
        "semesterData": [{"semester": 1, "timetable": [
            lesson("01", "Tutorial", "Monday", "1000", "1200"),
        ]}],
    }
    clash_b = {
        "moduleCode": "BETA",
        "semesterData": [{"semester": 1, "timetable": [
            lesson("01", "Tutorial", "Monday", "1000", "1200"),
        ]}],
    }
    monkeypatch.setattr(
        "optimiser.tui.startup.api.fetch_module",
        lambda ay, code, cache: {"ALPHA": clash_a, "BETA": clash_b}[code],
    )
    monkeypatch.setattr("optimiser.cli.run_app", lambda state, path: None)
    url = "https://nusmods.com/timetable/sem-1/share?ALPHA=TUT:01&BETA=TUT:01"
    with pytest.raises(SystemExit) as exc:
        main(["--config", str(tmp_path / "config.yaml"), "--cache-dir", str(tmp_path / "c"),
              "tui", url, "--acad-year", "2026-2027"])
    assert "no clash-free timetable" in str(exc.value)
