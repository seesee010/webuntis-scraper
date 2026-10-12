"""Tests for --only / --except: filter the views by subject (#25)."""
from __future__ import annotations

import argparse
import json
from datetime import date
from unittest.mock import AsyncMock

import pytest

from untis import filters
from untis import main as main_mod
from untis.config import ScraperConfig

MON = date(2026, 10, 5)


def _subj(short, long=None):
    return [{"short": short, "long": long}]


def _entry(short, long=None, **extra):
    return {"start": "2026-10-05T07:50", "end": "2026-10-05T08:40",
            "subjects": _subj(short, long) if short else [], **extra}


def _payload():
    return {
        "meta": {"window": {"start": "2026-10-05", "end": "2026-10-05"}},
        "timetable": {"days": [{"date": "2026-10-05", "entries": [
            _entry("MATH", "Mathematics"), _entry("ENG", "English"),
            _entry(None, is_event=True, info="Sports day")]}]},
        "exams": {"exams": [{"date": "2026-10-06", "subjects": _subj("MATH")},
                            {"date": "2026-10-07", "subjects": _subj("GER")}]},
        "homework": {"items": [{"due_date": "2026-10-06", "subjects": _subj("ENG")},
                               {"due_date": "2026-10-07", "subjects": _subj("REL")}]},
        "absences": {"items": [{"start_date": "2026-10-01"}]},
    }


# --- parse_subjects ----------------------------------------------------------
@pytest.mark.parametrize("text, terms", [
    ("MATH", ["math"]), ("MATH,eng", ["math", "eng"]), (" Math , ENG ,", ["math", "eng"]),
    ("Applied Mathematics", ["applied mathematics"]),
])
def test_parse_subjects(text, terms):
    assert filters.parse_subjects(text) == terms


@pytest.mark.parametrize("text", ["", " ", ",", " , "])
def test_parse_subjects_rejects_empty(text):
    with pytest.raises(ValueError):
        filters.parse_subjects(text)


# --- subject_names / keep ----------------------------------------------------------
def test_subject_names():
    assert filters.subject_names(_entry("MATH", "Mathematics")) == {"math", "mathematics"}
    assert filters.subject_names({"subjects": [{"short": "A"}, {"short": "B", "long": None}]}) \
        == {"a", "b"}
    assert filters.subject_names({}) == set()


@pytest.mark.parametrize("only, exclude, short, kept", [
    (None, None, "MATH", True),
    (["math"], None, "MATH", True),
    (["mathematics"], None, "MATH", True),         # long name
    (["eng"], None, "MATH", False),
    (["eng", "math"], None, "MATH", True),
    (None, ["math"], "MATH", False),
    (None, ["rel"], "MATH", True),
    (["math"], ["math"], "MATH", False),           # --except wins
    (["math"], None, None, False),                 # events have no subject
    (None, ["math"], None, True),
    (["mat"], None, "MATH", False),                # no prefix matching
])
def test_keep(only, exclude, short, kept):
    assert filters.keep(_entry(short, "Mathematics" if short else None), only, exclude) is kept


# --- filter_payload ----------------------------------------------------------------
def test_filter_payload_without_filters_is_unchanged():
    p = _payload()
    assert filters.filter_payload(p, None, None) is p
    assert filters.filter_payload(p, [], []) is p


def test_filter_payload_only():
    p = _payload()
    out = filters.filter_payload(p, ["math", "eng"], None)
    assert [e["subjects"][0]["short"] for e in out["timetable"]["days"][0]["entries"]] \
        == ["MATH", "ENG"]
    assert [e["subjects"][0]["short"] for e in out["exams"]["exams"]] == ["MATH"]
    assert [h["subjects"][0]["short"] for h in out["homework"]["items"]] == ["ENG"]
    assert out["absences"] == p["absences"]                      # no subject: untouched
    assert len(p["timetable"]["days"][0]["entries"]) == 3        # input not changed


def test_filter_payload_except_keeps_events():
    out = filters.filter_payload(_payload(), None, ["math", "rel"])
    entries = out["timetable"]["days"][0]["entries"]
    assert [e.get("is_event", False) for e in entries] == [False, True]
    assert [e["subjects"][0]["short"] for e in out["exams"]["exams"]] == ["GER"]
    assert [h["subjects"][0]["short"] for h in out["homework"]["items"]] == ["ENG"]


def test_filter_payload_jsonrpc_lessons_errors_and_missing_sections():
    p = {"timetable": {"lessons": [{"subjects": _subj("MATH")}, {"subjects": _subj("ENG")}]},
         "exams": {"error": "HTTP 500"}, "homework": {"error": "x"}}
    out = filters.filter_payload(p, ["eng"], None)
    assert [x["subjects"][0]["short"] for x in out["timetable"]["lessons"]] == ["ENG"]
    assert out["exams"] == {"error": "HTTP 500"} and out["homework"] == {"error": "x"}
    assert filters.filter_payload({"timetable": {"error": "x"}}, ["a"], None) \
        == {"timetable": {"error": "x"}}
    assert filters.filter_payload({}, ["a"], None) == {}


# --- CLI ---------------------------------------------------------------------------
def parse(argv, defaults=()):
    return main_mod._parse_args(argv, today=MON, default_args=list(defaults))


def test_subjects_arg():
    assert main_mod._subjects_arg("MATH,Eng") == ["math", "eng"]
    with pytest.raises(argparse.ArgumentTypeError):
        main_mod._subjects_arg(",")


def test_only_and_except_parse_and_repeat():
    args = parse(["--only", "MATH,ENG", "--only", "GER", "--except", "rel"])
    assert args.only == ["math", "eng", "ger"] and args.except_ == ["rel"]
    plain = parse([])
    assert plain.only is None and plain.except_ is None


def test_explicit_only_replaces_the_default_one():
    assert parse(["--only", "ENG"], ["--only", "MATH"]).only == ["eng"]
    assert parse([], ["--except", "REL"]).except_ == ["rel"]


@pytest.mark.parametrize("argv", [["--only", "MATH", "--now"], ["--except", "REL", "--start"],
                                  ["--only", "MATH", "--changes"], ["--only", ""]])
def test_only_conflicts_and_errors(argv):
    with pytest.raises(SystemExit) as exc:
        parse(argv)
    assert exc.value.code == 2


async def _run(monkeypatch, tmp_path, argv):
    c = ScraperConfig(server="s", school="sc", output_dir=str(tmp_path))
    monkeypatch.setattr(main_mod, "load_config", lambda *a: c)
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "last.json")
    monkeypatch.setattr(main_mod, "_fetch", AsyncMock(return_value=_payload()))
    await main_mod._async_main(parse(argv))


async def test_views_are_filtered_but_files_and_cache_are_not(monkeypatch, tmp_path, capsys):
    await _run(monkeypatch, tmp_path, ["-s", "--date", "05.10.", "--only", "math",
                                       "--color", "never"])
    out = capsys.readouterr().out
    assert "MATH" in out and "ENG" not in out and "Sports day" not in out
    latest = json.loads((tmp_path / "latest.json").read_text())
    assert len(latest["timetable"]["days"][0]["entries"]) == 3
    cached = json.loads((tmp_path / "last.json").read_text())["payload"]
    assert len(cached["timetable"]["days"][0]["entries"]) == 3


async def test_json_stdout_is_filtered(monkeypatch, tmp_path, capsys):
    await _run(monkeypatch, tmp_path, ["--json", "-", "--except", "MATH,ENG"])
    data = json.loads(capsys.readouterr().out)
    assert [e.get("is_event") for e in data["timetable"]["days"][0]["entries"]] == [True]
    assert [e["subjects"][0]["short"] for e in data["exams"]["exams"]] == ["GER"]


async def test_sections_are_filtered(monkeypatch, tmp_path, capsys):
    await _run(monkeypatch, tmp_path, ["--homework", "--only", "rel", "--color", "never",
                                       "--no-json"])
    out = capsys.readouterr().out
    assert "REL" in out and "ENG" not in out
