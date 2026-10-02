"""Render the scraped payload as a compact per-day terminal view."""
from __future__ import annotations

import os
import sys
from datetime import date
from typing import Any, Optional

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


def _render_timetable(timetable: dict, st: _Style) -> list[str]:
    days = _rows_from_grid(timetable) if "days" in timetable else _rows_from_lessons(timetable)
    days = {d: rows for d, rows in days.items() if d and rows}
    if not days:
        return [st.dim("  No lessons in this window.")]

    # Events don't use the columns, so they don't size them either.
    all_rows = [r for rows in days.values() for r in rows if r["subject"]]
    subj_w = max((len(r["subject"]) for r in all_rows), default=0)
    teach_w = max((len(_teachers(r["teachers"], st)[0]) for r in all_rows), default=0)
    room_w = max((len(r["rooms"]) for r in all_rows), default=0)
    out: list[str] = []
    for day_iso in sorted(days):
        out.append("")
        out.append(st.bold(_fmt_day(day_iso)))
        prev_slot = None
        for r in sorted(days[day_iso], key=lambda r: (r["start"], r["subject"])):
            slot = (r["start"], r["end"])
            time = f"{r['start']}–{r['end']}" if slot != prev_slot else ""
            prev_slot = slot

            label = _label(r)
            t_plain, t_styled = _teachers(r["teachers"], st)

            line = f"  {time:<11}  "
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
                line = st.dim(st.strike(line)) + "  " + st.red(label)
            elif label == "removed":
                line = st.dim(st.strike(line)) + "  " + st.dim(label)
            elif label == "exam":
                line += "  " + st.magenta(label)
            elif label == "event":
                line += "  " + st.blue(label)
            elif label:
                line += "  " + st.yellow(label)
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


def render_summary(payload: dict[str, Any], color: Optional[bool] = None) -> str:
    st = _Style(use_color() if color is None else color)
    meta = payload.get("meta") or {}
    window = meta.get("window") or {}
    lines = [st.bold(f"{meta.get('user') or ''}") + st.dim(
        f" · {meta.get('school') or ''} · {window.get('start', '')} → {window.get('end', '')}"
    )]

    for name, render in (("timetable", _render_timetable),
                         ("exams", _render_exams),
                         ("homework", _render_homework)):
        section = payload.get(name)
        if not section:
            continue
        if "error" in section:
            lines += ["", st.red(f"{name}: {section['error']}")]
            continue
        lines += render(section, st)

    counts = _count_line(payload, st)
    if counts:
        lines += ["", counts]
    errors = [n for n in ("absences", "messages") if "error" in (payload.get(n) or {})]
    for n in errors:
        lines.append(st.red(f"{n}: {payload[n]['error']}"))
    return "\n".join(lines)
