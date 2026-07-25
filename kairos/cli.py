from __future__ import annotations

import argparse
import datetime
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

from . import api, ballot, output, search
from .config import DEFAULT_BALLOTED, DEFAULT_PREFERENCES, load_config
from .model import LESSON_ABBREV
from .provenance import arrangement_provenance
from .tui.app import run_app

# NOTE: `build_state` is imported lazily inside cmd_tui (not at module level)
# because kairos.tui.startup imports guess_acad_year/parse_share_url from
# this module — a top-level `from .tui.startup import build_state` here would
# create a circular import (this module isn't finished initializing yet).


def parse_share_url(url: str):
    parsed = urlparse(url)
    match = re.search(r"/timetable/sem-(\d)/share", parsed.path)
    if not match:
        raise SystemExit(f"error: not an NUSMods share URL: {url}")
    semester = int(match.group(1))
    selections: dict = {}
    for code, values in parse_qs(parsed.query, keep_blank_values=True).items():
        picks: dict = {}
        for fragment in values[0].split(","):
            if not fragment:
                continue
            if ":" not in fragment:
                raise SystemExit(f"error: cannot parse '{fragment}' in share URL ({code})")
            abbrev, class_no = fragment.split(":", 1)
            picks[abbrev] = class_no
        selections[code.upper()] = picks
    if not selections:
        raise SystemExit("error: share URL contains no modules")
    return semester, selections


def guess_acad_year(today: datetime.date | None = None) -> str:
    today = today or datetime.date.today()
    if today.month >= 6:
        return f"{today.year}-{today.year + 1}"
    return f"{today.year - 1}-{today.year}"


def _prompt_difficulty(code: str, abbrev: str) -> int:
    while True:
        answer = input(f"difficulty for {code} {abbrev} (1-5) [3]: ").strip()
        if not answer:
            return 3
        if answer.isdigit() and 1 <= int(answer) <= 5:
            return int(answer)
        print("please enter a number from 1 to 5")


def cmd_init(args) -> None:
    config_path = Path(args.config)
    if config_path.exists():
        answer = input(f"{config_path} already exists — overwrite? [y/N] ").strip().lower()
        if answer != "y":
            raise SystemExit("aborted")

    semester, selections = parse_share_url(args.share_url)
    acad_year = args.acad_year or guess_acad_year()
    cache_dir = Path(args.cache_dir)

    modules_cfg: dict = {}
    locked: dict = {}
    for code, picks in selections.items():
        data = api.fetch_module(acad_year, code, cache_dir)
        groups = api.build_groups(code, api.semester_timetable(data, semester))
        difficulty: dict = {}
        for group in sorted(groups, key=lambda g: g.lesson_type):
            abbrev = LESSON_ABBREV.get(group.lesson_type, group.lesson_type)
            difficulty[abbrev] = _prompt_difficulty(code, abbrev)
            if abbrev not in DEFAULT_BALLOTED and len(group.choices) > 1:
                if abbrev in picks:
                    # `locked` pins the slot but stays switchable in the TUI
                    locked.setdefault(code, {})[abbrev] = picks[abbrev]
                else:
                    print(
                        f"note: {code} {abbrev} has {len(group.choices)} options and no pick "
                        "in the URL; it will be searched over"
                    )
        modules_cfg[code] = {"difficulty": difficulty}

    default_order = ",".join(selections)
    answer = input(f"priority order, most important first [{default_order}]: ").strip()
    priority = (
        [code.strip().upper() for code in answer.split(",")] if answer else list(selections)
    )
    unknown = [code for code in priority if code not in selections]
    if unknown:
        raise SystemExit(f"error: priority lists unknown module(s): {', '.join(unknown)}")

    config = {
        "acad_year": acad_year,
        "semester": semester,
        "balloted_types": list(DEFAULT_BALLOTED),
        "modules": modules_cfg,
        "fixed": {},
        "locked": locked,
        "priority": priority,
        "preferences": DEFAULT_PREFERENCES,
        "alternatives_per_module": 4,
        "top_n": 5,
        "max_arrangements": 50,
    }
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    print(f"wrote {config_path} — tweak preferences there, then: kairos run")


def cmd_run(args) -> None:
    config = load_config(Path(args.config))
    cache_dir = Path(args.cache_dir)

    groups = []
    for code in config.modules:
        data = api.fetch_module(config.acad_year, code, cache_dir)
        groups.extend(api.build_groups(code, api.semester_timetable(data, config.semester)))
    groups = search.prepare_groups(groups, config)

    space = search.enumerate_clashfree(groups)
    scored = search.score_combos(space, config)
    result = search.rank(space, config, scored=scored)
    if not result.top:
        pair = search.find_irreconcilable(groups)
        if pair:
            first, second = pair
            raise SystemExit(
                "error: no clash-free timetable — every "
                f"{first.module} {first.lesson_type} clashes with every "
                f"{second.module} {second.lesson_type}"
            )
        raise SystemExit("error: no clash-free timetable found")

    structure = search.build_arrangement_structure(space)
    prov = arrangement_provenance(space, config, scored=scored, structure=structure)
    arrangements = search.rank_arrangements(
        space, config, limit=config.top_n, scored=scored, structure=structure
    )

    # Both counts: `evaluated` counts combos, provenance denominators count
    # arrangements. They coincide until collapsing occurs; showing both is what
    # makes the ballot's "of N" self-explaining.
    print(
        f"evaluated {result.evaluated} clash-free timetable shapes "
        f"({prov.total} distinct arrangements)\n"
    )
    for position, arrangement in enumerate(arrangements, 1):
        print(f"=== timetable #{position} ===")
        print(output.render_breakdown(arrangement.score, arrangement.breakdown))
        print(output.render_week(arrangement.assignment))
        print(output.share_url(arrangement.assignment, config.semester))
        print()

    full = ballot.all_options(result, config, provenance=prov)
    print("=== backup choices per balloted group ===")
    print(output.render_options(ballot.ranked_options(result, config, provenance=prov)))
    entries = ballot.snake(ballot.fill_to_cap(full, config), config)
    print(f"\n=== ballot ranking (snake order, cap {ballot.BALLOT_CAP}) ===")
    print(output.render_snake(entries, provenance=prov))
    missing = ballot.shortfall(entries)
    if missing:
        print(
            f"\nwarning: ballot uses only {len(entries)} of {ballot.BALLOT_CAP} slots — "
            "no further clash-free options exist (or your `accept` lists exclude them). "
            "NUS notes a shorter list may mean not "
            "getting a tutorial allocated at all."
        )


def cmd_tui(args) -> None:
    from .tui.startup import build_state

    state = build_state(
        getattr(args, "share_url", None),
        Path(args.config),
        Path(args.cache_dir),
        getattr(args, "acad_year", None),
    )
    if state.is_empty():
        pair = state.irreconcilable()
        if pair:
            first, second = pair
            raise SystemExit(
                "error: no clash-free timetable — every "
                f"{first.module} {first.lesson_type} clashes with every "
                f"{second.module} {second.lesson_type}"
            )
        raise SystemExit("error: no clash-free timetable found")
    run_app(state, Path(args.config))


def _add_common_flags(subparser, dest_prefix: str) -> None:
    # NOTE: argparse's SubParsersAction parses the subcommand with a *fresh*
    # namespace and unconditionally copies every attribute back onto the
    # parent namespace — so a subparser argument sharing a dest with a
    # parent-parser argument would silently clobber a value set *before*
    # the subcommand (e.g. `kairos --config X run` would lose "X" to
    # the subparser's own default). Using distinct dests here and
    # resolving "subcommand value wins if given, else the global one" in
    # main() sidesteps that.
    subparser.add_argument(
        "--config", dest=f"{dest_prefix}_config", default=None, help="path to config.yaml"
    )
    subparser.add_argument(
        "--cache-dir", dest=f"{dest_prefix}_cache_dir", default=None, help="API cache directory"
    )


def main(argv: list | None = None) -> None:
    parser = argparse.ArgumentParser(prog="kairos", description="Kairos — NUS timetable optimiser")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--cache-dir", default="data/cache", help="API cache directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="generate config.yaml from a share URL")
    init_parser.add_argument("share_url", help="NUSMods share URL with your current picks")
    init_parser.add_argument("--acad-year", help="e.g. 2026-2027 (default: guessed from date)")
    _add_common_flags(init_parser, "init")

    run_parser = subparsers.add_parser("run", help="search timetables and print ballot ranking")
    _add_common_flags(run_parser, "run")

    tui_parser = subparsers.add_parser("tui", help="interactive live-tuning app")
    tui_parser.add_argument(
        "share_url", nargs="?", help="NUSMods share URL (optional; else uses config.yaml)"
    )
    tui_parser.add_argument("--acad-year", help="e.g. 2026-2027 (default: guessed from date)")
    _add_common_flags(tui_parser, "tui")

    args = parser.parse_args(argv)
    args.config = getattr(args, f"{args.command}_config", None) or args.config
    args.cache_dir = getattr(args, f"{args.command}_cache_dir", None) or args.cache_dir
    if args.command == "init":
        cmd_init(args)
    elif args.command == "run":
        cmd_run(args)
    else:
        cmd_tui(args)
