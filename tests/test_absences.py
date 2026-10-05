"""Tests for --absences (untis.absences, the client/scraper parts, the CLI)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from untis import absences as ab
from untis import main as main_mod
from untis.config import ScraperConfig
from untis.scraper import Scraper
from untis.summary import _plain
from untis.untis_client import WebUntisClient, _with_reasons

TODAY = date(2026, 11, 23)                      # a Monday
GRID = [{"start": "08:00", "end": "08:50"}, {"start": "08:50", "end": "09:40"},
        {"start": "09:55", "end": "10:45"}, {"start": "10:45", "end": "11:35"},
        {"start": "11:50", "end": "12:40"}, {"start": "12:45", "end": "13:35"},
        {"start": "14:25", "end": "15:15"}, {"start": "15:15", "end": "16:05"}]


def item(start="2026-11-16", end=None, frm="08:00", to="13:35", excused=False, **kw):
    return {"start_date": start, "end_date": end or start, "start_time": frm,
            "end_time": to, "is_excused": excused, **kw}


# --- _minutes ---------------------------------------------------------------
@pytest.mark.parametrize("hm, minutes", [("00:00", 0), ("08:00", 480), ("24:00", 1440)])
def test_minutes(hm, minutes):
    assert ab._minutes(hm) == minutes


# --- absence_days -----------------------------------------------------------
def test_absence_days_single_day():
    assert ab.absence_days(item()) == [(date(2026, 11, 16), "08:00", "13:35")]


def test_absence_days_over_several_days():
    days = ab.absence_days(item("2026-11-16", "2026-11-18", "09:55", "10:45"))
    assert days == [(date(2026, 11, 16), "09:55", "24:00"),
                    (date(2026, 11, 17), "00:00", "24:00"),
                    (date(2026, 11, 18), "00:00", "10:45")]


def test_absence_days_skips_the_weekend_in_between():
    days = ab.absence_days(item("2026-11-20", "2026-11-23"))      # Fri .. Mon
    assert [d for d, _, _ in days] == [date(2026, 11, 20), date(2026, 11, 23)]


def test_absence_days_single_weekend_day_still_counts():
    assert ab.absence_days(item("2026-11-21"))[0][0] == date(2026, 11, 21)


def test_absence_days_missing_times_mean_whole_day():
    assert ab.absence_days(item(frm=None, to=None)) == [(date(2026, 11, 16), "00:00", "24:00")]


def test_absence_days_missing_end_date_is_one_day():
    assert len(ab.absence_days({"start_date": "2026-11-16"})) == 1


def test_absence_days_end_before_start_is_clamped():
    assert len(ab.absence_days(item("2026-11-18", "2026-11-16"))) == 1


def test_absence_days_without_start_date():
    assert ab.absence_days({}) == []


# --- count_lessons ----------------------------------------------------------
def test_count_lessons_morning():
    assert ab.count_lessons(item(), GRID) == 6


def test_count_lessons_without_grid():
    assert ab.count_lessons(item(), []) is None


@pytest.mark.parametrize("frm, to, n", [
    ("08:50", "09:40", 1),         # exactly one period
    ("08:10", "08:20", 1),         # partly missed period counts
    ("09:40", "09:55", 0),         # the break only
    ("13:35", "14:25", 0),         # touching periods don't count
    ("12:10", "14:40", 3),
])
def test_count_lessons_overlap(frm, to, n):
    assert ab.count_lessons(item(frm=frm, to=to), GRID) == n


def test_count_lessons_over_several_days():
    # Mon from 12:45 (3), Tue whole (8), Wed until 08:50 (1)
    assert ab.count_lessons(item("2026-11-16", "2026-11-18", "12:45", "08:50"), GRID) == 12


def test_count_lessons_ignores_broken_grid_units():
    assert ab.count_lessons(item(), [{"start": "08:00"}, *GRID[:1]]) == 1


# --- totals -----------------------------------------------------------------
def test_totals():
    t = ab.totals([item(), item("2026-11-18", to="09:40", excused=True)], GRID)
    assert t == {"absences": 2, "days": 2, "lessons": 8, "not_excused": 1}


def test_totals_counts_a_day_once():
    t = ab.totals([item(to="08:50"), item(frm="12:45")], GRID)
    assert t["days"] == 1 and t["lessons"] == 2


def test_totals_without_grid_has_no_lessons():
    assert ab.totals([item()], [])["lessons"] is None


def test_totals_empty():
    assert ab.totals([], GRID) == {"absences": 0, "days": 0, "lessons": 0, "not_excused": 0}


# --- status -----------------------------------------------------------------
@pytest.mark.parametrize("it, want", [
    ({"is_excused": True}, "excused"),
    ({"is_excused": True, "excuse_status": "pending"}, "excused"),
    ({"is_excused": False}, "not excused"),
    ({"is_excused": False, "excuse_status": "  "}, "not excused"),
    ({"is_excused": False, "excuse_status": "pending"}, "pending"),
])
def test_status(it, want):
    assert ab.status(it) == want


# --- range_label ------------------------------------------------------------
@pytest.mark.parametrize("start, end, want", [
    ("2026-09-01", "2027-06-30", "since 01.09.2026"),     # reaches today
    ("2026-09-01", "2026-11-23", "since 01.09.2026"),     # ends today
    ("2026-09-01", None, "since 01.09.2026"),
    ("2026-11-17", "2026-11-20", "17.11.–20.11.2026"),
    ("2025-12-22", "2026-01-09", "22.12.2025–09.01.2026"),
    (None, "2026-11-20", ""),
])
def test_range_label(start, end, want):
    assert ab.range_label(start, end, TODAY) == want


# --- _when / _plural --------------------------------------------------------
def test_when_single_day():
    assert ab._when(item()) == "Mon 16.11.  08:00–13:35"


def test_when_several_days():
    assert ab._when(item("2026-11-16", "2026-11-18")) == "Mon 16.11. 08:00 – Wed 18.11. 13:35"


def test_when_without_times():
    assert ab._when(item(frm=None, to=None)) == "Mon 16.11."
    assert ab._when(item(to=None)) == "Mon 16.11.  08:00"


@pytest.mark.parametrize("n, want", [(0, "0 lessons"), (1, "1 lesson"), (6, "6 lessons")])
def test_plural(n, want):
    assert ab._plural(n, "lesson") == want


# --- render_absences --------------------------------------------------------
def payload(items, grid=GRID, start="2026-09-01", end="2027-06-30", **meta):
    return {"meta": meta, "absences": {"start": start, "end": end, "items": items,
                                       "time_grid": grid}}


def render(p, color=False, width=80):
    return ab.render_absences(p, color=color, today=TODAY, now=datetime(2026, 11, 23, 12, 0),
                              width=width)


def test_render_header_and_rows_oldest_first():
    out = render(payload([item("2026-11-18", to="09:40", excused=True, reason="Doctor"),
                          item(reason="Illness")]))
    lines = out.splitlines()
    assert lines[0] == "Absences since 01.09.2026 · 2 days · 8 lessons · 1 not excused"
    rows = [l for l in lines[1:] if l.strip()]
    assert rows[0].startswith("Mon 16.11.  08:00–13:35  6 lessons  not excused  Illness")
    assert rows[1].startswith("Wed 18.11.  08:00–09:40  2 lessons  excused      Doctor")


def test_render_text_and_excuse_on_indented_lines():
    out = render(payload([item(text="had a  fever", excuse_text="note from parents")]))
    assert "\n    had a fever" in out and "\n    Excuse: note from parents" in out


def test_render_wraps_long_text():
    out = render(payload([item(text="word " * 40)]), width=40)
    body = [l for l in out.splitlines() if l.startswith("    ")]
    assert len(body) > 1 and all(len(l) <= 40 for l in body)


def test_render_without_grid_leaves_lessons_out():
    out = render(payload([item()], grid=[]))
    assert out.splitlines()[0] == "Absences since 01.09.2026 · 1 day · 1 not excused"
    assert "lesson" not in out


def test_render_empty():
    out = render(payload([]))
    assert out.splitlines()[0] == "Absences since 01.09.2026 · 0 days · 0 lessons · 0 not excused"
    assert out.endswith("No absences in this window.")


def test_render_error():
    assert render({"absences": {"error": "HTTP 403"}}) == "absences: HTTP 403"


def test_render_missing_section():
    assert render({}).startswith("Absences · 0 days")


def test_render_cached_age():
    out = render(payload([], cached_at="2026-11-23T11:46:00"))
    assert out.splitlines()[0].endswith("(cached, 14 min old)")


def test_render_colors_not_excused_red_and_excused_dim():
    out = render(payload([item(text="x"), item("2026-11-18", excused=True, text="y")]),
                 color=True)
    lines = out.splitlines()
    assert lines[0].startswith("\033[1m")                       # bold header
    assert any(l.startswith("\033[31mMon 16.11.") for l in lines)
    assert any(l.startswith("Wed 18.11.") for l in lines)       # excused row plain
    assert "\033[2m    y" in out                                # its text dimmed
    assert _plain(out) == render(payload([item(text="x"),
                                          item("2026-11-18", excused=True, text="y")]))


# --- client: reasons --------------------------------------------------------
def test_with_reasons_fills_empty_reason():
    out = _with_reasons([{"reasonId": 3, "reason": ""}, {"reasonId": 4}],
                        [{"id": 3, "name": "Illness"}, {"id": 4, "longName": "Doctor"}])
    assert [a["reason"] for a in out] == ["Illness", "Doctor"]


def test_with_reasons_keeps_given_reason_and_unknown_ids():
    given = {"reasonId": 3, "reason": "Own text"}
    unknown = {"reasonId": 9, "reason": ""}
    assert _with_reasons([given, unknown], [{"id": 3, "name": "Illness"}]) == [given, unknown]


def test_with_reasons_without_list_and_bad_entries():
    a = {"reasonId": 0, "reason": ""}
    assert _with_reasons([a], []) == [a]
    assert _with_reasons([a], ["junk", None]) == [a]


def test_with_reasons_does_not_change_the_input():
    a = {"reasonId": 3}
    _with_reasons([a], [{"id": 3, "name": "Illness"}])
    assert a == {"reasonId": 3}


async def test_get_absences_uses_absence_reasons():
    client = WebUntisClient.__new__(WebUntisClient)
    client._require_person = lambda: (42, "STUDENT")
    client._api_get = AsyncMock(return_value={"data": {
        "absences": [{"id": 1, "reasonId": 3, "reason": ""}],
        "absenceReasons": [{"id": 3, "name": "Illness"}], "excuseStatuses": None}})
    out = await client.get_absences(date(2026, 9, 1), TODAY)
    assert out == [{"id": 1, "reasonId": 3, "reason": "Illness"}]
    path, params = client._api_get.call_args.args
    assert path == "/classreg/absences/students"
    assert params["studentId"] == 42 and params["startDate"] == 20260901


async def test_get_absences_empty_response():
    client = WebUntisClient.__new__(WebUntisClient)
    client._require_person = lambda: (42, "STUDENT")
    client._api_get = AsyncMock(return_value={})
    assert await client.get_absences(date(2026, 9, 1), TODAY) == []


# --- scraper: time grid -----------------------------------------------------
def _scraper(grid):
    cfg = ScraperConfig(server="s", school="sc")
    client = MagicMock()
    client.time_grid = grid
    client.get_absences = AsyncMock(return_value=[
        {"id": 1, "startDate": 20261116, "endDate": 20261116, "startTime": 800,
         "endTime": 1335, "isExcused": False}])
    return Scraper(cfg, client)


async def test_scrape_absences_includes_time_grid():
    out = await _scraper(GRID)._scrape_absences(date(2026, 9, 1), TODAY)
    assert out["time_grid"] == GRID
    assert out["items"][0]["start_time"] == "08:00"


async def test_scrape_absences_without_time_grid():
    out = await _scraper(None)._scrape_absences(date(2026, 9, 1), TODAY)
    assert out["time_grid"] == []


# --- CLI --------------------------------------------------------------------
def parse(argv, defaults=()):
    return main_mod._parse_args(argv, today=TODAY, default_args=list(defaults))


@pytest.mark.parametrize("argv", [["--absences"], ["-A"]])
def test_absences_flag(argv):
    a = parse(argv)
    assert a.absences and a.sections


def test_absences_off_by_default_and_no_flag():
    assert not parse([]).absences
    assert not parse(["--no-absences"], defaults=["-A"]).absences


def test_absences_combines_with_tests_homework_and_windows():
    a = parse(["-A", "-t", "-H", "--from", "mon", "--to", "fri"])
    assert a.absences and a.tests and a.homework and a.window_given


@pytest.mark.parametrize("argv", [
    ["-A", "--oneline"], ["-A", "--table"], ["-A", "--start"], ["-A", "--now"],
    ["-A", "--changes"],
])
def test_absences_errors(argv):
    with pytest.raises(SystemExit) as exc:
        parse(argv)
    assert exc.value.code == 2


def test_live_with_absences_keeps_the_view():
    a = parse(["-A", "--live"])
    assert a.absences and not a.short


@pytest.mark.parametrize("argv, exams, homework, absences, from_start", [
    (["-A"], False, False, True, True),
    (["-A", "-t"], True, False, True, True),
    (["-t"], True, False, False, False),
    (["-H"], False, True, False, True),
])
def test_only_sections_with_absences(argv, exams, homework, absences, from_start):
    cfg = ScraperConfig(server="s", school="sc")
    main_mod._only_sections(cfg, parse(argv))
    assert (cfg.scrape_exams, cfg.scrape_homework, cfg.scrape_absences) == \
        (exams, homework, absences)
    assert not (cfg.scrape_timetable or cfg.scrape_messages)
    assert cfg.until_school_year_end and cfg.from_school_year_start is from_start


def test_only_sections_absences_with_a_window():
    cfg = ScraperConfig(server="s", school="sc")
    main_mod._only_sections(cfg, parse(["-A", "--week"]))
    assert cfg.scrape_absences and not (cfg.until_school_year_end or cfg.from_school_year_start)


async def _async_main(monkeypatch, tmp_path, capsys, argv, p):
    c = ScraperConfig(server="s", school="sc", output_dir=str(tmp_path))
    monkeypatch.setattr(main_mod, "load_config", lambda *a: c)
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "last.json")
    monkeypatch.setattr(main_mod, "_fetch", AsyncMock(return_value=p))
    code = await main_mod._async_main(parse(argv))
    return code, capsys.readouterr().out, c


async def test_async_main_prints_absences(monkeypatch, tmp_path, capsys):
    p = payload([item()], start=(date.today() - timedelta(days=30)).isoformat(),
                end=(date.today() + timedelta(days=200)).isoformat())
    p["meta"] = {"window": {"start": p["absences"]["start"], "end": p["absences"]["end"]}}
    code, out, cfg = await _async_main(monkeypatch, tmp_path, capsys,
                                       ["-A", "--color", "never"], p)
    assert code == 0 and out.startswith("Absences since")
    assert "6 lessons" in out and cfg.scrape_absences and not cfg.scrape_timetable


async def test_async_main_absences_after_tests_and_homework(monkeypatch, tmp_path, capsys):
    today = date.today()
    p = payload([item()])
    p["meta"] = {"window": {"start": (today - timedelta(days=20)).isoformat(),
                            "end": (today + timedelta(days=200)).isoformat()}}
    p["exams"] = {"exams": [{"date": (today - timedelta(days=5)).isoformat(), "name": "Old"},
                            {"date": (today + timedelta(days=5)).isoformat(), "name": "New"}]}
    p["homework"] = {"items": []}
    _, out, _ = await _async_main(monkeypatch, tmp_path, capsys,
                                  ["-t", "-H", "-A", "--color", "never"], p)
    assert out.index("Upcoming tests") < out.index("Homework ·") < out.index("Absences")


async def test_async_main_tests_with_absences_only_upcoming(monkeypatch, tmp_path, capsys):
    # Absences start at the school year's beginning, but tests stay upcoming only.
    today = date.today()
    p = payload([])
    p["meta"] = {"window": {"start": (today - timedelta(days=20)).isoformat(),
                            "end": (today + timedelta(days=200)).isoformat()}}
    p["exams"] = {"exams": [{"date": (today - timedelta(days=5)).isoformat(), "name": "Old"},
                            {"date": (today + timedelta(days=5)).isoformat(), "name": "New"}]}
    _, out, _ = await _async_main(monkeypatch, tmp_path, capsys,
                                  ["-t", "-A", "--color", "never"], p)
    assert "New" in out and "Old" not in out
