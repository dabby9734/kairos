from __future__ import annotations

from dataclasses import dataclass

from .. import ballot
from ..model import DAYS, LESSON_ABBREV, fmt_clock
from ..search import (
    EnumeratedSpace,
    build_arrangement_structure,
    enumerate_clashfree,
    find_irreconcilable,
    prepare_groups,
    rank,
    rank_arrangements,
    score_raw,
    weight_scored,
)
from ..scoring import pairing_impossibility

_PREF_FIELDS = {
    "earliest_start",
    "latest_end",
    "lunch_start",
    "lunch_end",
    "lunch_minutes",
    "max_difficulty_per_day",
}


@dataclass(frozen=True)
class SelectableGroup:
    """A group the user can actually decide between — one row of the Classes pane.

    Deliberately distinct from search.SlotBid: a SlotBid is something you BALLOT
    for and may not be granted, whereas this covers any group offering more than
    one timeslot, including lectures you simply pick. Keeping them separate is
    what stops lectures leaking into the ballot output."""

    module: str
    lesson_type: str      # full name, e.g. "Lecture"
    abbrev: str           # e.g. "LEC"
    balloted: bool
    current_class_no: str
    locked: bool


def normalize_difficulties(config, groups) -> None:
    by_module: dict = {}
    for group in groups:
        abbrev = LESSON_ABBREV.get(group.lesson_type, group.lesson_type)
        by_module.setdefault(group.module, []).append(abbrev)
    for module, abbrevs in by_module.items():
        spec = config.modules.get(module, 3)
        resolved = {}
        for abbrev in abbrevs:
            if isinstance(spec, dict):
                resolved[abbrev] = spec.get(abbrev, 3)
            else:
                resolved[abbrev] = spec
        config.modules[module] = resolved


@dataclass
class AppState:
    config: object
    groups: list                       # prepared (post prepare_groups) groups
    space: EnumeratedSpace
    result: object = None
    arrangements: list = None
    base_groups: list = None           # raw groups, for re-locking rebuilds
    _raw_cache: list = None            # cached score_raw(space); reused by reweight()
    _arr_structure: list = None        # cached build_arrangement_structure(space); space-change only
    _unpairable: tuple = None          # cached pairing_impossibility(space.members); space-change only

    @classmethod
    def from_parts(cls, config, groups) -> "AppState":
        state = cls(
            config=config,
            groups=[],
            space=EnumeratedSpace((), {}),
            base_groups=list(groups),
        )
        state._rebuild()
        return state

    def _prepare_space(self):
        """Prepare groups from the raw base_groups under the current config and
        enumerate the clash-free space WITHOUT committing to self. Callers decide
        whether to keep the result (see _rebuild vs _apply_locked_change), so the
        pipeline lives in one place and can't drift between them.

        normalize_difficulties mutates config.modules in place; that is safe to
        run on a to-be-discarded prepare because prepare_groups only ever narrows
        a group's choices (never adds/removes a (module, abbrev) group), so the
        abbrev set it resolves is invariant and re-normalising is idempotent."""
        prepared = prepare_groups(self.base_groups, self.config)
        normalize_difficulties(self.config, prepared)
        return prepared, enumerate_clashfree(prepared)

    def _rebuild(self):
        self.groups, self.space = self._prepare_space()
        self._arr_structure = build_arrangement_structure(self.space)
        self._refresh_unpairable()
        return self.retune()

    def _refresh_unpairable(self):
        self._unpairable = pairing_impossibility(self.space.members)

    @property
    def unpairable_slots(self) -> frozenset:
        return self._unpairable[1]

    def _rank_from(self, scored):
        # Shared ranking tail: build result.top and the capped arrangement list
        # from an already-scored list. arrangements is capped at
        # config.max_arrangements (keeps the TUI ListView bounded); top_n only
        # sizes result.top (the raw timetable list). The arrangement grouping is
        # reused from the cached _arr_structure (rebuilt only on a space change).
        self.result = rank(self.space, self.config, scored=scored)
        self.arrangements = rank_arrangements(
            self.space, self.config, limit=self.config.max_arrangements,
            scored=scored, structure=self._arr_structure,
        )
        return self.result

    def retune(self):
        # Full path: rebuild the weight-independent raw cache, then rank. Used
        # whenever raw or the combo set may have changed (difficulty, time prefs,
        # locking, initial build).
        self._raw_cache = score_raw(self.space, self.config)
        return self._rank_from(weight_scored(self._raw_cache, self.config))

    def reweight(self):
        # Cheap path: reuse the cached raw entries, apply the current weights, and
        # re-rank. Valid only because raw is weight-independent — used by weight
        # sliders alone. Precondition: retune() has run at least once to populate
        # _raw_cache (from_parts guarantees this before any slider can fire).
        return self._rank_from(weight_scored(self._raw_cache, self.config))

    def is_empty(self) -> bool:
        return not self.space.combos

    def irreconcilable(self):
        return find_irreconcilable(self.groups)

    def set_weight(self, name: str, value):
        self.config.preferences.weights[name] = value
        return self.reweight()

    def set_difficulty(self, module: str, abbrev: str, value: int):
        self.config.modules[module][abbrev] = value
        return self.retune()

    def set_pref(self, name: str, value: int):
        if name not in _PREF_FIELDS:
            raise ValueError(f"unknown preference {name}")
        setattr(self.config.preferences, name, value)
        return self.retune()

    def is_locked(self, module: str, abbrev: str) -> bool:
        return abbrev in (self.config.locked.get(module) or {})

    def _apply_locked_change(self, mutate) -> bool:
        """Mutate config.locked, rebuild the space, and commit only if the
        result is non-empty; otherwise roll everything back and return False."""
        snapshot = (
            {m: dict(v) for m, v in self.config.locked.items()},
            self.groups, self.space, self.result, self.arrangements,
            self._raw_cache, self._arr_structure, self._unpairable,
        )
        mutate()
        prepared, space = self._prepare_space()
        if not space.combos:
            (self.config.locked, self.groups, self.space,
             self.result, self.arrangements,
             self._raw_cache, self._arr_structure, self._unpairable) = snapshot
            return False
        self.groups = prepared
        self.space = space
        self._arr_structure = build_arrangement_structure(space)
        self._refresh_unpairable()
        self.retune()
        return True

    def set_lock(self, module: str, abbrev: str, class_no: str) -> bool:
        def mutate():
            self.config.locked.setdefault(module, {})[abbrev] = str(class_no)
        return self._apply_locked_change(mutate)

    def clear_lock(self, module: str, abbrev: str) -> bool:
        def mutate():
            slots = self.config.locked.get(module)
            if slots:
                slots.pop(abbrev, None)
                if not slots:
                    self.config.locked.pop(module, None)
        return self._apply_locked_change(mutate)

    def _base_group(self, module, lesson_type):
        return next(
            (g for g in self.base_groups
             if g.module == module and g.lesson_type == lesson_type),
            None,
        )

    def offered_timeslots(self, module, lesson_type) -> list:
        """Distinct offered timeslots for a class, from the FULL offered set
        (base_groups, so a current lock does not narrow it). One dict per distinct
        slot_sig, sorted by (day, start): sig, class_nos (sorted), sessions (a
        representative choice's sessions), rep (representative class number),
        venues (sorted distinct venues across every class in the row — slot_sig
        deliberately ignores venue, so classes differing only by venue collapse
        into one row and all of their venues must be shown)."""
        group = self._base_group(module, lesson_type)
        if group is None:
            return []
        by_sig: dict = {}
        for choice in group.choices:
            by_sig.setdefault(choice.slot_sig, []).append(choice)
        rows = []
        for sig, choices in by_sig.items():
            choices = sorted(choices, key=lambda c: c.class_no)
            rows.append({
                "sig": sig,
                "class_nos": [c.class_no for c in choices],
                "sessions": choices[0].sessions,
                "rep": choices[0].class_no,
                "venues": sorted({s.venue for c in choices for s in c.sessions}),
            })
        rows.sort(key=lambda r: (DAYS.index(r["sessions"][0].day), r["sessions"][0].start))
        return rows

    def selectable_groups(self, assignment: dict) -> list[SelectableGroup]:
        """Rows for the Classes pane: every offered group with more than one
        distinct timeslot, balloted or not — except groups pinned by `fixed`,
        which offer nothing to decide (see the comment on that filter below).

        Slot counting uses base_groups (the FULL offered set) rather than the
        prepared groups, for the same reason offered_timeslots does — a locked
        group is narrowed to a single slot in the prepared set, so counting there
        would make the row disappear the moment the user locked it."""
        rows = []
        for group in self.base_groups:
            if len({c.slot_sig for c in group.choices}) < 2:
                continue
            abbrev = LESSON_ABBREV.get(group.lesson_type, group.lesson_type)
            # prepare_groups (search.py) applies `fixed` first and short-circuits
            # before ever reading `locked`. A group pinned by `fixed` would still
            # render here (it can still offer >1 slot_sig) and pressing `l` would
            # write a `locked` entry that prepare_groups silently ignores — the
            # row would show locked but the timetable would not move. Excluding
            # it matches the pane's model: no row when there is nothing to decide.
            if abbrev in (self.config.fixed.get(group.module) or {}):
                continue
            choice = assignment.get((group.module, group.lesson_type))
            rows.append(SelectableGroup(
                module=group.module,
                lesson_type=group.lesson_type,
                abbrev=abbrev,
                balloted=abbrev in self.config.balloted_types,
                current_class_no=choice.class_no if choice else "",
                locked=self.is_locked(group.module, abbrev),
            ))
        rows.sort(key=lambda r: (r.module, r.lesson_type))
        return rows

    def locked_sig(self, module, lesson_type):
        """The slot_sig this class is currently locked to, or None."""
        abbrev = LESSON_ABBREV.get(lesson_type, lesson_type)
        class_no = (self.config.locked.get(module) or {}).get(abbrev)
        if class_no is None:
            return None
        group = self._base_group(module, lesson_type)
        if group is None:
            return None
        choice = next((c for c in group.choices if c.class_no == str(class_no)), None)
        return choice.slot_sig if choice else None

    def move_priority(self, module: str, delta: int) -> None:
        order = self.config.priority
        if module not in order:
            return
        i = order.index(module)
        j = max(0, min(len(order) - 1, i + delta))
        if i != j:
            order.insert(j, order.pop(i))

    def top_timetables(self) -> list:
        return self.result.top

    def top_arrangements(self) -> list:
        return self.arrangements

    def ballot_options(self) -> dict:
        return ballot.ranked_options(self.result, self.config)

    def ballot_snake(self) -> list:
        full = ballot.all_options(self.result, self.config)
        return ballot.snake(ballot.fill_to_cap(full, self.config), self.config)

    def to_config_yaml(self) -> dict:
        prefs = self.config.preferences
        return {
            "acad_year": self.config.acad_year,
            "semester": self.config.semester,
            "balloted_types": list(self.config.balloted_types),
            "modules": {
                code: {"difficulty": spec}
                for code, spec in self.config.modules.items()
            },
            "fixed": self.config.fixed,
            "locked": self.config.locked,
            "priority": list(self.config.priority),
            "preferences": {
                "earliest_start": fmt_clock(prefs.earliest_start),
                "latest_end": fmt_clock(prefs.latest_end),
                "max_difficulty_per_day": prefs.max_difficulty_per_day,
                "lunch_window": [fmt_clock(prefs.lunch_start), fmt_clock(prefs.lunch_end)],
                "lunch_minutes": prefs.lunch_minutes,
                "weights": dict(prefs.weights),
            },
            "alternatives_per_module": self.config.alternatives_per_module,
            "top_n": self.config.top_n,
            "max_arrangements": self.config.max_arrangements,
        }
