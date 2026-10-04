"""What changed since the last --changes run (and desktop notifications).

A snapshot of lessons, exams and homework is kept in a private file. On
the next --changes run the fresh data is compared with it. Only days in
*both* windows are compared, so days that just moved out of the window
aren't reported as removed.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .privacy import write_private_text
from .summary import _days_rows, _fmt_day, _label, _rooms, _shorts, _Style, _teachers

log = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1
_PLAIN = _Style(False)


def _lesson_key(day: str, r: dict) -> str:
    return f"{day}|{r['start']}|{r['end']}|{r['subject'] or r['title']}"


def snapshot(payload: dict[str, Any], account: str, now: datetime) -> dict[str, Any]:
    """The comparable state of a payload."""
    lessons = {}
    for day, rows in _days_rows(payload.get("timetable") or {}).items():
        for r in rows:
            lessons[_lesson_key(day, r)] = {
                "status": _label(r) or "regular",
                "teachers": _teachers(r["teachers"], _PLAIN)[0],
                "rooms": _rooms(r["rooms"], _PLAIN)[0],
            }
    exams = {}
    for e in (payload.get("exams") or {}).get("exams") or []:
        subj = _shorts(e.get("subjects") or [])
        exams[f"{e.get('date')}|{subj}|{e.get('name') or ''}"] = {
            "date": e.get("date"), "subject": subj, "name": e.get("name") or "",
            "start": e.get("start_time") or ""}
    homework = {}
    for h in (payload.get("homework") or {}).get("items") or []:
        subj = _shorts(h.get("subjects") or [])
        digest = hashlib.sha1((h.get("text") or "").encode()).hexdigest()[:10]
        homework[f"{h.get('due_date')}|{subj}|{digest}"] = {
            "due": h.get("due_date"), "subject": subj, "text": " ".join((h.get("text") or "").split())}
    window = (payload.get("meta") or {}).get("window") or {}
    return {"version": SNAPSHOT_VERSION, "saved_at": now.isoformat(timespec="seconds"),
            "account": account, "window": {"start": window.get("start"), "end": window.get("end")},
            "lessons": lessons, "exams": exams, "homework": homework}


def load(path: Path) -> dict[str, Any] | None:
    try:
        snap = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return snap if isinstance(snap, dict) and snap.get("version") == SNAPSHOT_VERSION else None


def save(path: Path, snap: dict[str, Any]) -> None:
    write_private_text(Path(path), json.dumps(snap, ensure_ascii=False))


def _overlap(old: dict, new: dict) -> tuple[str, str]:
    lo = max(old["window"].get("start") or "", new["window"].get("start") or "")
    hi = min(old["window"].get("end") or "9", new["window"].get("end") or "9")
    return lo, hi


def diff(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    """Changes from `old` to `new`, sorted by date. Each is a dict with
    "date", "time", "subject" and "text"."""
    lo, hi = _overlap(old, new)
    inside = lambda day: lo <= (day or "") <= hi
    out = []

    def lesson(key: str, text: str):
        day, start, _end, subject = key.split("|", 3)
        out.append({"date": day, "time": start, "subject": subject, "text": text})

    for key in sorted(set(old["lessons"]) | set(new["lessons"])):
        if not inside(key.split("|")[0]):
            continue
        a, b = old["lessons"].get(key), new["lessons"].get(key)
        if a is None:
            lesson(key, "new lesson" + (f" ({b['status']})" if b["status"] != "regular" else ""))
        elif b is None:
            lesson(key, "no longer in the timetable")
        else:
            parts = []
            if a["status"] != b["status"]:
                parts.append("back to normal" if b["status"] == "regular" else b["status"])
            if a["teachers"] != b["teachers"]:
                parts.append(f"teacher {a['teachers'] or '-'} → {b['teachers'] or '-'}")
            if a["rooms"] != b["rooms"]:
                parts.append(f"room {a['rooms'] or '-'} → {b['rooms'] or '-'}")
            if parts:
                lesson(key, ", ".join(parts))

    for key in sorted(set(new["exams"]) - set(old["exams"])):
        e = new["exams"][key]
        if inside(e["date"]):
            out.append({"date": e["date"], "time": e["start"], "subject": e["subject"],
                        "text": f"new exam: {e['name']}".rstrip(": ")})
    for key in sorted(set(old["exams"]) - set(new["exams"])):
        e = old["exams"][key]
        if inside(e["date"]):
            out.append({"date": e["date"], "time": e["start"], "subject": e["subject"],
                        "text": f"exam removed: {e['name']}".rstrip(": ")})
    for key in sorted(set(new["homework"]) - set(old["homework"])):
        h = new["homework"][key]
        out.append({"date": h["due"] or "", "time": "", "subject": h["subject"],
                    "text": f"new homework: {h['text'][:60]}"})
    return sorted(out, key=lambda c: (c["date"], c["time"], c["subject"]))


def format_change(c: dict[str, Any]) -> str:
    when = _fmt_day(c["date"]) if c.get("date") else "?"
    when += f" {c['time']}" if c.get("time") else ""
    return f"{when:<16}  {c['subject']:<6}  {c['text']}"


def notify(changes: list[dict[str, Any]], title: str = "untis") -> int:
    """Send one desktop notification per change (notify-send on Linux,
    osascript on macOS). Returns how many were sent."""
    if sys.platform == "darwin" and shutil.which("osascript"):
        cmd = lambda body: ["osascript", "-e",
                            f"display notification {json.dumps(body)} with title {json.dumps(title)}"]
    elif shutil.which("notify-send"):
        cmd = lambda body: ["notify-send", "--app-name=untis", title, body]
    else:
        log.warning("No notify-send/osascript found; can't show desktop notifications")
        return 0
    sent = 0
    for c in changes:
        try:
            subprocess.run(cmd(format_change(c)), check=False, timeout=10)
            sent += 1
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("Notification failed: %s", exc)
    return sent
