from __future__ import annotations

from dataclasses import dataclass, field

from .. import ballot
from ..model import LESSON_ABBREV
from ..search import (
    EnumeratedSpace,
    enumerate_clashfree,
    find_irreconcilable,
    prepare_groups,
    rank,
)

_PREF_FIELDS = {
    "earliest_start",
    "latest_end",
    "lunch_start",
    "lunch_end",
    "lunch_minutes",
    "max_difficulty_per_day",
}


def _fmt_clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


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
    groups: list
    space: EnumeratedSpace
    result: object = None

    @classmethod
    def from_parts(cls, config, groups) -> "AppState":
        prepared = prepare_groups(groups, config)
        normalize_difficulties(config, prepared)
        space = enumerate_clashfree(prepared)
        state = cls(config=config, groups=prepared, space=space)
        state.retune()
        return state

    def retune(self):
        self.result = rank(self.space, self.config)
        return self.result

    def is_empty(self) -> bool:
        return not self.space.combos

    def irreconcilable(self):
        return find_irreconcilable(self.groups)

    def set_weight(self, name: str, value):
        self.config.preferences.weights[name] = value
        return self.retune()

    def set_difficulty(self, module: str, abbrev: str, value: int):
        self.config.modules[module][abbrev] = value
        return self.retune()

    def set_pref(self, name: str, value: int):
        if name not in _PREF_FIELDS:
            raise ValueError(f"unknown preference {name}")
        setattr(self.config.preferences, name, value)
        return self.retune()

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

    def ballot_options(self) -> dict:
        return ballot.ranked_options(self.result, self.config)

    def ballot_snake(self) -> list:
        return ballot.snake(self.ballot_options(), self.config)

    def to_config_yaml(self) -> dict:
        prefs = self.config.preferences
        return {
            "acad_year": self.config.acad_year,
            "semester": self.config.semester,
            "balloted_types": list(self.config.balloted_types),
            "modules": {
                code: {"difficulty": spec if isinstance(spec, dict) else spec}
                for code, spec in self.config.modules.items()
            },
            "fixed": self.config.fixed,
            "priority": list(self.config.priority),
            "preferences": {
                "earliest_start": _fmt_clock(prefs.earliest_start),
                "latest_end": _fmt_clock(prefs.latest_end),
                "max_difficulty_per_day": prefs.max_difficulty_per_day,
                "lunch_window": [_fmt_clock(prefs.lunch_start), _fmt_clock(prefs.lunch_end)],
                "lunch_minutes": prefs.lunch_minutes,
                "weights": dict(prefs.weights),
            },
            "alternatives_per_module": self.config.alternatives_per_module,
            "top_n": self.config.top_n,
        }
