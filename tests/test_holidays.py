"""Tests for --holidays: upcoming holidays and a countdown (#30)."""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from untis import cache
from untis import holidays as hol
from untis import main as main_mod
from untis.config import ScraperConfig, load_config
from untis.scraper import Scraper
from untis.summary import _plain

MON = date(2026, 10, 19)


def _h(name: str, start: str, end: str | None = None, **extra) -> dict:
    """A holiday as /app/data returns it."""
    return {"id": 1, "name": name, "start": f"{start}T00:00:00",
            "end": f"{end or start}T23:59:59", "bookable": False, **extra}


def _n(name: str, start: str, end: str | None = None) -> dict:
    """A normalized holiday."""
    return {"id": 1, "name": name, "start": start, "end": end or start}


def _payload(items: list[dict], **meta) -> dict:
    return {"meta": {"window": {"start": "2026-10-19", "end": "2026-10-19"}, **meta},
            "holidays": {"source": "rest_v1", "items": items}}


AUTUMN = _n("Autumn break", "2026-11-02", "2026-11-08")
CHRISTMAS = _n("Christmas", "2026-12-31", "2027-01-13")


# --- normalize ---------------------------------------------------------------
def test_normalize_holiday():
    assert hol.normalize_holiday(_h("Autumn break", "2026-11-02", "2026-11-08")) == {
        "id": 1, "name": "Autumn break", "start": "2026-11-02", "end": "2026-11-08"}


def test_normalize_holiday_prefers_long_name_and_has_a_fallback():
    assert hol.normalize_holiday(_h("AB", "2026-11-02", longName="Autumn break"))["name"] \
        == "Autumn break"
    assert hol.normalize_holiday({"start": "2026-11-02", "end": "2026-11-02"})["name"] \
        == "Holidays"


def test_normalize_holiday_plain_dates_and_swapped_range():
    out = hol.normalize_holiday({"name": "X", "start": "2026-11-08", "end": "2026-11-02"})
    assert (out["start"], out["end"]) == ("2026-11-02", "2026-11-08")


@pytest.mark.parametrize("raw", [{"name": "X"}, {"name": "X", "start": "soon", "end": "later"},
                                 {"name": "X", "start": "2026-11-02"}])
def test_normalize_holiday_unusable(raw):
    assert hol.normalize_holiday(raw) is None


def test_normalize_holidays_sorts_filters_and_skips_junk():
    raw = [_h("Christmas", "2026-12-31", "2027-01-13"), "junk", {"name": "no dates"},
           _h("Old", "2025-12-31", "2026-01-13"), _h("Autumn", "2026-11-02", "2026-11-08")]
    assert [h["name"] for h in hol.normalize_holidays(raw)] == ["Old", "Autumn", "Christmas"]
    assert [h["name"] for h in hol.normalize_holidays(raw, since=date(2026, 9, 21))] == [
        "Autumn", "Christmas"]
    assert hol.normalize_holidays(None) == []


# --- breaks ----------------------------------------------------------------
@pytest.mark.parametrize("prev_end, start, touches", [
    (date(2026, 11, 1), date(2026, 11, 2), True),     # adjacent
    (date(2026, 11, 6), date(2026, 11, 2), True),     # overlapping
    (date(2026, 10, 30), date(2026, 11, 2), True),     # Fri -> Mon: only a weekend
    (date(2026, 10, 29), date(2026, 11, 2), False),    # Friday is a school day
    (date(2026, 10, 27), date(2026, 10, 29), False),
])
def test_touches(prev_end, start, touches):
    assert hol._touches(prev_end, start) is touches


def test_merge_breaks_joins_touching_days_and_keeps_the_longest_name():
    items = [_n("Bridge day", "2026-11-02"), _n("Autumn break", "2026-11-03", "2026-11-08"),
             _n("All Saints", "2026-11-08"), CHRISTMAS]
    assert hol.merge_breaks(items) == [
        {"id": 1, "name": "Autumn break", "start": "2026-11-02", "end": "2026-11-08"},
        CHRISTMAS]


def test_merge_breaks_over_a_weekend_and_does_not_change_the_input():
    items = [_n("Day 1", "2026-12-14"), _n("Day 2", "2026-12-15"), _n("Friday", "2026-12-18"),
             _n("Monday", "2026-12-21")]
    merged = hol.merge_breaks(items)
    assert [(h["start"], h["end"]) for h in merged] == [
        ("2026-12-14", "2026-12-15"), ("2026-12-18", "2026-12-21")]
    assert items[0]["end"] == "2026-12-14"
    assert hol.merge_breaks([]) == []


def test_upcoming_keeps_the_running_break_and_drops_past_ones():
    items = [_n("Summer", "2026-07-18", "2026-09-20"), AUTUMN, CHRISTMAS]
    assert hol.upcoming(items, MON) == [AUTUMN, CHRISTMAS]
    assert hol.upcoming(items, date(2026, 11, 4)) == [AUTUMN, CHRISTMAS]
    assert hol.upcoming(items, date(2026, 11, 8)) == [AUTUMN, CHRISTMAS]   # last day
    assert hol.upcoming(items, date(2026, 11, 9)) == [CHRISTMAS]


# --- counting --------------------------------------------------------------
@pytest.mark.parametrize("day, expected", [
    (date(2026, 11, 1), False), (date(2026, 11, 2), True), (date(2026, 11, 8), True),
    (date(2026, 11, 9), False)])
def test_is_holiday(day, expected):
    assert hol.is_holiday(day, [AUTUMN]) is expected


def test_school_days_until():
    # Mon 19.10. .. Fri 30.10.: two school weeks, today included.
    assert hol.school_days_until(date(2026, 11, 2), MON, [AUTUMN]) == 10
    # A holiday in between doesn't count.
    assert hol.school_days_until(date(2026, 11, 2), MON,
                                 [AUTUMN, _n("Day off", "2026-10-21")]) == 9
    # From a Saturday; on the start day itself; start in the past.
    assert hol.school_days_until(date(2026, 11, 2), date(2026, 10, 31), []) == 0
    assert hol.school_days_until(MON, MON, []) == 0
    assert hol.school_days_until(date(2026, 10, 8), MON, []) == 0


def test_span_and_plural():
    assert hol._span(AUTUMN) == "02.11. – 08.11."
    assert hol._span(_n("Day", "2026-12-15")) == "15.12."
    assert hol._plural(1, "school day") == "1 school day"
    assert hol._plural(0, "school day") == "0 school days"
    assert hol._plural(17, "school day") == "17 school days"


@pytest.mark.parametrize("today, text", [
    (MON, "in 14 days (10 school days)"),
    (date(2026, 11, 1), "tomorrow (0 school days)"),
    (date(2026, 10, 30), "in 3 days (1 school day)"),
    (date(2026, 11, 2), "now, until 08.11."),
    (date(2026, 11, 8), "now, last day"),
])
def test_countdown(today, text):
    assert hol.countdown(AUTUMN, today, [AUTUMN]) == text


# --- render ------------------------------------------------------------------
def test_render_list_aligned():
    out = hol.render_holidays(_payload([CHRISTMAS, AUTUMN]), color=False, today=MON)
    assert out.splitlines() == [
        "Holidays · 2 upcoming",
        "",
        "Autumn break  02.11. – 08.11.  in 14 days (10 school days)",
        "Christmas     31.12. – 13.01.  in 73 days (48 school days)",
    ]


def test_render_running_break_is_highlighted():
    out = hol.render_holidays(_payload([AUTUMN]), color=True, today=date(2026, 11, 4))
    assert "\033[33mnow, until 08.11.\033[0m" in out
    assert _plain(out).splitlines()[-1] == "Autumn break  02.11. – 08.11.  now, until 08.11."


def test_render_empty_error_and_missing_section():
    assert "No upcoming holidays known." in hol.render_holidays(
        _payload([_n("Summer", "2026-07-18", "2026-09-20")]), color=False, today=MON)
    assert hol.render_holidays({"holidays": {"error": "HTTP 500"}}, color=False) \
        == "holidays: HTTP 500"
    assert hol.render_holidays({}, color=False, today=MON).startswith("Holidays · 0 upcoming")


def test_render_shows_cache_age():
    payload = _payload([AUTUMN], cached_at="2026-10-19T07:00:00")
    out = hol.render_holidays(payload, color=False, today=MON, now=datetime(2026, 10, 19, 7, 20))
    assert out.splitlines()[0] == "Holidays · 1 upcoming  (cached, 20 min old)"


@pytest.mark.parametrize("today, text", [
    (MON, "Autumn break starts in 14 days (10 school days left)."),
    (date(2026, 11, 1), "Autumn break starts tomorrow (0 school days left)."),
    (date(2026, 11, 3), "Autumn break is on now, until 08.11."),
    (date(2027, 1, 14), "No upcoming holidays known."),
])
def test_render_next_only(today, text):
    assert hol.render_holidays(_payload([AUTUMN, CHRISTMAS]), color=False, today=today,
                               next_only=True) == text


# --- scraper / client / config / cache ---------------------------------------
async def test_scraper_holidays_section_from_the_login_data():
    cfg = ScraperConfig(server="s", school="sc", scrape_timetable=False, scrape_exams=False,
                        scrape_homework=False, scrape_absences=False, scrape_messages=False,
                        scrape_holidays=True)
    client = MagicMock()
    client.user_display = "Max Muster"
    client.school_year_start = date(2026, 9, 21)
    client.holidays = [_h("Old", "2025-12-31", "2026-01-13"),
                       _h("Autumn break", "2026-11-02", "2026-11-08")]
    out = await Scraper(cfg, client).run(today=MON)
    assert out["holidays"] == {"source": "rest_v1", "items": [AUTUMN]}


async def test_scraper_holidays_without_data():
    cfg = ScraperConfig(server="s", school="sc", scrape_timetable=False, scrape_exams=False,
                        scrape_homework=False, scrape_absences=False, scrape_messages=False,
                        scrape_holidays=True)
    client = MagicMock(spec=["user_display"])
    client.user_display = "x"
    out = await Scraper(cfg, client).run(today=MON)
    assert out["holidays"] == {"source": "rest_v1", "items": []}


def test_holidays_not_scraped_by_default_but_configurable(tmp_path):
    assert ScraperConfig().scrape_holidays is False
    path = tmp_path / "config.json"
    path.write_text('{"server": "s", "school": "sc", "scrape_holidays": "yes"}')
    assert load_config(path, tmp_path / ".env").scrape_holidays is True


def test_cache_requires_holidays_only_when_asked():
    assert "holidays" in cache.MODULES
    entry = {"version": cache.CACHE_VERSION, "saved_at": "2026-10-19T07:00:00",
             "account": "s/sc/", "payload": {"meta": {"window": {
                 "start": "2026-10-19", "end": "2026-10-19"}}}}
    cfg = ScraperConfig(server="s", school="sc", scrape_timetable=False, scrape_exams=False,
                        scrape_homework=False, scrape_absences=False, scrape_messages=False,
                        start_date=MON)
    cache.from_cache(cfg, entry, MON, datetime(2026, 10, 19, 8))          # not asked: fine
    cfg.scrape_holidays = True
    with pytest.raises(cache.CacheMiss, match="no cached holidays"):
        cache.from_cache(cfg, entry, MON, datetime(2026, 10, 19, 8))


# --- CLI -----------------------------------------------------------------------
def parse(argv, defaults=()):
    return main_mod._parse_args(argv, today=MON, default_args=list(defaults))


def test_holidays_flag_is_a_section():
    args = parse(["--holidays"])
    assert args.holidays and args.sections
    assert parse(["--no-holidays"], ["--holidays"]).holidays is False


@pytest.mark.parametrize("argv", [["--holidays", "--oneline"], ["--holidays", "--table"],
                                  ["--holidays", "--start"], ["--holidays", "--now"],
                                  ["--holidays", "--changes"]])
def test_holidays_conflicts(capsys, argv):
    with pytest.raises(SystemExit) as exc:
        parse(argv)
    assert exc.value.code == 2
    assert "--holidays" in capsys.readouterr().err


def test_only_sections_holidays_alone_fetches_nothing_else():
    cfg = ScraperConfig(server="s", school="sc")
    args = parse(["--holidays", "--next"])
    main_mod._apply_date_shortcuts(cfg, args, MON)
    main_mod._only_sections(cfg, args)
    assert cfg.scrape_holidays
    assert not (cfg.scrape_timetable or cfg.scrape_exams or cfg.scrape_homework
                or cfg.scrape_absences or cfg.scrape_messages)
    assert cfg.pick_day is None                  # --next: no timetable lookahead


def test_only_sections_holidays_with_tests_keeps_next_as_window():
    cfg = ScraperConfig(server="s", school="sc")
    args = parse(["--holidays", "--tests", "--next"])
    main_mod._apply_date_shortcuts(cfg, args, MON)
    main_mod._only_sections(cfg, args)
    assert cfg.scrape_holidays and cfg.scrape_exams and cfg.pick_day == "next"


@pytest.mark.parametrize("flag", ["--now", "--start", "--changes"])
async def test_other_answers_never_need_holidays(monkeypatch, tmp_path, flag):
    c = ScraperConfig(server="s", school="sc", output_dir=str(tmp_path), scrape_holidays=True)
    monkeypatch.setattr(main_mod, "load_config", lambda *a: c)
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "last.json")
    monkeypatch.setattr(main_mod, "CHANGES_PATH", tmp_path / "changes.json")
    fetch = AsyncMock(return_value={"meta": {"window": {"start": "2026-10-19"}},
                                    "timetable": {"days": []}})
    monkeypatch.setattr(main_mod, "_fetch", fetch)
    await main_mod._async_main(parse([flag]))
    assert c.scrape_holidays is False


async def test_async_main_prints_holidays(monkeypatch, tmp_path, capsys):
    c = ScraperConfig(server="s", school="sc", output_dir=str(tmp_path))
    monkeypatch.setattr(main_mod, "load_config", lambda *a: c)
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "last.json")
    far = _n("Far away", "2099-12-31", "2100-01-13")
    monkeypatch.setattr(main_mod, "_fetch", AsyncMock(return_value=_payload([far])))
    await main_mod._async_main(parse(["--holidays", "--color", "never", "--no-json"]))
    out = capsys.readouterr().out
    assert out.startswith("Holidays · 1 upcoming") and "Far away" in out
    await main_mod._async_main(parse(["--holidays", "--next", "--color", "never",
                                      "--no-json"]))
    assert capsys.readouterr().out.startswith("Far away starts in ")
