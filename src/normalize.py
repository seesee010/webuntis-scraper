"""Normalize raw WebUntis JSON responses into clean, flat structures."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

log = logging.getLogger(__name__)


def _untis_date(value: Any) -> Optional[str]:
    """20260602 -> "2026-06-02". Passes ISO strings through."""
    if value in (None, "", 0):
        return None
    s = str(value)
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def _untis_time(value: Any) -> Optional[str]:
    """750 / "0750" -> "07:50". Passes "HH:MM" strings through."""
    if value in (None, ""):
        return None
    s = str(value)
    if s.isdigit() and len(s) <= 4:
        s = s.zfill(4)
        return f"{s[:2]}:{s[2:]}"
    return s


def _epoch_ms(value: Any) -> Optional[str]:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000).isoformat(timespec="seconds")


def _rpc_elements(items: Any) -> list[dict]:
    return [
        {"short": x.get("name"), "long": x.get("longname") or x.get("displayname")}
        for x in items or []
    ]


def _names(items: Any) -> list[dict]:
    """["M", "E"] -> [{"short": "M", "long": None}, ...]"""
    return [{"short": x, "long": None} for x in items or [] if x]


def normalize_timetable_lesson(lesson: dict) -> dict[str, Any]:
    """Flatten a JSON-RPC `getTimetable` element."""
    activity_type = lesson.get("actType") or lesson.get("activityType") or ""
    code = lesson.get("code") or ""   # "" | "cancelled" | "irregular"
    return {
        "id": lesson.get("id"),
        "date": _untis_date(lesson.get("date")),
        "start_time": _untis_time(lesson.get("startTime")),
        "end_time": _untis_time(lesson.get("endTime")),
        "type": activity_type,           # "Unterricht", "Klausur", ...
        "code": code,
        "is_exam": any(k in activity_type for k in ("Klausur", "Prüfung", "Exam"))
                   or lesson.get("lstype") == "ex",
        "is_substitution": code == "irregular"
                           or "Vertretung" in activity_type
                           or "Substitution" in activity_type,
        "is_cancelled": code == "cancelled"
                        or "Entfall" in activity_type or "Cancel" in activity_type,
        "subjects": _rpc_elements(lesson.get("su")),
        "teachers": _rpc_elements(lesson.get("te")),
        "classes": _rpc_elements(lesson.get("kl")),
        "rooms": _rpc_elements(lesson.get("ro")),
        "info": lesson.get("info") or "",
        "text": lesson.get("lstext") or lesson.get("lsw") or "",
        "substitution_text": lesson.get("substText") or "",
        "raw": lesson,
    }


def normalize_exam(exam: dict) -> dict[str, Any]:
    """Flatten an entry of `/WebUntis/api/exams`."""
    subject = exam.get("subject")
    return {
        "id": exam.get("id"),
        "date": _untis_date(exam.get("examDate") or exam.get("date")),
        "start_time": _untis_time(exam.get("startTime")),
        "end_time": _untis_time(exam.get("endTime")),
        "name": exam.get("name"),
        "type": exam.get("examType"),
        "text": exam.get("text") or "",
        "grade": exam.get("grade") or "",
        "subjects": _names([subject]) if isinstance(subject, str) else _rpc_elements(exam.get("su")),
        "teachers": _names(exam.get("teachers")) if "teachers" in exam else _rpc_elements(exam.get("te")),
        "classes": _names(exam.get("studentClass")) if "studentClass" in exam else _rpc_elements(exam.get("kl")),
        "rooms": _names(exam.get("rooms")) if "rooms" in exam else _rpc_elements(exam.get("ro")),
        "raw": exam,
    }


def normalize_homework(hw: dict) -> dict[str, Any]:
    """Flatten a homework item from `/WebUntis/api/homeworks/lessons`
    (already joined with `lesson`/`teacher` by the client)."""
    lesson = hw.get("lesson") or {}
    teacher = hw.get("teacher") or {}
    return {
        "id": hw.get("id"),
        "date": _untis_date(hw.get("date")),
        "due_date": _untis_date(hw.get("dueDate")),
        "text": (hw.get("text") or "").strip(),
        "remark": (hw.get("remark") or "").strip(),
        "completed": bool(hw.get("completed")),
        "lesson_type": lesson.get("lessonType"),
        "subjects": _names([lesson.get("subject")]),
        "teachers": _names([teacher.get("name")]),
        "attachments": hw.get("attachments") or [],
        "raw": hw,
    }


def normalize_absence(ab: dict) -> dict[str, Any]:
    """Flatten an entry of `/WebUntis/api/classreg/absences/students`."""
    excuse = ab.get("excuse") or {}
    is_excused = bool(ab.get("isExcused"))
    return {
        "id": ab.get("id"),
        "start_date": _untis_date(ab.get("startDate")),
        "end_date": _untis_date(ab.get("endDate")),
        "start_time": _untis_time(ab.get("startTime")),
        "end_time": _untis_time(ab.get("endTime")),
        "reason": ab.get("reason") or "",
        "text": ab.get("text") or "",
        "is_excused": is_excused,
        "excuse_status": ab.get("excuseStatus") or excuse.get("excuseStatus") or None,
        "excuse_text": excuse.get("text") or "",
        "created_by": ab.get("createdUser"),
        "created_at": _epoch_ms(ab.get("createDate")),
        "raw": ab,
    }


def normalize_message(msg: dict) -> dict[str, Any]:
    """Flatten an entry of REST v1 `/messages` -> `incomingMessages`."""
    sender = msg.get("sender") or {}
    if isinstance(sender, dict):
        sender = sender.get("displayName") or sender.get("name")
    return {
        "id": msg.get("id"),
        "subject": msg.get("subject"),
        "preview": msg.get("contentPreview") or msg.get("preview"),
        "from": sender,
        "date": msg.get("sentDateTime") or msg.get("date"),
        "read": bool(msg.get("isMessageRead", msg.get("read"))),
        "has_attachments": bool(msg.get("hasAttachments")),
        "raw": msg,
    }


# REST v1 grid entries put elements into position1..N, but which slot
# holds what differs per school — so group by the element's own type.
_GRID_TYPE_KEYS = {
    "SUBJECT": "subjects",
    "TEACHER": "teachers",
    "CLASS": "classes",
    "ROOM": "rooms",
}


def normalize_timetable_grid(grid: dict) -> dict[str, Any]:
    """Convert REST v1 timetable/entries into a per-day structure."""
    days_out: list[dict] = []
    for day in grid.get("days") or []:
        entries_out = []
        for entry in day.get("gridEntries") or []:
            duration = entry.get("duration") or {}
            status = entry.get("status")
            entries_out.append({
                "start": duration.get("start") or "",
                "end": duration.get("end") or "",
                "status": status,       # REGULAR, CANCELLED, CHANGED, ADDITIONAL, EXAM, ...
                "is_cancelled": status in ("CANCEL", "CANCELLED"),
                "is_exam": status == "EXAM" or entry.get("type") == "EXAM",
                "is_substitution": status in ("SUBSTITUTION", "CHANGED"),
                "type": entry.get("type") or "",
                "lesson_text": entry.get("lessonText") or "",
                "substitution_text": entry.get("substitutionText") or "",
                "info": entry.get("lessonInfo") or "",   # e.g. event title
                "notes": entry.get("notesAll") or "",
                **_collect_elements(entry),
                "raw": entry,
            })
        days_out.append({
            "date": day.get("date"),
            "status": day.get("status"),
            "entries": entries_out,
        })
    return {"days": days_out, "raw": grid}


def _collect_elements(entry: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {k: [] for k in _GRID_TYPE_KEYS.values()}
    i = 1
    while f"position{i}" in entry:
        for it in entry.get(f"position{i}") or []:
            removed = it.get("removed") or {}
            # A removed element without replacement only has `removed`.
            cur = it.get("current") or removed
            key = _GRID_TYPE_KEYS.get(cur.get("type") or "")
            if not key:
                continue
            item = {
                "short": cur.get("shortName"),
                "long": cur.get("longName") or cur.get("displayName"),
            }
            if cur.get("status") and cur.get("status") != "REGULAR":
                item["status"] = cur.get("status")
            if removed and cur is not removed:
                item["replaces"] = removed.get("shortName")
            out[key].append(item)
        i += 1
    return out
