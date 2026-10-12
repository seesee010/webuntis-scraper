"""Tests for the live school search of `untis init` (#76)."""
from __future__ import annotations

import io
import sys
import types

import httpx
import pytest

from untis import school_picker as sp
from untis.setup_wizard import SetupError


def _school(i: int, town: str = "Town") -> dict:
    return {"server": "demo.webuntis.com", "loginName": f"school-{i}",
            "displayName": f"Demo School {i}", "address": f"{1000 + i} {town}"}


SCHOOLS = [_school(i) for i in range(1, 4)]


class Search:
    """Fake school search: records the terms, answers from a dict."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.terms: list[str] = []

    def __call__(self, term):
        self.terms.append(term)
        answer = self.answers.get(term, [])
        if isinstance(answer, BaseException):
            raise answer
        return answer


# --- helpers ---------------------------------------------------------------------
@pytest.mark.parametrize("text, url", [
    ("https://demo.webuntis.com/today", True), ("demo.webuntis.com/WebUntis", True),
    ("HTTP://X", True), ("demo school", False), ("", False),
])
def test_looks_like_url(text, url):
    assert sp.looks_like_url(text) is url


def test_describe():
    assert sp.describe(_school(1)) == "Demo School 1 (1001 Town)"
    assert sp.describe({"loginName": "x"}) == "x"
    assert sp.describe({}) == "?"


def test_cut():
    assert sp._cut("abc", 3) == "abc"
    assert sp._cut("abcdef", 4) == "abc…"
    assert sp._cut("abc", 0) == "…"


# --- editing --------------------------------------------------------------------------
def test_editing_and_stale():
    p = sp.Picker(Search())
    assert p.stale is True                     # nothing searched yet
    p.type("De")
    p.type("mo\x07")                           # control chars are dropped
    assert p.query == "Demo" and p.stale
    p.backspace()
    assert p.query == "Dem"
    p.clear()
    assert p.query == ""
    p.backspace()
    assert p.query == ""


def test_stale_initially_and_after_refresh():
    p = sp.Picker(Search(), "demo")
    assert p.stale
    p.refresh()
    assert not p.stale
    p.type(" x")
    assert p.stale


def test_move_wraps_and_ignores_empty():
    p = sp.Picker(Search({"demo": SCHOOLS}), "demo")
    p.move(1)
    assert p.selected == 0                     # nothing found yet
    p.refresh()
    p.move(1)
    p.move(1)
    assert p.selected == 2
    p.move(1)
    assert p.selected == 0
    p.move(-1)
    assert p.selected == 2


# --- searching ------------------------------------------------------------------------
def test_refresh_short_query_is_not_sent():
    search = Search()
    p = sp.Picker(search, "d")
    p.refresh()
    assert search.terms == [] and p.message == "Keep typing…"
    p.clear()
    p.refresh()
    assert p.message == ""


def test_refresh_url_is_not_sent():
    search = Search()
    p = sp.Picker(search, "https://demo.webuntis.com/today")
    p.refresh()
    assert search.terms == [] and p.message == "Enter: use this URL"


def test_refresh_results_selection_reset_and_cache():
    search = Search({"demo": SCHOOLS, "demo s": SCHOOLS[:1]})
    p = sp.Picker(search, " demo ")
    p.refresh()
    assert p.results == SCHOOLS and p.message == "" and search.terms == ["demo"]
    p.move(2)
    p.type("s")                                # " demo s"
    p.refresh()
    assert p.results == SCHOOLS[:1] and p.selected == 0
    p.backspace()
    p.refresh()
    assert search.terms == ["demo", "demo s"]  # "demo" came from the cache


@pytest.mark.parametrize("answer, message", [
    ([], "No school matches 'demo'"),
    (SetupError("too many schools match 'demo'; be more specific"),
     "Too many schools match, keep typing…"),
    (SetupError("school search failed: boom"), "school search failed: boom"),
    (httpx.ConnectError("offline"), "Search failed: offline"),
    (ValueError("bad JSON"), "Search failed: bad JSON"),
])
def test_refresh_messages(answer, message):
    p = sp.Picker(Search({"demo": answer}), "demo")
    p.refresh()
    assert p.results == [] and p.message == message


def test_choice():
    p = sp.Picker(Search({"demo": SCHOOLS}), "demo")
    assert p.choice() is None                  # not searched yet
    p.refresh()
    p.move(1)
    assert p.choice() == ("school", SCHOOLS[1])
    p.type("x")
    assert p.choice() is None                  # list belongs to the old query
    p.clear()
    p.type(" https://demo.webuntis.com/today ")
    assert p.choice() == ("url", "https://demo.webuntis.com/today")


# --- rendering ------------------------------------------------------------------------
def test_render_input_line_only():
    assert sp.Picker(Search()).render() == ["School: "]


def test_render_results_and_footer():
    p = sp.Picker(Search({"demo": SCHOOLS}), "demo")
    p.refresh()
    p.move(1)
    assert p.render() == [
        "  Demo School 1 (1001 Town)",
        "▸ Demo School 2 (1002 Town)",
        "  Demo School 3 (1003 Town)",
        "3 found · ↑/↓ choose · Enter select · Esc cancel",
        "School: demo",
    ]


def test_render_scrolls_to_the_selection():
    many = [_school(i) for i in range(1, 13)]
    p = sp.Picker(Search({"demo": many}), "demo")
    p.refresh()
    lines = p.render(rows=4)
    assert lines[0].startswith("▸ Demo School 1 ") and len(lines) == 6
    assert lines[4].startswith("(+8 more) 12 found")
    p.move(-1)                                 # wraps to the last one
    lines = p.render(rows=4)
    assert [l[2:15] for l in lines[:4]] == ["Demo School 9", "Demo School 1", "Demo School 1",
                                           "Demo School 1"]
    assert lines[3].startswith("▸ Demo School 12")


def test_render_message_and_width():
    p = sp.Picker(Search(), "d")
    p.refresh()
    assert p.render(width=10) == ["Keep typi…", "School: d"]


# --- keys -------------------------------------------------------------------------------
@pytest.mark.parametrize("text, keys", [
    ("ab", ["a", "b"]),
    ("\x1b[A\x1b[B\x1bOA\x1bOB", [sp.UP, sp.DOWN, sp.UP, sp.DOWN]),
    ("\r\n", [sp.ENTER, sp.ENTER]),
    ("\x7f\x08", [sp.BACKSPACE, sp.BACKSPACE]),
    ("\x03", [sp.CANCEL]), ("\x1b", [sp.CANCEL]), ("\x04", [sp.CANCEL]),
    ("\x10\x0e\x15", [sp.UP, sp.DOWN, sp.CLEAR]),
    ("a\x1b[3~b\x1b[1;5Cc", ["a", "b", "c"]),      # other escape sequences are skipped
    ("ä", ["ä"]),
])
def test_parse_keys(text, keys):
    assert sp.parse_keys(text) == keys


# --- the loop ----------------------------------------------------------------------------
class Term:
    """Scripted terminal: `inputs` are what read() returns in order
    (None = the timeout passed); a fake clock advances on every read."""

    def __init__(self, inputs):
        self.inputs = list(inputs)
        self.timeouts: list = []
        self.output = ""
        self.now = 0.0

    def read(self, timeout):
        self.timeouts.append(timeout)
        self.now += 0.01
        return self.inputs.pop(0)

    def write(self, text):
        self.output += text

    def clock(self):
        return self.now


def _run(search, inputs, query=""):
    term = Term(inputs)
    result = sp.run(sp.Picker(search, query), term.read, term.write, 80, term.clock)
    return result, term


def test_run_types_waits_then_picks():
    search = Search({"demo": SCHOOLS})
    result, term = _run(search, ["de", "mo", None, "\x1b[B", "\r"])
    assert result == ("school", SCHOOLS[1])
    assert search.terms == ["demo"]                   # searched once, after the pause
    assert term.timeouts[0] is None                   # idle: wait for a key
    assert 0 < term.timeouts[1] <= sp.DEBOUNCE        # typing: wait for the pause
    assert "▸ Demo School 2" in term.output
    assert term.output.endswith("\r\n")


def test_run_enter_before_the_pause_searches_first():
    search = Search({"demo": SCHOOLS})
    result, _ = _run(search, ["demo\r"])
    assert result == ("school", SCHOOLS[0]) and search.terms == ["demo"]


def test_run_enter_without_a_match_keeps_going():
    search = Search({"none": [], "demo": SCHOOLS})
    result, term = _run(search, ["none\r", "\x15demo", "\r"])
    assert result == ("school", SCHOOLS[0])
    assert "No school matches 'none'" in term.output


def test_run_pasted_url():
    result, _ = _run(Search(), ["https://demo.webuntis.com/WebUntis/?school=x\r"])
    assert result == ("url", "https://demo.webuntis.com/WebUntis/?school=x")


def test_run_prefilled_query_searches_at_once():
    search = Search({"demo": SCHOOLS})
    result, _ = _run(search, ["\r"], query="demo")
    assert result == ("school", SCHOOLS[0]) and search.terms == ["demo"]


def test_run_redraw_moves_up():
    search = Search({"demo": SCHOOLS, "dem": []})
    result, term = _run(search, ["dem", None, "o", None, "\r"])
    assert result == ("school", SCHOOLS[0])
    assert "\x1b[4A" in term.output or "\x1b[1A" in term.output   # redraw from the top


def test_run_pause_without_typing_does_not_search():
    search = Search()
    with pytest.raises(KeyboardInterrupt):
        _run(search, [None, None, "\x1b"])
    assert search.terms == []


@pytest.mark.parametrize("key", ["\x03", "\x1b", "\x04"])
def test_run_cancel(key):
    with pytest.raises(KeyboardInterrupt):
        _run(Search(), ["de", key])


# --- terminal ----------------------------------------------------------------------------
class FakeTty(io.StringIO):
    def __init__(self, tty=True):
        super().__init__()
        self._tty = tty

    def isatty(self):
        return self._tty


def test_available():
    assert sp.available(FakeTty(), FakeTty()) is True
    assert sp.available(FakeTty(False), FakeTty()) is False
    assert sp.available(FakeTty(), FakeTty(False)) is False
    assert sp.available(object(), FakeTty()) is False      # no isatty at all


def test_available_without_termios(monkeypatch):
    monkeypatch.setitem(sys.modules, "termios", None)       # e.g. Windows
    assert sp.available(FakeTty(), FakeTty()) is False


def _fake_terminal(monkeypatch, chunks):
    """Fake termios/tty/select/os.read around pick()."""
    calls = {"setraw": 0, "restored": None}
    termios = types.SimpleNamespace(
        TCSADRAIN=1, tcgetattr=lambda fd: ["old"],
        tcsetattr=lambda fd, when, attrs: calls.__setitem__("restored", attrs))
    tty = types.SimpleNamespace(setraw=lambda fd: calls.__setitem__("setraw", calls["setraw"] + 1))
    data = list(chunks)
    def fake_select(r, w, x, timeout):
        if data and data[0] is None:               # the timeout passed
            data.pop(0)
            return [], [], []
        return r, [], []
    select = types.SimpleNamespace(select=fake_select)
    monkeypatch.setitem(sys.modules, "termios", termios)
    monkeypatch.setitem(sys.modules, "tty", tty)
    monkeypatch.setitem(sys.modules, "select", select)
    monkeypatch.setattr(sp.os, "read", lambda fd, n: data.pop(0))
    stdin = types.SimpleNamespace(fileno=lambda: 0)
    monkeypatch.setattr(sys, "stdin", stdin)
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    return calls, out


def test_pick_runs_raw_and_restores_the_terminal(monkeypatch):
    calls, out = _fake_terminal(monkeypatch, ["dé".encode()[:2], "é".encode()[1:] + b"mo",
                                             None, b"\r"])
    result = sp.pick(Search({"démo": SCHOOLS}))
    assert result == ("school", SCHOOLS[0])            # UTF-8 split across reads
    assert calls == {"setraw": 1, "restored": ["old"]}
    assert "School: démo" in out.getvalue()


def test_pick_restores_the_terminal_on_cancel(monkeypatch):
    calls, _ = _fake_terminal(monkeypatch, [b"\x03"])
    with pytest.raises(KeyboardInterrupt):
        sp.pick(Search())
    assert calls["restored"] == ["old"]
