"""High-level orchestrator: coordinates the WebUntisClient and the
normalizer to produce a single structured payload."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any

from .config import ScraperConfig
from .dates import (
    merge_timetables,
    pick_school_day,
    school_day_span,
    school_day_window,
    school_days,
    trim_timetable,
)
from .normalize import (
    normalize_absence,
    normalize_exam,
    normalize_homework,
    normalize_message,
    normalize_timetable_grid,
    normalize_timetable_lesson,
)
from .untis_client import WebUntisClient

log = logging.getLogger(__name__)

# --tests without a window, if WebUntis doesn't report the school year end.
FALLBACK_YEAR_DAYS = 365
# --homework: how far back to look for homework given before the window
# (the API filters by lesson date, the view by due date).
HOMEWORK_LOOKBACK_DAYS = 120
# How far --tomorrow / --next look ahead for a school day (holidays!).
PICK_SEARCH_DAYS = 21
# --days-forward/--days-back: if holidays leave too few school days in the
# first guess, fetch this many more calendar days, up to MAX_EXTENSIONS times.
EXTEND_DAYS = 14
MAX_EXTENSIONS = 4


class Scraper:
    def __init__(self, cfg: ScraperConfig, client: WebUntisClient):
        self.cfg = cfg
        self.client = client
        self._timetable: dict[str, Any] | None = None
        self._own_classes: set[str] | None = None

    async def run(
        self, today: date | None = None, now: datetime | None = None,
    ) -> dict[str, Any]:
        today = today or date.today()
        now = now or datetime.now()
        start, end = self._window(today)
        note = ""
        if self.cfg.pick_day:
            start, note = await self._pick_day(today, now)
            end = start
        elif self._counts_school_days():
            start, end, note = await self._school_day_window(today)
        log.info("Scraping window: %s .. %s %s", start, end, note)

        result: dict[str, Any] = {
            "meta": {
                "school": self.cfg.school,
                "server": self.cfg.server,
                "user": self.client.user_display or self.cfg.username,
                "generated_at": date.today().isoformat(),
                "window": {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    **({"note": note} if note else {}),
                },
            }
        }

        tasks: list[tuple[str, Any]] = []
        if self.cfg.scrape_timetable:
            tasks.append(("timetable", self._scrape_timetable(start, end)))
        if self.cfg.scrape_exams:
            tasks.append(("exams", self._scrape_exams(start, end)))
        if self.cfg.scrape_homework:
            tasks.append(("homework", self._scrape_homework(start, end)))
        if self.cfg.scrape_absences:
            tasks.append(("absences", self._scrape_absences(start, end)))
        if self.cfg.scrape_messages:
            tasks.append(("messages", self._scrape_messages()))

        # Sequential, not parallel - the server throttles per session.
        for name, coro in tasks:
            try:
                result[name] = await coro
                log.info("✓ %-10s : %d entries", name, _count(result[name]))
            except Exception as exc:
                log.error("✗ %-10s : %s", name, exc)
                result[name] = {"error": str(exc)}

        return result

    def _window(self, today: date) -> tuple[date, date]:
        if self.cfg.start_date:
            return self.cfg.start_date, self.cfg.end_date or self.cfg.start_date
        start = today
        if self.cfg.from_school_year_start:
            year_start = getattr(self.client, "school_year_start", None)
            start = year_start if isinstance(year_start, date) and year_start <= today \
                else today - timedelta(days=FALLBACK_YEAR_DAYS)
        if self.cfg.until_school_year_end:
            end = getattr(self.client, "school_year_end", None)
            if not isinstance(end, date) or end < today:
                end = today + timedelta(days=FALLBACK_YEAR_DAYS)
            return start, end
        return (today - timedelta(days=self.cfg.days_back),
                today + timedelta(days=self.cfg.days_forward))

    def _counts_school_days(self) -> bool:
        return (not self.cfg.start_date and not self.cfg.calendar_days
                and not self.cfg.until_school_year_end and not self.cfg.from_school_year_start
                and (self.cfg.days_back > 0 or self.cfg.days_forward > 0))

    async def _school_day_window(self, today: date) -> tuple[date, date, str]:
        """Today plus the next --days-forward / previous --days-back school
        days (days with at least one entry that takes place), so weekends
        and holidays don't eat into the count."""
        back, fwd = self.cfg.days_back, self.cfg.days_forward
        lo = today - timedelta(days=school_day_span(back))
        hi = today + timedelta(days=school_day_span(fwd))
        try:
            tt = await self._fetch_timetable(lo, hi)
            for _ in range(MAX_EXTENSIONS):
                days = school_days(tt)
                more_fwd = len([d for d in days if d > today]) < fwd
                more_back = len([d for d in days if d < today]) < back
                if not (more_fwd or more_back):
                    break
                if more_fwd:
                    new_hi = hi + timedelta(days=EXTEND_DAYS)
                    tt = merge_timetables(
                        tt, await self._fetch_timetable(hi + timedelta(days=1), new_hi))
                    hi = new_hi
                if more_back:
                    new_lo = lo - timedelta(days=EXTEND_DAYS)
                    tt = merge_timetables(
                        await self._fetch_timetable(new_lo, lo - timedelta(days=1)), tt)
                    lo = new_lo
        except Exception as exc:
            log.warning("Could not count school days, using calendar days: %s", exc)
            self._timetable = None
            return (today - timedelta(days=back), today + timedelta(days=fwd), "")

        start, end, note = school_day_window(tt, today, back, fwd, lo, hi)
        self._timetable = trim_timetable(tt, start, end)
        return start, end, note

    async def _pick_day(self, today: date, now: datetime) -> tuple[date, str]:
        """Resolve --tomorrow / --next to a concrete school day by looking
        at the real timetable, so weekends, holidays and fully cancelled
        days are skipped without a holiday calendar."""
        mode = self.cfg.pick_day
        first = today + timedelta(days=1) if mode == "tomorrow" else today
        after = now if mode == "next" else None
        try:
            tt = await self._scrape_timetable(
                first, first + timedelta(days=PICK_SEARCH_DAYS))
        except Exception as exc:
            log.warning("Could not look ahead for the next school day: %s", exc)
            self._timetable = None
            return first, ""
        day = pick_school_day(tt, first, after)
        if day is None:
            self._timetable = None
            return first, f"no lessons in the next {PICK_SEARCH_DAYS} days"
        self._timetable = trim_timetable(tt, day, day)
        return day, ("next school day" if day != first else "")

    # --- module scrapers ------------------------------------------------

    async def _scrape_timetable(self, start: date, end: date) -> dict[str, Any]:
        """Timetable for the window (cached: the window logic may already
        have fetched and trimmed it)."""
        if self._timetable is None:
            self._timetable = await self._fetch_timetable(start, end)
        return self._timetable

    async def _fetch_timetable(self, start: date, end: date) -> dict[str, Any]:
        """Try the REST v1 grid first, fall back to JSON-RPC."""
        try:
            grid = await self.client.get_timetable_grid(start, end)
            if grid.get("days"):
                own_classes = await self._get_own_classes()
                grid_units = getattr(self.client, "time_grid", None)
                return {
                    "source": "rest_v1",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "own_classes": sorted(own_classes),
                    "time_grid": grid_units if isinstance(grid_units, list) else [],
                    **normalize_timetable_grid(grid, own_classes),
                }
        except Exception as exc:
            log.warning("REST v1 timetable failed, falling back to JSON-RPC: %s", exc)

        raw = await self.client.get_timetable(start, end)
        return {
            "source": "jsonrpc",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "lessons": [normalize_timetable_lesson(x) for x in raw],
        }

    async def _get_own_classes(self) -> set[str]:
        if self._own_classes is None:
            try:
                self._own_classes = await self.client.get_own_classes()
            except Exception as exc:
                log.warning("Could not determine own class: %s", exc)
                self._own_classes = set()
        return self._own_classes

    async def _scrape_exams(self, start: date, end: date) -> dict[str, Any]:
        try:
            raw = await self.client.get_exams(start, end)
            return {
                "source": "api",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "exams": [normalize_exam(x) for x in raw],
            }
        except Exception as exc:
            log.warning("Exam endpoint failed (%s), deriving exams from timetable", exc)

        tt = await self._scrape_timetable(start, end)
        entries = list(tt.get("lessons") or [])
        for day in tt.get("days") or []:
            entries.extend(day.get("entries") or [])
        return {
            "source": "timetable_fallback",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "exams": [e for e in entries if e.get("is_exam")],
            "note": "Derived from the timetable; exam endpoint not available.",
        }

    async def _scrape_homework(self, start: date, end: date) -> dict[str, Any]:
        fetch_start = start
        if self.cfg.homework_by_due_date:
            # The API filters by the lesson the homework was given in, so
            # homework due in the window may come from earlier lessons.
            year_start = getattr(self.client, "school_year_start", None)
            fetch_start = min(start, year_start if isinstance(year_start, date)
                              else start - timedelta(days=HOMEWORK_LOOKBACK_DAYS))
        raw = await self.client.get_homework(fetch_start, end)
        items = [normalize_homework(x) for x in raw]
        if self.cfg.homework_by_due_date:
            lo, hi = start.isoformat(), end.isoformat()
            items = [h for h in items if lo <= (h.get("due_date") or h.get("date") or "") <= hi]
        return {
            "source": "api",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "items": items,
        }

    async def _scrape_absences(self, start: date, end: date) -> dict[str, Any]:
        raw = await self.client.get_absences(start, end)
        grid = getattr(self.client, "time_grid", None)
        return {
            "source": "api",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "items": [normalize_absence(x) for x in raw],
            # The school's periods, to count missed lessons (--absences)
            # without fetching the timetable.
            "time_grid": grid if isinstance(grid, list) else [],
        }

    async def _scrape_messages(self) -> dict[str, Any]:
        raw = await self.client.get_messages()
        return {
            "source": "rest_v1",
            "items": [normalize_message(x) for x in raw],
        }


def _count(value: Any) -> int:
    if isinstance(value, dict):
        if "items" in value and isinstance(value["items"], list):
            return len(value["items"])
        if "lessons" in value and isinstance(value["lessons"], list):
            return len(value["lessons"])
        if "exams" in value and isinstance(value["exams"], list):
            return len(value["exams"])
        if "days" in value and isinstance(value["days"], list):
            return sum(len(d.get("entries") or []) for d in value["days"])
        return 0
    if isinstance(value, list):
        return len(value)
    return 0
