from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field

from .model import LESSON_ABBREV, ChoiceGroup
from .scoring import score_assignment


@dataclass
class SearchResult:
    top: list
    best_by_footprint: dict
    members: dict
    evaluated: int = 0


def prepare_groups(groups: list, config) -> list:
    prepared = []
    for group in groups:
        abbrev = LESSON_ABBREV.get(group.lesson_type, group.lesson_type)
        fixed_no = (config.fixed.get(group.module) or {}).get(abbrev)
        if fixed_no is not None:
            chosen = [c for c in group.choices if c.class_no == str(fixed_no)]
            if not chosen:
                raise SystemExit(
                    f"error: {group.module} {abbrev} class {fixed_no} (config 'fixed') does not exist"
                )
            prepared.append(ChoiceGroup(group.module, group.lesson_type, chosen))
            continue
        if len(group.choices) > 1 and abbrev not in config.balloted_types:
            print(
                f"warning: {group.module} {abbrev} has {len(group.choices)} options "
                "and no fixed choice; searching over all of them"
            )
        prepared.append(group)
    return prepared


def find_irreconcilable(groups: list):
    for a, b in itertools.combinations(groups, 2):
        if all(ca.clashes(cb) for ca in a.choices for cb in b.choices):
            return a, b
    return None


def search(groups: list, config) -> SearchResult:
    deduped = []  # (group, reps, members)
    for group in groups:
        members: dict = {}
        for c in group.choices:
            members.setdefault(c.footprint, []).append(c)
        reps = [choices[0] for choices in members.values()]
        deduped.append((group, reps, members))
    deduped.sort(key=lambda item: len(item[1]))

    heap: list = []
    best_fp: dict = {}
    chosen: list = []
    state = {"evaluated": 0, "seq": 0}

    def recurse(depth: int) -> None:
        if depth == len(deduped):
            total, breakdown = score_assignment(chosen, config)
            state["evaluated"] += 1
            for c in chosen:
                key = (c.module, c.lesson_type, c.footprint)
                if total > best_fp.get(key, float("-inf")):
                    best_fp[key] = total
            assignment = {(c.module, c.lesson_type): c for c in chosen}
            state["seq"] += 1
            item = (total, state["seq"], breakdown, assignment)
            if len(heap) < config.top_n:
                heapq.heappush(heap, item)
            else:
                heapq.heappushpop(heap, item)
            return
        for choice in deduped[depth][1]:
            if any(choice.clashes(existing) for existing in chosen):
                continue
            chosen.append(choice)
            recurse(depth + 1)
            chosen.pop()

    recurse(0)

    top = [
        (total, breakdown, assignment)
        for total, _, breakdown, assignment in sorted(heap, key=lambda item: -item[0])
    ]
    members_out = {
        (group.module, group.lesson_type): {
            fp: sorted(choices, key=lambda c: c.class_no) for fp, choices in members.items()
        }
        for group, _, members in deduped
    }
    return SearchResult(top, best_fp, members_out, state["evaluated"])
