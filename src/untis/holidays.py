"""--holidays: upcoming school holidays and a countdown (#30).

The holidays come with REST v1 `/app/data`, which the client loads
during the session probe anyway, so this needs no extra request.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from .summary import _Style, _cache_age, use_color


def normalize_holiday(h: dict) -> Optional[dict[str, Any]]:
    """An entry of /app/data `holidays` -> {"id", "name", "start", "end"}
    with ISO dates; None if it has no usable dates."""
    try:
        start = date.fromisoformat(str(h.get("start") or "")[:10])
        end = date.fromisoformat(str(h.get("end") or "")[:10])
    except ValueError:
        return None
    if end < start:
        start, end = end, start
    return {
        "id": h.get("id"),
        "name": h.get("longName") or h.get("name") or "Holidays",
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


def normalize_holidays(raw: list[dict], since: Optional[date] = None) -> list[dict[str, Any]]:
    """All usable holidays, sorted by start. With `since`, only those that
    end on or after it (the API also returns many years of history)."""
    items = [n for n in (normalize_holiday(h) for h in raw or [] if isinstance(h, dict)) if n]
    if since:
        items = [h for h in items if h["end"] >= since.isoformat()]
    return sorted(items, key=lambda h: (h["start"], h["end"]))


def _touches(prev_end: date, start: date) -> bool:
    """No school day between prev_end and start (overlap, adjacent, or
    only a weekend in between)?"""
    day = prev_end + timedelta(days=1)
    while day < start:
        if day.weekday() < 5:
            return False
        day += timedelta(days=1)
    return True


def merge_breaks(items: list[dict]) -> list[dict]:
    """Merge holidays that overlap or touch (e.g. a single day right
    before the autumn break, or a public holiday inside it) into one
    break, named after its longest part."""
    out: list[dict] = []
    longest: list[int] = []
    for h in sorted(items, key=lambda h: (h["start"], h["end"])):
        start, end = date.fromisoformat(h["start"]), date.fromisoformat(h["end"])
        length = (end - start).days
        if out and _touches(date.fromisoformat(out[-1]["end"]), start):
            last = out[-1]
            if length > longest[-1]:
                last["name"], longest[-1] = h["name"], length
            last["end"] = max(last["end"], h["end"])
            continue
        out.append(dict(h))
        longest.append(length)
    return out


def upcoming(items: list[dict], today: date) -> list[dict]:
    """Breaks (merged holidays) that haven't ended yet, a running one
    included, by start."""
    return [h for h in merge_breaks(items) if h["end"] >= today.isoformat()]


def is_holiday(day: date, items: list[dict]) -> bool:
    iso = day.isoformat()
    return any(h["start"] <= iso <= h["end"] for h in items)


def school_days_until(start: date, today: date, items: list[dict]) -> int:
    """School days from today (included) up to `start` (excluded):
    Monday to Friday, minus holidays."""
    n, day = 0, today
    while day < start:
        if day.weekday() < 5 and not is_holiday(day, items):
            n += 1
        day += timedelta(days=1)
    return n


def _span(h: dict) -> str:
    start, end = date.fromisoformat(h["start"]), date.fromisoformat(h["end"])
    return f"{start:%d.%m.}" if start == end else f"{start:%d.%m.} – {end:%d.%m.}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def countdown(h: dict, today: date, items: list[dict]) -> str:
    """"in 24 days (17 school days)", "tomorrow (1 school day)",
    or for a running break "now, until 08.11."."""
    start, end = date.fromisoformat(h["start"]), date.fromisoformat(h["end"])
    if start <= today:
        return "now" + (f", until {end:%d.%m.}" if end > today else ", last day")
    days = (start - today).days
    when = "tomorrow" if days == 1 else f"in {days} days"
    return f"{when} ({_plural(school_days_until(start, today, items), 'school day')})"


def render_holidays(
    payload: dict[str, Any], color: Optional[bool] = None, today: Optional[date] = None,
    now=None, next_only: bool = False,
) -> str:
    """The upcoming holidays with a countdown (--holidays), or with
    `next_only` one sentence about the next one (--holidays --next)."""
    st = _Style(use_color() if color is None else color)
    today = today or date.today()
    section = payload.get("holidays") or {}
    if "error" in section:
        return st.red(f"holidays: {section['error']}")
    items = section.get("items") or []
    coming = upcoming(items, today)
    if next_only:
        if not coming:
            return st.dim("No upcoming holidays known.")
        h = coming[0]
        start = date.fromisoformat(h["start"])
        if start <= today:
            end = date.fromisoformat(h["end"])
            return f"{st.bold(h['name'])} is on now, until {end:%d.%m.}"
        days = (start - today).days
        school = school_days_until(start, today, items)
        when = "tomorrow" if days == 1 else f"in {days} days"
        return (f"{st.bold(h['name'])} starts {when} "
                f"({_plural(school, 'school day')} left).")
    header = st.bold(f"Holidays · {len(coming)} upcoming")
    meta = payload.get("meta") or {}
    if meta.get("cached_at") and now is not None:
        header += "  " + st.yellow(f"({_cache_age(meta['cached_at'], now)})")
    lines = [header]
    if not coming:
        return "\n".join(lines + ["", st.dim("No upcoming holidays known.")])
    name_w = max(len(h["name"]) for h in coming)
    span_w = max(len(_span(h)) for h in coming)
    lines.append("")
    for h in coming:
        when = countdown(h, today, items)
        line = f"{h['name'].ljust(name_w)}  {_span(h).ljust(span_w)}  "
        lines.append(line + (st.yellow(when) if when.startswith("now") else when))
    return "\n".join(lines)
