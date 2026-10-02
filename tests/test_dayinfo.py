"""Tests for --start / --end / --free (#24)."""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from unittest.mock import AsyncMock

import pytest

from untis import main as main_mod
from untis.config import ScraperConfig
from untis.dayinfo import (
    _merge,
    _minutes,
    day_info,
    format_answer,
    free_periods,
    query_day,
)

SAT, MON = date(2026, 10, 3), date(2026, 10, 5)
GRID = [("07:50", "08:40"), ("08:45", "09:35"), ("09:40", "10:30"), ("10:45", "11:35"),
        ("11:40", "12:30"), ("12:35", "13:25")]


# --- query_day -------------------------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("next", "next"), ("Next", "next"), ("nächster", "next"),
    ("today", SAT), ("heute", SAT), ("tomorrow", date(2026, 10, 4)), ("morgen", date(2026, 10, 4)),
    ("mon", MON), ("montag", MON), ("sat", SAT),                 # weekday: next one, today included
    ("fri", date(2026, 10, 9)), ("30.09.", date(2026, 9, 30)), ("2026-10-12", date(2026, 10, 12)),
])
def test_query_day(text, expected):
    assert query_day(text, SAT) == expected


def test_query_day_invalid():
    with pytest.raises(ValueError):
        query_day("someday", SAT)


# --- helpers ---------------------------------------------------------------
@pytest.mark.parametrize("hm, minutes", [("00:00", 0), ("07:50", 470), ("13:25", 805)])
def test_minutes(hm, minutes):
    assert _minutes(hm) == minutes


def test_merge():
    assert _merge([("09:40", "10:30"), ("07:50", "08:40"), ("08:40", "09:35"),
                   ("10:00", "11:00")]) == [("07:50", "09:35"), ("09:40", "11:00")]
    assert _merge([]) == []


def test_free_periods_with_grid():
    spans = [("07:50", "09:35"), ("11:40", "12:30")]
    assert free_periods(spans, GRID) == [("09:40", "11:35")]      # two periods merged
    assert free_periods([("07:50", "13:25")], GRID) == []
    assert free_periods([], GRID) == []


def test_free_periods_with_grid_keeps_separate_gaps():
    spans = [("07:50", "08:40"), ("09:40", "10:30"), ("12:35", "13:25")]
    assert free_periods(spans, GRID) == [("08:45", "09:35"), ("10:45", "12:30")]


def test_free_periods_without_grid():
    spans = [("07:50", "08:40"), ("08:45", "09:35"), ("11:40", "12:30")]
    assert free_periods(spans) == [("09:35", "11:40")]           # 5-min break isn't free
    assert free_periods([("08:00", "09:00"), ("08:30", "10:00")]) == []


# --- day_info / format_answer ----------------------------------------------
def _tt(entries, grid=True, day="2026-10-05"):
    return {"time_grid": [{"start": s, "end": e} for s, e in GRID] if grid else [],
            "days": [{"date": day, "entries": entries}]}


def _e(start, end, subject, day="2026-10-05", **flags):
    return {"start": f"{day}T{start}", "end": f"{day}T{end}",
            "subjects": [{"short": subject}] if subject else [], **flags}


def test_cancelled_first_lesson_moves_the_start():
    info = day_info(_tt([_e("07:50", "08:40", "GEO", is_cancelled=True),
                         _e("08:45", "09:35", "MATH"),
                         _e("12:35", "13:25", "ENG")]), MON)
    assert info == {"date": "2026-10-05", "start": "08:45", "end": "13:25", "first": "MATH",
                    "free": [{"start": "09:40", "end": "12:30"}]}


def test_removed_lessons_dont_count():
    info = day_info(_tt([_e("07:50", "08:40", "ETH", is_removed=True),
                         _e("08:45", "09:35", "MATH")]), MON)
    assert info["start"] == "08:45"


def test_no_school():
    assert day_info(_tt([_e("07:50", "08:40", "GEO", is_cancelled=True)]), MON) is None
    assert day_info(_tt([]), MON) is None
    assert day_info(_tt([_e("07:50", "08:40", "MATH")]), date(2026, 10, 6)) is None


def test_event_name_and_end_of_longest_entry():
    info = day_info(_tt([_e("07:50", "17:05", None, info="TRIP"),
                         _e("07:50", "08:40", "MATH")], grid=False), MON)
    assert info["end"] == "17:05" and info["first"] in ("TRIP", "MATH")


def test_jsonrpc_lessons():
    tt = {"lessons": [{"date": "2026-10-05", "start_time": "07:50", "end_time": "08:40",
                       "subjects": [{"short": "MATH"}]},
                      {"date": "2026-10-05", "start_time": "06:00", "end_time": "07:00",
                       "subjects": [{"short": "X"}], "is_cancelled": True}]}
    assert day_info(tt, MON)["start"] == "07:50"


@pytest.mark.parametrize("what, out", [("start", "08:45"), ("end", "13:25"),
                                       ("free", "09:40–10:30\n11:40–12:30")])
def test_format_answer(what, out):
    info = {"start": "08:45", "end": "13:25",
            "free": [{"start": "09:40", "end": "10:30"}, {"start": "11:40", "end": "12:30"}]}
    assert format_answer(info, what) == out


def test_format_answer_no_school_and_no_gaps():
    assert format_answer(None, "start") == "-"
    assert format_answer({"free": []}, "free") == ""


# --- CLI -------------------------------------------------------------------
def parse(argv, defaults=()):
    return main_mod._parse_args(argv, today=SAT, default_args=list(defaults))


@pytest.mark.parametrize("argv, query", [
    (["--start"], ("start", "today")), (["--end", "tomorrow"], ("end", "tomorrow")),
    (["--free", "mon"], ("free", "mon")), ([], None),
])
def test_query_parsing(argv, query):
    assert parse(argv).query == query


@pytest.mark.parametrize("argv", [["--start", "--end"], ["--start", "--week"],
                                  ["--end", "--days-forward", "2"], ["--free", "x y"],
                                  ["--start", "someday"]])
def test_query_usage_errors(capsys, argv):
    with pytest.raises(SystemExit) as exc:
        parse(argv)
    assert exc.value.code == 2


def test_explicit_query_replaces_default_window():
    args = parse(["--start", "tomorrow"], ["--today", "-s"])
    assert args.query == ("start", "tomorrow") and not args.today


def test_query_day_arg():
    assert main_mod._query_day_arg("next") == "next"
    with pytest.raises(argparse.ArgumentTypeError):
        main_mod._query_day_arg("nope")


def test_exit_code_documented():
    assert main_mod.EXIT_NO_SCHOOL == 5
    assert "5 no school" in main_mod._build_parser().epilog


async def _answer(monkeypatch, capsys, argv, payload):
    cfg = ScraperConfig(server="s", school="sc", scrape_exams=True)
    seen = {}

    async def fake_get_payload(c, args, today, now):
        seen["cfg"] = c
        return payload, True
    monkeypatch.setattr(main_mod, "_get_payload", fake_get_payload)
    args = parse(argv)
    code = await main_mod._answer_question(cfg, args, SAT, datetime(2026, 10, 3, 0, 0))
    return code, capsys.readouterr().out, seen["cfg"]


def _payload(day="2026-10-05", entries=None):
    return {"meta": {"window": {"start": day, "end": day}},
            "timetable": _tt(entries if entries is not None else
                             [_e("07:50", "08:40", "MATH", day=day), _e("11:40", "12:30", "ENG", day=day)],
                             day=day)}


async def test_answer_text(monkeypatch, capsys):
    code, out, cfg = await _answer(monkeypatch, capsys, ["--start", "mon"], _payload())
    assert (code, out) == (0, "07:50\n")
    assert cfg.start_date == MON and not cfg.scrape_exams          # only the timetable


async def test_answer_free(monkeypatch, capsys):
    code, out, _ = await _answer(monkeypatch, capsys, ["--free", "mon"], _payload())
    assert out == "08:45–11:35\n"


async def test_answer_json(monkeypatch, capsys):
    code, out, _ = await _answer(monkeypatch, capsys, ["--end", "mon", "--format", "json"], _payload())
    assert json.loads(out) == {"date": "2026-10-05", "start": "07:50", "end": "12:30",
                               "first": "MATH", "free": [{"start": "08:45", "end": "11:35"}]}


async def test_answer_no_school(monkeypatch, capsys):
    code, out, _ = await _answer(monkeypatch, capsys, ["--start"],
                                 _payload(day="2026-10-03", entries=[]))
    assert (code, out) == (main_mod.EXIT_NO_SCHOOL, "-\n")
    code, out, _ = await _answer(monkeypatch, capsys, ["--start", "--format", "json"],
                                 _payload(day="2026-10-03", entries=[]))
    assert json.loads(out) == {"date": "2026-10-03", "start": None, "end": None,
                               "first": None, "free": []}


async def test_answer_next_uses_the_picked_day(monkeypatch, capsys):
    code, out, cfg = await _answer(monkeypatch, capsys, ["--start", "next"], _payload())
    assert cfg.pick_day == "next" and cfg.start_date is None and out == "07:50\n"


async def test_answer_timetable_error(monkeypatch, capsys):
    with pytest.raises(main_mod.WebUntisError, match="HTTP 500"):
        await _answer(monkeypatch, capsys, ["--start"], {"timetable": {"error": "HTTP 500"}})


async def test_get_payload_saves_cache_after_fetch(monkeypatch, tmp_path):
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "last.json")
    monkeypatch.setattr(main_mod, "_fetch", AsyncMock(return_value={"meta": {}}))
    cfg = ScraperConfig(server="s", school="sc")
    payload, fetched = await main_mod._get_payload(cfg, parse([]), SAT, datetime.now())
    assert fetched and (tmp_path / "last.json").exists()
