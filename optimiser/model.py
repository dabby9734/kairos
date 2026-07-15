from __future__ import annotations

from dataclasses import dataclass

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

LESSON_ABBREV = {
    "Lecture": "LEC",
    "Tutorial": "TUT",
    "Recitation": "REC",
    "Laboratory": "LAB",
    "Sectional Teaching": "SEC",
    "Workshop": "WS",
    "Seminar-Style Module Class": "SEM",
    "Packaged Lecture": "PLEC",
    "Packaged Tutorial": "PTUT",
    "Design Lecture": "DLEC",
    "Tutorial Type 2": "TUT2",
}
LESSON_FULL = {ab: full for full, ab in LESSON_ABBREV.items()}


def parse_time(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[2:])


def parse_clock(hh_mm: str) -> int:
    hours, minutes = hh_mm.split(":")
    return int(hours) * 60 + int(minutes)


def fmt_time(minutes: int) -> str:
    return f"{minutes // 60:02d}{minutes % 60:02d}"


def week_label(weeks) -> str:
    """Short human label for a session's teaching weeks: '' for the full 13-week
    run (or empty), 'even wks'/'odd wks' for pure even/odd sets, else a compact
    'wks 2,4,6'."""
    weeks = frozenset(weeks)
    if not weeks or weeks == frozenset(range(1, 14)):
        return ""
    ordered = sorted(weeks)
    if all(w % 2 == 0 for w in ordered):
        return "even wks"
    if all(w % 2 == 1 for w in ordered):
        return "odd wks"
    return "wks " + ",".join(str(w) for w in ordered)


@dataclass(frozen=True)
class Session:
    day: str
    start: int
    end: int
    weeks: frozenset
    venue: str

    @property
    def online(self) -> bool:
        return self.venue.startswith("E-Learn")

    def clashes(self, other: "Session") -> bool:
        return (
            self.day == other.day
            and self.start < other.end
            and other.start < self.end
            and bool(self.weeks & other.weeks)
        )


@dataclass(frozen=True)
class Choice:
    module: str
    lesson_type: str  # full name, e.g. "Tutorial"
    class_no: str
    sessions: tuple

    @property
    def footprint(self) -> frozenset:
        return frozenset((s.day, s.start, s.end, s.weeks, s.online) for s in self.sessions)

    def clashes(self, other: "Choice") -> bool:
        return any(a.clashes(b) for a in self.sessions for b in other.sessions)


@dataclass
class ChoiceGroup:
    module: str
    lesson_type: str
    choices: list

    @property
    def key(self) -> tuple:
        return (self.module, self.lesson_type)
