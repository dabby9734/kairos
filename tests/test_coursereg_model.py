import pytest
import yaml


def make_profile_dict():
    return {
        "seniority": 2,
        "semester": 1,
        "round": 2,
        "candidates": {"CS2109S": "major", "GEH1049": "ue", "IS2218": "ue"},
    }


def test_profile_from_dict_parses_fields():
    from kairos.coursereg.model import profile_from_dict

    p = profile_from_dict(make_profile_dict())
    assert (p.seniority, p.semester, p.round) == (2, 1, 2)
    assert p.tiers == {"CS2109S": "major", "GEH1049": "ue", "IS2218": "ue"}
    assert p.order == ["CS2109S", "GEH1049", "IS2218"]  # mapping order = rank order
    assert p.ranked is False


def test_profile_from_dict_uppercases_course_codes():
    from kairos.coursereg.model import profile_from_dict

    d = make_profile_dict()
    d["candidates"] = {"cs2109s": "major"}
    p = profile_from_dict(d)
    assert p.order == ["CS2109S"] and "CS2109S" in p.tiers


@pytest.mark.parametrize(
    "key,value,fragment",
    [
        ("seniority", 5, "seniority"),
        ("seniority", 0, "seniority"),
        ("semester", 3, "semester"),
        ("round", 1, "round"),
        ("round", 4, "round"),
    ],
)
def test_profile_from_dict_rejects_out_of_range(key, value, fragment):
    from kairos.coursereg.model import profile_from_dict

    d = make_profile_dict()
    d[key] = value
    with pytest.raises(SystemExit) as exc:
        profile_from_dict(d)
    assert fragment in str(exc.value)


def test_profile_from_dict_rejects_bad_tier_and_empty_candidates():
    from kairos.coursereg.model import profile_from_dict

    d = make_profile_dict()
    d["candidates"] = {"CS2109S": "corr"}
    with pytest.raises(SystemExit):
        profile_from_dict(d)
    d["candidates"] = {}
    with pytest.raises(SystemExit):
        profile_from_dict(d)


def test_load_profile_missing_file_prints_template(tmp_path):
    from kairos.coursereg.model import TEMPLATE, load_profile

    with pytest.raises(SystemExit) as exc:
        load_profile(tmp_path / "coursereg.yaml")
    assert "error:" in str(exc.value) and TEMPLATE in str(exc.value)


def test_yaml_round_trip_preserves_order_and_ranked(tmp_path):
    from kairos.coursereg.model import load_profile, profile_from_dict, profile_to_yaml

    p = profile_from_dict(make_profile_dict())
    p.order = ["IS2218", "CS2109S", "GEH1049"]  # user reordered
    p.ranked = True
    path = tmp_path / "coursereg.yaml"
    path.write_text(profile_to_yaml(p))
    again = load_profile(path)
    assert again.order == ["IS2218", "CS2109S", "GEH1049"]
    assert again.ranked is True and again.tiers == p.tiers


def test_template_is_loadable_yaml():
    from kairos.coursereg.model import TEMPLATE, profile_from_dict

    p = profile_from_dict(yaml.safe_load(TEMPLATE))
    assert p.order  # template parses into a valid profile
