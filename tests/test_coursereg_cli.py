import pytest
import yaml
from pathlib import Path

from kairos.cli import main


def test_advise_missing_config_prints_template(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["advise"])
    message = str(exc.value)
    assert "error:" in message and "candidates:" in message


def test_advise_uses_own_config_and_cache_defaults():
    # The parser must default advise's config to coursereg.yaml (not the
    # global config.yaml) and its cache dir to data/coursereg.
    from kairos import cli

    captured = {}

    def fake_cmd_advise(args):
        captured["config"] = args.config
        captured["cache_dir"] = args.cache_dir

    original = cli.cmd_advise
    cli.cmd_advise = fake_cmd_advise
    try:
        cli.main(["advise"])
    finally:
        cli.cmd_advise = original
    assert captured == {"config": "coursereg.yaml", "cache_dir": "data/coursereg"}


def test_prompt_choice_default_shorthand_and_reprompt(monkeypatch, capsys):
    from kairos.cli import _prompt_choice

    tier_choices = {
        "core": "core", "major": "major", "ue": "ue",
        "c": "core", "m": "major", "u": "ue",
    }
    answers = iter(["", "U", "core!", "c"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert _prompt_choice("tier? ", tier_choices, "major") == "major"  # bare Enter
    assert _prompt_choice("tier? ", tier_choices, "major") == "ue"  # shorthand, any case
    # "core!" is rejected with a hint, then "c" is accepted
    assert _prompt_choice("tier? ", tier_choices, "major") == "core"
    assert "core, major, ue" in capsys.readouterr().out


ADVISE_URL = (
    "https://nusmods.com/timetable/sem-2/share?"
    "CS2109S=TUT:01,LEC:1&GEH1049=&MA2001=LEC:2"
)


def test_advise_setup_writes_profile_in_link_order(tmp_path, monkeypatch, capsys):
    from kairos.cli import _advise_setup

    # seniority, round, then one tier per course in link order
    answers = iter(["3", "3", "c", "", "u"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    config_path = tmp_path / "coursereg.yaml"
    profile = _advise_setup(ADVISE_URL, config_path)

    written = yaml.safe_load(config_path.read_text())
    assert written["seniority"] == 3
    assert written["semester"] == 2  # from the link, never prompted
    assert written["round"] == 3
    assert written["ranked"] is False
    assert written["candidates"] == {"CS2109S": "core", "GEH1049": "major", "MA2001": "ue"}
    assert list(written["candidates"]) == ["CS2109S", "GEH1049", "MA2001"]  # link order
    assert profile.order == ["CS2109S", "GEH1049", "MA2001"]
    assert f"wrote {config_path}" in capsys.readouterr().out


def test_advise_setup_all_defaults(tmp_path, monkeypatch):
    from kairos.cli import _advise_setup

    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    profile = _advise_setup(ADVISE_URL, tmp_path / "coursereg.yaml")
    assert profile.seniority == 2
    assert profile.round == 2
    assert set(profile.tiers.values()) == {"major"}


def test_advise_setup_declined_overwrite_aborts(tmp_path, monkeypatch):
    from kairos.cli import _advise_setup

    config_path = tmp_path / "coursereg.yaml"
    config_path.write_text("existing: true")
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    with pytest.raises(SystemExit, match="aborted"):
        _advise_setup(ADVISE_URL, config_path)
    assert config_path.read_text() == "existing: true"


def test_advise_setup_rejects_special_term_before_prompting(tmp_path, monkeypatch):
    from kairos.cli import _advise_setup

    config_path = tmp_path / "coursereg.yaml"
    config_path.write_text("existing: true")

    def no_prompts(prompt=""):
        raise AssertionError("prompted despite special-term link")

    monkeypatch.setattr("builtins.input", no_prompts)
    url = "https://nusmods.com/timetable/sem-3/share?CS2109S=TUT:01"
    with pytest.raises(SystemExit, match="special term"):
        _advise_setup(url, config_path)
    assert config_path.read_text() == "existing: true"


def test_advise_with_link_generates_config_then_launches_tui(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    answers = iter(["1", "2", "m", "core", "ue"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(
        "kairos.coursereg.fetch.load_history", lambda cache_dir, refetch=False: []
    )
    captured = {}
    monkeypatch.setattr(
        "kairos.coursereg.tui.app.run_advisor",
        lambda state, config_path: captured.update(
            profile=state.profile, config_path=config_path
        ),
    )

    main(["advise", ADVISE_URL])

    written = yaml.safe_load(Path("coursereg.yaml").read_text())
    assert written["candidates"] == {"CS2109S": "major", "GEH1049": "core", "MA2001": "ue"}
    assert captured["profile"].semester == 2
    assert captured["profile"].seniority == 1
    assert captured["config_path"] == Path("coursereg.yaml")


def test_advise_without_link_still_loads_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("coursereg.yaml").write_text(
        "seniority: 2\nsemester: 1\nround: 2\ncandidates:\n  CS2109S: major\n"
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("prompted"))
    monkeypatch.setattr(
        "kairos.coursereg.fetch.load_history", lambda cache_dir, refetch=False: []
    )
    captured = {}
    monkeypatch.setattr(
        "kairos.coursereg.tui.app.run_advisor",
        lambda state, config_path: captured.update(profile=state.profile),
    )

    main(["advise"])

    assert captured["profile"].tiers == {"CS2109S": "major"}
