"""Tests for --long and --who (#26)."""
from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from untis import cache
from untis import main as main_mod
from untis import names
from untis.config import ScraperConfig
from untis.summary import render_summary
from untis.untis_client import WebUntisError

DAY = "2026-10-05"


def _el(short, long=None, **extra):
    return {"short": short, "long": long, **extra}


def _payload():
    return {
        "meta": {"user": "Max Muster", "school": "demo", "window": {"start": DAY, "end": DAY}},
        "timetable": {"days": [{"date": DAY, "entries": [{
            "start": f"{DAY}T07:50", "end": f"{DAY}T08:40", "status": "CHANGED",
            "subjects": [_el("MATH", "Mathematics")],
            "teachers": [_el("TCH4", "Teacher Four", status="ADDED", replaces="TCH3",
                             replaces_long="Teacher Three")],
            "rooms": [_el("R101", "Classroom, building A")],
            "classes": [_el("1AB", "Class 1AB")],
        }]}], "lessons": [{"subjects": [_el("GER", "German")], "teachers": [], "rooms": []}]},
        "exams": {"exams": [{"date": "2026-10-06", "subjects": [_el("ENG", "English")],
                             "teachers": [_el("TCH2")], "rooms": []}]},
        "homework": {"items": [{"due_date": "2026-10-07", "subjects": [_el("PROG")],
                                "teachers": [_el("TCH1", None)]}]},
    }


# --- use_long_names -------------------------------------------------------------
def test_use_long_names_swaps_where_known():
    p = _payload()
    out = names.use_long_names(p)
    entry = out["timetable"]["days"][0]["entries"][0]
    assert entry["subjects"][0]["short"] == "Mathematics"
    assert entry["teachers"][0]["short"] == "Teacher Four"
    assert entry["teachers"][0]["replaces"] == "Teacher Three"
    assert entry["rooms"][0]["short"] == "Classroom, building A"
    assert out["timetable"]["lessons"][0]["subjects"][0]["short"] == "German"
    assert out["exams"]["exams"][0]["subjects"][0]["short"] == "English"
    assert out["exams"]["exams"][0]["teachers"][0]["short"] == "TCH2"       # no long name
    assert out["homework"]["items"][0]["subjects"][0]["short"] == "PROG"
    assert p["timetable"]["days"][0]["entries"][0]["subjects"][0]["short"] == "MATH"


def test_use_long_names_keeps_short_replaces_without_long():
    p = {"timetable": {"days": [{"entries": [{"teachers": [_el("NEW", "New", replaces="OLD")]}]}]}}
    t = names.use_long_names(p)["timetable"]["days"][0]["entries"][0]["teachers"][0]
    assert (t["short"], t["replaces"]) == ("New", "OLD")


def test_use_long_names_empty_and_errors():
    assert names.use_long_names({}) == {}
    p = {"timetable": {"error": "x"}, "exams": {"error": "y"}}
    assert names.use_long_names(p) == p


def test_long_names_in_the_day_view():
    out = render_summary(names.use_long_names(_payload()), color=False,
                         now=datetime(2000, 1, 1))
    assert "Mathematics" in out and "Teacher Four (for Teacher Three)" in out
    assert "Classroom, building A" in out


# --- collecting -----------------------------------------------------------------------
def test_add():
    found: names.Names = {}
    names._add(found, "room", "R1", None)
    assert found == {("room", "R1"): ""}
    names._add(found, "room", "R1", "Lab")
    names._add(found, "room", "R1", None)            # never drops a known long name
    names._add(found, "room", None, "ignored")
    names._add(found, "room", " R2 ", " Hall ")
    assert found == {("room", "R1"): "Lab", ("room", "R2"): "Hall"}


def test_collect_names():
    found = names.collect_names(_payload())
    assert found[("subject", "MATH")] == "Mathematics"
    assert found[("teacher", "TCH4")] == "Teacher Four"
    assert found[("room", "R101")] == "Classroom, building A"
    assert found[("class", "1AB")] == "Class 1AB"
    assert found[("subject", "GER")] == "German"
    assert found[("teacher", "TCH2")] == "" and found[("subject", "PROG")] == ""
    assert names.collect_names({}) == {}


def test_names_from_filter():
    response = {
        "rooms": [{"room": {"shortName": "R101", "longName": "Classroom"}}, "junk",
                  {"room": {"shortName": "R102", "displayName": "Lab"}}],
        "classes": [{"class": {"shortName": "1AB", "longName": "Class 1AB"},
                     "classTeacher1": {"shortName": "TCH1", "longName": "Teacher One"},
                     "classTeacher2": None}],
        "subjects": [{"subject": {"shortName": "MATH", "longName": "Mathematics"}}],
        "students": [{"student": {"shortName": "x"}}],
    }
    assert names.names_from_filter(response) == {
        ("room", "R101"): "Classroom", ("room", "R102"): "Lab", ("class", "1AB"): "Class 1AB",
        ("teacher", "TCH1"): "Teacher One", ("subject", "MATH"): "Mathematics"}
    assert names.names_from_filter({}) == {}


# --- lookup / format ---------------------------------------------------------------------
KNOWN = {("subject", "MATH"): "Mathematics", ("subject", "PHM"): "Physics and Mathematics",
         ("teacher", "TCH1"): "Teacher One", ("room", "TCH1"): "Odd room",
         ("room", "R101"): ""}


@pytest.mark.parametrize("code, found", [
    ("math", [("subject", "MATH", "Mathematics")]),
    ("MATHEMATICS", [("subject", "MATH", "Mathematics")]),           # exact long name
    ("tch1", [("room", "TCH1", "Odd room"), ("teacher", "TCH1", "Teacher One")]),
    ("mathem", [("subject", "MATH", "Mathematics"), ("subject", "PHM", "Physics and Mathematics")]),
    ("phm", [("subject", "PHM", "Physics and Mathematics")]),
    ("ma", []),                                                       # too short to search
    ("", []), ("  ", []), ("nothing", []),
    ("r101", [("room", "R101", "")]),
])
def test_lookup(code, found):
    assert names.lookup(KNOWN, code) == found


def test_format_who():
    assert names.format_who([("room", "TCH1", "Odd room"), ("teacher", "TCH1", "Teacher One"),
                             ("room", "R1", "")]) == (
        "TCH1   room      Odd room\n"
        "TCH1   teacher   Teacher One\n"
        "R1     room      -")
    assert names.format_who([]) == ""


# --- CLI ------------------------------------------------------------------------------------
def parse(argv, defaults=()):
    return main_mod._parse_args(argv, default_args=list(defaults))


def test_flags():
    assert parse(["--long"]).long is True
    assert parse(["--who", "TCH1"]).who == "TCH1"
    assert parse([]).who is None


@pytest.mark.parametrize("argv", [
    ["--who", "X", "-s"], ["--who", "X", "--tests"], ["--who", "X", "--now"],
    ["--who", "X", "--start"], ["--who", "X", "--json", "-"], ["--who", "X", "--live"],
    ["--who", "X", "--legend"], ["--long", "--now"], ["--long", "--changes"],
])
def test_conflicts(argv):
    with pytest.raises(SystemExit) as exc:
        parse(argv)
    assert exc.value.code == 2


def test_who_not_allowed_in_default_args():
    with pytest.raises(SystemExit):
        parse([], ["--who", "X"])


def _setup(monkeypatch, tmp_path, payload=None, account=None):
    cfg = ScraperConfig(server="s", school="sc", username="u", output_dir=str(tmp_path))
    monkeypatch.setattr(main_mod, "load_config", lambda *a: cfg)
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "last.json")
    if payload is not None:
        cache.save(tmp_path / "last.json", payload, cfg, datetime(2026, 10, 5, 7))
        if account:
            entry = json.loads((tmp_path / "last.json").read_text())
            entry["account"] = account
            (tmp_path / "last.json").write_text(json.dumps(entry))
    fetch = AsyncMock(return_value={("class", "2CD"): "Class 2CD"})
    monkeypatch.setattr(main_mod, "_fetch_names", fetch)
    return cfg, fetch


async def test_who_from_the_cache_without_network(monkeypatch, tmp_path, capsys):
    _, fetch = _setup(monkeypatch, tmp_path, _payload())
    assert await main_mod._async_main(parse(["--who", "tch4"])) == 0
    assert capsys.readouterr().out.strip() == "TCH4   teacher   Teacher Four"
    fetch.assert_not_awaited()


async def test_who_falls_back_to_the_lists(monkeypatch, tmp_path, capsys):
    _, fetch = _setup(monkeypatch, tmp_path, _payload())
    assert await main_mod._async_main(parse(["--who", "2cd"])) == 0
    assert "2CD   class   Class 2CD" in capsys.readouterr().out
    fetch.assert_awaited_once()


async def test_who_ignores_another_accounts_cache(monkeypatch, tmp_path, capsys):
    _, fetch = _setup(monkeypatch, tmp_path, _payload(), account="other/x/y")
    assert await main_mod._async_main(parse(["--who", "TCH4"])) == main_mod.EXIT_NOT_FOUND
    fetch.assert_awaited_once()


async def test_who_offline_never_fetches(monkeypatch, tmp_path, capsys):
    _, fetch = _setup(monkeypatch, tmp_path)
    assert await main_mod._async_main(parse(["--who", "2CD", "--offline"])) \
        == main_mod.EXIT_NOT_FOUND
    assert "in the cached data" in capsys.readouterr().err
    fetch.assert_not_awaited()


async def test_who_not_found(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, tmp_path, _payload())
    assert await main_mod._async_main(parse(["--who", "ZZZ9"])) == main_mod.EXIT_NOT_FOUND
    assert "no subject, teacher, room or class 'ZZZ9'" in capsys.readouterr().err


async def test_fetch_names_uses_filters_and_this_week(monkeypatch, tmp_path):
    cfg = ScraperConfig(server="s", school="sc", output_dir=str(tmp_path))

    class Session:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
    client = MagicMock()
    client.login = AsyncMock()
    client.close = AsyncMock()

    async def get_filter(kind):
        if kind == "ROOM":
            return {"rooms": [{"room": {"shortName": "R101", "longName": "Classroom"}}]}
        raise WebUntisError("HTTP 403")
    client.get_filter = get_filter
    scraper = MagicMock()
    scraper.return_value.run = AsyncMock(return_value=_payload())
    monkeypatch.setattr(main_mod, "BrowserSession", Session)
    monkeypatch.setattr(main_mod, "WebUntisClient", lambda cfg, session: client)
    monkeypatch.setattr(main_mod, "Scraper", scraper)
    found = await main_mod._fetch_names(cfg, parse([]))
    assert found[("room", "R101")] == "Classroom, building A"   # timetable name wins
    assert found[("subject", "MATH")] == "Mathematics"
    assert cfg.start_date and cfg.end_date and (cfg.end_date - cfg.start_date).days == 6
    assert not (cfg.scrape_exams or cfg.scrape_homework or cfg.scrape_absences
                or cfg.scrape_messages)
    client.close.assert_awaited_once()


async def test_long_views_but_unchanged_json(monkeypatch, tmp_path, capsys):
    cfg, _ = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(main_mod, "_fetch", AsyncMock(return_value=_payload()))
    await main_mod._async_main(parse(["-s", "--long", "--date", "05.10.2026",
                                      "--color", "never"]))
    out = capsys.readouterr().out
    assert "Mathematics" in out and "MATH " not in out
    latest = json.loads((tmp_path / "latest.json").read_text())
    assert latest["timetable"]["days"][0]["entries"][0]["subjects"][0]["short"] == "MATH"
