from __future__ import annotations

from dataclasses import dataclass
from statistics import median as _median

from .search import build_arrangement_structure, candidates_from_structure, score_combos

TOLERANCE = 1e-9


@dataclass(frozen=True)
class ClusterStats:
    """Quality of the arrangements containing one interchangeable cluster.

    `ceiling` is the best score attainable with this cluster; `median` is the
    typical outcome. Ceiling alone is a poor ranking signal because ties
    dominate, and raw `support` is anti-correlated with quality -- see the
    design doc's "What the data showed"."""

    ceiling: float
    median: float
    support: int
    ceiling_tier: int
    median_tier: int


@dataclass(frozen=True)
class Provenance:
    total: int
    scores: tuple            # per arrangement index, descending
    distinct: tuple          # distinct scores, descending; tier == index + 1
    by_arrangement: tuple    # index -> frozenset of (module, lesson_type, class_no)
    by_class: dict           # (module, lesson_type, class_no) -> tuple of indices

    @property
    def tiers(self) -> int:
        return len(self.distinct)

    def tier_of(self, score: float) -> int:
        """1-based tier of `score` among distinct arrangement scores.

        A score between two observed values (a median can be) takes the tier of
        the best distinct score <= it, so an interpolated value never claims a
        better tier than any arrangement actually achieved."""
        for index, value in enumerate(self.distinct):
            if value <= score + TOLERANCE:
                return index + 1
        return len(self.distinct)

    def cluster_stats(self, keys) -> ClusterStats | None:
        """Stats over every arrangement containing ANY of `keys`.

        Callers pass a whole interchangeable cluster, because twins are
        substitutable by construction -- a timetable using one has a valid twin
        using another. Returns None when no arrangement contains any of them
        (a class that is never part of a clash-free timetable)."""
        indices = set()
        for key in keys:
            indices.update(self.by_class.get(key, ()))
        if not indices:
            return None
        values = [self.scores[index] for index in indices]
        ceiling = max(values)
        middle = _median(values)
        return ClusterStats(
            ceiling=ceiling,
            median=middle,
            support=len(values),
            ceiling_tier=self.tier_of(ceiling),
            median_tier=self.tier_of(middle),
        )


def arrangement_provenance(space, config, scored=None, structure=None) -> Provenance:
    """Which classes each clash-free arrangement contains, and how good it is.

    Built from candidates_from_structure rather than rank_arrangements: the
    expensive part of rank_arrangements is _make_arrangement's bid construction
    and venue expansion, none of which is needed here.

    ALWAYS covers every arrangement. Do not reuse AppState.arrangements, which
    is capped at config.max_arrangements to bound the TUI's ListView -- feeding
    that in would make the TUI's denominators disagree with the CLI's."""
    if scored is None:
        scored = score_combos(space, config)
    if structure is None:
        structure = build_arrangement_structure(space)

    candidates = candidates_from_structure(structure, scored)
    # Must match rank_arrangements' ordering exactly: TUI highlighting indexes
    # by_arrangement with a selection made against rank_arrangements(limit=...).
    candidates.sort(key=lambda candidate: -candidate[0])

    scores = []
    by_arrangement = []
    by_class: dict = {}
    for index, (score, _entry, slot_opts, _variants) in enumerate(candidates):
        keys = set()
        for (module, lesson_type), by_footprint in slot_opts.items():
            members = space.members.get((module, lesson_type), {})
            for footprint in by_footprint:
                for sibling in members.get(footprint, []):
                    keys.add((module, lesson_type, sibling.class_no))
        frozen = frozenset(keys)
        scores.append(score)
        by_arrangement.append(frozen)
        for key in frozen:
            by_class.setdefault(key, []).append(index)

    distinct: list = []
    for score in scores:
        if not distinct or abs(score - distinct[-1]) > TOLERANCE:
            distinct.append(score)

    return Provenance(
        total=len(scores),
        scores=tuple(scores),
        distinct=tuple(distinct),
        by_arrangement=tuple(by_arrangement),
        by_class={key: tuple(indices) for key, indices in by_class.items()},
    )
