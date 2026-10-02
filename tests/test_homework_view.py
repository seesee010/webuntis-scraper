"""Tests for the --homework view and its school-year / due-date window (#4)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from untis import cache
from untis import main as main_mod
from untis.config import ScraperConfig
from untis.scraper import FALLBACK_YEAR_DAYS, HOMEWORK_LOOKBACK_DAYS, Scraper
from untis.summary import _homework_order, _plain, render_homework, render_tests
from untis.untis_client import _school_year_bound, _school_year_end

SAT = date(2026, 10, 3)
YEAR = {"currentSchoolYear": {"dateRange": {"start": "2026-09-14", "end": "2027-07-11"}}}


# --- school year bounds ----------------------------------------------------
def test_school_year_bounds():
    assert _school_year_bound(YEAR, "start") == date(2026, 9, 14)
    assert _school_year_bound(YEAR, "end") == date(2027, 7, 11) == _school_year_end(YEAR)
    assert _school_year_bound({}, "start") is None
    assert _school_year_bound({"currentSchoolYear": {"dateRange": {"start": "x"}}}, "start") is None


def _scraper(year_start=date(2026, 9, 14), year_end=date(2027, 7, 11), **kw):
    client = MagicMock()
    client.school_year_start, client.school_year_end = year_start, year_end
    client.get_homework = AsyncMock(return_value=[])
    return Scraper(ScraperConfig(server="s", school="sc", **kw), client), client


def test_window_whole_school_year():
    s, _ = _scraper(until_school_year_end=True, from_school_year_start=True)
    assert s._window(SAT) == (date(2026, 9, 14), date(2027, 7, 11))
    assert s._counts_school_days() is False


@pytest.mark.parametrize("year_start", [None, date(2026, 12, 1)])
def test_window_school_year_start_fallback(year_start):
    s, _ = _scraper(year_start=year_start, until_school_year_end=True, from_school_year_start=True)
    assert s._window(SAT)[0] == SAT - timedelta(days=FALLBACK_YEAR_DAYS)


def test_from_school_year_start_alone_disables_school_day_counting():
    s, _ = _scraper(from_school_year_start=True, days_forward=4)
    assert s._counts_school_days() is False


# --- homework by due date ----------------------------------------------------
def _hw(hid, given, due, completed=False):
    return {"id": hid, "date": int(given.replace("-", "")), "dueDate": int(due.replace("-", "")),
            "text": f"task {hid}", "completed": completed}


async def test_homework_by_due_date_fetches_from_year_start_and_filters():
    s, client = _scraper(homework_by_due_date=True)
    client.get_homework = AsyncMock(return_value=[
        _hw(1, "2026-09-20", "2026-10-05"),     # given before the window, due inside
        _hw(2, "2026-10-04", "2026-10-20"),     # due after the window
        _hw(3, "2026-09-15", "2026-09-30"),     # due before the window
    ])
    out = await s._scrape_homework(SAT, date(2026, 10, 9))
    client.get_homework.assert_awaited_once_with(date(2026, 9, 14), date(2026, 10, 9))
    assert [h["id"] for h in out["items"]] == [1]


async def test_homework_by_due_date_without_year_start_looks_back():
    s, client = _scraper(year_start=None, homework_by_due_date=True)
    await s._scrape_homework(SAT, SAT)
    assert client.get_homework.await_args.args[0] == SAT - timedelta(days=HOMEWORK_LOOKBACK_DAYS)


async def test_homework_without_due_date_mode_is_unchanged():
    s, client = _scraper()
    client.get_homework = AsyncMock(return_value=[_hw(1, "2026-10-03", "2026-12-01")])
    out = await s._scrape_homework(SAT, SAT)
    client.get_homework.assert_awaited_once_with(SAT, SAT)
    assert len(out["items"]) == 1


def test_offline_window_whole_year():
    c = ScraperConfig(server="s", school="sc", until_school_year_end=True,
                      from_school_year_start=True)
    payload = {"meta": {"window": {"start": "2026-09-14", "end": "2027-07-11"}}}
    assert cache.offline_window(c, payload, SAT, datetime(2026, 10, 3))[:2] == \
        (date(2026, 9, 14), date(2027, 7, 11))


# --- render_tests(upcoming_only) ---------------------------------------------
def test_tests_upcoming_only_hides_past_tests():
    payload = {"meta": {"window": {"start": "2026-09-14", "end": "2027-07-11"}},
               "exams": {"exams": [{"date": "2026-09-28", "name": "Old"},
                                   {"date": "2026-10-19", "name": "New"}]}}
    out = render_tests(payload, color=False, today=SAT, upcoming_only=True)
    assert out.startswith("Upcoming tests · 1 test in the next 281 days")
    assert "New" in out and "Old" not in out
    assert "Old" in render_tests(payload, color=False, today=SAT)


# --- render_homework -----------------------------------------------------------
ITEMS = [
    {"due_date": "2026-10-20", "text": "Read chapter 3", "subjects": [{"short": "GER"}],
     "teachers": [{"short": "TCH2"}], "completed": False},
    {"due_date": "2026-09-28", "text": "Essay", "subjects": [{"short": "ENG"}],
     "teachers": [{"short": "TCH1"}], "completed": False, "remark": "  hand in\n on paper ",
     "attachments": [{"name": "a.pdf"}]},
    {"due_date": "2026-10-05", "text": "p. 42, ex. 3-7", "subjects": [{"short": "MATH"}],
     "teachers": [{"short": "TCH3"}], "completed": False, "attachments": [{}, {}]},
    {"due_date": "2026-09-24", "text": "Vocabulary unit 2", "subjects": [{"short": "ENG"}],
     "teachers": [{"short": "TCH4"}], "completed": True},
]


def _payload(items=ITEMS, **meta):
    return {"meta": {"window": {"start": "2026-09-14", "end": "2027-07-11"}, **meta},
            "homework": {"items": items}}


def test_homework_order():
    ordered = sorted(ITEMS, key=_homework_order)
    assert [h["due_date"] for h in ordered] == ["2026-09-28", "2026-10-05", "2026-10-20",
                                                "2026-09-24"]


def test_render_homework_plain():
    out = render_homework(_payload(), color=False, today=SAT, width=80)
    lines = out.splitlines()
    assert lines[0] == "Homework · 3 open · 1 overdue · 1 done"
    blocks = out.split("\n\n")[1:]
    assert blocks[0].startswith("overdue  Mon 28.09.  ENG   TCH1  5 days ago")
    assert "    Essay" in blocks[0]
    assert "    Note: hand in on paper" in blocks[0]          # whitespace collapsed
    assert "📎 1 attachment" in blocks[0]
    assert blocks[1].startswith("due      Mon 05.10.  MATH  TCH3  in 2 days")
    assert "📎 2 attachments" in blocks[1]
    assert blocks[2].startswith("due      Tue 20.10.  GER   TCH2  in 17 days")
    assert blocks[3].startswith("✓        Thu 24.09.  ENG   TCH4") and "days" not in blocks[3]


def test_render_homework_wraps_long_text():
    long = {"due_date": "2026-10-05", "text": "word " * 40, "subjects": [{"short": "GER"}],
            "completed": False}
    out = render_homework(_payload([long]), color=False, today=SAT, width=40)
    body = [l for l in out.splitlines()[3:] if l.strip()]
    assert len(body) > 3 and all(len(l) <= 40 and l.startswith("    ") for l in body)


def test_render_homework_colors():
    out = render_homework(_payload(), color=True, today=SAT, width=80)
    lines = out.splitlines()
    overdue = next(l for l in lines if _plain(l).startswith("overdue"))
    assert overdue.startswith("\033[31m")
    done = next(l for l in lines if _plain(l).startswith("✓"))
    assert done.startswith("\033[2m")
    due = next(l for l in lines if _plain(l).startswith("due"))
    assert due.startswith("\033[1m")


def test_render_homework_empty_error_cache_age():
    assert render_homework(_payload([]), color=False, today=SAT).endswith(
        "No homework in this window.")
    assert render_homework({"homework": {"error": "HTTP 500"}}, color=False) == "homework: HTTP 500"
    out = render_homework(_payload([], cached_at="2026-10-03T08:46:00"), color=False, today=SAT,
                          now=datetime(2026, 10, 3, 9, 0))
    assert out.splitlines()[0].endswith("(cached, 14 min old)")


# --- CLI -------------------------------------------------------------------------
def parse(argv, defaults=()):
    return main_mod._parse_args(argv, today=SAT, default_args=list(defaults))


@pytest.mark.parametrize("flag", ["-H", "--homework"])
def test_homework_flag(flag):
    assert parse([flag]).homework is True


def test_homework_negation_and_conflicts(capsys):
    assert parse(["--no-homework"], ["-H"]).homework is False
    for argv in (["-H", "--start"], ["-H", "--oneline"], ["-H", "--table"]):
        with pytest.raises(SystemExit) as exc:
            parse(argv)
        assert exc.value.code == 2


@pytest.mark.parametrize("argv, exams, homework, until, from_start", [
    (["-t"], True, False, True, False),
    (["-H"], False, True, True, True),
    (["-t", "-H"], True, True, True, True),
    (["-H", "--days-forward", "5"], False, True, False, False),
])
def test_only_sections(argv, exams, homework, until, from_start):
    cfg = ScraperConfig(server="s", school="sc")
    main_mod._only_sections(cfg, parse(argv))
    assert (cfg.scrape_exams, cfg.scrape_homework) == (exams, homework)
    assert not (cfg.scrape_timetable or cfg.scrape_absences or cfg.scrape_messages)
    assert (cfg.until_school_year_end, cfg.from_school_year_start) == (until, from_start)
    assert cfg.homework_by_due_date is homework


async def test_async_main_prints_tests_then_homework(monkeypatch, tmp_path, capsys):
    c = ScraperConfig(server="s", school="sc", output_dir=str(tmp_path))
    monkeypatch.setattr(main_mod, "load_config", lambda *a: c)
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "last.json")
    today = date.today()
    payload = {"meta": {"window": {"start": (today - timedelta(days=20)).isoformat(),
                                   "end": (today + timedelta(days=200)).isoformat()}},
               "exams": {"exams": [{"date": (today - timedelta(days=5)).isoformat(), "name": "Old"},
                                   {"date": (today + timedelta(days=5)).isoformat(), "name": "New"}]},
               "homework": {"items": []}}
    monkeypatch.setattr(main_mod, "_fetch", AsyncMock(return_value=payload))
    await main_mod._async_main(parse(["-t", "-H", "--color", "never"]))
    out = capsys.readouterr().out
    assert out.index("Upcoming tests") < out.index("Homework ·")
    assert "New" in out and "Old" not in out                    # upcoming only
