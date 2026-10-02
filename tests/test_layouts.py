"""Tests for --oneline / --table and the school time grid (#23)."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from untis import main as main_mod
from untis.scraper import Scraper
from untis.config import ScraperConfig
from untis.summary import (
    _cell,
    _days_rows,
    _fit,
    _grid_units,
    _plain,
    _render_oneline,
    _render_table,
    _slots,
    _Style,
    _token,
    render_summary,
)
from untis.untis_client import _time_grid

ON, OFF = _Style(True), _Style(False)
NOT_LIVE = datetime(2000, 1, 1, 12, 0)
GRID = [{"start": "07:50", "end": "08:40"}, {"start": "08:45", "end": "09:35"},
        {"start": "09:40", "end": "10:30"}, {"start": "10:45", "end": "11:35"}]


def _e(day, start, end, subject, room="R101", **flags):
    return {"start": f"{day}T{start}", "end": f"{day}T{end}", "status": "REGULAR",
            "type": "NORMAL_TEACHING_PERIOD", "subjects": [{"short": subject}] if subject else [],
            "teachers": [{"short": "TCH1"}], "rooms": [{"short": room}] if room else [],
            "info": flags.pop("info", ""), "lesson_text": "", "substitution_text": "",
            "is_cancelled": False, "is_exam": False, **flags}


MON, TUE = "2026-10-05", "2026-10-06"
TT = {"time_grid": GRID, "days": [
    {"date": MON, "entries": [
        _e(MON, "07:50", "09:35", "MATH"),                                   # double lesson
        _e(MON, "10:45", "11:35", "ENG", status="CHANGED",
           teachers=[{"short": "TCH4", "status": "ADDED", "replaces": "TCH3"}]),
    ]},
    {"date": TUE, "entries": [
        _e(TUE, "07:50", "08:40", "NET", room="R201"),
        _e(TUE, "07:50", "08:40", "PROG", room="R202"),                     # parallel group
        _e(TUE, "08:45", "09:35", "GEO", is_cancelled=True, status="CANCELLED"),
        _e(TUE, "09:40", "10:30", "MATH", is_exam=True),
    ]},
    {"date": "2026-10-10", "entries": []},                                   # Saturday
]}


# --- time grid -----------------------------------------------------------
def test_time_grid_from_app_data():
    app = {"currentSchoolYear": {"timeGrid": {"units": [
        {"startTime": 845, "endTime": 935, "unitOfDay": 2},
        {"startTime": 750, "endTime": 840, "unitOfDay": 1},
        {"startTime": None, "endTime": 900}]}}}
    assert _time_grid(app) == [{"start": "07:50", "end": "08:40"},
                               {"start": "08:45", "end": "09:35"}]
    assert _time_grid({}) == []


async def test_scraper_stores_time_grid():
    client = MagicMock()
    client.time_grid = GRID
    client.get_timetable_grid = AsyncMock(return_value={"days": [{"date": MON, "gridEntries": []}]})
    client.get_own_classes = AsyncMock(return_value=set())
    tt = await Scraper(ScraperConfig(server="s", school="sc"), client)._fetch_timetable(
        datetime(2026, 10, 5).date(), datetime(2026, 10, 5).date())
    assert tt["time_grid"] == GRID


async def test_scraper_ignores_non_list_time_grid():
    client = MagicMock()                      # MagicMock attribute, not a list
    client.get_timetable_grid = AsyncMock(return_value={"days": [{"date": MON, "gridEntries": []}]})
    client.get_own_classes = AsyncMock(return_value=set())
    tt = await Scraper(ScraperConfig(server="s", school="sc"), client)._fetch_timetable(
        datetime(2026, 10, 5).date(), datetime(2026, 10, 5).date())
    assert tt["time_grid"] == []


# --- helpers ---------------------------------------------------------------
def test_days_rows_sorted_and_without_empty_days():
    days = _days_rows(TT)
    assert list(days) == [MON, TUE]
    assert [r["subject"] for r in days[TUE]] == ["NET", "PROG", "GEO", "MATH"]


def test_grid_units_from_time_grid_or_lessons():
    assert _grid_units(TT, _days_rows(TT))[0] == ("07:50", "08:40")
    no_grid = {k: v for k, v in TT.items() if k != "time_grid"}
    assert _grid_units(no_grid, _days_rows(no_grid)) == [
        ("07:50", "08:40"), ("07:50", "09:35"), ("08:45", "09:35"),
        ("09:40", "10:30"), ("10:45", "11:35")]


def test_slots_double_lesson_fills_two_periods():
    slots = _slots(_days_rows(TT)[MON], [(u["start"], u["end"]) for u in GRID])
    assert [[r["subject"] for r in s] for s in slots] == [["MATH"], ["MATH"], [], ["ENG"]]


@pytest.mark.parametrize("flags, plain_on, plain_off", [
    ({}, "MATH", "MATH"),
    ({"is_cancelled": True, "status": "CANCELLED"}, "MATH", "~MATH~"),
    ({"is_removed": True, "status": "CHANGED"}, "MATH", "~MATH~"),
    ({"status": "CHANGED"}, "MATH*", "MATH*"),
    ({"no_teacher": True, "status": "CHANGED"}, "MATH*", "MATH*"),
    ({"is_exam": True}, "MATH!", "MATH!"),
])
def test_token(flags, plain_on, plain_off):
    row = _days_rows({"days": [{"date": MON, "entries": [_e(MON, "07:50", "08:40", "MATH", **flags)]}]})[MON][0]
    assert _plain(_token(row, ON)) == plain_on
    assert _token(row, OFF) == plain_off


def test_token_event():
    row = _days_rows({"days": [{"date": MON, "entries": [
        _e(MON, "07:50", "17:05", None, room=None, is_event=True, info="TRIP")]}]})[MON][0]
    assert _token(row, OFF) == "★ TRIP"


def test_cell_parallel_rooms_and_dedupe():
    rows = _days_rows(TT)[TUE]
    assert _cell(rows[:2], OFF) == "NET/PROG"
    assert _cell(rows[:2], OFF, with_room=True) == "NET/PROG"         # no room for groups
    assert _cell([rows[3]], OFF, with_room=True) == "MATH! R101"
    assert _cell([rows[0], rows[0]], OFF) == "NET"


@pytest.mark.parametrize("text, width, out", [("MATH", 6, "MATH  "), ("MATH R101", 6, "MATH …"),
                                              ("ABC", 3, "ABC"), ("ABCD", 1, "…")])
def test_fit(text, width, out):
    assert _fit(text, width) == out


def test_fit_keeps_colors_when_it_fits():
    styled = ON.role("exam", "MATH")
    assert _fit(styled, 6) == styled + "  "


# --- --oneline -------------------------------------------------------------
def test_oneline():
    lines = _render_oneline(TT, OFF)
    assert lines[0] == "Mon 05.10.  07:50–11:35  MATH MATH - ENG*"
    assert lines[1] == "Tue 06.10.  07:50–10:30  NET/PROG ~GEO~ MATH!"


def test_oneline_rows_outside_the_grid_are_kept():
    tt = {"time_grid": GRID[:1], "days": [{"date": MON, "entries": [
        _e(MON, "07:50", "08:40", "MATH"), _e(MON, "18:00", "18:45", "LATE")]}]}
    assert _render_oneline(tt, OFF)[0].endswith("MATH LATE")


def test_oneline_empty():
    assert _render_oneline({"days": []}, OFF) == ["No lessons in this window."]


def test_render_summary_oneline_has_no_extra_sections():
    out = render_summary({"meta": {"user": "Max"}, "timetable": TT,
                          "messages": {"items": [{"read": False}]}},
                         color=False, now=NOT_LIVE, layout="oneline")
    assert out.splitlines()[0].startswith("Mon 05.10.") and "unread" not in out
    err = render_summary({"timetable": {"error": "HTTP 500"}}, color=False, layout="oneline")
    assert err == "timetable: HTTP 500"


# --- --table ---------------------------------------------------------------
def test_table():
    lines = [l for l in _render_table(TT, OFF, width=60) if l]
    assert lines[0].split() == ["Mon", "05.10.", "Tue", "06.10."]
    assert lines[1].startswith("07:50  MATH R101") and "NET/PROG" in lines[1]
    assert lines[2].startswith("08:45  MATH R101") and "~GEO~ R101" in lines[2]
    assert lines[3].startswith("09:40") and "MATH! R101" in lines[3]       # free on Mon
    assert lines[4].startswith("10:45  ENG* R101")
    assert all(l == l.rstrip() for l in lines)


def test_table_columns_are_aligned_and_fit_the_width():
    lines = [l for l in _render_table(TT, ON, width=40) if l]
    plains = [_plain(l) for l in lines]
    assert all(len(p) <= 40 for p in plains)
    tue_col = plains[0].index("Tue")
    assert plains[1][tue_col:].startswith("NET/PROG")


def test_table_splits_weeks():
    tt = {"time_grid": GRID, "days": [
        {"date": MON, "entries": [_e(MON, "07:50", "08:40", "A")]},
        {"date": "2026-10-12", "entries": [_e("2026-10-12", "07:50", "08:40", "B")]}]}
    lines = _render_table(tt, OFF, width=80)
    headers = [l for l in lines if l.strip().startswith("Mon")]
    assert len(headers) == 2


def test_table_empty():
    assert "No lessons" in _render_table({"days": []}, OFF)[1]


def test_render_summary_table_keeps_other_sections():
    out = render_summary({"meta": {"user": "Max"}, "timetable": TT,
                          "messages": {"items": [{"read": False}]}},
                         color=False, now=NOT_LIVE, layout="table", width=60)
    assert "07:50" in out and "1 unread message" in out


# --- CLI -------------------------------------------------------------------
@pytest.mark.parametrize("argv, layout", [([], None), (["-s"], "days"), (["--oneline"], "oneline"),
                                          (["--table"], "table"), (["-s", "--table"], "table")])
def test_layout_choice(argv, layout):
    assert main_mod._layout(main_mod._parse_args(argv, default_args=[])) == layout


def test_oneline_and_table_together_is_an_error(capsys):
    with pytest.raises(SystemExit) as exc:
        main_mod._parse_args(["--oneline", "--table"], default_args=[])
    assert exc.value.code == 2


def test_default_layout_can_be_turned_off():
    args = main_mod._parse_args(["--no-oneline", "--table"], default_args=["--oneline"])
    assert main_mod._layout(args) == "table"


async def test_async_main_prints_the_chosen_layout(monkeypatch, tmp_path, capsys):
    c = ScraperConfig(server="s", school="sc", output_dir=str(tmp_path))
    monkeypatch.setattr(main_mod, "load_config", lambda *a: c)
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "last.json")
    monkeypatch.setattr(main_mod, "_fetch", AsyncMock(return_value={"meta": {}, "timetable": TT}))
    await main_mod._async_main(main_mod._parse_args(["--oneline", "--color", "never"],
                                                    default_args=[]))
    assert capsys.readouterr().out.startswith("Mon 05.10.  07:50–11:35  MATH MATH - ENG*")
