"""High-level orchestrator: coordinates the WebUntisClient and the
normalizer to produce a single structured payload."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any

from .config import ScraperConfig
from .dates import pick_school_day, trim_timetable
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

# How far --tomorrow / --next look ahead for a school day (holidays!).
PICK_SEARCH_DAYS = 21


class Scraper:
    def __init__(self, cfg: ScraperConfig, client: WebUntisClient):
        self.cfg = cfg
        self.client = client
        self._timetable: dict[str, Any] | None = None

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
        return (today - timedelta(days=self.cfg.days_back),
                today + timedelta(days=self.cfg.days_forward))

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
        """Try the REST v1 grid first, fall back to JSON-RPC."""
        if self._timetable is not None:
            return self._timetable
        try:
            grid = await self.client.get_timetable_grid(start, end)
            if grid.get("days"):
                try:
                    own_classes = await self.client.get_own_classes()
                except Exception as exc:
                    log.warning("Could not determine own class: %s", exc)
                    own_classes = set()
                self._timetable = {
                    "source": "rest_v1",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "own_classes": sorted(own_classes),
                    **normalize_timetable_grid(grid, own_classes),
                }
                return self._timetable
        except Exception as exc:
            log.warning("REST v1 timetable failed, falling back to JSON-RPC: %s", exc)

        raw = await self.client.get_timetable(start, end)
        self._timetable = {
            "source": "jsonrpc",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "lessons": [normalize_timetable_lesson(x) for x in raw],
        }
        return self._timetable

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
        raw = await self.client.get_homework(start, end)
        return {
            "source": "api",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "items": [normalize_homework(x) for x in raw],
        }

    async def _scrape_absences(self, start: date, end: date) -> dict[str, Any]:
        raw = await self.client.get_absences(start, end)
        return {
            "source": "api",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "items": [normalize_absence(x) for x in raw],
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
