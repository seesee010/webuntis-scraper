"""When does school start / end on a day, and where are the gaps?

Used by --start / --end / --free. Only lessons that take place count:
a cancelled first period, or one your class was removed from, moves the
start later.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from .dates import WEEKDAY_NAMES, parse_day_spec

# Without the school's time grid, a gap shorter than this is a break.
MIN_GAP_MINUTES = 15


def query_day(text: str, today: date) -> date | str:
    """Day for --start/--end/--free: "next" (kept as is, needs the
    timetable), or a date. today/tomorrow (also German), dates, and
    weekday names, which mean the next such day (today included)."""
    key = text.strip().lower().rstrip(".")
    if key in ("next", "nächster", "naechster"):
        return "next"
    if key in WEEKDAY_NAMES:
        return today + timedelta(days=(WEEKDAY_NAMES[key] - today.weekday()) % 7)
    kind, value = parse_day_spec(text, today)
    assert kind == "date"
    return value


def _minutes(hm: str) -> int:
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def _merge(spans: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Merge overlapping/adjacent (start, end) "HH:MM" spans."""
    out: list[list[str]] = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return [(a, b) for a, b in out]


def free_periods(
    spans: list[tuple[str, str]], units: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """Free time between the first and the last lesson.

    With the school's time grid: the periods inside the school day that
    no lesson touches (consecutive ones merged). Without it: gaps of at
    least MIN_GAP_MINUTES between lessons (shorter ones are breaks).
    """
    if not spans:
        return []
    first, last = min(s for s, _ in spans), max(e for _, e in spans)
    if units:
        free = [(us, ue) for us, ue in units
                if us >= first and ue <= last
                and not any(s < ue and e > us for s, e in spans)]
        merged: list[tuple[str, str]] = []
        for us, ue in free:
            if merged and _minutes(us) - _minutes(merged[-1][1]) <= MIN_GAP_MINUTES:
                merged[-1] = (merged[-1][0], ue)
            else:
                merged.append((us, ue))
        return merged
    taken = _merge(spans)
    return [(a_end, b_start) for (_, a_end), (b_start, _) in zip(taken, taken[1:])
            if _minutes(b_start) - _minutes(a_end) >= MIN_GAP_MINUTES]


def day_info(timetable: dict[str, Any], day: date) -> Optional[dict[str, Any]]:
    """{"date", "start", "end", "first", "free"} for `day`, or None if no
    lesson takes place that day."""
    iso = day.isoformat()
    lessons = []
    for d in timetable.get("days") or []:
        if d.get("date") != iso:
            continue
        for e in d.get("entries") or []:
            if e.get("is_cancelled") or e.get("is_removed"):
                continue
            start, end = (e.get("start") or "")[11:16], (e.get("end") or "")[11:16]
            if start and end:
                name = ", ".join(s.get("short") or "?" for s in e.get("subjects") or []) \
                       or e.get("info") or e.get("lesson_text") or ""
                lessons.append((start, end, name))
    for l in timetable.get("lessons") or []:                 # JSON-RPC fallback
        if l.get("date") == iso and not l.get("is_cancelled"):
            name = ", ".join(s.get("short") or "?" for s in l.get("subjects") or [])
            lessons.append((l.get("start_time") or "", l.get("end_time") or "", name))
    lessons = [x for x in lessons if x[0] and x[1]]
    if not lessons:
        return None
    lessons.sort()
    units = [(u["start"], u["end"]) for u in timetable.get("time_grid") or []
             if u.get("start") and u.get("end")]
    spans = [(s, e) for s, e, _ in lessons]
    return {
        "date": iso,
        "start": lessons[0][0],
        "end": max(e for _, e, _ in lessons),
        "first": lessons[0][2],
        "free": [{"start": a, "end": b} for a, b in free_periods(spans, units)],
    }


def format_answer(info: Optional[dict[str, Any]], what: str) -> str:
    """The one-word text answer: "07:50", "13:25", free spans one per
    line, or "-" when there's no school."""
    if info is None:
        return "-"
    if what == "free":
        return "\n".join(f"{f['start']}–{f['end']}" for f in info["free"])
    return info[what]
