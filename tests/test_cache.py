"""Tests for --offline / --max-age and the payload cache (#32)."""
from __future__ import annotations

import argparse
import json
import logging
import os
import stat
import sys
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from untis import cache
from untis import main as main_mod
from untis.cache import (
    CacheMiss,
    account_key,
    age_seconds,
    from_cache,
    offline_window,
    parse_duration,
    slice_payload,
)
from untis.config import ScraperConfig
from untis.summary import _cache_age, render_summary

FRI = date(2026, 10, 2)
NOW = datetime(2026, 10, 2, 9, 0)


def cfg(**kw) -> ScraperConfig:
    base = dict(server="srv", school="sch", username="u", days_forward=0, days_back=0)
    return ScraperConfig(**{**base, **kw})


def _day(iso: str, lessons: bool = True) -> dict:
    entries = [{"start": f"{iso}T07:50", "end": f"{iso}T08:40", "subjects": [{"short": "MATH"}],
                "teachers": [], "rooms": [], "is_cancelled": False}] if lessons else []
    return {"date": iso, "entries": entries}


def payload(start="2026-10-01", end="2026-10-09", **extra) -> dict:
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    days = [_day((d0 + timedelta(i)).isoformat(), (d0 + timedelta(i)).weekday() < 5)
            for i in range((d1 - d0).days + 1)]
    return {
        "meta": {"user": "Max Muster", "school": "sch", "window": {"start": start, "end": end}},
        "timetable": {"source": "rest_v1", "start": start, "end": end, "days": days,
                      "raw": {"days": []}},
        "exams": {"exams": [{"date": "2026-10-05", "name": "Test"},
                            {"date": "2026-10-20", "name": "Later"}]},
        "homework": {"items": [{"date": "2026-10-02", "due_date": "2026-10-06"},
                               {"date": "2026-09-20", "due_date": "2026-09-22"}]},
        "absences": {"items": [{"start_date": "2026-10-01"}, {"start_date": "2026-09-01"}]},
        "messages": {"items": [{"id": 1}]},
        **extra,
    }


def entry(p=None, saved=NOW - timedelta(minutes=5), account="srv/sch/u") -> dict:
    return {"version": 1, "saved_at": saved.isoformat(timespec="seconds"),
            "account": account, "payload": p or payload()}


# --- parse_duration / account_key / save / load / age --------------------
@pytest.mark.parametrize("text, seconds", [("90s", 90), ("10m", 600), ("2h", 7200),
                                           ("1d", 86400), ("15", 900), (" 1.5h ", 5400),
                                           ("0", 0), ("10M", 600)])
def test_parse_duration(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "ten", "10x", "-5m", "m"])
def test_parse_duration_rejects(text):
    with pytest.raises(ValueError, match="invalid duration"):
        parse_duration(text)


def test_account_key():
    assert account_key(cfg()) == "srv/sch/u"


def test_save_and_load_roundtrip_private_without_raw(tmp_path):
    path = tmp_path / "cache" / "last.json"
    cache.save(path, payload(), cfg(), NOW)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    loaded = cache.load(path)
    assert loaded["saved_at"] == "2026-10-02T09:00:00" and loaded["account"] == "srv/sch/u"
    assert "raw" not in loaded["payload"]["timetable"]


@pytest.mark.parametrize("content", ["{broken", json.dumps({"version": 99}), "[]"])
def test_load_ignores_unusable_files(tmp_path, content):
    p = tmp_path / "last.json"
    p.write_text(content)
    assert cache.load(p) is None
    assert cache.load(tmp_path / "missing.json") is None


def test_age_seconds():
    assert age_seconds(entry(), NOW) == 300


# --- offline_window --------------------------------------------------------
def test_offline_window_explicit_dates():
    c = cfg(start_date=date(2026, 10, 5), end_date=date(2026, 10, 6))
    assert offline_window(c, payload(), FRI, NOW) == (date(2026, 10, 5), date(2026, 10, 6), "")


def test_offline_window_tomorrow_skips_weekend():
    assert offline_window(cfg(pick_day="tomorrow"), payload(), FRI, NOW) == \
        (date(2026, 10, 5), date(2026, 10, 5), "next school day")


def test_offline_window_next_after_school():
    late = datetime(2026, 10, 2, 15, 0)
    during = datetime(2026, 10, 2, 8, 0)           # the fixture's lesson is 07:50-08:40
    assert offline_window(cfg(pick_day="next"), payload(), FRI, late)[0] == date(2026, 10, 5)
    assert offline_window(cfg(pick_day="next"), payload(), FRI, during)[0] == FRI


def test_offline_window_pick_day_missing():
    with pytest.raises(CacheMiss, match="no school day"):
        offline_window(cfg(pick_day="tomorrow"), payload(end="2026-10-04"), FRI, NOW)


def test_offline_window_school_days():
    assert offline_window(cfg(days_forward=2), payload(), FRI, NOW)[:2] == \
        (FRI, date(2026, 10, 6))


def test_offline_window_not_enough_school_days():
    with pytest.raises(CacheMiss, match="only"):
        offline_window(cfg(days_forward=10), payload(), FRI, NOW)


def test_offline_window_calendar_and_zero():
    assert offline_window(cfg(days_forward=2, calendar_days=True), payload(), FRI, NOW)[:2] == \
        (FRI, date(2026, 10, 4))
    assert offline_window(cfg(), payload(), FRI, NOW)[:2] == (FRI, FRI)


# --- slice_payload -----------------------------------------------------------
def test_slice_payload_trims_everything_and_marks_cached():
    p = payload()
    out = slice_payload(p, FRI, date(2026, 10, 6), "next school day", "2026-10-02T08:55:00")
    assert out["meta"]["window"] == {"start": "2026-10-02", "end": "2026-10-06",
                                     "note": "next school day"}
    assert out["meta"]["cached_at"] == "2026-10-02T08:55:00"
    assert [d["date"] for d in out["timetable"]["days"]][0] == "2026-10-02"
    assert [e["name"] for e in out["exams"]["exams"]] == ["Test"]
    assert len(out["homework"]["items"]) == 1 and len(out["absences"]["items"]) == 0
    assert out["messages"]["items"] == [{"id": 1}]
    assert len(p["timetable"]["days"]) == 9                    # input untouched


def test_slice_payload_without_note():
    assert "note" not in slice_payload(payload(), FRI, FRI, "", "x")["meta"]["window"]


@pytest.mark.parametrize("max_age", [None, 600])
@pytest.mark.parametrize("by_due_date, expected", [(True, [1, 3, 4, 6, 7]),
                                                 (False, [2, 3, 4, 6, 7])])
def test_cached_homework_uses_requested_date_mode(max_age, by_due_date, expected):
    day = date(2026, 10, 6)
    items = [
        {"id": 1, "date": "2026-10-02", "due_date": "2026-10-06"},
        {"id": 2, "date": "2026-10-06", "due_date": "2026-10-09"},
        {"id": 3, "date": "2026-10-06", "due_date": None},
        {"id": 4, "date": "2026-10-06", "due_date": "2026-10-06"},
        {"id": 5, "date": "2026-10-02", "due_date": "2026-10-09"},
        {"id": 6, "date": "2026-10-06"},
        {"id": 7, "due_date": "2026-10-06"},
        {"id": 8},
    ]
    p = payload(homework={"items": items})
    out = from_cache(cfg(start_date=day, homework_by_due_date=by_due_date),
                     entry(p), FRI, NOW, max_age=max_age)
    assert [h["id"] for h in out["homework"]["items"]] == expected
    assert p["homework"]["items"] == items


@pytest.mark.parametrize("mode", [["--offline"], ["--max-age", "1h"]])
def test_cli_cached_homework_filters_by_due_date(monkeypatch, tmp_path, capsys, mode):
    c = cfg(output_dir=str(tmp_path / "out"))
    monkeypatch.setattr(main_mod, "load_config", lambda *a: c)
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "last.json")
    p = payload(homework={"items": [
        {"id": 1, "date": "2026-10-02", "due_date": "2026-10-06"},
        {"id": 2, "date": "2026-10-06", "due_date": "2026-10-09"},
        {"id": 3, "date": "2026-10-06", "due_date": None},
    ]})
    cache.save(main_mod.CACHE_PATH, p, c, datetime.now())
    fetch = AsyncMock(side_effect=AssertionError("cache hit must not fetch"))
    monkeypatch.setattr(main_mod, "_fetch", fetch)
    monkeypatch.delenv("UNTIS_DEFAULT_ARGS", raising=False)
    monkeypatch.setattr(sys, "argv", ["untis", "--config", str(tmp_path / "config.json"),
                                     "--homework", "--date", "2026-10-06", "--json", "-", *mode])
    assert main_mod.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert [h["id"] for h in out["homework"]["items"]] == [1, 3]
    assert out["meta"]["cached_at"]
    fetch.assert_not_awaited()
    assert not (tmp_path / "out").exists()


# --- from_cache --------------------------------------------------------------
def test_from_cache_hit():
    out = from_cache(cfg(start_date=FRI), entry(), FRI, NOW, max_age=600)
    assert out["meta"]["window"]["start"] == "2026-10-02" and out["meta"]["cached_at"]


def test_from_cache_other_account():
    with pytest.raises(CacheMiss, match="another account"):
        from_cache(cfg(start_date=FRI), entry(account="x/y/z"), FRI, NOW)


def test_from_cache_too_old():
    with pytest.raises(CacheMiss, match="5 min old"):
        from_cache(cfg(start_date=FRI), entry(), FRI, NOW, max_age=60)


def test_from_cache_without_max_age_ignores_age():
    old = entry(saved=NOW - timedelta(days=3))
    assert from_cache(cfg(start_date=FRI), old, FRI, NOW)


@pytest.mark.parametrize("change", [lambda p: p.pop("exams"),
                                    lambda p: p.update(homework={"error": "HTTP 500"})])
def test_from_cache_missing_or_failed_module(change):
    p = payload()
    change(p)
    with pytest.raises(CacheMiss, match="no cached"):
        from_cache(cfg(start_date=FRI), entry(p), FRI, NOW)


def test_from_cache_module_not_requested_is_fine():
    p = payload()
    p.pop("messages")
    assert from_cache(cfg(start_date=FRI, scrape_messages=False), entry(p), FRI, NOW)


def test_from_cache_window_not_covered():
    with pytest.raises(CacheMiss, match="covers 2026-10-01..2026-10-09"):
        from_cache(cfg(start_date=date(2026, 10, 12)), entry(), FRI, NOW)


# --- main wiring -------------------------------------------------------------
def _args(**kw) -> argparse.Namespace:
    return argparse.Namespace(**{"offline": False, "max_age": None, **kw})


def test_main_from_cache_hit(monkeypatch, tmp_path):
    path = tmp_path / "last.json"
    path.write_text(json.dumps(entry()))
    monkeypatch.setattr(main_mod, "CACHE_PATH", path)
    out = main_mod._from_cache(cfg(start_date=FRI), _args(offline=True), FRI, NOW)
    assert out["meta"]["cached_at"]


def test_main_offline_miss_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "missing.json")
    with pytest.raises(CacheMiss, match="no cached data yet"):
        main_mod._from_cache(cfg(), _args(offline=True), FRI, NOW)


def test_main_max_age_miss_falls_back_to_fetching(monkeypatch, tmp_path, caplog):
    path = tmp_path / "last.json"
    path.write_text(json.dumps(entry()))
    monkeypatch.setattr(main_mod, "CACHE_PATH", path)
    with caplog.at_level(logging.INFO, logger="untis.main"):
        assert main_mod._from_cache(cfg(start_date=FRI), _args(max_age=60), FRI, NOW) is None
    assert any("Not using the cache" in r.getMessage() for r in caplog.records)


def test_cache_miss_maps_to_exit_4():
    code, msg = main_mod._describe_error(CacheMiss("nope"), _args(config="c", env="e"))
    assert code == main_mod.EXIT_NETWORK and msg == "offline: nope"


def test_duration_arg():
    assert main_mod._duration_arg("10m") == 600
    with pytest.raises(argparse.ArgumentTypeError):
        main_mod._duration_arg("soon")


def test_cli_flags():
    a = main_mod._parse_args(["--offline", "--max-age", "2h"], default_args=[])
    assert a.offline is True and a.max_age == 7200
    assert main_mod._parse_args(["--no-offline"], default_args=["--offline"]).offline is False


async def _run_async_main(monkeypatch, tmp_path, argv, cached):
    """_async_main with config, fetching and writing mocked out."""
    c = cfg(start_date=FRI, end_date=FRI, output_dir=str(tmp_path / "out"))
    monkeypatch.setattr(main_mod, "load_config", lambda *a: c)
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "last.json")
    if cached:      # _async_main uses the real clock, so save "now"
        (tmp_path / "last.json").write_text(json.dumps(entry(saved=datetime.now())))
    fetch = AsyncMock(return_value=payload())
    monkeypatch.setattr(main_mod, "_fetch", fetch)
    args = main_mod._parse_args(argv, today=FRI, default_args=[])
    await main_mod._async_main(args)
    return fetch


async def test_async_main_cache_hit_skips_fetch_and_json(monkeypatch, tmp_path):
    fetch = await _run_async_main(monkeypatch, tmp_path, ["--max-age", "1h", "--config", "x"], True)
    fetch.assert_not_awaited()
    assert not (tmp_path / "out").exists()


async def test_async_main_miss_fetches_and_saves_cache(monkeypatch, tmp_path):
    fetch = await _run_async_main(monkeypatch, tmp_path, ["--max-age", "1h"], False)
    fetch.assert_awaited_once()
    assert (tmp_path / "out" / "latest.json").exists()
    assert cache.load(tmp_path / "last.json")["account"] == "srv/sch/u"


# --- summary header ----------------------------------------------------------
@pytest.mark.parametrize("minutes, text", [(0, "cached, just now"), (14, "cached, 14 min old"),
                                           (75, "cached, 1 h 15 min old")])
def test_cache_age(minutes, text):
    assert _cache_age((NOW - timedelta(minutes=minutes)).isoformat(), NOW) == text


def test_header_shows_cache_age():
    out = slice_payload(payload(), FRI, FRI, "", (NOW - timedelta(minutes=14)).isoformat())
    assert "(cached, 14 min old)" in render_summary(out, color=False, now=NOW).splitlines()[0]
    fresh = payload()
    assert "cached" not in render_summary(fresh, color=False, now=NOW).splitlines()[0]
