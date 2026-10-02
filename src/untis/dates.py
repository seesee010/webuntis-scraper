"""Date helpers for the CLI shortcuts (--date, --week, --tomorrow, --next)."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

_DOTTED = re.compile(r"^(\d{1,2})\.(\d{1,2})\.?(\d{4})?$")


def parse_date(text: str, today: date) -> date:
    """Parse "2026-10-12", "12.10.2026", "12.10." or "12.10".

    Without a year, pick the year that puts the date closest to today,
    so "05.01." in December means next January.
    """
    text = text.strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    m = _DOTTED.match(text)
    if not m:
        raise ValueError(f"invalid date {text!r} (use YYYY-MM-DD or DD.MM.[YYYY])")
    day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
    if year:
        return date(int(year), month, day)
    candidates = []
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            candidates.append(date(y, month, day))
        except ValueError:      # e.g. 29.02. in a non-leap year
            continue
    if not candidates:
        raise ValueError(f"invalid date {text!r}")
    return min(candidates, key=lambda d: abs((d - today).days))


def week_range(today: date, offset: int = 0) -> tuple[date, date]:
    """Monday..Sunday of the current week (offset=1: next week)."""
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    return monday, monday + timedelta(days=6)


def active_spans(timetable: dict[str, Any]) -> dict[str, list[tuple[str, str]]]:
    """Per ISO day: (start, end) "YYYY-MM-DDTHH:MM" of entries that
    actually take place for the user (not cancelled, class not removed)."""
    spans: dict[str, list[tuple[str, str]]] = {}
    for day in timetable.get("days") or []:
        for e in day.get("entries") or []:
            if e.get("is_cancelled") or e.get("is_removed"):
                continue
            spans.setdefault(day.get("date"), []).append((e.get("start") or "", e.get("end") or ""))
    for lesson in timetable.get("lessons") or []:
        if lesson.get("is_cancelled"):
            continue
        d = lesson.get("date") or ""
        spans.setdefault(d, []).append(
            (f"{d}T{lesson.get('start_time') or ''}", f"{d}T{lesson.get('end_time') or ''}")
        )
    return spans


def pick_school_day(
    timetable: dict[str, Any], first: date, after: Optional[datetime] = None,
) -> Optional[date]:
    """First day >= `first` with lessons that take place.

    With `after`, a day only counts if its last lesson ends after that
    moment (used by --next: today only while school isn't over yet).
    """
    cutoff = after.strftime("%Y-%m-%dT%H:%M") if after else ""
    for iso, spans in sorted(active_spans(timetable).items()):
        if not iso or iso < first.isoformat():
            continue
        if max(end for _, end in spans) > cutoff:
            return date.fromisoformat(iso)
    return None


def trim_timetable(timetable: dict[str, Any], start: date, end: date) -> dict[str, Any]:
    """Copy of a normalized timetable restricted to start..end."""
    s, e = start.isoformat(), end.isoformat()
    out = dict(timetable, start=s, end=e)
    if "days" in timetable:
        out["days"] = [d for d in timetable["days"] if s <= (d.get("date") or "") <= e]
    if "lessons" in timetable:
        out["lessons"] = [x for x in timetable["lessons"] if s <= (x.get("date") or "") <= e]
    raw = timetable.get("raw")
    if isinstance(raw, dict) and "days" in raw:
        out["raw"] = dict(raw, days=[d for d in raw["days"] if s <= (d.get("date") or "") <= e])
    return out


def school_days(timetable: dict[str, Any]) -> list[date]:
    """Sorted days on which at least one entry takes place for the user."""
    return [date.fromisoformat(d) for d in sorted(active_spans(timetable)) if d]


def school_day_span(n: int) -> int:
    """Calendar days that usually contain n school days (weekends plus a
    small buffer). Holidays are handled by fetching more if needed."""
    if n <= 0:
        return 0
    return n + 2 * ((n + 4) // 5) + 2


def merge_timetables(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Combine two normalized timetables of adjacent ranges."""
    out = {**b, **a}        # metadata (source, own_classes, …) from either
    for key in ("days", "lessons"):
        if key in a or key in b:
            out[key] = sorted(
                (a.get(key) or []) + (b.get(key) or []),
                key=lambda x: (x.get("date") or "", x.get("start_time") or ""),
            )
    out["start"] = min(a.get("start") or "9", b.get("start") or "9")
    out["end"] = max(a.get("end") or "", b.get("end") or "")
    if isinstance(a.get("raw"), dict) and isinstance(b.get("raw"), dict):
        out["raw"] = {"days": (a["raw"].get("days") or []) + (b["raw"].get("days") or [])}
    return out


# --- --from / --to (#43) ---------------------------------------------------
WEEKDAY_NAMES: dict[str, int] = {}
for _i, _names in enumerate([
    ("mon", "monday", "mo", "montag"),
    ("tue", "tues", "tuesday", "di", "dienstag"),
    ("wed", "wednesday", "mi", "mittwoch"),
    ("thu", "thur", "thurs", "thursday", "do", "donnerstag"),
    ("fri", "friday", "fr", "freitag"),
    ("sat", "saturday", "sa", "samstag"),
    ("sun", "sunday", "so", "sonntag"),
]):
    for _n in _names:
        WEEKDAY_NAMES[_n] = _i

RELATIVE_DAYS = {"today": 0, "heute": 0, "tomorrow": 1, "morgen": 1}


def parse_day_spec(text: str, today: date) -> tuple[str, date | int]:
    """Parse a --from/--to value.

    Returns ("date", <date>) for dates, today/tomorrow (also German), or
    ("weekday", 0..6) for weekday names (English/German, short or long,
    any case). Raises ValueError for anything else.
    """
    key = text.strip().lower().rstrip(".")
    if key in RELATIVE_DAYS:
        return "date", today + timedelta(days=RELATIVE_DAYS[key])
    if key in WEEKDAY_NAMES:
        return "weekday", WEEKDAY_NAMES[key]
    try:
        return "date", parse_date(text, today)
    except ValueError:
        raise ValueError(
            f"invalid day {text!r} (use a date like 12.10. / 2026-10-12, "
            "today, tomorrow, or a weekday like mon / montag)"
        ) from None


def resolve_from_to(
    from_text: str | None, to_text: str | None, today: date,
) -> tuple[date, date]:
    """Turn --from/--to into a (start, end) window.

    - A weekday for --from means that day of the current week (Mon-Sun),
      even if it already passed.
    - A weekday for --to means that day of the current week, unless that
      is before the start; then the next week(s).
    - Only --from: that single day. Only --to: from today.
    - An explicit --to before --from is an error.
    """
    if from_text is None and to_text is None:
        raise ValueError("--from or --to is required")
    monday = today - timedelta(days=today.weekday())

    if from_text is None:
        start = today
    else:
        kind, value = parse_day_spec(from_text, today)
        start = monday + timedelta(days=value) if kind == "weekday" else value

    if to_text is None:
        return start, start
    kind, value = parse_day_spec(to_text, today)
    if kind == "weekday":
        end = monday + timedelta(days=value)
        while end < start:
            end += timedelta(days=7)
    else:
        end = value
        if end < start:
            raise ValueError(f"--to ({end:%d.%m.%Y}) is before --from ({start:%d.%m.%Y})")
    return start, end
