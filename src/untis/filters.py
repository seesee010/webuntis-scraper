"""--only / --except: filter the views by subject (#25).

A subject matches by its short name (MATH) or long name (Mathematics),
case-insensitively. The timetable, exams and homework are filtered;
absences have no subject and are left alone. Entries without a subject
(events) only survive --except, not --only.
"""
from __future__ import annotations

import copy
from typing import Any, Optional


def parse_subjects(text: str) -> list[str]:
    """"MATH, eng" -> ["math", "eng"]. Raises ValueError if empty."""
    terms = [t.strip().lower() for t in (text or "").split(",") if t.strip()]
    if not terms:
        raise ValueError("expected one or more subjects, e.g. MATH or MATH,ENG")
    return terms


def subject_names(item: dict) -> set[str]:
    """Lower-case short and long names of an entry's subjects."""
    names = set()
    for s in item.get("subjects") or []:
        for key in ("short", "long"):
            if s.get(key):
                names.add(str(s[key]).strip().lower())
    return names


def keep(item: dict, only: Optional[list[str]], exclude: Optional[list[str]]) -> bool:
    """Does `item` pass --only (any of the subjects) and --except (none)?"""
    names = subject_names(item)
    if only and not names & set(only):
        return False
    return not (exclude and names & set(exclude))


def filter_payload(
    payload: dict[str, Any], only: Optional[list[str]], exclude: Optional[list[str]],
) -> dict[str, Any]:
    """A copy of the payload with only the matching timetable entries,
    exams and homework. Without filters, the payload itself."""
    if not only and not exclude:
        return payload
    out = copy.deepcopy(payload)
    ok = lambda x: keep(x, only, exclude)       # noqa: E731
    tt = out.get("timetable")
    if isinstance(tt, dict) and "error" not in tt:
        for day in tt.get("days") or []:
            day["entries"] = [e for e in day.get("entries") or [] if ok(e)]
        if "lessons" in tt:
            tt["lessons"] = [x for x in tt.get("lessons") or [] if ok(x)]
    exams = out.get("exams")
    if isinstance(exams, dict) and "exams" in exams:
        exams["exams"] = [e for e in exams["exams"] or [] if ok(e)]
    homework = out.get("homework")
    if isinstance(homework, dict) and "items" in homework:
        homework["items"] = [h for h in homework["items"] or [] if ok(h)]
    return out
