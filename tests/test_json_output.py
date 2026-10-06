"""Tests for controlling the JSON output: --json, --no-json, --json -,
--keep and the config keys write_json / keep_json (#15).
All data here is made up."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from untis import cache
from untis import main as main_mod
from untis.config import DEFAULT_KEEP_JSON, ConfigError, ScraperConfig, load_config, parse_keep
from untis.exporter import dump_json, export, prune

PAYLOAD = {"meta": {"user": "Erika Beispiel", "raw": {"id": 1}},
           "timetable": {"days": [{"date": "2026-10-05", "entries": [],
                                   "raw": {"x": 2}}]}}


def stamped(tmp_path, *stamps: str) -> list:
    """Create timestamped output files (content doesn't matter)."""
    files = []
    for ts in stamps:
        f = tmp_path / f"untis_{ts}.json"
        f.write_text("{}")
        files.append(f)
    return files


def names(path) -> list[str]:
    return sorted(f.name for f in path.iterdir())


# --- dump_json -------------------------------------------------------------
def test_dump_json_pretty_strips_raw():
    text = dump_json(PAYLOAD)
    assert "\n  " in text
    data = json.loads(text)
    assert "raw" not in data["meta"] and "raw" not in data["timetable"]["days"][0]
    assert data["meta"]["user"] == "Erika Beispiel"


def test_dump_json_compact():
    assert "\n" not in dump_json({"a": [1, 2]}, pretty=False)
    assert dump_json({"a": [1, 2]}, pretty=False) == '{"a":[1,2]}'


def test_dump_json_keep_raw():
    assert json.loads(dump_json(PAYLOAD, keep_raw=True))["meta"]["raw"] == {"id": 1}


def test_dump_json_keeps_umlauts():
    assert "Ä" in dump_json({"subject": "Äpfel"})


def test_dump_json_does_not_change_the_payload():
    dump_json(PAYLOAD)
    assert "raw" in PAYLOAD["meta"]


# --- prune -----------------------------------------------------------------
def test_prune_keeps_the_newest(tmp_path):
    old = stamped(tmp_path, "20261001_070000", "20261002_070000", "20261003_070000")
    (tmp_path / "latest.json").write_text("{}")
    assert prune(str(tmp_path), 1) == old[:2]
    assert names(tmp_path) == ["latest.json", "untis_20261003_070000.json"]


def test_prune_sorts_by_timestamp_not_creation_order(tmp_path):
    stamped(tmp_path, "20261003_070000", "20261001_070000", "20261002_070000")
    prune(str(tmp_path), 2)
    assert names(tmp_path) == ["untis_20261002_070000.json", "untis_20261003_070000.json"]


def test_prune_none_keeps_all(tmp_path):
    stamped(tmp_path, "20261001_070000", "20261002_070000")
    assert prune(str(tmp_path), None) == []
    assert len(names(tmp_path)) == 2


def test_prune_zero_deletes_all_timestamped(tmp_path):
    stamped(tmp_path, "20261001_070000", "20261002_070000")
    (tmp_path / "latest.json").write_text("{}")
    assert len(prune(str(tmp_path), 0)) == 2
    assert names(tmp_path) == ["latest.json"]


def test_prune_fewer_files_than_keep(tmp_path):
    stamped(tmp_path, "20261001_070000")
    assert prune(str(tmp_path), 5) == []
    assert names(tmp_path) == ["untis_20261001_070000.json"]


def test_prune_leaves_other_files_alone(tmp_path):
    stamped(tmp_path, "20261001_070000")
    for name in ("untis_backup.json", "untis_20261001_0700.json", "notes.txt",
                 "untis_20261001_070000.json.bak"):
        (tmp_path / name).write_text("x")
    (tmp_path / "untis_20261002_070000.json").mkdir()   # not a file
    prune(str(tmp_path), 0)
    assert names(tmp_path) == ["notes.txt", "untis_20261001_0700.json",
                               "untis_20261001_070000.json.bak",
                               "untis_20261002_070000.json", "untis_backup.json"]


def test_prune_missing_dir(tmp_path):
    assert prune(str(tmp_path / "nope"), 3) == []


# --- export ----------------------------------------------------------------
def test_export_writes_both(tmp_path):
    written = export(PAYLOAD, str(tmp_path), keep=None)
    assert [p.name for p in written][1] == "latest.json"
    assert written[0].name.startswith("untis_") and len(names(tmp_path)) == 2


def test_export_keep_zero_writes_only_latest(tmp_path):
    stamped(tmp_path, "20261001_070000")
    written = export(PAYLOAD, str(tmp_path), keep=0)
    assert [p.name for p in written] == ["latest.json"]
    assert names(tmp_path) == ["latest.json"]


def test_export_prunes_after_writing(tmp_path):
    stamped(tmp_path, "20000101_000000", "20000102_000000")
    written = export(PAYLOAD, str(tmp_path), keep=2)
    assert names(tmp_path) == sorted(["latest.json", "untis_20000102_000000.json",
                                      written[0].name])


def test_export_passes_pretty_and_raw(tmp_path):
    export(PAYLOAD, str(tmp_path), pretty=False, keep_raw=True, keep=None)
    stamp = next(f for f in tmp_path.iterdir() if f.name != "latest.json")
    assert "\n" not in stamp.read_text()
    assert json.loads(stamp.read_text())["meta"]["raw"] == {"id": 1}


# --- parse_keep / config ---------------------------------------------------
@pytest.mark.parametrize("value, expected", [
    (0, 0), (5, 5), ("7", 7), ("0", 0), (" 3 ", 3), ("all", None), ("ALL", None), (" All ", None),
])
def test_parse_keep_accepts(value, expected):
    assert parse_keep(value) == expected


@pytest.mark.parametrize("value, msg", [
    (-1, "0 or more"), ("-2", "0 or more"), ("x", "number or 'all'"), ("", "number or 'all'"),
    (2.5, "number or 'all'"), ("2.5", "number or 'all'"), (True, "number or 'all'"),
    (None, "number or 'all'"), ([3], "number or 'all'"),
])
def test_parse_keep_rejects(value, msg):
    with pytest.raises(ValueError, match=msg):
        parse_keep(value)


def _load(tmp_path, **cfg):
    js = tmp_path / "config.json"
    js.write_text(json.dumps({"server": "s", "school": "sc", **cfg}))
    return load_config(js, tmp_path / "missing.env")


def test_config_defaults(tmp_path):
    c = _load(tmp_path)
    assert c.write_json is True and c.keep_json == DEFAULT_KEEP_JSON == 20


@pytest.mark.parametrize("raw, expected", [(False, False), ("false", False), (True, True)])
def test_config_write_json(tmp_path, raw, expected):
    assert _load(tmp_path, write_json=raw).write_json is expected


@pytest.mark.parametrize("raw, expected", [(5, 5), (0, 0), ("all", None), ("12", 12)])
def test_config_keep_json(tmp_path, raw, expected):
    assert _load(tmp_path, keep_json=raw).keep_json == expected


@pytest.mark.parametrize("raw", [-1, "many", 1.5])
def test_config_keep_json_invalid(tmp_path, raw):
    with pytest.raises(ConfigError, match="keep_json"):
        _load(tmp_path, keep_json=raw)


# --- argument types and parsing ---------------------------------------------
def test_json_target_arg():
    assert main_mod._json_target_arg("-") == "-"
    with pytest.raises(main_mod.argparse.ArgumentTypeError, match="only '-'"):
        main_mod._json_target_arg("out.json")


@pytest.mark.parametrize("text, expected", [("3", 3), ("0", 0), ("all", "all")])
def test_keep_arg(text, expected):
    assert main_mod._keep_arg(text) == expected


@pytest.mark.parametrize("text", ["x", "-1", ""])
def test_keep_arg_rejects(text):
    with pytest.raises(main_mod.argparse.ArgumentTypeError):
        main_mod._keep_arg(text)


def parse(argv, default_args=()):
    return main_mod._parse_args(argv, default_args=list(default_args))


@pytest.mark.parametrize("argv, expected", [
    ([], None), (["--json"], True), (["--no-json"], False), (["--json", "-"], "-"),
    (["--json", "-", "--no-json"], False),
])
def test_json_flag_values(argv, expected):
    assert parse(argv).json == expected


def test_explicit_json_beats_default_no_json():
    assert parse(["--json"], ["--no-json"]).json is True
    assert parse(["--no-json"], ["--json", "-"]).json is False


def test_keep_flag():
    assert parse(["--keep", "4"]).keep == 4
    assert parse(["--keep", "all"]).keep == "all"
    assert parse([]).keep is None


@pytest.mark.parametrize("argv", [
    ["--json", "-", "-s"], ["--json", "-", "--table"], ["--json", "-", "--oneline"],
    ["--json", "-", "--legend"], ["--json", "-", "--now"], ["--json", "-", "--start"],
    ["--json", "-", "--changes"], ["--json", "-", "--live"],
    ["--json", "x"], ["--keep", "-3"], ["--keep", "some"],
])
def test_usage_errors_exit_2(capsys, argv):
    with pytest.raises(SystemExit) as exc:
        parse(argv)
    assert exc.value.code == 2


def test_json_stdout_drops_views_from_default_args():
    args = parse(["--json", "-"], ["-s", "--legend", "--table", "--days-forward", "3"])
    assert not (args.short or args.legend or args.table)
    assert main_mod._layout(args) is None
    assert args.days_forward == 3                       # the window is kept


def test_json_stdout_keeps_sections():
    args = parse(["--json", "-", "-t"])
    assert args.tests and args.sections


def test_json_stdout_with_turned_off_view_is_fine():
    assert parse(["--json", "-", "--no-short"]).json == "-"


def test_views_without_json_stdout_are_kept():
    assert parse(["--no-json"], ["-s"]).short is True


# --- _async_main ------------------------------------------------------------
async def run_main(monkeypatch, tmp_path, argv, live=None, **cfg_kw):
    c = ScraperConfig(server="s", school="sc", output_dir=str(tmp_path / "out"), **cfg_kw)
    monkeypatch.setattr(main_mod, "load_config", lambda *a: c)
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "last.json")
    fetch = AsyncMock(return_value=json.loads(json.dumps(PAYLOAD)))
    monkeypatch.setattr(main_mod, "_fetch", fetch)
    args = parse(argv)
    args.live = live
    await main_mod._async_main(args)
    out = tmp_path / "out"
    return sorted(f.name for f in out.iterdir()) if out.exists() else []


async def test_default_writes_both_files(monkeypatch, tmp_path):
    files = await run_main(monkeypatch, tmp_path, [])
    assert len(files) == 2 and "latest.json" in files


async def test_no_json_writes_nothing(monkeypatch, tmp_path, capsys):
    assert await run_main(monkeypatch, tmp_path, ["--no-json"]) == []
    assert capsys.readouterr().out == ""
    assert cache.load(tmp_path / "last.json") is not None   # the cache is still saved


async def test_config_write_json_false(monkeypatch, tmp_path):
    assert await run_main(monkeypatch, tmp_path, [], write_json=False) == []


async def test_json_flag_beats_config(monkeypatch, tmp_path):
    assert len(await run_main(monkeypatch, tmp_path, ["--json"], write_json=False)) == 2


async def test_json_stdout_prints_and_writes_no_files(monkeypatch, tmp_path, capsys):
    assert await run_main(monkeypatch, tmp_path, ["--json", "-"]) == []
    data = json.loads(capsys.readouterr().out)
    assert data["meta"] == {"user": "Erika Beispiel"}             # raw stripped


async def test_json_stdout_respects_pretty_and_raw(monkeypatch, tmp_path, capsys):
    await run_main(monkeypatch, tmp_path, ["--json", "-", "--keep-raw"], pretty_json=False)
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and json.loads(out)["meta"]["raw"] == {"id": 1}


async def test_json_stdout_from_cache(monkeypatch, tmp_path, capsys):
    c = ScraperConfig(server="s", school="sc", username="u",
                      output_dir=str(tmp_path / "out"))
    monkeypatch.setattr(main_mod, "load_config", lambda *a: c)
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "last.json")
    monkeypatch.setattr(main_mod, "_from_cache", lambda *a: {"meta": {"user": "Cached"}})
    fetch = AsyncMock()
    monkeypatch.setattr(main_mod, "_fetch", fetch)
    await main_mod._async_main(parse(["--json", "-", "--offline"]))
    fetch.assert_not_awaited()
    assert json.loads(capsys.readouterr().out) == {"meta": {"user": "Cached"}}


async def test_keep_zero_writes_only_latest(monkeypatch, tmp_path):
    assert await run_main(monkeypatch, tmp_path, ["--keep", "0"]) == ["latest.json"]


async def test_keep_prunes_old_files(monkeypatch, tmp_path):
    (tmp_path / "out").mkdir()
    stamped(tmp_path / "out", "20000101_000000", "20000102_000000", "20000103_000000")
    files = await run_main(monkeypatch, tmp_path, ["--keep", "2"])
    assert "untis_20000103_000000.json" in files and len(files) == 3
    assert "untis_20000101_000000.json" not in files


async def test_keep_from_config(monkeypatch, tmp_path):
    (tmp_path / "out").mkdir()
    stamped(tmp_path / "out", "20000101_000000", "20000102_000000")
    files = await run_main(monkeypatch, tmp_path, [], keep_json=1)
    assert len(files) == 2 and not any(f.startswith("untis_2000") for f in files)


async def test_keep_all_never_deletes(monkeypatch, tmp_path):
    (tmp_path / "out").mkdir()
    stamped(tmp_path / "out", *(f"200001{d:02}_000000" for d in range(1, 30)))
    files = await run_main(monkeypatch, tmp_path, ["--keep", "all"])
    assert len(files) == 31


async def test_live_writes_only_latest(monkeypatch, tmp_path):
    files = await run_main(monkeypatch, tmp_path, ["-s", "--color", "never"], live=300)
    assert files == ["latest.json"]


async def test_live_with_no_json_writes_nothing(monkeypatch, tmp_path):
    assert await run_main(monkeypatch, tmp_path, ["-s", "--no-json"], live=300) == []


def test_json_stdout_quiets_logging(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(main_mod.sys, "argv", ["untis", "--json", "-"])
    monkeypatch.setattr(main_mod, "_setup_logging", lambda v, quiet: seen.setdefault("q", quiet))

    async def fake(args):
        return 0
    monkeypatch.setattr(main_mod, "_async_main", fake)
    assert main_mod.main() == 0
    assert seen["q"] is True

