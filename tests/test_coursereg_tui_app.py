import yaml
from textual.widgets import ListView, Static

from kairos.coursereg.model import DemandRecord, Profile
from kairos.coursereg.tui.app import AdvisorApp
from kairos.coursereg.tui.state import AdvisorState


def rec(course, year, sem, rnd, demand, vacancy):
    return DemandRecord(course, year, sem, rnd, demand, vacancy)


def make_state():
    records = []
    for year, (a, b, c) in {
        "2324": (90, 40, 200), "2425": (110, 50, 180), "2526": (95, 60, 210),
    }.items():
        records += [
            rec("AAA1000", year, 1, 2, a, 100),
            rec("BBB1000", year, 1, 2, b, 100),
            rec("CCC1000", year, 1, 2, c, 100),
        ]
    tiers = {"AAA1000": "major", "BBB1000": "major", "CCC1000": "major"}
    profile = Profile(seniority=2, semester=1, round=2, tiers=tiers,
                      order=list(tiers), ranked=False)
    return AdvisorState(profile, records)


async def test_opens_in_suggested_order_with_dossier(tmp_path):
    app = AdvisorApp(make_state(), tmp_path / "coursereg.yaml")
    async with app.run_test() as pilot:
        await pilot.pause()
        ranking = app.query_one("#ranking", ListView)
        assert ranking.index == 0
        detail = app.query_one("#dossier", Static)
        # textual 8.2.8's Static has no public `renderable`; `.content` holds
        # the last value passed to `.update()` (see tests/test_tui_app.py).
        text = str(detail.content)
        assert "AAA1000" in text and "CONTESTED" in text
        assert "25/26" in text  # dossier shows per-year rows


async def test_shift_j_moves_course_down(tmp_path):
    state = make_state()
    app = AdvisorApp(state, tmp_path / "coursereg.yaml")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("J")
        await pilot.pause()
        assert state.order[1] == "AAA1000"
        assert app.query_one("#ranking", ListView).index == 1


async def test_t_cycles_tier_and_recomputes(tmp_path):
    state = make_state()
    app = AdvisorApp(state, tmp_path / "coursereg.yaml")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("t")  # AAA1000 major -> ue
        await pilot.pause()
        assert state.profile.tiers["AAA1000"] == "ue"
        assert state.verdicts["AAA1000"].standing == "TOUGH"


async def test_r_toggles_round(tmp_path):
    state = make_state()
    app = AdvisorApp(state, tmp_path / "coursereg.yaml")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        assert state.profile.round == 3


async def test_a_restores_suggested_order(tmp_path):
    state = make_state()
    app = AdvisorApp(state, tmp_path / "coursereg.yaml")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("J")
        await pilot.press("a")
        await pilot.pause()
        assert state.order == state.suggested


async def test_s_saves_ranking_to_yaml(tmp_path):
    state = make_state()
    path = tmp_path / "coursereg.yaml"
    app = AdvisorApp(state, path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("J")
        await pilot.press("s")
        await pilot.pause()
    data = yaml.safe_load(path.read_text())
    assert data["ranked"] is True
    assert list(data["candidates"]) == state.order


async def test_warnings_strip_flags_safe_in_top_rank(tmp_path):
    state = make_state()
    state.order = ["BBB1000", "AAA1000", "CCC1000"]  # SAFE first
    app = AdvisorApp(state, tmp_path / "coursereg.yaml")
    async with app.run_test() as pilot:
        await pilot.pause()
        summary = app.query_one("#summary", Static)
        assert "BBB1000" in str(summary.content)
