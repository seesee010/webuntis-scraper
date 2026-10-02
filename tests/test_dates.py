"""Tests for the date shortcut helpers."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from src.dates import parse_date, pick_school_day, trim_timetable, week_range

FRI = date(2026, 10, 2)


@pytest.mark.parametrize("text, expected", [
    ("2026-10-12", date(2026, 10, 12)),
    ("12.10.2026", date(2026, 10, 12)),
    ("12.10.", date(2026, 10, 12)),
    ("12.10", date(2026, 10, 12)),
    ("5.1.", date(2027, 1, 5)),          # closest year: next January
])
def test_parse_date(text, expected):
    assert parse_date(text, FRI) == expected


def test_parse_date_without_year_prefers_closest_past():
    assert parse_date("20.12.", date(2027, 1, 10)) == date(2026, 12, 20)


@pytest.mark.parametrize("text", ["31.02.", "tomorrow", "2026-13-01", "1.2.3"])
def test_parse_date_rejects(text):
    with pytest.raises(ValueError):
        parse_date(text, FRI)


def test_week_range():
    assert week_range(FRI) == (date(2026, 9, 28), date(2026, 10, 4))
    assert week_range(FRI, 1) == (date(2026, 10, 5), date(2026, 10, 11))
    sunday = date(2026, 10, 4)
    assert week_range(sunday)[0] == date(2026, 9, 28)


def _tt(days: dict[str, list[tuple[str, str, dict]]]) -> dict:
    return {"days": [
        {"date": d, "entries": [
            {"start": f"{d}T{s}", "end": f"{d}T{e}", **flags} for s, e, flags in entries
        ]} for d, entries in days.items()
    ]}


TT = _tt({
    "2026-10-02": [("07:50", "13:25", {})],                          # Fri
    "2026-10-03": [],                                                # Sat
    "2026-10-05": [("07:50", "08:40", {"is_cancelled": True})],      # all cancelled
    "2026-10-06": [("07:50", "09:35", {"is_removed": True}),
                   ("09:40", "10:30", {})],                          # one real lesson
})


def test_pick_skips_weekends_and_fully_cancelled_days():
    assert pick_school_day(TT, date(2026, 10, 3)) == date(2026, 10, 6)


def test_pick_next_today_while_school_runs():
    assert pick_school_day(TT, FRI, datetime(2026, 10, 2, 10, 0)) == FRI


def test_pick_next_after_school_is_over():
    assert pick_school_day(TT, FRI, datetime(2026, 10, 2, 13, 30)) == date(2026, 10, 6)


def test_pick_nothing_found():
    assert pick_school_day(TT, date(2026, 10, 7)) is None


def test_trim_timetable():
    tt = dict(TT, raw={"days": [{"date": "2026-10-02"}, {"date": "2026-10-06"}]})
    out = trim_timetable(tt, date(2026, 10, 6), date(2026, 10, 6))
    assert [d["date"] for d in out["days"]] == ["2026-10-06"]
    assert [d["date"] for d in out["raw"]["days"]] == ["2026-10-06"]
    assert out["start"] == out["end"] == "2026-10-06"
    assert len(TT["days"]) == 4                 # original untouched
