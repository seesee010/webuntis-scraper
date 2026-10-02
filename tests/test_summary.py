"""Tests for the --short terminal summary."""
from __future__ import annotations

from datetime import datetime

from src.summary import render_summary

# Fixed "now" far away from the fixtures, so the live marker never kicks in.
NOT_LIVE = datetime(2000, 1, 1, 12, 0)


def _payload(**sections):
    return {
        "meta": {"user": "Max Muster", "school": "demo",
                 "window": {"start": "2026-10-05", "end": "2026-10-06"}},
        **sections,
    }


def _entry(start, end, subject, teachers, rooms=(), status="REGULAR", **kw):
    return {
        "start": f"2026-10-05T{start}", "end": f"2026-10-05T{end}",
        "status": status, "is_cancelled": kw.get("cancelled", False),
        "is_exam": False, "type": "NORMAL_TEACHING_PERIOD",
        "subjects": [{"short": subject}] if subject else [],
        "teachers": list(teachers), "rooms": [{"short": r} for r in rooms],
        "info": kw.get("info", ""), "lesson_text": "", "substitution_text": "",
        "is_event": kw.get("event", False), "is_removed": kw.get("removed", False),
        "no_teacher": kw.get("no_teacher", False),
    }


def test_day_view_marks_changes_and_cancellations():
    tt = {"source": "rest_v1", "days": [
        {"date": "2026-10-05", "entries": [
            _entry("09:40", "10:30", "E1",
                   [{"short": "NEW", "status": "ADDED", "replaces": "OLD"}],
                   ["T130"], status="CHANGED"),
            _entry("07:50", "08:40", "AM", [{"short": "FELT"}], ["T130"]),
            _entry("08:45", "09:35", "D", [{"short": "SPOD"}],
                   status="CANCELLED", cancelled=True),
            _entry("10:45", "11:35", "ITS", [{"short": "SANH", "status": "REMOVED"}],
                   status="CHANGED"),
            _entry("12:35", "13:25", None, [], status="CHANGED", info="Assembly"),
        ]},
        {"date": "2026-10-06", "entries": []},
    ]}
    out = render_summary(_payload(timetable=tt), color=False, now=NOT_LIVE)
    lines = out.splitlines()

    assert "Mon 05.10." in out
    assert "Tue 06.10." not in out          # empty days are skipped
    assert lines.index(next(l for l in lines if "AM" in l)) < \
           lines.index(next(l for l in lines if "E1" in l))  # sorted by time
    assert "NEW (for OLD)" in out
    assert "~SANH~" in out
    assert next(l for l in lines if " D " in l).endswith("cancelled")
    assert "Assembly" in out


def test_exams_homework_and_counts():
    out = render_summary(_payload(
        exams={"exams": [{"date": "2026-10-19", "start_time": "10:45",
                          "name": "Test", "subjects": [{"short": "SYT"}],
                          "rooms": [{"short": "T130"}]}]},
        homework={"items": [
            {"due_date": "2026-10-07", "text": "p. 42", "completed": False,
             "subjects": [{"short": "M"}]},
            {"due_date": "2026-10-08", "text": "done already", "completed": True,
             "subjects": []},
        ]},
        absences={"items": [{"is_excused": False}, {"is_excused": True}]},
        messages={"items": [{"read": False}]},
    ), color=False, now=NOT_LIVE)
    assert "Mon 19.10. 10:45" in out and "SYT" in out
    assert "due Wed 07.10." in out and "p. 42" in out
    assert "done already" not in out
    assert "2 absences (1 not excused)" in out
    assert "1 unread message" in out


def test_module_error_is_shown():
    out = render_summary(_payload(timetable={"error": "HTTP 500"}), color=False, now=NOT_LIVE)
    assert "timetable: HTTP 500" in out


def test_event_removed_and_no_teacher_labels():
    tt = {"source": "rest_v1", "days": [{"date": "2026-09-30", "entries": [
        _entry("07:50", "17:05", None, [{"short": "TCH8"}, {"short": "TCH9"}],
               status="CHANGED", info="EVENT-NAME", event=True),
        _entry("07:50", "08:40", "GEO", [{"short": "TCH1"}], ["R101"],
               status="CANCELLED", cancelled=True),
        _entry("13:25", "14:15", "ETH", [{"short": "TCH5"}], ["R102"],
               status="CHANGED", removed=True),
        _entry("14:20", "15:10", "PROG", [{"short": "TCH3", "status": "REMOVED"}],
               ["R101"], status="CHANGED", no_teacher=True),
        _entry("15:20", "16:10", "ENG",
               [{"short": "TCH10", "status": "ADDED", "replaces": "TCH2"}],
               ["R101"], status="CHANGED"),
    ]}]}
    lines = render_summary(_payload(timetable=tt), color=False, now=NOT_LIVE).splitlines()
    line = lambda needle: next(l for l in lines if needle in l)

    assert "★ EVENT-NAME" in line("EVENT-NAME")
    assert "TCH8, TCH9" in line("EVENT-NAME")
    assert line("EVENT-NAME").endswith("event")
    assert line("GEO").endswith("cancelled")
    assert line("ETH").endswith("removed")
    assert line("PROG").endswith("no teacher")
    assert line("ENG").endswith("changed")     # real substitution unchanged


def test_cancelled_wins_over_removed():
    tt = {"source": "rest_v1", "days": [{"date": "2026-09-30", "entries": [
        _entry("07:50", "08:40", "GEO", [{"short": "TCH1"}], status="CANCELLED",
               cancelled=True, removed=True),
    ]}]}
    out = render_summary(_payload(timetable=tt), color=False, now=NOT_LIVE)
    assert next(l for l in out.splitlines() if "GEO" in l).endswith("cancelled")
    assert "removed" not in out
