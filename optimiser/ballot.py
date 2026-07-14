from __future__ import annotations

from dataclasses import dataclass

from .model import LESSON_ABBREV, week_label

BALLOT_TYPE_ORDER = ["Tutorial", "Sectional Teaching", "Recitation", "Laboratory"]


@dataclass
class BallotOption:
    module: str
    lesson_type: str
    class_no: str
    letter: str
    best_score: float
    sessions: tuple
    tied_with: list


def ranked_options(result, config) -> dict:
    options_by_group: dict = {}
    for (module, lesson_type), fp_members in result.members.items():
        if LESSON_ABBREV.get(lesson_type) not in config.balloted_types:
            continue
        # Merge footprints that share a slot signature (day/time/online), so
        # same-slot week-twins are interchangeable in the ballot too.
        by_slot: dict = {}
        for fp, choices in fp_members.items():
            best = result.best_by_footprint.get((module, lesson_type, fp))
            if best is None:
                continue  # never part of any clash-free timetable
            sig = frozenset((s.day, s.start, s.end, s.online) for s in choices[0].sessions)
            slot = by_slot.setdefault(sig, {"best": best, "choices": []})
            slot["best"] = max(slot["best"], best)
            slot["choices"].extend(choices)
        scored = [(slot["best"], slot["choices"]) for slot in by_slot.values()]
        scored.sort(key=lambda item: (-item[0], item[1][0].class_no))

        options = []
        for best, choices in scored:
            class_nos = [c.class_no for c in choices]
            for c in choices:
                if len(options) >= config.alternatives_per_module:
                    break
                options.append(
                    BallotOption(
                        module=module,
                        lesson_type=lesson_type,
                        class_no=c.class_no,
                        letter=chr(ord("A") + len(options)),
                        best_score=best,
                        sessions=c.sessions,
                        tied_with=[n for n in class_nos if n != c.class_no],
                    )
                )
        if options:
            options_by_group[(module, lesson_type)] = options
    return options_by_group


def snake(options_by_group: dict, config, cap: int = 20) -> list:
    def column_key(key):
        module, lesson_type = key
        module_rank = (
            config.priority.index(module) if module in config.priority else len(config.priority)
        )
        type_rank = (
            BALLOT_TYPE_ORDER.index(lesson_type)
            if lesson_type in BALLOT_TYPE_ORDER
            else len(BALLOT_TYPE_ORDER)
        )
        return (module_rank, type_rank)

    columns = [options_by_group[key] for key in sorted(options_by_group, key=column_key)]
    entries = []
    depth = max((len(col) for col in columns), default=0)
    for round_no in range(depth):
        row = [col[round_no] for col in columns if len(col) > round_no]
        if round_no % 2 == 1:
            row.reverse()
        entries.extend(row)
    return entries[:cap]
