"""Tests for the date shortcut helpers."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from untis.dates import parse_date, pick_school_day, trim_timetable, week_range

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


# --- school-day counting (#42) --------------------------------------------
from untis.dates import merge_timetables, school_day_span, school_days  # noqa: E402


def test_school_days_skips_empty_cancelled_and_removed_days():
    assert school_days(TT) == [date(2026, 10, 2), date(2026, 10, 6)]


def test_school_days_from_jsonrpc_lessons():
    tt = {"lessons": [
        {"date": "2026-10-06", "start_time": "07:50", "end_time": "08:40"},
        {"date": "2026-10-05", "start_time": "07:50", "end_time": "08:40",
         "is_cancelled": True},
    ]}
    assert school_days(tt) == [date(2026, 10, 6)]


def test_school_days_empty():
    assert school_days({}) == []


@pytest.mark.parametrize("n, span", [(-1, 0), (0, 0), (1, 5), (4, 8), (5, 9), (10, 16)])
def test_school_day_span(n, span):
    assert school_day_span(n) == span


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6, 10, 14])
@pytest.mark.parametrize("weekday", range(7))
def test_school_day_span_covers_n_weekdays_from_any_day(n, weekday):
    """Without holidays, the first guess always contains n school days."""
    today = date(2026, 10, 5) + timedelta(days=weekday)      # Mon..Sun
    span = school_day_span(n)
    days = [today + timedelta(days=i) for i in range(1, span + 1)]
    assert len([d for d in days if d.weekday() < 5]) >= n


def test_merge_timetables():
    a = {"start": "2026-10-01", "end": "2026-10-04", "days": [{"date": "2026-10-02"}],
         "raw": {"days": [{"date": "2026-10-02"}]}, "own_classes": ["CLASS-A"]}
    b = {"start": "2026-10-05", "end": "2026-10-11", "days": [{"date": "2026-10-05"}],
         "raw": {"days": [{"date": "2026-10-05"}]}}
    out = merge_timetables(b, a)                     # order doesn't matter
    assert [d["date"] for d in out["days"]] == ["2026-10-02", "2026-10-05"]
    assert (out["start"], out["end"]) == ("2026-10-01", "2026-10-11")
    assert len(out["raw"]["days"]) == 2
    assert out["own_classes"] == ["CLASS-A"]         # kept from either side
    assert "lessons" not in out


def test_merge_timetables_lessons():
    a = {"start": "2026-10-01", "end": "2026-10-01", "lessons": [{"date": "2026-10-01"}]}
    b = {"start": "2026-10-02", "end": "2026-10-02", "lessons": [{"date": "2026-10-02"}]}
    assert len(merge_timetables(a, b)["lessons"]) == 2
