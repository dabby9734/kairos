from __future__ import annotations

from ..advisor import dossier_rows, leverage_warnings, suggested_order, verdict
from ..model import RANK_CAP, TIERS, Profile, profile_to_yaml


class AdvisorState:
    """Mutable session object behind the advisor TUI. Pure-python (no Textual
    imports) so every interaction is testable without a terminal — mirrors the
    timetable TUI's AppState/App split."""

    def __init__(self, profile: Profile, records: list):
        self.profile = profile
        self.records = records
        self.verdicts: dict = {}
        self.suggested: list = []
        self.recompute()
        # A fresh config opens in the advisor's suggested order; a config the
        # TUI has saved (ranked: true) keeps the user's own order.
        self.order = list(profile.order) if profile.ranked else list(self.suggested)

    def recompute(self) -> None:
        self.verdicts = {
            course: verdict(self.records, course, self.profile)
            for course in self.profile.tiers
        }
        standings = {course: v.standing for course, v in self.verdicts.items()}
        self.suggested = suggested_order(standings)

    def rows(self) -> list:
        return [
            (
                position if position <= RANK_CAP else None,
                course,
                self.verdicts[course].standing,
                self.profile.tiers[course],
            )
            for position, course in enumerate(self.order, 1)
        ]

    def move(self, index: int, delta: int) -> int:
        target = index + delta
        if not (0 <= index < len(self.order)) or not (0 <= target < len(self.order)):
            return index
        self.order[index], self.order[target] = self.order[target], self.order[index]
        return target

    def cycle_tier(self, course: str) -> None:
        current = TIERS.index(self.profile.tiers[course])
        self.profile.tiers[course] = TIERS[(current + 1) % len(TIERS)]
        self.recompute()

    def toggle_round(self) -> None:
        self.profile.round = 5 - self.profile.round  # 2 <-> 3
        self.recompute()

    def restore_suggested(self) -> None:
        self.order = list(self.suggested)

    def warnings(self) -> list:
        standings = {course: v.standing for course, v in self.verdicts.items()}
        return leverage_warnings(self.order, standings)

    def dossier(self, course: str) -> tuple:
        return dossier_rows(
            self.records, course, self.profile.round, self.profile.semester
        )

    def to_yaml(self) -> str:
        self.profile.order = list(self.order)
        self.profile.ranked = True
        return profile_to_yaml(self.profile)
