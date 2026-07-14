from __future__ import annotations

from dataclasses import dataclass

from .model import LESSON_ABBREV

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
    # rest-of-timetable sets per (module, lesson_type, footprint), used to PROVE
    # two same-slot week-twins are genuinely interchangeable (Fix C). Absent for
    # fake test SearchResults -> such footprints never merge (cluster alone).
    rests = getattr(result, "rests", None) or {}
    options_by_group: dict = {}
    for (module, lesson_type), fp_members in result.members.items():
        if LESSON_ABBREV.get(lesson_type) not in config.balloted_types:
            continue
        # Cluster footprints. Two footprints join iff they share a slot signature
        # (day/time/online) AND have EXACTLY equal rest-of-timetable sets (equal
        # rest-sets => every timetable using one has a valid twin using the other).
        clusters: list = []  # {sig, rest, best, choices}
        for fp, choices in fp_members.items():
            best = result.best_by_footprint.get((module, lesson_type, fp))
            if best is None:
                continue  # never part of any clash-free timetable
            sig = frozenset((s.day, s.start, s.end, s.online) for s in choices[0].sessions)
            rest = rests.get((module, lesson_type, fp))  # may be None
            placed = False
            for cl in clusters:
                if cl["sig"] != sig:
                    continue
                # merge only when BOTH sides have a proven-equal rest-set
                if rest is not None and cl["rest"] is not None and cl["rest"] == rest:
                    cl["best"] = max(cl["best"], best)
                    cl["choices"].extend(choices)
                    placed = True
                    break
            if not placed:
                clusters.append({"sig": sig, "rest": rest, "best": best, "choices": list(choices)})

        # class numbers within a cluster fold in venue-twins (I1 for the ballot);
        # sort by class_no for deterministic letters / ordering (M4)
        scored = []
        for cl in clusters:
            cl_choices = sorted(cl["choices"], key=lambda c: c.class_no)
            scored.append((cl["best"], cl_choices))
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
