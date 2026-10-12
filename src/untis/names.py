"""--long full names and --who CODE lookup (#26).

The API returns a long name for every subject, teacher, room and class;
the normalizer keeps it as `long` next to the `short` code.
"""
from __future__ import annotations

import copy
from typing import Any, Iterator

# Element lists in the payload -> what they are.
KINDS = {"subjects": "subject", "teachers": "teacher", "rooms": "room", "classes": "class"}
# Lists of /timetable/filter -> (key of the element inside, kind).
_FILTER_LISTS = {"rooms": ("room", "room"), "classes": ("class", "class"),
                 "subjects": ("subject", "subject"), "teachers": ("teacher", "teacher")}

Names = dict[tuple[str, str], str]          # (kind, short) -> long ("" if unknown)


def _entries(payload: dict[str, Any]) -> Iterator[dict]:
    """Every timetable entry/lesson, exam and homework of the payload."""
    tt = payload.get("timetable") or {}
    for day in tt.get("days") or []:
        yield from day.get("entries") or []
    yield from tt.get("lessons") or []
    yield from (payload.get("exams") or {}).get("exams") or []
    yield from (payload.get("homework") or {}).get("items") or []


def use_long_names(payload: dict[str, Any]) -> dict[str, Any]:
    """A copy of the payload whose `short` names are the long ones (where
    known), so every view shows full names (--long)."""
    out = copy.deepcopy(payload)
    for entry in _entries(out):
        for key in KINDS:
            for element in entry.get(key) or []:
                if element.get("long"):
                    element["short"] = element["long"]
                if element.get("replaces_long"):
                    element["replaces"] = element["replaces_long"]
    return out


def _add(names: Names, kind: str, short: Any, long: Any) -> None:
    if not short:
        return
    key = (kind, str(short).strip())
    if long or key not in names:
        names[key] = str(long or "").strip()


def collect_names(payload: dict[str, Any]) -> Names:
    """All codes with their long names from a (cached) payload."""
    names: Names = {}
    for entry in _entries(payload):
        for key, kind in KINDS.items():
            for element in entry.get(key) or []:
                _add(names, kind, element.get("short"), element.get("long"))
    return names


def names_from_filter(response: dict[str, Any]) -> Names:
    """Codes from a /timetable/filter response: rooms, classes (with
    their class teachers), subjects and teachers, as far as the account
    may see them."""
    names: Names = {}
    for list_key, (inner, kind) in _FILTER_LISTS.items():
        for item in response.get(list_key) or []:
            if not isinstance(item, dict):
                continue
            element = item.get(inner) or {}
            _add(names, kind, element.get("shortName"),
                 element.get("longName") or element.get("displayName"))
            if inner == "class":
                for t in ("classTeacher1", "classTeacher2"):
                    teacher = item.get(t) or {}
                    _add(names, "teacher", teacher.get("shortName"),
                         teacher.get("longName") or teacher.get("displayName"))
    return names


def lookup(names: Names, code: str) -> list[tuple[str, str, str]]:
    """(kind, short, long) for a code or name, case-insensitively: exact
    short or long name first, otherwise long names containing it (from
    3 characters). Sorted by kind and code."""
    term = code.strip().lower()
    if not term:
        return []
    exact = [(k, s, l) for (k, s), l in names.items() if term in (s.lower(), l.lower())]
    if exact or len(term) < 3:
        return sorted(exact)
    return sorted((k, s, l) for (k, s), l in names.items() if term in l.lower())


def format_who(matches: list[tuple[str, str, str]]) -> str:
    """"TCH1   teacher   Fullname-of-teacher", aligned."""
    if not matches:
        return ""
    short_w = max(len(s) for _, s, _ in matches)
    kind_w = max(len(k) for k, _, _ in matches)
    return "\n".join(f"{s.ljust(short_w)}   {k.ljust(kind_w)}   {l or '-'}".rstrip()
                     for k, s, l in matches)
