"""Tests for the --tests view and the school-year window (#3)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from untis import cache
from untis import main as main_mod
from untis.config import ScraperConfig
from untis.scraper import FALLBACK_YEAR_DAYS, Scraper
from untis.summary import _plain, _relative_day, render_tests
from untis.untis_client import _school_year_end

SAT = date(2026, 10, 3)


# --- school year end -------------------------------------------------------
def test_school_year_end():
    assert _school_year_end({"currentSchoolYear": {"dateRange": {"start": "2026-09-14",
                                                                 "end": "2027-07-11"}}}) \
        == date(2027, 7, 11)
    assert _school_year_end({}) is None
    assert _school_year_end({"currentSchoolYear": {"dateRange": {"end": "soon"}}}) is None


def _scraper(end=None, **cfg_kw):
    cfg = ScraperConfig(server="s", school="sc", **cfg_kw)
    client = MagicMock()
    client.school_year_end = end
    return Scraper(cfg, client)


def test_window_until_school_year_end():
    s = _scraper(date(2027, 7, 11), until_school_year_end=True, days_forward=14)
    assert s._window(SAT) == (SAT, date(2027, 7, 11))
    assert s._counts_school_days() is False             # days_forward is ignored


@pytest.mark.parametrize("end", [None, date(2026, 1, 1), "2027-07-11"])
def test_window_until_school_year_end_fallback(end):
    s = _scraper(end, until_school_year_end=True)
    assert s._window(SAT) == (SAT, SAT + timedelta(days=FALLBACK_YEAR_DAYS))


def test_explicit_dates_win_over_school_year_end():
    s = _scraper(date(2027, 7, 11), until_school_year_end=True, start_date=SAT, end_date=SAT)
    assert s._window(SAT) == (SAT, SAT)


def test_offline_window_until_school_year_end():
    c = ScraperConfig(server="s", school="sc", until_school_year_end=True, days_forward=14)
    payload = {"meta": {"window": {"start": "2026-10-03", "end": "2027-07-11"}}}
    assert cache.offline_window(c, payload, SAT, datetime(2026, 10, 3, 9))[:2] == \
        (SAT, date(2027, 7, 11))


# --- _relative_day / render_tests --------------------------------------------
@pytest.mark.parametrize("delta, text", [(0, "today"), (1, "tomorrow"), (-1, "yesterday"),
                                         (16, "in 16 days"), (-3, "3 days ago")])
def test_relative_day(delta, text):
    assert _relative_day(SAT + timedelta(days=delta), SAT) == text


EXAMS = [
    {"date": "2026-11-09", "start_time": "09:40", "end_time": "10:30", "name": "1. SA",
     "subjects": [{"short": "GER"}], "teachers": [{"short": "TCH2"}], "rooms": [{"short": "R101"}]},
    {"date": "2026-10-19", "start_time": "10:45", "end_time": "11:35", "name": "Test",
     "subjects": [{"short": "PROG"}], "teachers": [{"short": "TCH1"}], "rooms": [{"short": "R101"}]},
    {"date": "2026-11-16", "start_time": "07:50", "name": "SA",
     "subjects": [{"short": "MATH"}], "teachers": [{"short": "TCH3"}], "rooms": []},
]


def _payload(exams=EXAMS, start="2026-10-03", end="2027-07-11", **meta):
    return {"meta": {"window": {"start": start, "end": end}, **meta}, "exams": {"exams": exams}}


def test_render_tests_sorted_aligned_with_relative_days():
    lines = render_tests(_payload(), color=False, today=SAT).splitlines()
    assert lines[0] == "Upcoming tests · 3 tests in the next 281 days"
    rows = lines[2:]
    assert [r.split()[2] for r in rows] == ["10:45–11:35", "09:40–10:30", "07:50"]
    assert rows[0].endswith("in 16 days") and rows[2].endswith("in 44 days")
    assert len({r.index("in ") for r in rows}) == 1      # "in N days" lines up (empty room)


def test_render_tests_past_window_grades_and_dimming():
    past = [{"date": "2026-09-28", "name": "Quiz", "subjects": [{"short": "ENG"}], "grade": "2"},
            {"date": "2026-10-05", "name": "Test", "subjects": [{"short": "PROG"}]}]
    out = render_tests(_payload(past, start="2026-09-21", end="2026-10-10"), color=True, today=SAT)
    lines = out.splitlines()
    assert _plain(lines[0]) == "Tests · 2 tests from 21.09.2026 to 10.10.2026"
    assert lines[2].startswith("\033[2m") and "grade: 2" in lines[2] and "5 days ago" in lines[2]
    assert not lines[3].startswith("\033[2m") and _plain(lines[3]).endswith("in 2 days")


def test_render_tests_singular_empty_and_error():
    assert "1 test in" in render_tests(_payload(EXAMS[:1]), color=False, today=SAT)
    assert render_tests(_payload([]), color=False, today=SAT).endswith("No tests in this window.")
    assert render_tests({"exams": {"error": "HTTP 403"}}, color=False) == "exams: HTTP 403"


def test_render_tests_shows_cache_age():
    out = render_tests(_payload(cached_at="2026-10-03T08:46:00"), color=False, today=SAT,
                       now=datetime(2026, 10, 3, 9, 0))
    assert out.splitlines()[0].endswith("(cached, 14 min old)")


def test_render_tests_exam_subject_colored():
    out = render_tests(_payload(EXAMS[1:2]), color=True, today=SAT)
    assert "\033[1;35mPROG\033[0m" in out


# --- CLI ---------------------------------------------------------------------
def parse(argv, defaults=()):
    return main_mod._parse_args(argv, today=SAT, default_args=list(defaults))


@pytest.mark.parametrize("flag", ["--tests", "-t", "--exams"])
def test_tests_aliases(flag):
    assert parse([flag]).tests is True


def test_tests_negation_and_window_given():
    assert parse(["--no-tests"], ["--tests"]).tests is False
    assert parse(["-t"]).window_given is False
    assert parse(["-t", "--days-forward", "5"]).window_given is True


@pytest.mark.parametrize("argv", [["-t", "--start"], ["-t", "--oneline"], ["-t", "--table"]])
def test_tests_conflicts(capsys, argv):
    with pytest.raises(SystemExit) as exc:
        parse(argv)
    assert exc.value.code == 2


@pytest.mark.parametrize("argv, until", [(["-t"], True), (["-t", "--week"], False),
                                         (["-t", "--days-forward", "3"], False)])
def test_only_tests_config(argv, until):
    cfg = ScraperConfig(server="s", school="sc")
    main_mod._only_sections(cfg, parse(argv))
    assert cfg.scrape_exams and not (cfg.scrape_timetable or cfg.scrape_homework
                                     or cfg.scrape_absences or cfg.scrape_messages)
    assert cfg.until_school_year_end is until


async def test_async_main_prints_tests(monkeypatch, tmp_path, capsys):
    c = ScraperConfig(server="s", school="sc", output_dir=str(tmp_path))
    monkeypatch.setattr(main_mod, "load_config", lambda *a: c)
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "last.json")
    fetch = AsyncMock(return_value=_payload(start=date.today().isoformat(),
                                            end=(date.today() + timedelta(days=30)).isoformat()))
    monkeypatch.setattr(main_mod, "_fetch", fetch)
    await main_mod._async_main(parse(["--tests", "--color", "never"]))
    assert capsys.readouterr().out.startswith("Upcoming tests")
    assert c.until_school_year_end and not c.scrape_timetable
