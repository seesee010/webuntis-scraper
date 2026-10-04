"""The current and the next lesson (--now), for terminals and status bars.

The window is "next" (today while school runs, otherwise the next school
day), so after school or on a weekend the next lesson is the first one of
the next school day.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

from .summary import (
    _days_rows,
    _fmt_day,
    _fmt_minutes,
    _label,
    _minutes_between,
    _rooms,
    _Style,
    _takes_place,
    _teachers,
)


def now_state(timetable: dict[str, Any], day: date, now: datetime) -> dict[str, Any]:
    """{"day", "current": [rows], "next": [rows]}.

    `current` are the lessons running right now (parallel groups: all of
    them), `next` the lessons with the next start time. Cancelled lessons
    and lessons your class was removed from are skipped. On another day
    than today nothing is current and `next` is that day's first lesson.
    """
    rows = [r for r in _days_rows(timetable).get(day.isoformat(), []) if _takes_place(r)]
    hm = now.strftime("%H:%M") if day == now.date() else "00:00"
    current = [r for r in rows if r["start"] <= hm < r["end"]] if day == now.date() else []
    upcoming = [r for r in rows if r["start"] > hm]
    first = min((r["start"] for r in upcoming), default=None)
    return {"day": day.isoformat(),
            "current": current,
            "next": [r for r in upcoming if r["start"] == first]}


def _describe(rows: list[dict]) -> dict[str, Any] | None:
    """Plain-data view of one slot (parallel lessons joined with "/")."""
    if not rows:
        return None
    st = _Style(False)
    r = rows[0]
    labels = sorted({_label(x) for x in rows} - {""})
    return {
        "subject": "/".join(x["subject"] or x["title"] or "?" for x in rows),
        "teachers": "/".join(_teachers(x["teachers"], st)[0] for x in rows if x["teachers"]),
        "rooms": "/".join(_rooms(x["rooms"], st)[0] for x in rows if x["rooms"]),
        "start": r["start"],
        "end": max(x["end"] for x in rows),
        "status": labels[0] if labels else "",
    }


def now_data(state: dict[str, Any], now: datetime) -> dict[str, Any]:
    """The --format json answer."""
    cur, nxt = _describe(state["current"]), _describe(state["next"])
    if cur:
        cur["minutes_left"] = _minutes_between(now.strftime("%H:%M"), cur["end"])
    if nxt:
        nxt["date"] = state["day"]
        if state["day"] == now.date().isoformat():
            nxt["starts_in"] = _minutes_between(now.strftime("%H:%M"), nxt["start"])
    return {"now": cur, "next": nxt}


def _line(what: str, d: dict[str, Any], tail: str) -> str:
    parts = [what.ljust(4), d["subject"], d["teachers"], d["rooms"]]
    line = "  ".join(p for p in parts if p) + "   " + tail
    return line + (f"   {d['status']}" if d["status"] else "")


def format_text(data: dict[str, Any], today: date, idle_empty: bool = False) -> str:
    """Two short lines: what's running now and what comes next."""
    cur, nxt = data["now"], data["next"]
    lines = []
    if cur:
        lines.append(_line("now", cur, f"until {cur['end']} ({_fmt_minutes(cur['minutes_left'])})"))
    if nxt and not (idle_empty and not cur):
        when = f"{nxt['start']}–{nxt['end']}"
        if nxt["date"] != today.isoformat():
            when = f"{_fmt_day(nxt['date'])} {when}"
        lines.append(_line("next", nxt, when))
    return "\n".join(lines)


def short_minutes(minutes: int) -> str:
    """Compact duration for status bars: 12m, 1h05m."""
    minutes = max(minutes, 0)
    return f"{minutes}m" if minutes < 60 else f"{minutes // 60}h{minutes % 60:02d}m"


def format_waybar(data: dict[str, Any], today: date, idle_empty: bool = False) -> str:
    """Waybar custom-module JSON: {"text", "tooltip", "class"}.

    During a lesson: "MATH R101 · 12m". Otherwise the next lesson
    ("next: 09:40 ENG", with the weekday if it's not today), or an empty
    text with `idle_empty` (Waybar hides empty modules)."""
    cur, nxt = data["now"], data["next"]
    tooltip = format_text(data, today)
    if cur:
        text = f"{cur['subject']} {cur['rooms']}".strip() + f" · {short_minutes(cur['minutes_left'])}"
        css = cur["status"] or "lesson"
    elif nxt and not idle_empty:
        day = "" if nxt["date"] == today.isoformat() else f"{_fmt_day(nxt['date']).split()[0]} "
        text, css = f"next: {day}{nxt['start']} {nxt['subject']}", "idle"
    else:
        text, css = "", "idle"
    css = css.replace(" ", "-")
    return json.dumps({"text": text, "tooltip": tooltip, "class": css}, ensure_ascii=False)


def has_anything(data: dict[str, Any]) -> bool:
    return bool(data["now"] or data["next"])


def target_day(payload: dict[str, Any], today: date) -> date:
    window = (payload.get("meta") or {}).get("window") or {}
    try:
        return date.fromisoformat(window.get("start") or today.isoformat())
    except ValueError:
        return today


def answer(payload: dict[str, Any], fmt: str, today: date, now: datetime,
           idle_empty: bool = False) -> tuple[str, Optional[dict[str, Any]]]:
    """(output, data) for --now in the given format."""
    timetable = payload.get("timetable") or {}
    data = now_data(now_state(timetable, target_day(payload, today), now), now)
    if fmt == "json":
        return json.dumps(data, ensure_ascii=False), data
    if fmt == "waybar":
        return format_waybar(data, today, idle_empty), data
    return format_text(data, today, idle_empty), data
