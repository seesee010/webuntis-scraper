"""Render the scraped payload as a compact per-day terminal view."""
from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime
from typing import Any, Optional

_ANSI = re.compile(r"\033\[[0-9;]*m")

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Shown for entries without a more specific label (see _label()).
_STATUS_LABELS = {
    "CHANGED": "changed",
    "SUBSTITUTION": "substitution",
    "CANCEL": "cancelled",
    "CANCELLED": "cancelled",
    "ADDITIONAL": "extra",
    "EXAM": "exam",
}


class _Style:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled and text else text

    def bold(self, t: str) -> str: return self._wrap("1", t)
    def dim(self, t: str) -> str: return self._wrap("2", t)
    def red(self, t: str) -> str: return self._wrap("31", t)
    def yellow(self, t: str) -> str: return self._wrap("33", t)
    def magenta(self, t: str) -> str: return self._wrap("35", t)
    def blue(self, t: str) -> str: return self._wrap("34", t)
    def cyan(self, t: str) -> str: return self._wrap("36", t)
    def strike(self, t: str) -> str: return self._wrap("9", t)


def use_color() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _fmt_day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{WEEKDAYS[d.weekday()]} {d:%d.%m.}"


def _shorts(items: list[dict]) -> str:
    return ", ".join(x.get("short") or "?" for x in items)


def _teachers(items: list[dict], st: _Style) -> tuple[str, str]:
    """Return (plain, styled) so columns can be padded on visible width."""
    plain, styled = [], []
    for t in items:
        name = t.get("short") or "?"
        if t.get("status") == "REMOVED":
            # Strikethrough needs ANSI; mark it textually without colors.
            plain.append(name if st.enabled else f"~{name}~")
            styled.append(st.red(st.strike(name)) if st.enabled else f"~{name}~")
        elif t.get("replaces"):
            plain.append(f"{name} (for {t['replaces']})")
            styled.append(st.yellow(name) + st.dim(f" (for {t['replaces']})"))
        else:
            plain.append(name)
            styled.append(name)
    return ", ".join(plain), ", ".join(styled)


def _pad(styled: str, plain: str, width: int) -> str:
    return styled + " " * max(width - len(plain), 0)


def _rows_from_grid(timetable: dict) -> dict[str, list[dict]]:
    days: dict[str, list[dict]] = {}
    for day in timetable.get("days") or []:
        rows = []
        for e in day.get("entries") or []:
            rows.append({
                "start": (e.get("start") or "")[11:16],
                "end": (e.get("end") or "")[11:16],
                "status": e.get("status") or "REGULAR",
                "is_cancelled": e.get("is_cancelled"),
                "is_exam": e.get("is_exam"),
                "subject": _shorts(e.get("subjects") or []),
                "title": e.get("info") or e.get("lesson_text")
                         or (e.get("type") or "").replace("_", " ").title(),
                "teachers": e.get("teachers") or [],
                "rooms": _shorts(e.get("rooms") or []),
                "note": e.get("substitution_text") or e.get("lesson_text") or "",
                "is_event": e.get("is_event"),
                "is_removed": e.get("is_removed"),
                "no_teacher": e.get("no_teacher"),
            })
        days[day.get("date")] = rows
    return days


def _rows_from_lessons(timetable: dict) -> dict[str, list[dict]]:
    days: dict[str, list[dict]] = {}
    for l in timetable.get("lessons") or []:
        status = "CANCELLED" if l.get("is_cancelled") else (
            "CHANGED" if l.get("is_substitution") else "REGULAR")
        days.setdefault(l.get("date"), []).append({
            "start": l.get("start_time") or "",
            "end": l.get("end_time") or "",
            "status": status,
            "is_cancelled": l.get("is_cancelled"),
            "is_exam": l.get("is_exam"),
            "subject": _shorts(l.get("subjects") or []),
            "title": l.get("type") or "",
            "teachers": l.get("teachers") or [],
            "rooms": _shorts(l.get("rooms") or []),
            "note": l.get("substitution_text") or l.get("text") or "",
        })
    return days


def _label(r: dict) -> str:
    """Most specific label first: what matters for the student wins."""
    if r.get("is_cancelled"):
        return "cancelled"
    if r.get("is_removed"):
        return "removed"          # your class was taken out of the lesson
    if r.get("is_exam"):
        return "exam"
    if r.get("is_event"):
        return "event"
    if r.get("no_teacher"):
        return "no teacher"
    return _STATUS_LABELS.get(r.get("status") or "", "")


def _plain(text: str) -> str:
    """Strip ANSI codes, so a whole line can be restyled (dim/strike)
    without inner resets cutting the outer style short."""
    return _ANSI.sub("", text)


def _fmt_minutes(minutes: int) -> str:
    """5 -> "5 min", 65 -> "1 h 5 min", 120 -> "2 h"."""
    minutes = max(minutes, 0)
    hours, mins = divmod(minutes, 60)
    if not hours:
        return f"{mins} min"
    return f"{hours} h {mins} min" if mins else f"{hours} h"


def _minutes_between(hm_from: str, hm_to: str) -> int:
    """Minutes from "HH:MM" to "HH:MM" on the same day."""
    (h1, m1), (h2, m2) = (map(int, hm_from.split(":")), map(int, hm_to.split(":")))
    return (h2 * 60 + m2) - (h1 * 60 + m1)


def _takes_place(r: dict) -> bool:
    return not r.get("is_cancelled") and not r.get("is_removed")


def _live_state(day_iso: str, rows: list[dict], now: Optional[datetime]) -> Optional[dict]:
    """Where "now" is on today's (time-sorted) rows.

    Returns None unless `day_iso` is today and school isn't over yet.
    Otherwise: {"now": "HH:MM", "past": set of row indexes that ended,
    "current": set of indexes running right now (only lessons that take
    place), "line_before": index to put the "now" line in front of, or
    None while a lesson is running, "next_in": minutes until it}.
    """
    if now is None or day_iso != now.date().isoformat():
        return None
    hm = now.strftime("%H:%M")
    active = [r for r in rows if _takes_place(r) and r.get("start") and r.get("end")]
    if not active or hm >= max(r["end"] for r in active):
        return None                                     # no school / school is over
    state: dict[str, Any] = {"now": hm, "past": set(), "current": set(),
                             "line_before": None, "next_in": None}
    for i, r in enumerate(rows):
        if r.get("end") and r["end"] <= hm:
            state["past"].add(i)
        elif _takes_place(r) and r.get("start") and r["start"] <= hm < r.get("end", ""):
            state["current"].add(i)
    if not state["current"]:
        upcoming = [(i, r) for i, r in enumerate(rows)
                    if _takes_place(r) and r.get("start", "") > hm]
        if upcoming:
            i, r = upcoming[0]
            # Put the line before every row that hasn't started yet (also
            # cancelled ones in that slot), not just before the next lesson.
            state["line_before"] = min(j for j, x in enumerate(rows) if x.get("start", "") > hm)
            state["next_in"] = _minutes_between(hm, r["start"])
    return state


def _cache_age(cached_at: str, now: datetime) -> str:
    """"cached, 14 min old" for data answered from the cache."""
    minutes = int((now - datetime.fromisoformat(cached_at)).total_seconds() // 60)
    return "cached, just now" if minutes < 1 else f"cached, {_fmt_minutes(minutes)} old"


def _day_header(day_iso: str, rows: list[dict], note: str, st: _Style) -> str:
    """"Mon 05.10.  07:50–13:25" – span of what actually takes place."""
    header = st.bold(_fmt_day(day_iso))
    active = [r for r in rows if not r.get("is_cancelled") and not r.get("is_removed")]
    if active:
        header += st.dim(f"  {min(r['start'] for r in active)}–{max(r['end'] for r in active)}")
    if note:
        header += "  " + st.yellow(f"({note})")
    return header


def _render_timetable(
    timetable: dict, st: _Style, window: dict | None = None,
    now: Optional[datetime] = None,
) -> list[str]:
    days = _rows_from_grid(timetable) if "days" in timetable else _rows_from_lessons(timetable)
    days = {d: rows for d, rows in days.items() if d and rows}
    window = window or {}
    if not days:
        note = f" ({window['note']})" if window.get("note") else ""
        return ["", st.dim(f"  No lessons in this window.{note}")]

    # Events don't use the columns, so they don't size them either.
    all_rows = [r for rows in days.values() for r in rows if r["subject"]]
    subj_w = max((len(r["subject"]) for r in all_rows), default=0)
    teach_w = max((len(_teachers(r["teachers"], st)[0]) for r in all_rows), default=0)
    room_w = max((len(r["rooms"]) for r in all_rows), default=0)
    out: list[str] = []
    for day_iso in sorted(days):
        note = window.get("note", "") if day_iso == window.get("start") else ""
        out.append("")
        out.append(_day_header(day_iso, days[day_iso], note, st))
        rows = sorted(days[day_iso], key=lambda r: (r["start"], r["subject"]))
        live = _live_state(day_iso, rows, now)
        prev_slot = None
        for idx, r in enumerate(rows):
            if live and live["line_before"] == idx:
                out.append("  " + st.cyan(
                    f"──── now {live['now']} · next in {_fmt_minutes(live['next_in'])} ────"))
            is_current = bool(live) and idx in live["current"]
            is_past = bool(live) and idx in live["past"]
            slot = (r["start"], r["end"])
            time = f"{r['start']}–{r['end']}" if slot != prev_slot else ""
            prev_slot = slot

            label = _label(r)
            t_plain, t_styled = _teachers(r["teachers"], st)

            gutter = st.bold(st.yellow("▶")) + " " if is_current else "  "
            # Pad on the visible width; ANSI codes would break f"{x:<11}".
            time_cell = (st.bold(time) if is_current else time) + " " * (11 - len(time))
            line = gutter + time_cell + "  "
            if r["subject"] and not r.get("is_event"):
                line += _pad(st.bold(r["subject"]), r["subject"], subj_w) + "  "
                line += _pad(t_styled, t_plain, teach_w) + "  "
                line += _pad(st.cyan(r["rooms"]), r["rooms"], room_w)
            else:
                # Events have no subject: title across the columns, then
                # whoever runs them.
                title = r["title"] or r["subject"]
                line += st.bold(st.blue(f"★ {title}"))
                if t_plain:
                    line += f"  {t_styled}"
                if r["rooms"]:
                    line += f"  {st.cyan(r['rooms'])}"
            if r["note"]:
                line += f"  {st.dim(r['note'])}"
            if not label:
                line = line.rstrip()
            if label == "cancelled":
                line = st.dim(st.strike(_plain(line))) + "  " + st.red(label)
            elif label == "removed":
                line = st.dim(st.strike(_plain(line))) + "  " + st.dim(label)
            elif label == "exam":
                line += "  " + st.magenta(label)
            elif label == "event":
                line += "  " + st.blue(label)
            elif label:
                line += "  " + st.yellow(label)
            if is_current:
                left = _minutes_between(live["now"], r["end"])
                line += "  " + st.bold(st.yellow(f"now · {_fmt_minutes(left)} left"))
            elif is_past and label not in ("cancelled", "removed"):
                line = st.dim(_plain(line))
            out.append(line)
    return out


def _render_exams(exams: dict, st: _Style) -> list[str]:
    items = exams.get("exams") or []
    if not items:
        return []
    out = ["", st.bold("Exams")]
    for e in sorted(items, key=lambda e: (e.get("date") or "", e.get("start_time") or "")):
        when = _fmt_day(e["date"]) if e.get("date") else "?"
        if e.get("start_time"):
            when += f" {e['start_time']}"
        subj = _shorts(e.get("subjects") or [])
        name = e.get("name") or e.get("type") or ""
        rooms = _shorts(e.get("rooms") or [])
        line = f"  {when:<16} {st.magenta(subj)}  {name}"
        if rooms:
            line += f"  {st.cyan(rooms)}"
        out.append(line)
    return out


def _render_homework(homework: dict, st: _Style) -> list[str]:
    items = [h for h in homework.get("items") or [] if not h.get("completed")]
    if not items:
        return []
    out = ["", st.bold("Homework")]
    for h in sorted(items, key=lambda h: h.get("due_date") or ""):
        due = _fmt_day(h["due_date"]) if h.get("due_date") else "?"
        subj = _shorts(h.get("subjects") or [])
        text = " ".join((h.get("text") or "").split())
        out.append(f"  due {due}  {st.bold(subj)}  {text[:80]}")
    return out


def _count_line(payload: dict, st: _Style) -> str:
    parts = []
    absences = payload.get("absences") or {}
    if "items" in absences:
        n = len(absences["items"])
        unexcused = sum(1 for a in absences["items"] if not a.get("is_excused"))
        txt = f"{n} absence{'s' if n != 1 else ''}"
        if unexcused:
            txt += f" ({unexcused} not excused)"
        parts.append(st.red(txt) if unexcused else txt)
    messages = payload.get("messages") or {}
    if "items" in messages:
        unread = sum(1 for m in messages["items"] if not m.get("read"))
        txt = f"{unread} unread message{'s' if unread != 1 else ''}"
        parts.append(st.yellow(txt) if unread else txt)
    return st.dim(" · ").join(parts)


def render_summary(
    payload: dict[str, Any], color: Optional[bool] = None,
    now: Optional[datetime] = None,
) -> str:
    """`now` marks the running lesson on today's block (default: the
    current time); pass it explicitly for tests."""
    st = _Style(use_color() if color is None else color)
    now = now or datetime.now()
    meta = payload.get("meta") or {}
    window = meta.get("window") or {}
    header = st.bold(f"{meta.get('user') or ''}") + st.dim(
        f" · {meta.get('school') or ''} · {window.get('start', '')} → {window.get('end', '')}"
    )
    if meta.get("cached_at"):
        header += "  " + st.yellow(f"({_cache_age(meta['cached_at'], now)})")
    lines = [header]

    for name, render in (("timetable", _render_timetable),
                         ("exams", _render_exams),
                         ("homework", _render_homework)):
        section = payload.get(name)
        if not section:
            continue
        if "error" in section:
            lines += ["", st.red(f"{name}: {section['error']}")]
            continue
        if name == "timetable":
            lines += _render_timetable(section, st, window, now)
        else:
            lines += render(section, st)

    counts = _count_line(payload, st)
    if counts:
        lines += ["", counts]
    errors = [n for n in ("absences", "messages") if "error" in (payload.get(n) or {})]
    for n in errors:
        lines.append(st.red(f"{n}: {payload[n]['error']}"))
    return "\n".join(lines)
