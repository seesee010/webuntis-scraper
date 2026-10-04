"""Tests for the live "current lesson" marker in the day view (#41)."""
from __future__ import annotations

from datetime import datetime

import pytest

from untis import summary as summary_mod
from untis.summary import (
    _fmt_minutes,
    _live_state,
    _minutes_between,
    _plain,
    _takes_place,
    render_summary,
)

DAY = "2026-10-05"


def _row(start, end, subject="MATH", **flags):
    return {"start": start, "end": end, "subject": subject, **flags}


ROWS = [                                    # already sorted by start
    _row("07:50", "09:35", "MATH"),
    _row("09:40", "10:30", "GER"),
    _row("10:45", "11:35", "PROG"),
    _row("10:45", "11:35", "NET"),          # parallel group lesson
    _row("11:40", "12:30", "ENG", is_cancelled=True),
    _row("12:35", "13:25", "GEO"),
]


def at(hm: str, day: str = DAY) -> datetime:
    return datetime.fromisoformat(f"{day}T{hm}")


# --- small helpers -------------------------------------------------------
def test_plain_strips_ansi():
    assert _plain("\033[1m\033[33m▶\033[0m MATH \033[36mR101\033[0m") == "▶ MATH R101"
    assert _plain("no codes") == "no codes"


@pytest.mark.parametrize("minutes, text", [
    (0, "0 min"), (5, "5 min"), (59, "59 min"), (60, "1 h"), (65, "1 h 5 min"),
    (120, "2 h"), (-3, "0 min"),
])
def test_fmt_minutes(minutes, text):
    assert _fmt_minutes(minutes) == text


@pytest.mark.parametrize("a, b, diff", [("09:40", "10:30", 50), ("10:30", "09:40", -50),
                                        ("07:00", "07:00", 0), ("23:59", "00:00", -1439)])
def test_minutes_between(a, b, diff):
    assert _minutes_between(a, b) == diff


@pytest.mark.parametrize("flags, expected", [({}, True), ({"is_cancelled": True}, False),
                                             ({"is_removed": True}, False)])
def test_takes_place(flags, expected):
    assert _takes_place(flags) is expected


# --- _live_state -----------------------------------------------------------
def test_not_today_or_no_now():
    assert _live_state(DAY, ROWS, at("10:00", "2026-10-06")) is None
    assert _live_state(DAY, ROWS, None) is None


def test_after_school_nothing_is_marked():
    assert _live_state(DAY, ROWS, at("13:25")) is None
    assert _live_state(DAY, ROWS, at("18:00")) is None


def test_no_lessons_that_take_place():
    assert _live_state(DAY, [_row("08:00", "09:00", is_cancelled=True)], at("08:30")) is None


def test_before_school_puts_line_first():
    s = _live_state(DAY, ROWS, at("07:12"))
    assert s["current"] == set() and s["past"] == set()
    assert s["line_before"] == 0 and s["next_in"] == 38


def test_during_a_lesson():
    s = _live_state(DAY, ROWS, at("09:52"))
    assert s["current"] == {1}
    assert s["past"] == {0}
    assert s["line_before"] is None


def test_start_and_end_boundaries():
    assert _live_state(DAY, ROWS, at("09:40"))["current"] == {1}     # starts now
    s = _live_state(DAY, ROWS, at("09:35"))                         # just ended
    assert s["current"] == set() and 0 in s["past"]
    assert s["line_before"] == 1 and s["next_in"] == 5


def test_parallel_lessons_are_all_current():
    assert _live_state(DAY, ROWS, at("11:00"))["current"] == {2, 3}


def test_cancelled_slot_is_never_current():
    s = _live_state(DAY, ROWS, at("12:00"))
    assert s["current"] == set()
    assert s["line_before"] == 5 and s["next_in"] == 35


def test_break_line_goes_before_cancelled_rows_of_the_next_slot():
    rows = [_row("08:00", "09:00"), _row("09:10", "10:00", "X", is_cancelled=True),
            _row("09:10", "10:00", "Y")]
    s = _live_state(DAY, rows, at("09:05"))
    assert s["line_before"] == 1 and s["next_in"] == 5


# --- rendering -------------------------------------------------------------
def _payload(*entries, day=DAY):
    return {"meta": {"user": "Max Muster", "school": "demo",
                     "window": {"start": day, "end": day}},
            "timetable": {"days": [{"date": day, "entries": list(entries)}]}}


def _entry(start, end, subject, room="R101", **flags):
    return {"start": f"{DAY}T{start}", "end": f"{DAY}T{end}", "status": "REGULAR",
            "type": "NORMAL_TEACHING_PERIOD", "subjects": [{"short": subject}],
            "teachers": [{"short": "TCH1"}], "rooms": [{"short": room}],
            "info": "", "lesson_text": "", "substitution_text": "",
            "is_cancelled": False, "is_exam": False, **flags}


PAYLOAD = _payload(
    _entry("07:50", "09:35", "MATH"),
    _entry("09:40", "10:30", "GER"),
    _entry("10:45", "11:35", "PROG"),
    _entry("11:40", "12:30", "ENG", is_cancelled=True, status="CANCELLED"),
)


def _lines(now, payload=PAYLOAD, color=False):
    return render_summary(payload, color=color, now=now).splitlines()


def test_marker_and_time_left_on_current_lesson():
    lines = _lines(at("09:52"))
    cur = next(l for l in lines if "GER" in l)
    assert cur.startswith("▶ 09:40–10:30")
    assert cur.endswith("now · 38 min left")
    assert not any(l.startswith("▶") for l in lines if "GER" not in l)


def test_marker_keeps_columns_aligned():
    lines = _lines(at("09:52"))
    col = lambda needle: next(l for l in lines if needle in l).index("TCH1")
    assert col("GER") == col("MATH") == col("PROG")


def test_now_line_in_break():
    lines = _lines(at("10:37"))
    i = next(i for i, l in enumerate(lines) if "now 10:37" in l)
    assert "next in 8 min" in lines[i]
    assert "GER" in lines[i - 1] and "PROG" in lines[i + 1]
    assert not any(l.startswith("▶") for l in lines)


def test_past_lessons_are_dimmed_with_colors():
    lines = _lines(at("09:52"), color=True)
    math = next(l for l in lines if "MATH" in l)
    assert math.startswith("\033[2m") and math.count("\033[") == 2   # one dim, one reset
    prog = next(l for l in lines if "PROG" in l)
    assert not prog.startswith("\033[2m")


def test_cancelled_line_is_struck_through_completely():
    lines = _lines(at("09:52"), color=True)
    eng = next(l for l in lines if "ENG" in l)
    struck = eng.split("\033[0m")[0]                 # first styled segment
    assert "ENG" in struck and "R101" in struck      # strike covers the whole row


def test_other_days_and_after_school_are_unchanged():
    tomorrow = render_summary(PAYLOAD, color=False, now=at("09:52", "2026-10-04"))
    after = render_summary(PAYLOAD, color=False, now=at("15:00"))
    assert tomorrow == after
    assert "▶" not in after and "now " not in after


def test_default_now_is_the_current_time(monkeypatch):
    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromisoformat(f"{DAY}T09:52")
    monkeypatch.setattr(summary_mod, "datetime", FakeDateTime)
    assert "▶ 09:40–10:30" in render_summary(PAYLOAD, color=False)
