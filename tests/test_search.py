import itertools

import pytest

from optimiser.api import build_groups, semester_timetable
from optimiser.model import ChoiceGroup
from optimiser.scoring import score_assignment
from optimiser.search import find_irreconcilable, prepare_groups, search


@pytest.fixture
def groups(alpha_json, beta_json, config):
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1)) + build_groups(
        "BETA", semester_timetable(beta_json, 1)
    )
    return prepare_groups(gs, config)


def test_prepare_groups_applies_fixed(groups):
    beta_lec = next(g for g in groups if g.key == ("BETA", "Lecture"))
    assert [c.class_no for c in beta_lec.choices] == ["1"]  # config.fixed pins it


def test_prepare_groups_warns_for_free_nonballoted_group(capsys, beta_json, config):
    config.fixed = {}
    gs = build_groups("BETA", semester_timetable(beta_json, 1))
    prepared = prepare_groups(gs, config)
    beta_lec = next(g for g in prepared if g.key == ("BETA", "Lecture"))
    assert [c.class_no for c in beta_lec.choices] == ["1", "2"]
    out = capsys.readouterr().out
    assert "warning:" in out
    assert "BETA" in out


def test_prepare_groups_bad_fixed(alpha_json, config):
    config.fixed = {"ALPHA": {"LEC": "99"}}
    gs = build_groups("ALPHA", semester_timetable(alpha_json, 1))
    with pytest.raises(SystemExit):
        prepare_groups(gs, config)


def test_search_footprint_dedup_and_clash(groups, config):
    result = search(groups, config)
    # ALPHA TUT footprints: {Mon}, {Tue} (02+03 collapse). BETA LAB: L1, L2.
    # L1 clashes ALPHA TUT 01 -> clash-free footprint combos = 2*2 - 1 = 3
    assert result.evaluated == 3
    tut_members = result.members[("ALPHA", "Tutorial")]
    assert sorted(len(v) for v in tut_members.values()) == [1, 2]


def test_search_top_sorted_and_assignment_shape(groups, config):
    result = search(groups, config)
    totals = [t for t, _, _ in result.top]
    assert totals == sorted(totals, reverse=True)
    _, _, assignment = result.top[0]
    assert set(assignment) == {
        ("ALPHA", "Lecture"),
        ("ALPHA", "Tutorial"),
        ("BETA", "Lecture"),
        ("BETA", "Laboratory"),
    }


def test_best_by_footprint_matches_bruteforce(groups, config):
    result = search(groups, config)
    best = {}
    for combo in itertools.product(*(g.choices for g in groups)):
        if any(a.clashes(b) for a, b in itertools.combinations(combo, 2)):
            continue
        total, _ = score_assignment(list(combo), config)
        for c in combo:
            key = (c.module, c.lesson_type, c.footprint)
            best[key] = max(best.get(key, float("-inf")), total)
    assert result.best_by_footprint == pytest.approx(best)


def test_find_irreconcilable(config):
    from tests.conftest import lesson
    from optimiser.api import build_groups as bg

    a = bg("A", [lesson("1", "Tutorial", "Monday", "1000", "1200")])
    b = bg("B", [lesson("1", "Tutorial", "Monday", "1100", "1300")])
    pair = find_irreconcilable(a + b)
    assert pair is not None
    assert {pair[0].module, pair[1].module} == {"A", "B"}
