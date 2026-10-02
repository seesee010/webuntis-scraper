"""Render the scraped payload as a compact per-day terminal view."""
from __future__ import annotations

import os
import re
import shutil
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


# Status -> ANSI SGR codes. One table, so all colors live in one place
# (and can become themes later, #45).
ROLE_STYLES: dict[str, str] = {
    "cancelled": "31;9",       # red, struck through
    "removed": "2;9",          # gray (dim), struck through: your class was taken out
    "changed": "32",           # green: substitute, moved, other change
    "substitution": "32",
    "extra": "32",             # additional lesson
    "no teacher": "33",        # yellow: teacher gone, nobody replaces them yet
    "exam": "1;35",            # bold magenta
    "event": "1;34",           # bold blue
    "added": "1;32",           # the substitute teacher / new room itself
    "gone": "31;9",            # a removed teacher / room
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
    def green(self, t: str) -> str: return self._wrap("32", t)

    def role(self, name: str, t: str) -> str:
        """Style `t` for a status from ROLE_STYLES (unknown -> unchanged)."""
        code = ROLE_STYLES.get(name)
        return self._wrap(code, t) if code else t


def resolve_color(mode: str = "auto") -> Optional[bool]:
    """--color auto|always|never -> the `color` argument of render_summary.
    "always" wins over NO_COLOR (explicit flags beat the env var)."""
    return {"always": True, "never": False}.get(mode)


def use_color() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _fmt_day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{WEEKDAYS[d.weekday()]} {d:%d.%m.}"


def _shorts(items: list[dict]) -> str:
    return ", ".join(x.get("short") or "?" for x in items)


def _elements(items: list[dict], st: _Style, base=None) -> tuple[str, str]:
    """Teachers or rooms as (plain, styled), so columns can be padded on
    the visible width. Substitutes / new rooms are highlighted, removed
    ones struck through (`~X~` without colors); `base` styles the rest."""
    plain, styled = [], []
    for t in items:
        name = t.get("short") or "?"
        if t.get("status") == "REMOVED":
            # Strikethrough needs ANSI; mark it textually without colors.
            plain.append(name if st.enabled else f"~{name}~")
            styled.append(st.role("gone", name) if st.enabled else f"~{name}~")
        elif t.get("replaces") or t.get("status") == "ADDED":
            note = f" (for {t['replaces']})" if t.get("replaces") else ""
            plain.append(name + note)
            styled.append(st.role("added", name) + st.dim(note))
        else:
            plain.append(name)
            styled.append(base(name) if base else name)
    return ", ".join(plain), ", ".join(styled)


def _teachers(items: list[dict], st: _Style) -> tuple[str, str]:
    return _elements(items, st)


def _rooms(items: list[dict], st: _Style) -> tuple[str, str]:
    return _elements(items, st, base=st.cyan)


def _label_tag(label: str, st: _Style) -> str:
    """The status word at the end of a row (not struck through itself)."""
    if label == "cancelled":
        return st.red(label)
    if label == "removed":
        return st.dim(label)
    return st.role(label, label) if label else ""


# Labels whose color also tints the subject (cancelled/removed restyle
# the whole line instead).
_TINTED_SUBJECT = ("changed", "substitution", "extra", "no teacher", "exam")


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
                "rooms": e.get("rooms") or [],
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
            "rooms": l.get("rooms") or [],
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
    room_w = max((len(_rooms(r["rooms"], st)[0]) for r in all_rows), default=0)
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
            r_plain, r_styled = _rooms(r["rooms"], st)

            gutter = st.bold(st.yellow("▶")) + " " if is_current else "  "
            # Pad on the visible width; ANSI codes would break f"{x:<11}".
            time_cell = (st.bold(time) if is_current else time) + " " * (11 - len(time))
            line = gutter + time_cell + "  "
            if r["subject"] and not r.get("is_event"):
                subject = (st.role(label, r["subject"]) if label in _TINTED_SUBJECT
                           else st.bold(r["subject"]))
                line += _pad(subject, r["subject"], subj_w) + "  "
                line += _pad(t_styled, t_plain, teach_w) + "  "
                line += _pad(r_styled, r_plain, room_w)
            else:
                # Events have no subject: title across the columns, then
                # whoever runs them.
                title = r["title"] or r["subject"]
                line += st.role("event", f"★ {title}")
                if t_plain:
                    line += f"  {t_styled}"
                if r_plain:
                    line += f"  {r_styled}"
            if r["note"]:
                line += f"  {st.dim(r['note'])}"
            if not label:
                line = line.rstrip()
            if label in ("cancelled", "removed"):
                line = st.role(label, _plain(line)) + "  " + _label_tag(label, st)
            elif label:
                line += "  " + _label_tag(label, st)
            if is_current:
                left = _minutes_between(live["now"], r["end"])
                line += "  " + st.bold(st.yellow(f"now · {_fmt_minutes(left)} left"))
            elif is_past and label not in ("cancelled", "removed"):
                line = st.dim(_plain(line))
            out.append(line)
    return out


# --- --oneline / --table (#23) ---------------------------------------------
def _days_rows(timetable: dict) -> dict[str, list[dict]]:
    days = _rows_from_grid(timetable) if "days" in timetable else _rows_from_lessons(timetable)
    return {d: sorted(rows, key=lambda r: (r["start"], r["subject"]))
            for d, rows in days.items() if d and rows}


def _grid_units(timetable: dict, days: dict[str, list[dict]]) -> list[tuple[str, str]]:
    """The school's periods (time grid from /app/data); without it, the
    distinct periods of the lessons themselves."""
    grid = [(u["start"], u["end"]) for u in timetable.get("time_grid") or []
            if u.get("start") and u.get("end")]
    if grid:
        return grid
    return sorted({(r["start"], r["end"]) for rows in days.values() for r in rows
                   if r["start"] and r["end"]})


def _slots(rows: list[dict], units: list[tuple[str, str]]) -> list[list[dict]]:
    """For every period, the rows overlapping it (a double lesson fills two)."""
    return [[r for r in rows if r["start"] < end and r["end"] > start] for start, end in units]


def _token(r: dict, st: _Style) -> str:
    """One lesson as a short token: MATH, ENG* (changed), ~GEO~ (cancelled
    or removed; struck through with colors), MATH! (exam), ★ EVENT."""
    if r.get("is_event") or not r["subject"]:
        return st.role("event", f"★ {r['title'] or r['subject']}")
    name, label = r["subject"], _label(r)
    if label in ("cancelled", "removed"):
        return st.role(label, name) if st.enabled else f"~{name}~"
    if label == "exam":
        return st.role("exam", name) + "!"
    if label in ("changed", "substitution", "extra", "no teacher"):
        return st.role(label, name) + "*"
    return name


def _cell(rows: list[dict], st: _Style, with_room: bool = False) -> str:
    """All lessons of one period, parallel ones joined with "/"."""
    parts, seen = [], set()
    for r in rows:
        key = (r["subject"], r.get("title"), _label(r))
        if key in seen:
            continue
        seen.add(key)
        text = _token(r, st)
        if with_room and len(rows) == 1 and r["rooms"]:
            text += " " + _rooms(r["rooms"], st)[1]
        parts.append(text)
    return "/".join(parts)


def _fit(styled: str, width: int) -> str:
    """Pad to `width` visible chars; cut longer text with "…" (the cut
    version drops colors, it can't be split safely)."""
    plain = _plain(styled)
    if len(plain) <= width:
        return styled + " " * (width - len(plain))
    return plain[: max(width - 1, 0)] + "…"


def _render_oneline(timetable: dict, st: _Style, window: dict | None = None) -> list[str]:
    days = _days_rows(timetable)
    if not days:
        return [st.dim("No lessons in this window.")]
    units = _grid_units(timetable, days)
    window = window or {}
    out = []
    for day_iso, rows in sorted(days.items()):
        slots = _slots(rows, units)
        used = [i for i, slot in enumerate(slots) if slot]
        tokens = ([_cell(slot, st) if slot else st.dim("-")
                   for slot in slots[used[0]: used[-1] + 1]] if used else [])
        placed = {id(r) for slot in slots for r in slot}
        tokens += [_token(r, st) for r in rows if id(r) not in placed]  # outside the grid
        note = window.get("note", "") if day_iso == window.get("start") else ""
        out.append(_day_header(day_iso, rows, note, st) + "  " + " ".join(tokens))
    return out


def _render_table(
    timetable: dict, st: _Style, window: dict | None = None, width: int | None = None,
) -> list[str]:
    days = _days_rows(timetable)
    if not days:
        return ["", st.dim("  No lessons in this window.")]
    width = width or shutil.get_terminal_size((100, 24)).columns
    units = _grid_units(timetable, days)
    weeks: dict[tuple[int, int], list[str]] = {}
    for day_iso in sorted(days):
        weeks.setdefault(date.fromisoformat(day_iso).isocalendar()[:2], []).append(day_iso)
    out: list[str] = []
    for week_days in weeks.values():
        slots = {d: _slots(days[d], units) for d in week_days}
        used = [i for i in range(len(units)) if any(slots[d][i] for d in week_days)]
        if not used:
            continue
        col_w = max(10, min(20, (width - 8) // len(week_days) - 2))
        out.append("")
        out.append((" " * 7 + "  ".join(_fit(st.bold(_fmt_day(d)), col_w)
                                       for d in week_days)).rstrip())
        for i in range(used[0], used[-1] + 1):
            cells = [_fit(_cell(slots[d][i], st, with_room=True), col_w) for d in week_days]
            out.append(f"{units[i][0]:<7}" + "  ".join(cells).rstrip())
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
    now: Optional[datetime] = None, layout: str = "days", width: int | None = None,
) -> str:
    """`now` marks the running lesson on today's block (default: the
    current time); pass it explicitly for tests."""
    st = _Style(use_color() if color is None else color)
    now = now or datetime.now()
    if layout == "oneline":
        section = payload.get("timetable") or {}
        if "error" in section:
            return st.red(f"timetable: {section['error']}")
        return "\n".join(_render_oneline(section, st, (payload.get("meta") or {}).get("window")))
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
        if name == "timetable" and layout == "table":
            lines += _render_table(section, st, window, width)
        elif name == "timetable":
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


# One example row per status for --legend (anonymized, like the README).
_LEGEND = [
    ("regular", "MATH", [{"short": "TCH1"}], [{"short": "R101"}], ""),
    ("cancelled", "GEO", [{"short": "TCH2"}], [{"short": "R101"}], "cancelled"),
    ("removed", "ETH", [{"short": "TCH5"}], [{"short": "R102"}], "removed"),
    ("substitute", "ENG", [{"short": "TCH4", "status": "ADDED", "replaces": "TCH3"}],
     [{"short": "R101"}], "changed"),
    ("new room", "PROG", [{"short": "TCH6"}],
     [{"short": "R205", "status": "ADDED", "replaces": "R101"}], "changed"),
    ("no teacher", "NET", [{"short": "TCH7", "status": "REMOVED"}], [{"short": "R103"}],
     "no teacher"),
    ("exam", "MATH", [{"short": "TCH1"}], [{"short": "R101"}], "exam"),
]


def render_legend(color: Optional[bool] = None) -> str:
    """What each color / marker in the day view means (--legend)."""
    st = _Style(use_color() if color is None else color)
    lines = [st.bold("Legend")]
    for name, subject, teachers, rooms, label in _LEGEND:
        t_plain, t_styled = _teachers(teachers, st)
        r_plain, r_styled = _rooms(rooms, st)
        subj = st.role(label, subject) if label in _TINTED_SUBJECT else st.bold(subject)
        row = f"{_pad(subj, subject, 5)}  {_pad(t_styled, t_plain, 15)}  {_pad(r_styled, r_plain, 15)}"
        if label in ("cancelled", "removed"):
            row = st.role(label, _plain(row))
        tag = _label_tag(label, st)
        lines.append(f"  {name:<11} {row}  {tag}".rstrip())
    lines.append(f"  {'event':<11} " + st.role("event", "★ EVENT") + "  TCH8, TCH9  "
                 + st.role("event", "event"))
    lines.append(f"  {'now':<11} " + st.bold(st.yellow("▶")) + " the running lesson, "
                 + st.dim("dimmed") + " = already over")
    return "\n".join(lines)
