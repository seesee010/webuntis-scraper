"""Tests for the --short terminal summary."""
from __future__ import annotations

from src.summary import render_summary


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
    out = render_summary(_payload(timetable=tt), color=False)
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
    ), color=False)
    assert "Mon 19.10. 10:45" in out and "SYT" in out
    assert "due Wed 07.10." in out and "p. 42" in out
    assert "done already" not in out
    assert "2 absences (1 not excused)" in out
    assert "1 unread message" in out


def test_module_error_is_shown():
    out = render_summary(_payload(timetable={"error": "HTTP 500"}), color=False)
    assert "timetable: HTTP 500" in out
