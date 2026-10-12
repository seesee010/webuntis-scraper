"""Tests for --lang / "language": the day view in German (#27)."""
from __future__ import annotations

import re
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from untis import main as main_mod
from untis import summary
from untis.config import ConfigError, ScraperConfig, load_config, resolve_language
from untis.summary import _plain, render_legend, render_summary, tr

NOT_LIVE = datetime(2000, 1, 1, 12, 0)
DAY = "2026-10-05"                                   # a Monday


def _entry(start, end, subject, teachers=(), rooms=("R101",), status="REGULAR", **kw):
    return {
        "start": f"{DAY}T{start}", "end": f"{DAY}T{end}", "status": status,
        "is_cancelled": kw.get("cancelled", False), "is_exam": kw.get("exam", False),
        "subjects": [{"short": subject}] if subject else [],
        "teachers": list(teachers) or [{"short": "TCH1"}],
        "rooms": [{"short": r} for r in rooms],
        "info": kw.get("info", ""), "lesson_text": "", "substitution_text": "",
        "is_event": kw.get("event", False), "is_removed": kw.get("removed", False),
        "no_teacher": kw.get("no_teacher", False),
    }


def _payload(**extra):
    return {
        "meta": {"user": "Max Muster", "school": "demo",
                 "window": {"start": DAY, "end": DAY}, **extra.pop("meta", {})},
        "timetable": {"days": [{"date": DAY, "entries": [
            _entry("07:50", "08:40", "MATH"),
            _entry("08:45", "09:35", "ENG",
                   [{"short": "TCH4", "status": "ADDED", "replaces": "TCH3"}], status="CHANGED"),
            _entry("09:40", "10:30", "GEO", status="CANCELLED", cancelled=True),
            _entry("10:45", "11:35", "ETH", removed=True),
            _entry("11:40", "12:30", "NET", [{"short": "TCH7", "status": "REMOVED"}],
                   no_teacher=True),
            _entry("12:35", "13:25", "PROG", exam=True),
            _entry("13:25", "14:15", None, event=True, info="Sports day"),
        ]}]},
        **extra,
    }


# --- tr / _Style.t / _fmt_day ------------------------------------------------
def test_tr():
    assert tr("cancelled") == "cancelled"
    assert tr("cancelled", "de") == "entfällt"
    assert tr("now · {left} left", "de", left="5 min") == "jetzt · noch 5 min"
    assert tr("now · {left} left", "en", left="5 min") == "now · 5 min left"
    assert tr("not translated", "de") == "not translated"
    assert tr("cancelled", "xx") == "cancelled"


def test_issue_labels_in_german():
    de = summary._TEXT["de"]
    assert (de["cancelled"], de["removed"], de["no teacher"], de["changed"], de["exam"],
            de["event"], de["substitution"]) == (
        "entfällt", "ausgetragen", "kein Lehrer", "geändert", "Prüfung", "Veranstaltung",
        "Supplierung")


@pytest.mark.parametrize("lang", [l for l in summary.LANGUAGES if l != "en"])
def test_translations_keep_the_placeholders(lang):
    fields = lambda t: sorted(re.findall(r"{(\w+)}", t))      # noqa: E731
    for en, other in summary._TEXT[lang].items():
        assert fields(en) == fields(other), en


def test_style_t():
    assert summary._Style(False).t("Time") == "Time"
    assert summary._Style(False, "de").t("Time") == "Zeit"
    assert summary._Style(True, "de").lang == "de"


def test_fmt_day():
    assert summary._fmt_day(DAY) == "Mon 05.10."
    assert summary._fmt_day(DAY, "de") == "Mo 05.10."
    assert summary._fmt_day("2026-10-11", "de") == "So 11.10."
    assert summary._fmt_day(DAY, "xx") == "Mon 05.10."


def test_cache_age():
    now = datetime(2026, 10, 5, 8, 0)
    assert summary._cache_age("2026-10-05T07:46:00", now, "de") == "zwischengespeichert, 14 min alt"
    assert summary._cache_age("2026-10-05T07:59:50", now, "de") == "zwischengespeichert, gerade eben"
    assert summary._cache_age("2026-10-05T07:46:00", now) == "cached, 14 min old"


# --- day view ------------------------------------------------------------------
def test_day_view_in_german():
    out = render_summary(_payload(), color=False, now=NOT_LIVE, lang="de")
    lines = out.splitlines()
    assert "Mo 05.10." in out and "Mon" not in out
    assert "TCH4 (statt TCH3)" in out
    row = lambda subj: next(l for l in lines if f" {subj} " in l)    # noqa: E731
    assert row("ENG").endswith("geändert")
    assert row("GEO").endswith("entfällt")
    assert row("ETH").endswith("ausgetragen")
    assert row("NET").endswith("kein Lehrer")
    assert row("PROG").endswith("Prüfung")
    assert next(l for l in lines if "Sports day" in l).endswith("Veranstaltung")


def test_day_view_english_is_unchanged():
    out = render_summary(_payload(), color=False, now=NOT_LIVE)
    assert "Mon 05.10." in out and "TCH4 (for TCH3)" in out and "entfällt" not in out


def test_day_view_live_lines_in_german():
    during = render_summary(_payload(), color=False, now=datetime(2026, 10, 5, 8, 0), lang="de")
    assert "jetzt · noch 40 min" in during
    brk = render_summary(_payload(), color=False, now=datetime(2026, 10, 5, 8, 42), lang="de")
    assert "──── jetzt 08:42 · nächste in 3 min ────" in brk


def test_empty_window_counts_and_cache_header_in_german():
    payload = {"meta": {"window": {"start": DAY, "end": DAY}, "cached_at": "2026-10-05T07:00:00"},
               "timetable": {"days": []},
               "absences": {"items": [{"is_excused": False}, {"is_excused": True}]},
               "messages": {"items": [{"read": False}]}}
    out = render_summary(payload, color=False, now=datetime(2026, 10, 5, 7, 30), lang="de")
    assert "Keine Stunden in diesem Zeitraum." in out
    assert "2 Abwesenheiten (1 nicht entschuldigt)" in out
    assert "1 ungelesene Nachricht" in out
    assert "(zwischengespeichert, 30 min alt)" in out


def test_exams_and_homework_sections_in_german():
    payload = _payload(exams={"exams": [{"date": "2026-10-06", "subjects": [{"short": "MATH"}],
                                         "name": "Test"}]},
                       homework={"items": [{"due_date": "2026-10-07",
                                            "subjects": [{"short": "ENG"}], "text": "p. 12"}]})
    out = render_summary(payload, color=False, now=NOT_LIVE, lang="de")
    assert "Prüfungen" in out and "Di 06.10." in out
    assert "Hausübungen" in out and "fällig Mi 07.10." in out


def test_oneline_and_table_in_german():
    one = render_summary(_payload(), color=False, now=NOT_LIVE, layout="oneline", lang="de")
    assert one.startswith("Mo 05.10.")
    table = render_summary(_payload(), color=False, now=NOT_LIVE, layout="table",
                           width=120, lang="de")
    assert "│ Zeit " in table and "Mo 05.10." in table


def test_table_now_line_in_german():
    during = render_summary(_payload(), color=False, now=datetime(2026, 10, 5, 8, 0),
                            layout="table", width=120, lang="de")
    assert "▶ jetzt 08:00 · MATH · noch 40 min" in during
    before = render_summary(_payload(), color=False, now=datetime(2026, 10, 5, 7, 30),
                            layout="table", width=120, lang="de")
    assert "jetzt 07:30 · als Nächstes: MATH um 07:50 (in 20 min)" in before


# --- legend ----------------------------------------------------------------------
def test_legend_in_german_is_aligned():
    lines = render_legend(False, "de").splitlines()
    assert lines[0] == "Legende"
    assert any(l.strip().startswith("Veranstaltung") for l in lines)
    rows = [l for l in lines[1:8]]
    cols = {re.search(r" R\d{3}", l).start() for l in rows}
    assert len(cols) == 1                                    # rooms line up
    assert "TCH4 (statt TCH3)" in "\n".join(lines)


def test_legend_english_is_unchanged():
    lines = render_legend(False).splitlines()
    assert lines[0] == "Legend"
    assert lines[1] == "  regular     MATH   TCH1             R101"


# --- config ---------------------------------------------------------------------
@pytest.mark.parametrize("value, locale, lang", [
    (None, "de-DE", "en"), ("", "de-DE", "en"), ("en", "de-DE", "en"), ("DE", "en-US", "de"),
    ("auto", "de-AT", "de"), ("auto", "de_CH", "de"), ("auto", "en-GB", "en"),
    ("auto", "fr-FR", "en"), ("auto", "", "en"), (" Auto ", "de", "de"),
])
def test_resolve_language(value, locale, lang):
    assert resolve_language(value, locale) == lang


@pytest.mark.parametrize("value", ["fr", "german", 1])
def test_resolve_language_rejects(value):
    with pytest.raises(ValueError, match="en, de or auto"):
        resolve_language(value, "de-DE")


def _config(tmp_path, text):
    path = tmp_path / "config.json"
    path.write_text(text)
    return load_config(path, tmp_path / ".env")


def test_config_language(tmp_path):
    base = '"server": "s", "school": "sc"'
    assert _config(tmp_path, "{" + base + "}").language == "en"
    assert _config(tmp_path, "{" + base + ', "language": "de"}').language == "de"
    assert _config(tmp_path, "{" + base + ', "language": "auto", "locale": "de-AT"}').language \
        == "de"
    with pytest.raises(ConfigError, match="language"):
        _config(tmp_path, "{" + base + ', "language": "fr"}')


# --- CLI ------------------------------------------------------------------------
def test_lang_flag():
    assert main_mod._parse_args(["--lang", "de"], default_args=[]).lang == "de"
    assert main_mod._parse_args([], default_args=[]).lang is None
    with pytest.raises(SystemExit):
        main_mod._parse_args(["--lang", "fr"], default_args=[])


def test_legend_language(tmp_path):
    args = main_mod._parse_args(["--config", str(tmp_path / "none.json")], default_args=[])
    assert main_mod._legend_language(args) == "en"
    args.lang = "de"
    assert main_mod._legend_language(args) == "de"
    path = tmp_path / "config.json"
    path.write_text('{"language": "auto", "locale": "de-AT"}')
    args = main_mod._parse_args(["--config", str(path)], default_args=[])
    assert main_mod._legend_language(args) == "de"
    path.write_text('{"language": "klingon"}')
    assert main_mod._legend_language(args) == "en"


def test_main_legend_only_in_german(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("sys.argv", ["untis", "--legend", "--lang", "de", "--color", "never",
                                     "--config", str(tmp_path / "none.json")])
    assert main_mod.main() == 0
    assert capsys.readouterr().out.startswith("Legende")


@pytest.mark.parametrize("argv, cfg_lang, expected", [
    (["-s", "--lang", "de"], "en", "Mo 05.10."), (["-s"], "de", "Mo 05.10."),
    (["-s", "--lang", "en"], "de", "Mon 05.10."), (["-s"], "en", "Mon 05.10."),
])
async def test_async_main_language(monkeypatch, tmp_path, capsys, argv, cfg_lang, expected):
    c = ScraperConfig(server="s", school="sc", output_dir=str(tmp_path), language=cfg_lang)
    monkeypatch.setattr(main_mod, "load_config", lambda *a: c)
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "last.json")
    monkeypatch.setattr(main_mod, "_fetch", AsyncMock(return_value=_payload()))
    await main_mod._async_main(main_mod._parse_args(
        argv + ["--date", "05.10.", "--color", "never", "--no-json"], default_args=[]))
    assert expected in _plain(capsys.readouterr().out)
