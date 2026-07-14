from __future__ import annotations

import argparse
import datetime
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

from . import api
from .config import DEFAULT_BALLOTED, DEFAULT_PREFERENCES
from .model import LESSON_ABBREV


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
    fixed: dict = {}
    for code, picks in selections.items():
        data = api.fetch_module(acad_year, code, cache_dir)
        groups = api.build_groups(code, api.semester_timetable(data, semester))
        difficulty: dict = {}
        for group in sorted(groups, key=lambda g: g.lesson_type):
            abbrev = LESSON_ABBREV.get(group.lesson_type, group.lesson_type)
            difficulty[abbrev] = _prompt_difficulty(code, abbrev)
            if abbrev not in DEFAULT_BALLOTED and len(group.choices) > 1:
                if abbrev in picks:
                    fixed.setdefault(code, {})[abbrev] = picks[abbrev]
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
        "fixed": fixed,
        "priority": priority,
        "preferences": DEFAULT_PREFERENCES,
        "alternatives_per_module": 4,
        "top_n": 5,
    }
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    print(f"wrote {config_path} — tweak preferences there, then: optimiser run")


def cmd_run(args) -> None:
    raise SystemExit("run: not implemented yet")


def main(argv: list | None = None) -> None:
    parser = argparse.ArgumentParser(prog="optimiser", description="NUS timetable optimiser")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--cache-dir", default="data/cache", help="API cache directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="generate config.yaml from a share URL")
    init_parser.add_argument("share_url", help="NUSMods share URL with your current picks")
    init_parser.add_argument("--acad-year", help="e.g. 2026-2027 (default: guessed from date)")

    subparsers.add_parser("run", help="search timetables and print ballot ranking")

    args = parser.parse_args(argv)
    if args.command == "init":
        cmd_init(args)
    else:
        cmd_run(args)
