"""Tests for --now and the Waybar output (#8)."""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from untis import main as main_mod
from untis import now as now_mod
from untis.config import ScraperConfig
from untis.now import (
    _describe,
    format_text,
    format_waybar,
    has_anything,
    now_data,
    now_state,
    short_minutes,
    target_day,
)

FRI = date(2026, 10, 2)
DAY = FRI.isoformat()


def _e(start, end, subject, room="R101", teacher="TCH1", **flags):
    return {"start": f"{DAY}T{start}", "end": f"{DAY}T{end}", "status": "REGULAR",
            "subjects": [{"short": subject}], "teachers": [{"short": teacher}],
            "rooms": [{"short": room}], "info": "", "lesson_text": "", "substitution_text": "",
            "is_cancelled": False, "is_exam": False, **flags}


TT = {"days": [{"date": DAY, "entries": [
    _e("07:50", "08:40", "GEO", is_cancelled=True, status="CANCELLED"),
    _e("08:45", "09:35", "MATH"),
    _e("09:40", "10:30", "NET", room="R201"),
    _e("09:40", "10:30", "PROG", room="R202", teacher="TCH2"),
    _e("10:45", "11:35", "ENG", status="CHANGED",
       teachers=[{"short": "TCH4", "status": "ADDED", "replaces": "TCH3"}]),
]}]}


def at(hm: str) -> datetime:
    return datetime.fromisoformat(f"{DAY}T{hm}")


# --- now_state ---------------------------------------------------------------
def test_during_a_lesson():
    s = now_state(TT, FRI, at("09:00"))
    assert [r["subject"] for r in s["current"]] == ["MATH"]
    assert [r["subject"] for r in s["next"]] == ["NET", "PROG"]       # parallel group


def test_in_a_break_and_before_school():
    s = now_state(TT, FRI, at("10:37"))
    assert s["current"] == [] and [r["subject"] for r in s["next"]] == ["ENG"]
    s = now_state(TT, FRI, at("07:00"))
    assert [r["subject"] for r in s["next"]] == ["MATH"]               # GEO is cancelled


def test_cancelled_lesson_is_never_current():
    assert now_state(TT, FRI, at("08:00"))["current"] == []


def test_after_school_and_other_day():
    assert now_state(TT, FRI, at("12:00")) == {"day": DAY, "current": [], "next": []}
    s = now_state(TT, FRI, datetime(2026, 10, 1, 20, 0))      # evening before
    assert s["current"] == [] and [r["subject"] for r in s["next"]] == ["MATH"]


# --- data / formatting -------------------------------------------------------
def test_describe_joins_parallel_lessons():
    d = _describe(now_state(TT, FRI, at("09:00"))["next"])
    assert d == {"subject": "NET/PROG", "teachers": "TCH1/TCH2", "rooms": "R201/R202",
                 "start": "09:40", "end": "10:30", "status": ""}
    assert _describe([]) is None


def test_describe_status_and_substitute():
    d = _describe(now_state(TT, FRI, at("10:40"))["next"])
    assert d["status"] == "changed" and d["teachers"] == "TCH4 (for TCH3)"


def test_now_data_minutes():
    data = now_data(now_state(TT, FRI, at("09:23")), at("09:23"))
    assert data["now"]["minutes_left"] == 12
    assert data["next"]["starts_in"] == 17 and data["next"]["date"] == DAY


def test_now_data_next_on_another_day_has_no_starts_in():
    t = datetime(2026, 10, 1, 20, 0)
    data = now_data(now_state(TT, FRI, t), t)
    assert data["now"] is None and "starts_in" not in data["next"]


@pytest.mark.parametrize("m, text", [(0, "0m"), (12, "12m"), (59, "59m"), (60, "1h00m"),
                                     (65, "1h05m"), (-1, "0m")])
def test_short_minutes(m, text):
    assert short_minutes(m) == text


def test_format_text_during_lesson():
    data = now_data(now_state(TT, FRI, at("09:23")), at("09:23"))
    assert format_text(data, FRI).splitlines() == [
        "now   MATH  TCH1  R101   until 09:35 (12 min)",
        "next  NET/PROG  TCH1/TCH2  R201/R202   09:40–10:30",
    ]


def test_format_text_next_on_another_day_and_status():
    t = datetime(2026, 10, 1, 20, 0)
    data = now_data(now_state(TT, FRI, t), t)
    assert format_text(data, t.date()) == "next  MATH  TCH1  R101   Fri 02.10. 08:45–09:35"
    data = now_data(now_state(TT, FRI, at("10:40")), at("10:40"))
    assert format_text(data, FRI).endswith("10:45–11:35   changed")


def test_format_text_idle_empty():
    data = now_data(now_state(TT, FRI, at("10:37")), at("10:37"))
    assert format_text(data, FRI, idle_empty=True) == ""
    busy = now_data(now_state(TT, FRI, at("09:23")), at("09:23"))
    assert format_text(busy, FRI, idle_empty=True).count("\n") == 1     # now + next


def test_format_waybar_lesson_idle_and_empty():
    busy = json.loads(format_waybar(now_data(now_state(TT, FRI, at("09:23")), at("09:23")), FRI))
    assert busy["text"] == "MATH R101 · 12m" and busy["class"] == "lesson"
    assert busy["tooltip"].startswith("now   MATH")
    idle = json.loads(format_waybar(now_data(now_state(TT, FRI, at("10:37")), at("10:37")), FRI))
    assert idle == {"text": "next: 10:45 ENG", "tooltip": idle["tooltip"], "class": "idle"}
    hidden = json.loads(format_waybar(now_data(now_state(TT, FRI, at("10:37")), at("10:37")),
                                      FRI, idle_empty=True))
    assert hidden["text"] == "" and hidden["class"] == "idle"


def test_format_waybar_class_from_status_and_other_day():
    tt = {"days": [{"date": DAY, "entries": [_e("08:45", "09:35", "MATH", no_teacher=True,
                                                 status="CHANGED")]}]}
    data = now_data(now_state(tt, FRI, at("09:00")), at("09:00"))
    assert json.loads(format_waybar(data, FRI))["class"] == "no-teacher"
    t = datetime(2026, 10, 1, 20, 0)
    data = now_data(now_state(TT, FRI, t), t)
    assert json.loads(format_waybar(data, t.date()))["text"] == "next: Fri 08:45 MATH"


def test_has_anything_and_target_day():
    assert has_anything({"now": None, "next": {"x": 1}})
    assert not has_anything({"now": None, "next": None})
    assert target_day({"meta": {"window": {"start": "2026-10-05"}}}, FRI) == date(2026, 10, 5)
    assert target_day({}, FRI) == FRI
    assert target_day({"meta": {"window": {"start": "bad"}}}, FRI) == FRI


@pytest.mark.parametrize("fmt", ["text", "json", "waybar"])
def test_answer_formats(fmt):
    payload = {"meta": {"window": {"start": DAY}}, "timetable": TT}
    out, data = now_mod.answer(payload, fmt, FRI, at("09:23"))
    assert data["now"]["subject"] == "MATH"
    if fmt != "text":
        json.loads(out)


# --- CLI -----------------------------------------------------------------------
def parse(argv, defaults=()):
    return main_mod._parse_args(argv, today=FRI, default_args=list(defaults))


def test_now_flags():
    a = parse(["--now", "--format", "waybar", "--idle-empty"])
    assert a.now and a.format == "waybar" and a.idle_empty


@pytest.mark.parametrize("argv", [["--format", "waybar"], ["--now", "--week"], ["--now", "--start"],
                                  ["--now", "-t"], ["--now", "--oneline"], ["--now", "--days-forward", "2"]])
def test_now_usage_errors(capsys, argv):
    with pytest.raises(SystemExit) as exc:
        parse(argv)
    assert exc.value.code == 2


def test_explicit_now_replaces_default_window_and_vice_versa():
    assert parse(["--now"], ["--today"]).today is False
    args = parse(["--week"], ["--now"])
    assert args.week and not args.now


async def _run_now(monkeypatch, capsys, argv, payload):
    cfg = ScraperConfig(server="s", school="sc", scrape_exams=True)

    async def fake_get_payload(c, args, today, now):
        return payload, True
    monkeypatch.setattr(main_mod, "_get_payload", fake_get_payload)
    code = await main_mod._answer_now(cfg, parse(argv), FRI, at("09:23"))
    return code, capsys.readouterr().out, cfg


async def test_answer_now_text(monkeypatch, capsys):
    code, out, cfg = await _run_now(monkeypatch, capsys, ["--now"],
                                    {"meta": {"window": {"start": DAY}}, "timetable": TT})
    assert code == 0 and out.startswith("now   MATH")
    assert cfg.pick_day == "next" and not cfg.scrape_exams


async def test_answer_now_nothing(monkeypatch, capsys):
    empty = {"meta": {"window": {"start": DAY}}, "timetable": {"days": []}}
    code, out, _ = await _run_now(monkeypatch, capsys, ["--now"], empty)
    assert (code, out) == (main_mod.EXIT_NO_SCHOOL, "-\n")
    code, out, _ = await _run_now(monkeypatch, capsys, ["--now", "--format", "json"], empty)
    assert code == main_mod.EXIT_NO_SCHOOL and json.loads(out) == {"now": None, "next": None}
    code, out, _ = await _run_now(monkeypatch, capsys, ["--now", "--format", "waybar"], empty)
    assert code == 0 and json.loads(out)["text"] == ""            # the bar always gets JSON


async def test_answer_now_idle_empty_prints_nothing(monkeypatch, capsys):
    payload = {"meta": {"window": {"start": DAY}}, "timetable": TT}

    async def fake_get_payload(c, args, today, now):
        return payload, True
    monkeypatch.setattr(main_mod, "_get_payload", fake_get_payload)
    code = await main_mod._answer_now(ScraperConfig(server="s", school="sc"),
                                      parse(["--now", "--idle-empty"]), FRI, at("10:37"))
    assert code == 0 and capsys.readouterr().out == ""


async def test_answer_now_timetable_error(monkeypatch, capsys):
    with pytest.raises(main_mod.WebUntisError, match="HTTP 500"):
        await _run_now(monkeypatch, capsys, ["--now"], {"timetable": {"error": "HTTP 500"}})
