"""The --absences view: every absence of the window plus totals.

Lessons are counted with the school's time grid (the periods from
/app/data), not with the timetable: a period counts if the absence
overlaps it. Absences over several days are split per day; weekend days
in between don't count. Holidays aren't known here, so an absence across
a holiday counts its weekdays.
"""
from __future__ import annotations

import shutil
import textwrap
from datetime import date, datetime, timedelta
from typing import Any, Optional

from .summary import _cache_age, _fmt_day, _plain, _Style, use_color

DAY_START, DAY_END = "00:00", "24:00"


def _minutes(hm: str) -> int:
    """"08:00" -> 480, "24:00" -> 1440."""
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def absence_days(item: dict[str, Any]) -> list[tuple[date, str, str]]:
    """(day, from, to) for every weekday the absence covers: the first
    day from its start time, the last day until its end time, days in
    between whole. A missing time means the whole day."""
    if not item.get("start_date"):
        return []
    first = date.fromisoformat(item["start_date"])
    last = date.fromisoformat(item.get("end_date") or item["start_date"])
    if last < first:
        last = first
    out, day = [], first
    while day <= last:
        if day.weekday() < 5 or first == last:      # a weekend-only entry still counts
            frm = (item.get("start_time") or DAY_START) if day == first else DAY_START
            to = (item.get("end_time") or DAY_END) if day == last else DAY_END
            out.append((day, frm, to))
        day += timedelta(days=1)
    return out


def count_lessons(item: dict[str, Any], grid: list[dict[str, str]]) -> Optional[int]:
    """How many periods of the time grid the absence overlaps (None
    without a grid, then lessons can't be counted)."""
    if not grid:
        return None
    units = [(_minutes(u["start"]), _minutes(u["end"])) for u in grid
             if u.get("start") and u.get("end")]
    n = 0
    for _, frm, to in absence_days(item):
        lo, hi = _minutes(frm), _minutes(to)
        n += sum(1 for s, e in units if s < hi and e > lo)
    return n


def totals(items: list[dict[str, Any]], grid: list[dict[str, str]]) -> dict[str, Any]:
    """{"absences", "days", "lessons" (None without a grid), "not_excused"}.
    `days` are distinct days, even if two absences fall on the same day."""
    days = {d for item in items for d, _, _ in absence_days(item)}
    counts = [count_lessons(item, grid) for item in items]
    return {
        "absences": len(items),
        "days": len(days),
        "lessons": None if not grid else sum(c or 0 for c in counts),
        "not_excused": sum(1 for item in items if not item.get("is_excused")),
    }


def status(item: dict[str, Any]) -> str:
    """"excused", "not excused", or the school's own excuse status text
    (e.g. a pending excuse) if it isn't excused yet."""
    if item.get("is_excused"):
        return "excused"
    return (item.get("excuse_status") or "").strip() or "not excused"


def range_label(start: Optional[str], end: Optional[str], today: date) -> str:
    """"since 01.09.2026" while the window reaches today, otherwise
    "01.09.–20.11.2026"; "" if unknown."""
    if not start:
        return ""
    s = date.fromisoformat(start)
    e = date.fromisoformat(end) if end else None
    if e is None or e >= today:
        return f"since {s:%d.%m.%Y}"
    return f"{s:%d.%m.}–{e:%d.%m.%Y}" if s.year == e.year else f"{s:%d.%m.%Y}–{e:%d.%m.%Y}"


def _when(item: dict[str, Any]) -> str:
    """"Mon 16.11.  08:00–12:40" or "Mon 16.11. 08:00 – Wed 18.11. 12:40"."""
    start, end = item.get("start_date"), item.get("end_date") or item.get("start_date")
    frm, to = item.get("start_time") or "", item.get("end_time") or ""
    if start == end:
        times = f"{frm}–{to}" if frm and to else (frm or to)
        return f"{_fmt_day(start)}  {times}".rstrip()
    return f"{_fmt_day(start)} {frm} – {_fmt_day(end)} {to}".replace("  ", " ").strip()


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def render_absences(
    payload: dict[str, Any], color: Optional[bool] = None, today: Optional[date] = None,
    now: Optional[datetime] = None, width: int | None = None,
) -> str:
    """All absences of the window, oldest first, with totals in the
    header. Not excused ones are red; reason, text and excuse note go
    on indented lines."""
    st = _Style(use_color() if color is None else color)
    today = today or date.today()
    width = width or shutil.get_terminal_size((100, 24)).columns
    section = payload.get("absences") or {}
    if "error" in section:
        return st.red(f"absences: {section['error']}")
    items = sorted(section.get("items") or [],
                   key=lambda a: (a.get("start_date") or "", a.get("start_time") or ""))
    grid = section.get("time_grid") or []
    t = totals(items, grid)
    parts = [" ".join(p for p in ("Absences", range_label(section.get("start"),
                                                         section.get("end"), today)) if p),
             _plural(t["days"], "day")]
    if t["lessons"] is not None:
        parts.append(_plural(t["lessons"], "lesson"))
    parts.append(f"{t['not_excused']} not excused")
    header = st.bold(" · ".join(parts))
    meta = payload.get("meta") or {}
    if meta.get("cached_at"):
        header += "  " + st.yellow(f"({_cache_age(meta['cached_at'], now or datetime.now())})")
    lines = [header]
    if not items:
        return "\n".join(lines + ["", st.dim("No absences in this window.")])
    whens = [_when(a) for a in items]
    when_w = max(len(w) for w in whens)
    counts = [count_lessons(a, grid) for a in items]
    count_w = max(len(_plural(c, "lesson")) if c is not None else 0 for c in counts)
    stat_w = max(len(status(a)) for a in items)
    indent = " " * 4
    for a, when, n in zip(items, whens, counts):
        stat = status(a)
        cols = [when.ljust(when_w)]
        if count_w:
            cols.append((_plural(n, "lesson") if n is not None else "").ljust(count_w))
        cols += [stat.ljust(stat_w), (a.get("reason") or "").strip()]
        row = "  ".join(cols).rstrip()
        body = []
        for label, text in (("", a.get("text")), ("Excuse: ", a.get("excuse_text"))):
            text = " ".join((text or "").split())
            if text:
                body += [indent + b for b in textwrap.wrap(label + text,
                                                          max(width - len(indent), 20))]
        lines.append("")
        if a.get("is_excused"):
            lines += [row] + [st.dim(_plain(b)) for b in body]
        else:
            lines += [st.red(row)] + body
    return "\n".join(lines)
