"""Tests for the scraper's window handling (date shortcuts)."""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

from untis.config import ScraperConfig
from untis.scraper import Scraper


def _grid(*days: tuple[str, str]) -> dict:
    """(iso_date, status) per day, one lesson each."""
    return {"days": [{"date": d, "gridEntries": [{
        "type": "NORMAL_TEACHING_PERIOD", "status": status,
        "duration": {"start": f"{d}T07:50", "end": f"{d}T08:40"},
        "position1": [{"current": {"type": "SUBJECT", "shortName": "MATH"}}],
    }]} for d, status in days]}


def _scraper(pick: str | None, grid: dict) -> tuple[Scraper, MagicMock]:
    cfg = ScraperConfig(server="s", school="sc", pick_day=pick,
                        scrape_exams=False, scrape_homework=False,
                        scrape_absences=False, scrape_messages=False)
    client = MagicMock()
    client.user_display = "Max Muster"
    client.get_timetable_grid = AsyncMock(return_value=grid)
    client.get_own_classes = AsyncMock(return_value=set())
    return Scraper(cfg, client), client


async def test_tomorrow_skips_weekend_and_cancelled_day():
    grid = _grid(("2026-10-05", "CANCELLED"), ("2026-10-06", "REGULAR"),
                 ("2026-10-07", "REGULAR"))
    scraper, client = _scraper("tomorrow", grid)
    out = await scraper.run(today=date(2026, 10, 2), now=datetime(2026, 10, 2, 20, 0))

    assert out["meta"]["window"] == {
        "start": "2026-10-06", "end": "2026-10-06", "note": "next school day"}
    assert [d["date"] for d in out["timetable"]["days"]] == ["2026-10-06"]
    # Looked ahead from tomorrow, and fetched the timetable only once.
    assert client.get_timetable_grid.await_args.args[0] == date(2026, 10, 3)
    assert client.get_timetable_grid.await_count == 1


async def test_next_is_today_while_school_runs():
    scraper, _ = _scraper("next", _grid(("2026-10-02", "REGULAR")))
    out = await scraper.run(today=date(2026, 10, 2), now=datetime(2026, 10, 2, 8, 0))
    assert out["meta"]["window"] == {"start": "2026-10-02", "end": "2026-10-02"}


async def test_no_school_day_found():
    # Holidays: WebUntis returns the days, just without entries.
    holidays = {"days": [{"date": d, "status": "HOLIDAY", "gridEntries": []}
                         for d in ("2026-10-05", "2026-10-06")]}
    scraper, _ = _scraper("tomorrow", holidays)
    out = await scraper.run(today=date(2026, 10, 2), now=datetime(2026, 10, 2, 20, 0))
    assert out["meta"]["window"]["start"] == "2026-10-03"
    assert "no lessons" in out["meta"]["window"]["note"]


async def test_explicit_dates_override_days_forward():
    scraper, client = _scraper(None, _grid(("2026-09-30", "REGULAR")))
    scraper.cfg.start_date = scraper.cfg.end_date = date(2026, 9, 30)
    out = await scraper.run(today=date(2026, 10, 2))
    assert out["meta"]["window"] == {"start": "2026-09-30", "end": "2026-09-30"}


# --- --days-forward / --days-back count school days (#42) -----------------
import pytest  # noqa: E402
from datetime import timedelta  # noqa: E402

FRI = date(2026, 10, 2)


def _fake_untis(holidays: set[date] = frozenset(), fail: bool = False):
    """get_timetable_grid fake: weekdays have one lesson, weekends and
    `holidays` come back as empty days (like the real API)."""
    calls: list[tuple[date, date]] = []

    async def get_timetable_grid(start: date, end: date) -> dict:
        calls.append((start, end))
        if fail:
            raise RuntimeError("boom")
        days, d = [], start
        while d <= end:
            iso = d.isoformat()
            entries = [] if d.weekday() >= 5 or d in holidays else [{
                "type": "NORMAL_TEACHING_PERIOD", "status": "REGULAR",
                "duration": {"start": f"{iso}T07:50", "end": f"{iso}T08:40"},
                "position1": [{"current": {"type": "SUBJECT", "shortName": "MATH"}}],
            }]
            days.append({"date": iso, "gridEntries": entries})
            d += timedelta(days=1)
        return {"days": days}
    return get_timetable_grid, calls


def _window_scraper(back=0, fwd=4, holidays=frozenset(), fail=False, **cfg_kw):
    cfg = ScraperConfig(server="s", school="sc", days_back=back, days_forward=fwd,
                        scrape_exams=False, scrape_homework=False,
                        scrape_absences=False, scrape_messages=False, **cfg_kw)
    client = MagicMock()
    client.user_display = "Max Muster"
    client.get_timetable_grid, calls = _fake_untis(holidays, fail)
    client.get_own_classes = AsyncMock(return_value={"CLASS-A"})
    client.get_timetable = AsyncMock(side_effect=RuntimeError("no rpc either"))
    return Scraper(cfg, client), client, calls


def _shown(out) -> list[str]:
    return [d["date"] for d in out["timetable"]["days"] if d["entries"]]


async def test_days_forward_counts_school_days_from_friday():
    scraper, _, calls = _window_scraper(fwd=4)
    out = await scraper.run(today=FRI)
    assert _shown(out) == ["2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"]
    assert out["meta"]["window"] == {"start": "2026-10-02", "end": "2026-10-08"}
    assert len(calls) == 1                           # first guess was enough


async def test_today_stays_included_on_a_weekend():
    scraper, _, _ = _window_scraper(fwd=1)
    out = await scraper.run(today=date(2026, 10, 3))          # Saturday
    assert out["meta"]["window"] == {"start": "2026-10-03", "end": "2026-10-05"}


async def test_days_back_counts_school_days():
    scraper, _, _ = _window_scraper(back=2, fwd=0)
    out = await scraper.run(today=date(2026, 10, 5))          # Monday
    assert out["meta"]["window"] == {"start": "2026-10-01", "end": "2026-10-05"}
    assert _shown(out) == ["2026-10-01", "2026-10-02", "2026-10-05"]


async def test_back_and_forward_together():
    scraper, _, _ = _window_scraper(back=1, fwd=1)
    out = await scraper.run(today=FRI)
    assert out["meta"]["window"] == {"start": "2026-10-01", "end": "2026-10-05"}


async def test_holidays_trigger_extension_fetch():
    autumn = {date(2026, 10, 5) + timedelta(days=i) for i in range(12)}  # Mon 05.10.–Fri 16.10.
    scraper, _, calls = _window_scraper(fwd=2, holidays=autumn)
    out = await scraper.run(today=FRI)
    assert out["meta"]["window"]["end"] == "2026-10-20"       # Mon 19., Tue 20.
    assert len(calls) == 2                                    # one extension
    assert calls[1][0] == calls[0][1] + timedelta(days=1)     # adjacent range
    assert "note" not in out["meta"]["window"]


async def test_long_holidays_give_a_note():
    summer = {FRI + timedelta(days=i) for i in range(1, 120)}
    scraper, _, calls = _window_scraper(fwd=3, holidays=summer)
    out = await scraper.run(today=FRI)
    assert len(calls) == 1 + 4                                # MAX_EXTENSIONS
    assert "only 0 school days in the next" in out["meta"]["window"]["note"]


async def test_back_extension_finds_days_before_a_break():
    break_ = {date(2026, 10, 5) - timedelta(days=i) for i in range(1, 40)}   # 39 days
    scraper, _, calls = _window_scraper(back=2, fwd=0, holidays=break_)
    out = await scraper.run(today=date(2026, 10, 5))
    assert out["meta"]["window"]["start"] == "2026-08-25"    # 2 school days before the break
    assert "note" not in out["meta"]["window"]
    assert len(calls) > 1


async def test_back_note_when_break_is_longer_than_the_search():
    break_ = {date(2026, 10, 5) - timedelta(days=i) for i in range(1, 120)}
    scraper, _, _ = _window_scraper(back=2, fwd=0, holidays=break_)
    out = await scraper.run(today=date(2026, 10, 5))
    assert "only 0 school days in the last" in out["meta"]["window"]["note"]


async def test_calendar_days_keeps_old_behaviour():
    scraper, _, _ = _window_scraper(fwd=4, calendar_days=True)
    out = await scraper.run(today=FRI)
    assert out["meta"]["window"] == {"start": "2026-10-02", "end": "2026-10-06"}


async def test_zero_days_is_just_today_without_lookahead():
    scraper, _, calls = _window_scraper(back=0, fwd=0)
    out = await scraper.run(today=FRI)
    assert out["meta"]["window"] == {"start": "2026-10-02", "end": "2026-10-02"}
    assert calls == [(FRI, FRI)]


async def test_fetch_error_falls_back_to_calendar_days():
    scraper, _, _ = _window_scraper(fwd=4, fail=True)
    out = await scraper.run(today=FRI)
    assert out["meta"]["window"] == {"start": "2026-10-02", "end": "2026-10-06"}
    assert "error" in out["timetable"]


@pytest.mark.parametrize("cfg_kw, expected", [
    ({"days_forward": 4}, True),
    ({"days_back": 2, "days_forward": 0}, True),
    ({"days_back": 0, "days_forward": 0}, False),
    ({"days_forward": 4, "calendar_days": True}, False),
    ({"days_forward": 4, "start_date": FRI}, False),
])
def test_counts_school_days(cfg_kw, expected):
    cfg = ScraperConfig(server="s", school="sc", **cfg_kw)
    assert Scraper(cfg, MagicMock())._counts_school_days() is expected


async def test_own_classes_are_fetched_once_and_errors_degrade():
    scraper, client, _ = _window_scraper()
    assert await scraper._get_own_classes() == {"CLASS-A"}
    assert await scraper._get_own_classes() == {"CLASS-A"}
    client.get_own_classes.assert_awaited_once()

    scraper2, client2, _ = _window_scraper()
    client2.get_own_classes = AsyncMock(side_effect=RuntimeError("403"))
    assert await scraper2._get_own_classes() == set()


async def test_scrape_timetable_uses_cache():
    scraper, _, calls = _window_scraper()
    first = await scraper._scrape_timetable(FRI, FRI)
    assert await scraper._scrape_timetable(FRI, date(2026, 12, 1)) is first
    assert len(calls) == 1


async def test_fetch_timetable_rest_then_jsonrpc_fallback():
    scraper, client, _ = _window_scraper()
    tt = await scraper._fetch_timetable(FRI, FRI)
    assert tt["source"] == "rest_v1" and tt["own_classes"] == ["CLASS-A"]

    client.get_timetable_grid = AsyncMock(return_value={"days": []})
    client.get_timetable = AsyncMock(return_value=[{"date": 20261002, "startTime": 750,
                                                    "endTime": 840, "su": [], "te": []}])
    tt = await scraper._fetch_timetable(FRI, FRI)
    assert tt["source"] == "jsonrpc" and tt["lessons"][0]["date"] == "2026-10-02"
