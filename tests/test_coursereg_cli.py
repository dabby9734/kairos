import pytest

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
