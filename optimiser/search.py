from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass

from .model import LESSON_ABBREV, ChoiceGroup, week_label
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


@dataclass(frozen=True)
class EnumeratedSpace:
    combos: tuple
    members: dict

    def evaluated_count(self) -> int:
        return len(self.combos)


def enumerate_clashfree(groups: list) -> EnumeratedSpace:
    deduped = []  # (group, reps, members)
    for group in groups:
        members: dict = {}
        for c in group.choices:
            members.setdefault(c.footprint, []).append(c)
        reps = [choices[0] for choices in members.values()]
        deduped.append((group, reps, members))
    deduped.sort(key=lambda item: len(item[1]))

    combos: list = []
    chosen: list = []

    def recurse(depth: int) -> None:
        if depth == len(deduped):
            combos.append(tuple(chosen))
            return
        for choice in deduped[depth][1]:
            if any(choice.clashes(existing) for existing in chosen):
                continue
            chosen.append(choice)
            recurse(depth + 1)
            chosen.pop()

    recurse(0)

    members_out = {
        (group.module, group.lesson_type): {
            fp: sorted(choices, key=lambda c: c.class_no) for fp, choices in members.items()
        }
        for group, _, members in deduped
    }
    return EnumeratedSpace(tuple(combos), members_out)


def rank(space: EnumeratedSpace, config) -> SearchResult:
    heap: list = []
    best_fp: dict = {}
    seq = 0
    for combo in space.combos:
        total, breakdown = score_assignment(list(combo), config)
        for c in combo:
            key = (c.module, c.lesson_type, c.footprint)
            if total > best_fp.get(key, float("-inf")):
                best_fp[key] = total
        assignment = {(c.module, c.lesson_type): c for c in combo}
        seq += 1
        item = (total, seq, breakdown, assignment)
        if len(heap) < config.top_n:
            heapq.heappush(heap, item)
        else:
            heapq.heappushpop(heap, item)

    top = [
        (total, breakdown, assignment)
        for total, _, breakdown, assignment in sorted(heap, key=lambda item: -item[0])
    ]
    return SearchResult(top, best_fp, space.members, len(space.combos))


@dataclass(frozen=True)
class SlotBid:
    module: str
    lesson_type: str
    options: tuple  # ((class_no, week_label), ...), interchangeable twins at this slot


@dataclass
class Arrangement:
    score: float
    breakdown: dict
    assignment: dict       # representative (best variant) {(module, lesson_type): Choice}
    bids: list             # list[SlotBid], balloted slots only, sorted by (module, lesson_type)
    variant_count: int


def _arrangement_key(combo) -> frozenset:
    # Slot layout, ignoring class number AND weeks: two combos share a key iff
    # they occupy the same (module, type, day, start, end, online) slots.
    return frozenset(
        (c.module, c.lesson_type, s.day, s.start, s.end, s.online)
        for c in combo
        for s in c.sessions
    )


def _make_arrangement(entry, slot_opts, config, variant_count) -> "Arrangement":
    total, breakdown, assignment, _combo = entry
    bids = []
    for (module, lesson_type), by_no in slot_opts.items():
        if LESSON_ABBREV.get(lesson_type, lesson_type) not in config.balloted_types:
            continue
        options = tuple(
            (class_no, week_label(weeks)) for class_no, weeks in sorted(by_no.items())
        )
        bids.append(SlotBid(module, lesson_type, options))
    bids.sort(key=lambda b: (b.module, b.lesson_type))
    return Arrangement(
        score=total, breakdown=breakdown, assignment=assignment,
        bids=bids, variant_count=variant_count,
    )


def rank_arrangements(space, config, limit=None) -> list:
    """Collapse clash-free timetables that share a slot layout (differing only by
    interchangeable same-slot week-twins) into ranked Arrangements. Twins are
    offered as free per-slot bids only when the group's clash-free combos form a
    full Cartesian product; otherwise the combos are kept as separate
    arrangements (soundness — see design doc)."""
    scored = []  # (total, breakdown, assignment, combo)
    for combo in space.combos:
        total, breakdown = score_assignment(list(combo), config)
        assignment = {(c.module, c.lesson_type): c for c in combo}
        scored.append((total, breakdown, assignment, combo))

    groups: dict = {}
    for entry in scored:
        groups.setdefault(_arrangement_key(entry[3]), []).append(entry)

    arrangements = []
    for entries in groups.values():
        slot_opts: dict = {}  # (module, lesson_type) -> {class_no: weeks}
        for _t, _b, _a, combo in entries:
            for c in combo:
                slot_opts.setdefault((c.module, c.lesson_type), {})[c.class_no] = c.sessions[0].weeks
        product = 1
        for by_no in slot_opts.values():
            product *= len(by_no)
        if product == len(entries):  # independent -> collapse
            best = min(entries, key=lambda e: (-e[0], tuple(sorted(c.class_no for c in e[3]))))
            arrangements.append(_make_arrangement(best, slot_opts, config, len(entries)))
        else:  # entangled -> keep each combo as its own arrangement
            for entry in entries:
                single = {
                    (c.module, c.lesson_type): {c.class_no: c.sessions[0].weeks}
                    for c in entry[3]
                }
                arrangements.append(_make_arrangement(entry, single, config, 1))

    arrangements.sort(key=lambda a: -a.score)
    return arrangements[:limit] if limit else arrangements


def search(groups: list, config) -> SearchResult:
    return rank(enumerate_clashfree(groups), config)
