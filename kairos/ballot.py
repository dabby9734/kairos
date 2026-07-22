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


def all_options(result, config) -> dict:
    """Every viable ballot option per balloted group, best-first, UNCAPPED.

    Letters are assigned positionally over the full list, so any prefix of a
    group's list carries correct letters — which is what lets ranked_options
    and fill_to_cap both slice this without recomputing."""
    # Interchangeability via CLASH-SET equality (cheap + sound). Build the set of
    # viable footprints (those in some clash-free timetable) with a representative
    # choice each, then two same-slot footprints of a group are interchangeable
    # iff they clash with the EXACT same set of viable other-group classes:
    # swapping one for the other in any clash-free timetable introduces no new
    # clash. This is ~O(viable^2) instead of O(combos * groups) rest-sets.
    viable: dict = {}  # (module, lesson_type, footprint) -> representative Choice
    for (module, lesson_type), fp_members in result.members.items():
        for fp, choices in fp_members.items():
            if (module, lesson_type, fp) in result.best_by_footprint:
                viable[(module, lesson_type, fp)] = choices[0]

    clashsets: dict = {}
    for key, rep in viable.items():
        group = (key[0], key[1])
        clashsets[key] = frozenset(
            other_key
            for other_key, other_rep in viable.items()
            if (other_key[0], other_key[1]) != group and other_rep.clashes(rep)
        )

    options_by_group: dict = {}
    for (module, lesson_type), fp_members in result.members.items():
        if LESSON_ABBREV.get(lesson_type) not in config.balloted_types:
            continue
        # Cluster footprints. Two footprints join iff they share a slot signature
        # (day/time/online) AND have EQUAL clash-sets (=> every clash-free
        # timetable using one has a valid twin using the other).
        clusters: list = []  # {sig, clash, best, choices}
        for fp, choices in fp_members.items():
            key = (module, lesson_type, fp)
            if key not in viable:
                continue  # never part of any clash-free timetable
            best = result.best_by_footprint[key]
            sig = choices[0].slot_sig
            clash = clashsets[key]
            placed = False
            for cl in clusters:
                if cl["sig"] == sig and cl["clash"] == clash:
                    cl["best"] = max(cl["best"], best)
                    cl["choices"].extend(choices)
                    placed = True
                    break
            if not placed:
                clusters.append({"sig": sig, "clash": clash, "best": best, "choices": list(choices)})

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


def ranked_options(result, config) -> dict:
    """Per-group options truncated to config.alternatives_per_module.

    This is the "backup choices per balloted group" view. The ballot itself uses
    fill_to_cap, which treats alternatives_per_module as a baseline rather than a
    ceiling.

    Groups whose capped list is empty are excluded from the result dict's keys.
    With a cap <= 0, no groups appear (returns empty dict)."""
    if config.alternatives_per_module <= 0:
        return {}
    return {
        key: opts[: config.alternatives_per_module]
        for key, opts in all_options(result, config).items()
        if opts[: config.alternatives_per_module]
    }


def fill_to_cap(full: dict, config, cap: int = 20) -> dict:
    """Extend the per-group baseline up to `cap` total entries, best score first.

    NUS allows 20 ranked tutorial/lab slots as a GLOBAL budget across all enrolled
    courses, and states that a shorter list "may also mean that a student may not
    be successful in getting a tutorial allocated at all". So an unused slot is a
    free lottery ticket thrown away: start at alternatives_per_module per group,
    then hand each remaining slot to whichever group's next unused option scores
    highest. Ties break on (module, lesson_type, class_no) for determinism.

    Only draws from `full` (the output of all_options), so non-viable footprints
    stay excluded -- every entry is part of some clash-free timetable."""
    picked = {key: opts[: config.alternatives_per_module] for key, opts in full.items()}
    total = sum(len(opts) for opts in picked.values())
    while total < cap:
        candidates = []
        for key, opts in full.items():
            depth = len(picked[key])
            if depth < len(opts):
                option = opts[depth]
                candidates.append(((-option.best_score, key[0], key[1], option.class_no), key, option))
        if not candidates:
            break  # every group exhausted: fewer than `cap` viable options exist
        _, key, option = min(candidates, key=lambda c: c[0])
        picked[key] = picked[key] + [option]
        total += 1
    return picked


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
