"""Tests for the bordered --table grid (#69). All data is invented."""
from __future__ import annotations

import pytest

from untis.summary import (
    _MAX_COL,
    _MIN_COL,
    _absent_spans,
    _block_role,
    _column_widths,
    _days_rows,
    _draw_table,
    _is_absent,
    _junction,
    _plain,
    _render_table,
    _Style,
    _table_cell,
    render_legend,
    render_summary,
)

from test_layouts import GRID, MON, NOT_LIVE, OFF, ON, TT, TUE, _e

ABSENT_TUE_3RD = {"items": [{"start_date": TUE, "end_date": TUE, "start_time": "09:40",
                             "end_time": "10:30", "is_excused": False}]}


def rows(day=TUE):
    return _days_rows(TT)[day]


def body(lines):
    """The table lines without the leading blank line."""
    return [l for l in lines if l]


# --- _absent_spans / _is_absent ---------------------------------------------
def test_absent_spans():
    spans = _absent_spans({"items": [
        {"start_date": MON, "end_date": TUE, "start_time": "10:00", "end_time": "09:00"}]})
    assert spans == {MON: [("10:00", "24:00")], TUE: [("00:00", "09:00")]}


@pytest.mark.parametrize("absences", [None, {}, {"items": []}, {"error": "HTTP 403"}])
def test_absent_spans_without_absences(absences):
    assert _absent_spans(absences) == {}


@pytest.mark.parametrize("start, end, absent", [
    ("09:40", "10:30", True),     # the same period
    ("09:00", "09:45", True),     # partly
    ("10:30", "11:20", False),    # touching only
    ("08:00", "09:40", False),
])
def test_is_absent(start, end, absent):
    assert _is_absent([("09:40", "10:30")], start, end) is absent


def test_is_absent_without_spans():
    assert not _is_absent([], "07:50", "08:40")


# --- _block_role ------------------------------------------------------------
def test_block_role_regular_and_empty():
    assert _block_role([rows(MON)[0]]) == ""
    assert _block_role([]) == ""
    assert _block_role([], absent=True) == ""


def test_block_role_states():
    net, prog, geo, math_exam = rows()
    assert _block_role([geo]) == "cancelled"
    assert _block_role([math_exam]) == "exam"
    assert _block_role([rows(MON)[1]]) == "changed"


def test_block_role_absent_beats_exam_but_not_cancelled():
    _, _, geo, math_exam = rows()
    assert _block_role([math_exam], absent=True) == "absent"
    assert _block_role([geo], absent=True) == "cancelled"


def test_block_role_parallel_group_with_one_cancelled_lesson_still_takes_place():
    net, prog, geo, _ = rows()
    assert _block_role([net, geo]) == ""


def test_block_role_removed_and_event():
    removed = _days_rows({"days": [{"date": MON, "entries": [
        _e(MON, "07:50", "08:40", "ETH", is_removed=True)]}]})[MON][0]
    event = _days_rows({"days": [{"date": MON, "entries": [
        _e(MON, "07:50", "08:40", None, is_event=True, info="TRIP")]}]})[MON][0]
    assert _block_role([removed]) == "removed"
    assert _block_role([event]) == "event"


# --- _table_cell ------------------------------------------------------------
def test_table_cell_empty():
    assert _table_cell([], OFF) == ([], None)


def test_table_cell_lesson_and_room():
    lines, key = _table_cell([rows(MON)[0]], OFF)
    assert lines == ["MATH", "R101"] and key == ("MATH", "R101", "")


def test_table_cell_parallel_group_lists_every_room_once():
    net, prog, *_ = rows()
    assert _table_cell([net, prog], OFF)[0] == ["NET/PROG", "R201, R202"]
    assert _table_cell([net, net], OFF)[0] == ["NET", "R201"]


def test_table_cell_without_room():
    row = _days_rows({"days": [{"date": MON, "entries": [
        _e(MON, "07:50", "08:40", "PE", room=None)]}]})[MON][0]
    assert _table_cell([row], OFF)[0] == ["PE"]
    assert _table_cell([row], ON)[0] == ["PE"]


def test_table_cell_markers_without_colors():
    _, _, geo, math_exam = rows()
    assert _table_cell([geo], OFF)[0][0] == "~GEO~"
    assert _table_cell([math_exam], OFF)[0][0] == "MATH!"
    assert _table_cell([math_exam], OFF, absent=True)[0][0] == "[MATH!]"


def test_table_cell_colors_the_whole_block():
    _, _, geo, math_exam = rows()
    lines, key = _table_cell([math_exam], ON)
    assert lines == ["\033[1;35mMATH!\033[0m", "\033[1;35mR101\033[0m"]
    assert key[2] == "exam"
    assert _table_cell([geo], ON)[0][0] == "\033[31;9mGEO\033[0m"        # no ~ with colors
    assert _table_cell([math_exam], ON, absent=True)[0] == ["\033[2mMATH!\033[0m",
                                                          "\033[2mR101\033[0m"]


def test_table_cell_regular_keeps_the_normal_styles():
    lines, _ = _table_cell([rows(MON)[0]], ON)
    assert lines == ["MATH", "\033[36mR101\033[0m"]                       # room in cyan


def test_table_cell_keys_differ_by_state():
    _, _, _, math_exam = rows()
    assert _table_cell([rows(MON)[0]], OFF)[1] != _table_cell([math_exam], OFF)[1]
    assert _table_cell([math_exam], OFF)[1] != _table_cell([math_exam], OFF, absent=True)[1]


# --- _junction --------------------------------------------------------------
@pytest.mark.parametrize("up, down, left, right, char", [
    (True, True, True, True, "┼"), (True, True, True, False, "┤"),
    (True, True, False, True, "├"), (True, True, False, False, "│"),
    (False, True, True, True, "┬"), (True, False, True, True, "┴"),
    (False, False, True, True, "─"), (False, True, False, True, "┌"),
    (False, True, True, False, "┐"), (True, False, False, True, "└"),
    (True, False, True, False, "┘"), (True, False, False, False, "│"),
    (False, False, True, False, "─"), (False, False, False, False, " "),
])
def test_junction(up, down, left, right, char):
    assert _junction(up, down, left, right) == char


# --- _column_widths ---------------------------------------------------------
def test_column_widths_fit_the_content():
    cells = [[(["MATH", "R101"], 1)], [(["NET/PROG", "R201, R202"], 2)]]
    assert _column_widths(["Mon 05.10.", "Tue 06.10."], cells, 200) == [10, 10]


def test_column_widths_minimum_and_maximum():
    cells = [[(["A"], 1)], [(["X" * 60], 2)]]
    assert _column_widths(["a", "b"], cells, 500) == [_MIN_COL, _MAX_COL]


def test_column_widths_shrink_to_the_terminal():
    cells = [[(["X" * 20], 1)] for _ in range(5)]
    widths = _column_widths(["h"] * 5, cells, 80)
    assert _TIME_TOTAL + sum(w + 3 for w in widths) <= 80


def test_column_widths_never_below_the_minimum():
    cells = [[(["X" * 20], 1)] for _ in range(5)]
    assert _column_widths(["h"] * 5, cells, 20) == [_MIN_COL] * 5


def test_column_widths_ignore_colors():
    cells = [[(["\033[1;35mMATH!\033[0m"], 1)]]
    assert _column_widths(["\033[1mMon\033[0m"], cells, 100) == [_MIN_COL]


_TIME_TOTAL = 9                       # "│ 07:50 " + the closing "│"


# --- _draw_table ------------------------------------------------------------
UNITS = [("07:50", "08:40"), ("08:45", "09:35"), ("09:40", "10:30")]


def test_draw_table_frame():
    out = _draw_table(OFF, UNITS[:1], ["Mon 05.10."], [[(["MATH", "R101"], 1)]], 80)
    assert out == ["┌───────┬────────────┐",
                   "│ Time  │ Mon 05.10. │",
                   "├───────┼────────────┤",
                   "│ 07:50 │ MATH       │",
                   "│ 08:40 │ R101       │",
                   "└───────┴────────────┘"]


def test_draw_table_merges_equal_neighbours():
    cells = [[(["MATH", "R101"], "k"), (["MATH", "R101"], "k"), (["ENG", "R102"], "e")]]
    out = _draw_table(OFF, UNITS, ["Mon 05.10."], cells, 80)
    assert out[3:] == ["│ 07:50 │ MATH       │",
                       "│ 08:40 │ R101       │",
                       "├───────┤            │",                 # no line inside the merged cell
                       "│ 08:45 │            │",
                       "│ 09:35 │            │",
                       "├───────┼────────────┤",
                       "│ 09:40 │ ENG        │",
                       "│ 10:30 │ R102       │",
                       "└───────┴────────────┘"]


def test_draw_table_keeps_boxes_for_free_periods_between_lessons():
    cells = [[(["A"], "a"), ([], None), (["B"], "b")]]
    out = _draw_table(OFF, UNITS, ["Mon"], cells, 80)
    assert out[5] == "├───────┼────────┤"                     # box above the free period
    assert out[8] == "├───────┼────────┤"                     # and below it
    assert out[6] == "│ 08:45 │        │"


def test_draw_table_no_boxes_after_the_last_lesson():
    cells = [[(["A"], "a"), ([], None), ([], None)], [(["B"], "b"), (["C"], "c"), (["D"], "d")]]
    out = _draw_table(OFF, UNITS, ["Mon", "Tue"], cells, 80)
    assert out[5] == "├───────┼────────┼────────┤"            # closes the last lesson's box
    assert out[8] == "├───────┤        ├────────┤"            # then the column stays open
    assert out[9] == "│ 09:40 │        │ D      │"
    assert out[-1] == "└───────┘        └────────┘"           # no bottom border under it


def test_draw_table_day_without_lessons_is_one_open_column():
    cells = [[([], None), ([], None)], [(["A"], "a"), (["B"], "b")]]
    out = _draw_table(OFF, UNITS[:2], ["Mon", "Tue"], cells, 80)
    assert out[2] == "├───────┼────────┼────────┤"            # the header box still closes
    assert out[5] == "├───────┤        ├────────┤"
    assert out[-1] == "└───────┘        └────────┘"


def test_draw_table_open_columns_have_no_line_between_or_at_the_edge():
    cells = [[(["A"], "a"), ([], None), ([], None)],
             [(["B"], "b"), ([], None), ([], None)],
             [(["C"], "c"), (["D"], "d"), ([], None)]]
    out = _draw_table(OFF, UNITS, ["Mon", "Tue", "Wed"], cells, 80)
    assert out[5] == "├───────┼────────┴────────┼────────┤"     # both close, open below
    assert out[6] == "│ 08:45 │                 │ D      │"     # no line between Mon and Tue
    assert out[8] == "├───────┤                 └────────┘"     # Wed's box closes, no right edge
    assert out[9] == "│ 09:40 │"                               # nothing to the right anymore
    assert out[-1] == "└───────┘"


def test_draw_table_last_column_closes_with_a_corner():
    cells = [[(["A"], "a"), (["B"], "b")], [(["C"], "c"), ([], None)]]
    out = _draw_table(OFF, UNITS[:2], ["Mon", "Tue"], cells, 80)
    assert out[5] == "├───────┼────────┼────────┘"
    assert out[6] == "│ 08:45 │ B      │"
    assert out[-1] == "└───────┴────────┘"


def test_render_table_short_day_ends_open():
    tt = {"time_grid": GRID, "days": [
        {"date": MON, "entries": [_e(MON, "07:50", "08:40", "A")]},
        {"date": TUE, "entries": [_e(TUE, "07:50", "08:40", "B"),
                                  _e(TUE, "08:45", "09:35", "C"),
                                  _e(TUE, "09:40", "10:30", "D")]}]}
    out = body(_render_table(tt, OFF, width=80))
    assert out[5] == "├───────┼────────────┼────────────┤"
    assert out[8] == "├───────┤            ├────────────┤"


def test_draw_table_junction_between_merged_and_split_columns():
    cells = [[(["A"], "a"), (["A"], "a")], [(["B"], "b"), (["C"], "c")]]
    assert _draw_table(OFF, UNITS[:2], ["Mon", "Tue"], cells, 80)[5] == \
        "├───────┤        ├────────┤"


def test_draw_table_lines_have_equal_width():
    cells = [[(["MATH", "R101"], 1), ([], None)], [(["X" * 40], 2), (["B"], 3)]]
    out = _draw_table(ON, UNITS[:2], ["Mon 05.10.", "Tue 06.10."], cells, 50)
    assert len({len(_plain(l)) for l in out}) == 1
    assert all(len(_plain(l)) <= 50 for l in out)


def test_draw_table_end_time_dimmed_with_colors():
    out = _draw_table(ON, UNITS[:1], ["Mon"], [[(["A"], 1)]], 80)
    assert "\033[2m08:40\033[0m" in out[4]
    assert "\033[1mTime\033[0m" in out[1]


# --- _render_table ----------------------------------------------------------
def test_render_table_week():
    out = body(_render_table(TT, OFF, width=80, absences=ABSENT_TUE_3RD))
    assert out[1].split("│")[1:-1] == [" Time  ", " Mon 05.10. ", " Tue 06.10. "]
    assert out[3] == "│ 07:50 │ MATH       │ NET/PROG   │"
    assert out[4] == "│ 08:40 │ R101       │ R201, R202 │"
    assert out[5] == "├───────┤            ├────────────┤"         # double lesson merged
    assert out[6] == "│ 08:45 │            │ ~GEO~      │"
    assert out[9] == "│ 09:40 │            │ [MATH!]    │"         # absent + exam
    assert out[11] == "├───────┼────────────┼────────────┘"     # Tue is over
    assert out[12] == "│ 10:45 │ ENG*       │"
    assert out[-1] == "└───────┴────────────┘"


def test_render_table_single_day():
    tt = {"time_grid": GRID, "days": [{"date": MON, "entries": [
        _e(MON, "08:45", "09:35", "ENG")]}]}
    out = body(_render_table(tt, OFF, width=80))
    assert out[1] == "│ Time  │ Mon 05.10. │"
    assert out[3:6] == ["│ 08:45 │ ENG        │", "│ 09:35 │ R101       │",
                        "└───────┴────────────┘"]                       # only the used periods


def test_render_table_splits_weeks():
    nxt = "2026-10-12"
    tt = {"time_grid": GRID, "days": [
        {"date": MON, "entries": [_e(MON, "07:50", "08:40", "A")]},
        {"date": nxt, "entries": [_e(nxt, "07:50", "08:40", "B")]}]}
    out = _render_table(tt, OFF, width=80)
    assert sum(1 for l in out if l.startswith("┌")) == 2
    assert out[0] == "" and "" in out[1:]                                 # blank line between


def test_render_table_without_time_grid_uses_lesson_times():
    tt = {"days": [{"date": MON, "entries": [_e(MON, "08:00", "08:45", "ART")]}]}
    out = body(_render_table(tt, OFF, width=80))
    assert out[3].startswith("│ 08:00 │ ART") and out[4].startswith("│ 08:45 │")


def test_render_table_empty():
    assert "No lessons" in _render_table({"days": []}, OFF)[1]


def test_render_table_fits_narrow_terminals():
    out = body(_render_table(TT, ON, width=30))
    assert all(len(_plain(l)) <= 30 for l in out)
    assert "…" in _plain("\n".join(out))


def test_render_summary_table_uses_absences_and_keeps_header_and_footer():
    out = render_summary({"meta": {"user": "Max", "school": "demo",
                                   "window": {"start": MON, "end": TUE}},
                          "timetable": TT, "absences": ABSENT_TUE_3RD,
                          "messages": {"items": []}},
                         color=False, now=NOT_LIVE, layout="table", width=80)
    lines = out.splitlines()
    assert lines[0] == f"Max · demo · {MON} → {TUE}"
    assert "[MATH!]" in out
    assert lines[-1] == "1 absence (1 not excused) · 0 unread messages"


# --- legend -----------------------------------------------------------------
def test_legend_explains_the_absent_mark():
    assert "  absent      [MATH] in --table" in render_legend(False)
    assert "\033[2mMATH\033[0m in --table" in render_legend(True)


# --- now: the running lesson, past periods, the line under the table -------
from datetime import datetime  # noqa: E402

from untis.summary import _block_mark, _mark_lines, _now_line, _period_mark  # noqa: E402

TUE_0952 = datetime(2026, 10, 6, 9, 52)        # during Tue's exam (09:40–10:30)
MON_0900 = datetime(2026, 10, 5, 9, 0)         # 2nd half of Mon's double lesson
MON_1000 = datetime(2026, 10, 5, 10, 0)        # break before Mon's ENG at 10:45
MON_0700 = datetime(2026, 10, 5, 7, 0)         # before school
MON_1300 = datetime(2026, 10, 5, 13, 0)        # school is over


@pytest.mark.parametrize("start, end, hm, mark", [
    ("07:50", "08:40", "09:00", "past"),
    ("07:50", "08:40", "08:40", "past"),           # ends exactly now
    ("08:45", "09:35", "09:00", "current"),
    ("08:45", "09:35", "08:45", "current"),        # starts exactly now
    ("09:40", "10:30", "09:00", None),
])
def test_period_mark(start, end, hm, mark):
    assert _period_mark(start, end, hm) == mark


@pytest.mark.parametrize("marks, mark", [
    (["past", "current"], "current"), (["current", None], "current"),
    (["past", "past"], "past"), (["past", None], None), ([None], None), ([], None),
])
def test_block_mark(marks, mark):
    assert _block_mark(marks) == mark


def test_mark_lines_current_without_colors():
    assert _mark_lines(["MATH", "R101"], "current", "", OFF) == ["▶ MATH", "R101"]


def test_mark_lines_current_with_colors():
    out = _mark_lines(["MATH", "R101"], "current", "", ON)
    assert out[0] == "\033[1m\033[33m▶ \033[0m\033[0m\033[1m\033[33mMATH\033[0m\033[0m"
    exam = _mark_lines(["\033[1;35mMATH!\033[0m"], "current", "exam", ON)
    assert exam[0].endswith("\033[1;35mMATH!\033[0m")                  # keeps its color


def test_mark_lines_past():
    assert _mark_lines(["\033[36mR101\033[0m"], "past", "", ON) == ["\033[2mR101\033[0m"]
    assert _mark_lines(["MATH"], "past", "", OFF) == ["MATH"]
    geo = ["\033[31;9mGEO\033[0m"]
    assert _mark_lines(geo, "past", "cancelled", ON) == geo                 # keeps red


def test_mark_lines_nothing():
    assert _mark_lines(["MATH"], None, "", ON) == ["MATH"]
    assert _mark_lines([], "current", "", ON) == []


def test_now_line_during_a_lesson():
    rows_mon = _days_rows(TT)[MON]
    live = {"now": "09:00", "current": {0}, "next_in": None}
    assert _now_line(rows_mon, live, OFF) == "▶ now 09:00 · MATH · 35 min left"


def test_now_line_parallel_lessons_and_break():
    rows_tue = _days_rows(TT)[TUE]
    live = {"now": "07:55", "current": {0, 1}, "next_in": None}
    assert _now_line(rows_tue, live, OFF) == "▶ now 07:55 · NET/PROG · 45 min left"
    live = {"now": "07:30", "current": set(), "next_in": 20}
    assert _now_line(rows_tue, live, OFF) == "now 07:30 · next: NET/PROG at 07:50 (in 20 min)"


def test_now_line_skips_cancelled_next_lesson():
    rows_tue = _days_rows(TT)[TUE]
    live = {"now": "08:42", "current": set(), "next_in": 58}
    assert _now_line(rows_tue, live, OFF).startswith("now 08:42 · next: MATH at 09:40")


def test_column_widths_make_room_for_the_marker():
    cells = [[(["ABCDEFGH"], 1, "current")]]
    assert _column_widths(["Mon"], cells, 100) == [10]
    assert _column_widths(["Mon"], [[(["ABCDEFGH"], 1, "past")]], 100) == [8]


def test_draw_table_today_header_and_period_times():
    cells = [[(["A"], "a", "past"), (["B"], "b", "current")]]
    out = _draw_table(ON, UNITS[:2], ["Mon"], cells, 80, periods=["past", "current"], today=0)
    assert "\033[33mMon" in out[1]
    assert "\033[2m07:50\033[0m" in out[3]                                   # past: dimmed
    assert "\033[33m08:45" in out[6] and "▶ " in out[6]


def test_draw_table_marks_a_merged_block_by_any_period():
    cells = [[(["A"], "k", "past"), (["A"], "k", "current")]]
    out = _draw_table(OFF, UNITS[:2], ["Mon"], cells, 80, periods=["past", "current"])
    assert out[3] == "│ 07:50 │ ▶ A    │"


def test_render_table_during_a_lesson():
    out = body(_render_table(TT, OFF, width=80, now=TUE_0952))
    assert out[9] == "│ 09:40 │            │ ▶ MATH!    │"
    assert out[-1] == "▶ now 09:52 · MATH · 38 min left"
    assert not any("▶" in l for l in out[:9])                       # Mon and past periods


def test_render_table_merged_double_lesson_is_current():
    out = body(_render_table(TT, OFF, width=80, now=MON_0900))
    assert out[3] == "│ 07:50 │ ▶ MATH     │ NET/PROG   │"
    assert out[-1] == "▶ now 09:00 · MATH · 35 min left"


def test_render_table_break_and_before_school():
    assert body(_render_table(TT, OFF, width=80, now=MON_1000))[-1] == \
        "now 10:00 · next: ENG at 10:45 (in 45 min)"
    out = body(_render_table(TT, OFF, width=80, now=MON_0700))
    assert out[-1] == "now 07:00 · next: MATH at 07:50 (in 50 min)"
    assert not any("▶" in l for l in out)


def test_render_table_no_marks_after_school_or_on_other_days():
    for now in (MON_1300, datetime(2026, 10, 7, 9, 0), None):
        out = body(_render_table(TT, ON, width=80, now=now))
        assert out[-1].startswith("└") and not any("▶" in l for l in out)
        assert "\033[2mMATH" not in "\n".join(out)                       # nothing dimmed
        assert "\033[33m" not in "\n".join(out[2:])                      # no yellow below


def test_render_table_today_header_stays_yellow_after_school():
    assert "\033[33mMon 05.10." in body(_render_table(TT, ON, width=80, now=MON_1300))[1]
    other = body(_render_table(TT, ON, width=80, now=datetime(2026, 10, 7, 9, 0)))
    assert "\033[33m" not in other[1]                                    # today not shown


def test_render_table_cancelled_lesson_is_not_running():
    out = body(_render_table(TT, OFF, width=80, now=datetime(2026, 10, 6, 9, 0)))
    assert out[6] == "│ 08:45 │            │ ~GEO~      │"                # no ▶
    assert out[-1] == "now 09:00 · next: MATH at 09:40 (in 40 min)"


def test_render_table_past_periods_dimmed_today_only():
    out = body(_render_table(TT, ON, width=80, now=TUE_0952))
    assert "\033[2mNET/PROG\033[0m" in out[3]                            # Tue: over
    assert "\033[31;9mGEO\033[0m" in out[6]                              # cancelled keeps red
    assert "MATH" in out[3] and "\033[2mMATH" not in out[3]              # Mon: untouched


def test_render_summary_table_passes_now():
    out = render_summary({"meta": {}, "timetable": TT}, color=False, now=TUE_0952,
                         layout="table", width=80)
    assert "▶ now 09:52 · MATH · 38 min left" in out
