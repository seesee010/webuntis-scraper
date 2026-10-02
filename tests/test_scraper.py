"""Tests for the scraper's window handling (date shortcuts)."""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

from src.config import ScraperConfig
from src.scraper import Scraper


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
