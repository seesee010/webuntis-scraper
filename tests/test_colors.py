"""Tests for status colors, --color and --legend (#2)."""
from __future__ import annotations

import sys
from datetime import datetime

import pytest

from untis import main as main_mod
from untis.summary import (
    ROLE_STYLES,
    _elements,
    _label_tag,
    _plain,
    _rooms,
    _Style,
    _teachers,
    render_legend,
    render_summary,
    resolve_color,
)

NOT_LIVE = datetime(2000, 1, 1, 12, 0)
ON, OFF = _Style(True), _Style(False)
DAY = "2026-10-05"


def sgr(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"


# --- _Style / ROLE_STYLES ------------------------------------------------
def test_every_status_label_has_a_style():
    for label in ("cancelled", "removed", "changed", "substitution", "extra",
                  "no teacher", "exam", "event", "added", "gone"):
        assert label in ROLE_STYLES


@pytest.mark.parametrize("role, code", [("cancelled", "31;9"), ("removed", "2;9"),
                                        ("changed", "32"), ("no teacher", "33"),
                                        ("exam", "1;35"), ("event", "1;34"), ("added", "1;32")])
def test_role_codes(role, code):
    assert ON.role(role, "X") == sgr(code, "X")


def test_role_unknown_or_disabled_is_plain():
    assert ON.role("nope", "X") == "X"
    assert OFF.role("cancelled", "X") == "X"
    assert ON.green("x") == sgr("32", "x")


@pytest.mark.parametrize("mode, color", [("auto", None), ("always", True), ("never", False)])
def test_resolve_color(mode, color):
    assert resolve_color(mode) is color


# --- teachers / rooms ------------------------------------------------------
def test_elements_substitute_new_room_removed_and_base():
    items = [{"short": "NEW", "status": "ADDED", "replaces": "OLD"},
             {"short": "GONE", "status": "REMOVED"},
             {"short": "KEPT"}]
    plain, styled = _elements(items, ON, base=ON.cyan)
    assert plain == "NEW (for OLD), GONE, KEPT"
    assert sgr("1;32", "NEW") in styled and sgr("2", " (for OLD)") in styled
    assert sgr("31;9", "GONE") in styled and sgr("36", "KEPT") in styled


def test_elements_added_without_replaces():
    plain, styled = _elements([{"short": "R205", "status": "ADDED"}], ON)
    assert plain == "R205" and styled == sgr("1;32", "R205")


def test_elements_without_colors_use_text_markers():
    plain, styled = _elements([{"short": "GONE", "status": "REMOVED"}, {"short": "A"}], OFF)
    assert plain == styled == "~GONE~, A"


def test_teachers_and_rooms_wrappers():
    assert _teachers([{"short": "T"}], ON) == ("T", "T")
    assert _rooms([{"short": "R"}], ON) == ("R", sgr("36", "R"))


@pytest.mark.parametrize("label, expected", [("cancelled", sgr("31", "cancelled")),
                                             ("removed", sgr("2", "removed")),
                                             ("exam", sgr("1;35", "exam")), ("", "")])
def test_label_tag(label, expected):
    assert _label_tag(label, ON) == expected


# --- day view lines --------------------------------------------------------
def _entry(subject, label_flags=None, teachers=None, rooms=None, status="REGULAR", **kw):
    return {"start": f"{DAY}T07:50", "end": f"{DAY}T08:40", "status": status,
            "type": "NORMAL_TEACHING_PERIOD", "subjects": [{"short": subject}],
            "teachers": teachers or [{"short": "TCH1"}], "rooms": rooms or [{"short": "R101"}],
            "info": "", "lesson_text": "", "substitution_text": "",
            "is_cancelled": False, "is_exam": False, **(label_flags or {}), **kw}


def _lines(*entries, color=True):
    p = {"meta": {"window": {"start": DAY, "end": DAY}},
         "timetable": {"days": [{"date": DAY, "entries": list(entries)}]}}
    return render_summary(p, color=color, now=NOT_LIVE).splitlines()


def _row(lines, needle):
    return next(l for l in lines if needle in _plain(l))


def test_regular_lesson_bold_subject_only():
    line = _row(_lines(_entry("MATH")), "MATH")
    assert sgr("1", "MATH") in line and "\033[3" not in line.split("MATH")[0][-10:]


def test_cancelled_whole_line_red_struck():
    line = _row(_lines(_entry("GEO", {"is_cancelled": True}, status="CANCELLED")), "GEO")
    assert line.startswith("\033[31;9m") and "R101" in line.split("\033[0m")[0]
    assert line.endswith(sgr("31", "cancelled"))


def test_removed_whole_line_gray_struck():
    line = _row(_lines(_entry("ETH", {"is_removed": True}, status="CHANGED")), "ETH")
    assert line.startswith("\033[2;9m") and line.endswith(sgr("2", "removed"))


def test_substitution_is_green():
    line = _row(_lines(_entry("ENG", teachers=[{"short": "TCH4", "status": "ADDED",
                                                  "replaces": "TCH3"}], status="CHANGED")), "ENG")
    assert sgr("32", "ENG") in line and sgr("1;32", "TCH4") in line
    assert line.endswith(sgr("32", "changed"))


def test_new_room_is_highlighted():
    line = _row(_lines(_entry("PROG", rooms=[{"short": "R205", "status": "ADDED",
                                               "replaces": "R101"}], status="CHANGED")), "PROG")
    assert sgr("1;32", "R205") in line and "(for R101)" in _plain(line)


def test_no_teacher_is_yellow():
    line = _row(_lines(_entry("NET", {"no_teacher": True},
                              teachers=[{"short": "TCH7", "status": "REMOVED"}],
                              status="CHANGED")), "NET")
    assert sgr("33", "NET") in line and sgr("31;9", "TCH7") in line
    assert line.endswith(sgr("33", "no teacher"))


def test_exam_and_event_colors():
    exam = _row(_lines(_entry("MATH", {"is_exam": True})), "MATH")
    assert sgr("1;35", "MATH") in exam and exam.endswith(sgr("1;35", "exam"))
    ev = _entry("", {"is_event": True}, teachers=[{"short": "TCH8"}], rooms=[])
    ev["subjects"], ev["info"] = [], "EVENT"
    line = _row(_lines(ev), "EVENT")
    assert sgr("1;34", "★ EVENT") in line and line.endswith(sgr("1;34", "event"))


def test_columns_stay_aligned_with_colors():
    lines = _lines(_entry("MATH"),
                   _entry("ENGLISH", teachers=[{"short": "TCH4", "status": "ADDED",
                                                  "replaces": "TCH3"}], status="CHANGED"),
                   _entry("GEO", rooms=[{"short": "R205", "status": "ADDED",
                                          "replaces": "R101"}], status="CHANGED"))
    rows = [_plain(_row(lines, s)) for s in ("MATH", "ENGLISH", "GEO")]
    col = lambda row, word: row.index(word)
    assert col(rows[0], "TCH1") == col(rows[1], "TCH4") == col(rows[2], "TCH1")
    assert col(rows[0], "R101") == col(rows[1], "R101") == col(rows[2], "R205")


def test_no_escape_codes_without_color():
    lines = _lines(_entry("GEO", {"is_cancelled": True}, status="CANCELLED"), color=False)
    assert not any("\033[" in l for l in lines)


# --- legend ----------------------------------------------------------------
def test_legend_lists_every_status():
    text = render_legend(False)
    for name in ("regular", "cancelled", "removed", "substitute", "new room",
                 "no teacher", "exam", "event", "now"):
        assert f"  {name}" in text
    assert "~TCH7~" in text and "TCH4 (for TCH3)" in text and "R205 (for R101)" in text
    assert "\033[" not in text


def test_legend_with_colors_uses_the_role_styles():
    text = render_legend(True)
    for code in ("31;9", "2;9", "1;32", "33", "1;35", "1;34"):
        assert f"\033[{code}m" in text


# --- CLI -------------------------------------------------------------------
def test_color_flag_parsing(capsys):
    assert main_mod._parse_args([], default_args=[]).color == "auto"
    assert main_mod._parse_args(["--color", "never"], default_args=["--color", "always"]).color == "never"
    with pytest.raises(SystemExit) as exc:
        main_mod._parse_args(["--color", "rainbow"], default_args=[])
    assert exc.value.code == 2


def test_legend_alone_needs_no_login(monkeypatch, capsys):
    async def fail(args):
        raise AssertionError("must not fetch")
    monkeypatch.setattr(main_mod, "_async_main", fail)
    monkeypatch.setattr(sys, "argv", ["untis", "--legend", "--color", "never"])
    assert main_mod.main() == 0
    assert capsys.readouterr().out.startswith("Legend")


async def test_legend_after_the_day_view(monkeypatch, tmp_path, capsys):
    from unittest.mock import AsyncMock
    from untis.config import ScraperConfig
    c = ScraperConfig(server="s", school="sc", output_dir=str(tmp_path))
    monkeypatch.setattr(main_mod, "load_config", lambda *a: c)
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "last.json")
    monkeypatch.setattr(main_mod, "_fetch", AsyncMock(return_value={"meta": {"user": "Max"}}))
    args = main_mod._parse_args(["-s", "--legend", "--color", "never"], default_args=[])
    await main_mod._async_main(args)
    out = capsys.readouterr().out
    assert out.index("Max") < out.index("Legend")
