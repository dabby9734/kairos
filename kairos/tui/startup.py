from __future__ import annotations

from pathlib import Path

from .. import api
from ..cli import guess_acad_year, parse_share_url
from ..config import DEFAULT_BALLOTED, DEFAULT_PREFERENCES, config_from_dict, load_config
from ..model import LESSON_ABBREV
from .state import AppState


def _config_from_url(share_url: str, cache_dir: Path, acad_year: str | None):
    semester, selections = parse_share_url(share_url)
    acad_year = acad_year or guess_acad_year()
    modules_cfg: dict = {}
    locked: dict = {}
    groups = []
    for code, picks in selections.items():
        data = api.fetch_module(acad_year, code, cache_dir)
        code_groups = api.build_groups(code, api.semester_timetable(data, semester))
        groups.extend(code_groups)
        difficulty: dict = {}
        for group in code_groups:
            abbrev = LESSON_ABBREV.get(group.lesson_type, group.lesson_type)
            difficulty[abbrev] = 3
            if abbrev not in DEFAULT_BALLOTED and len(group.choices) > 1 and abbrev in picks:
                # `locked`, not `fixed`: pins the SLOT while keeping the group
                # switchable from the TUI and keeping venue-twins interchangeable.
                locked.setdefault(code, {})[abbrev] = picks[abbrev]
        modules_cfg[code] = {"difficulty": difficulty}
    data = {
        "acad_year": acad_year,
        "semester": semester,
        "balloted_types": list(DEFAULT_BALLOTED),
        "modules": modules_cfg,
        "fixed": {},
        "locked": locked,
        "priority": list(selections),
        "preferences": DEFAULT_PREFERENCES,
    }
    return config_from_dict(data, "share URL"), groups


def _config_from_file(config_path: Path, cache_dir: Path):
    config = load_config(config_path)
    groups = []
    for code in config.modules:
        data = api.fetch_module(config.acad_year, code, cache_dir)
        groups.extend(api.build_groups(code, api.semester_timetable(data, config.semester)))
    return config, groups


def migrate_fixed_to_locked(config) -> None:
    """Convert non-balloted `fixed` pins into `locked` pins, in place.

    Such entries were auto-written from a share URL by earlier versions, and
    `fixed` beats `locked` in prepare_groups — so the group is pinned to one
    class AND unswitchable from the TUI. `locked` pins the same slot while
    leaving the group selectable. Balloted `fixed` entries are hand-written and
    deliberate, so they are left alone.

    TUI-load only: `kairos run` / load_config are untouched, so CLI behaviour
    does not move. The migrated form reaches disk only when the user saves."""
    for code in list(config.fixed):
        slots = config.fixed[code]
        for abbrev in list(slots):
            if abbrev in config.balloted_types:
                continue
            # fixed previously won over locked, so it wins this overwrite too
            config.locked.setdefault(code, {})[abbrev] = str(slots.pop(abbrev))
        if not slots:
            config.fixed.pop(code)


def build_state(share_url, config_path: Path, cache_dir: Path, acad_year=None) -> AppState:
    if share_url:
        config, groups = _config_from_url(share_url, cache_dir, acad_year)
    elif Path(config_path).exists():
        config, groups = _config_from_file(Path(config_path), cache_dir)
    else:
        raise SystemExit(
            "error: no config.yaml found — start from a share URL: kairos tui <share-url>"
        )
    migrate_fixed_to_locked(config)
    return AppState.from_parts(config, groups)
