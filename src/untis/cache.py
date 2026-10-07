"""Render views from the last fetched data (--offline / --max-age).

After every real fetch, the payload (without `raw`) is saved to a private
cache file. A later run can be answered from it, without a browser or any
network request, as long as the cache covers the requested window, is
from the same account and (for --max-age) is recent enough.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import ScraperConfig
from .dates import pick_school_day, school_day_window, trim_timetable
from .exporter import _strip_raw
from .privacy import write_private_text

CACHE_VERSION = 1
MODULES = ("timetable", "exams", "homework", "absences", "messages")
_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "": 60}


class CacheMiss(Exception):
    """The cache can't answer this request (missing, too old, not covering)."""


def parse_duration(text: str) -> int:
    """"90s" / "10m" / "2h" / "1d" -> seconds. A plain number means minutes."""
    m = _DURATION.match(text or "")
    if not m:
        raise ValueError(f"invalid duration {text!r} (use e.g. 90s, 10m, 2h, 1d)")
    return int(float(m.group(1)) * _UNIT_SECONDS[m.group(2).lower()])


def account_key(cfg: ScraperConfig) -> str:
    return f"{cfg.server}/{cfg.school}/{cfg.username}"


def save(path: Path, payload: dict[str, Any], cfg: ScraperConfig, now: datetime) -> None:
    entry = {
        "version": CACHE_VERSION,
        "saved_at": now.isoformat(timespec="seconds"),
        "account": account_key(cfg),
        "payload": _strip_raw(payload),
    }
    write_private_text(Path(path), json.dumps(entry, ensure_ascii=False))


def load(path: Path) -> dict[str, Any] | None:
    """The cache entry, or None if there is none / it's unreadable / outdated."""
    try:
        entry = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(entry, dict) or entry.get("version") != CACHE_VERSION:
        return None
    return entry


def age_seconds(entry: dict[str, Any], now: datetime) -> float:
    return (now - datetime.fromisoformat(entry["saved_at"])).total_seconds()


def offline_window(
    cfg: ScraperConfig, payload: dict[str, Any], today: date, now: datetime,
) -> tuple[date, date, str]:
    """The window a real run would use, worked out from the cached
    timetable instead of fetching (same rules as Scraper.run)."""
    tt = payload.get("timetable") or {}
    window = (payload.get("meta") or {}).get("window") or {}
    lo = date.fromisoformat(window.get("start") or today.isoformat())
    hi = date.fromisoformat(window.get("end") or today.isoformat())
    if cfg.start_date:
        return cfg.start_date, cfg.end_date or cfg.start_date, ""
    if cfg.until_school_year_end:          # --tests/--homework: the cached range
        start = lo if cfg.from_school_year_start else today
        return start, max(hi, today), ""
    if cfg.pick_day:
        first = today + timedelta(days=1) if cfg.pick_day == "tomorrow" else today
        day = pick_school_day(tt, first, now if cfg.pick_day == "next" else None)
        if day is None:
            raise CacheMiss(f"no school day after {first:%d.%m.} in the cached data")
        return day, day, ("next school day" if day != first else "")
    back, fwd = cfg.days_back, cfg.days_forward
    if cfg.calendar_days or not (back or fwd):
        return today - timedelta(days=back), today + timedelta(days=fwd), ""
    start, end, note = school_day_window(tt, today, back, fwd, lo, hi)
    if note:                       # not enough school days in the cache
        raise CacheMiss(f"cached data has {note}")
    return start, end, ""


def _in(value: str | None, start: date, end: date) -> bool:
    return bool(value) and start.isoformat() <= value[:10] <= end.isoformat()


def slice_payload(
    payload: dict[str, Any], start: date, end: date, note: str, saved_at: str,
    homework_by_due_date: bool = False,
) -> dict[str, Any]:
    """The cached payload restricted to start..end, marked as cached."""
    out = json.loads(json.dumps(payload))                  # deep copy
    meta = out.setdefault("meta", {})
    meta["window"] = {"start": start.isoformat(), "end": end.isoformat(),
                      **({"note": note} if note else {})}
    meta["cached_at"] = saved_at
    if "timetable" in out and "error" not in out["timetable"]:
        out["timetable"] = trim_timetable(out["timetable"], start, end)
    if "exams" in out and "exams" in out["exams"]:
        out["exams"]["exams"] = [e for e in out["exams"]["exams"] if _in(e.get("date"), start, end)]
    if "homework" in out and "items" in out["homework"]:
        primary, fallback = ("due_date", "date") if homework_by_due_date else ("date", "due_date")
        out["homework"]["items"] = [h for h in out["homework"]["items"]
                                    if _in(h.get(primary) or h.get(fallback), start, end)]
    if "absences" in out and "items" in out["absences"]:
        out["absences"]["items"] = [a for a in out["absences"]["items"]
                                    if _in(a.get("start_date"), start, end)]
    return out


def from_cache(
    cfg: ScraperConfig, entry: dict[str, Any], today: date, now: datetime,
    max_age: int | None = None,
) -> dict[str, Any]:
    """A payload answered from the cache, or CacheMiss with the reason."""
    if entry.get("account") != account_key(cfg):
        raise CacheMiss("cached data belongs to another account/school")
    if max_age is not None:
        age = age_seconds(entry, now)
        if age > max_age:
            raise CacheMiss(f"cached data is {int(age // 60)} min old (max {max_age // 60} min)")
    payload = entry.get("payload") or {}
    wanted = [m for m in MODULES if getattr(cfg, f"scrape_{m}")]
    missing = [m for m in wanted if m not in payload or "error" in (payload[m] or {})]
    if missing:
        raise CacheMiss(f"no cached {', '.join(missing)}")
    start, end, note = offline_window(cfg, payload, today, now)
    window = (payload.get("meta") or {}).get("window") or {}
    if not (window.get("start", "9") <= start.isoformat() and end.isoformat() <= window.get("end", "")):
        raise CacheMiss(
            f"cached data covers {window.get('start')}..{window.get('end')}, "
            f"not {start.isoformat()}..{end.isoformat()}")
    return slice_payload(payload, start, end, note, entry["saved_at"],
                         homework_by_due_date=cfg.homework_by_due_date)
