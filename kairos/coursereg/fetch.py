from __future__ import annotations

import json
import re
from dataclasses import asdict
from html.parser import HTMLParser
from pathlib import Path

import requests

from .model import UNLIMITED, DemandRecord

# First "x / y" in a round cell; the trailing "(z)" span (Vacancy-PDF figure)
# is deliberately not captured.
_CELL_RE = re.compile(r"(\d+|∞)\s*/\s*(\d+|∞)")
_ROUND_RE = re.compile(r"Round\s+(\d)")


class _TableParser(HTMLParser):
    """Collects the round numbers from <th class='table-round'> headers and the
    raw text of every <td> per <tbody> row of table#table-data."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_table = False
        self.in_round_th = False
        self.in_td = False
        self.rounds: list[int] = []
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table" and attrs.get("id") == "table-data":
            self.in_table = True
        elif self.in_table and tag == "th" and "table-round" in (attrs.get("class") or ""):
            self.in_round_th = True
            self._text = []
        elif self.in_table and tag == "tr":
            self._row = []
        elif self.in_table and tag == "td":
            self.in_td = True
            self._text = []

    def handle_endtag(self, tag):
        if tag == "table":
            self.in_table = False
        elif tag == "th" and self.in_round_th:
            self.in_round_th = False
            match = _ROUND_RE.search(" ".join(self._text))
            if match:
                self.rounds.append(int(match.group(1)))
        elif tag == "td" and self.in_td:
            self.in_td = False
            if self._row is not None:
                self._row.append(" ".join(self._text))
        elif tag == "tr" and self._row:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self.in_round_th or self.in_td:
            self._text.append(data.strip())


def _cell_values(text: str) -> tuple[int | None, int | None]:
    match = _CELL_RE.search(text)
    if not match:  # N/A or empty
        return None, None
    demand_raw, vacancy_raw = match.groups()
    # A literal ∞ demand does not occur in the data; treat it as missing.
    demand = None if demand_raw == "∞" else int(demand_raw)
    vacancy = UNLIMITED if vacancy_raw == "∞" else int(vacancy_raw)
    return demand, vacancy


def parse_history_html(html: str, acad_year: str, semester: int) -> list[DemandRecord]:
    parser = _TableParser()
    parser.feed(html)
    if not parser.rounds or not parser.rows:
        raise SystemExit(
            "error: courserekt page has no recognisable history table — "
            "the site may have changed; try --refetch"
        )
    # (course, round) -> [demand_sum, vacancy_sum, any_unlimited, any_numeric]
    merged: dict = {}
    for row in parser.rows:
        if len(row) < 3 + len(parser.rounds):
            continue  # defensive: malformed row
        course = row[0].strip().upper()
        for offset, rnd in enumerate(parser.rounds):
            demand, vacancy = _cell_values(row[3 + offset])
            if demand is None and vacancy is None:
                continue  # N/A cell: skipped, never imputed
            slot = merged.setdefault((course, rnd), [0, 0, False, False])
            slot[3] = True
            if demand is not None:
                slot[0] += demand
            if vacancy == UNLIMITED:
                slot[2] = True
            elif vacancy is not None:
                slot[1] += vacancy
    records = [
        DemandRecord(
            course=course,
            acad_year=acad_year,
            semester=semester,
            round=rnd,
            demand=demand_sum,
            vacancy=UNLIMITED if any_unlimited else vacancy_sum,
        )
        for (course, rnd), (demand_sum, vacancy_sum, any_unlimited, has_data) in merged.items()
        if has_data
    ]
    # Deterministic output order: course code, then round.
    return sorted(records, key=lambda r: (r.course, r.round))


COURSEREKT_URL = "https://courserekt.vercel.app/"
YEARS = ("2122", "2223", "2324", "2425", "2526")


def fetch_semester(acad_year: str, semester: int) -> str:
    resp = requests.post(
        COURSEREKT_URL,
        data={"year": acad_year, "semester": str(semester), "type": "ug"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.text


def load_history(cache_dir: Path, refetch: bool = False) -> list[DemandRecord]:
    """All UG demand records across every archived semester. Cache-first with
    NO TTL: the upstream project is archived and its data frozen, so a cache
    hit is always valid. `refetch` exists only as a repair hatch."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    records: list[DemandRecord] = []
    for acad_year in YEARS:
        for semester in (1, 2):
            cache_file = cache_dir / f"{acad_year}-{semester}.json"
            if cache_file.exists() and not refetch:
                try:
                    rows = json.loads(cache_file.read_text())
                except json.JSONDecodeError:
                    raise SystemExit(
                        f"error: cache file {cache_file} is corrupt — "
                        "re-run with --refetch to rebuild it"
                    )
                records.extend(DemandRecord(**row) for row in rows)
                continue
            try:
                html = fetch_semester(acad_year, semester)
            except requests.RequestException as exc:
                raise SystemExit(
                    f"error: courserekt.vercel.app unreachable and no cached data in "
                    f"{cache_dir} — copy a friend's cache there (the data is frozen "
                    f"and identical for everyone): {exc}"
                )
            parsed = parse_history_html(html, acad_year, semester)
            cache_file.write_text(json.dumps([asdict(r) for r in parsed]))
            records.extend(parsed)
    return records
