"""Tests for default arguments from config.json / UNTIS_DEFAULT_ARGS (#44)."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date

import pytest

from untis import main as main_mod
from untis.main import (
    NOT_IN_DEFAULTS,
    WINDOW_DESTS,
    DefaultArgsError,
    _build_parser,
    _load_default_args,
    _parse_args,
    _RaisingParser,
)

WED = date(2026, 10, 7)


def parse(argv, defaults, today=WED):
    return _parse_args(argv, today=today, default_args=defaults)


# --- _build_parser / _RaisingParser --------------------------------------
def test_suppress_parser_only_returns_given_options():
    assert vars(_build_parser(suppress=True).parse_args([])) == {}
    given = vars(_build_parser(suppress=True).parse_args(["-s", "--transport", "http"]))
    assert given == {"short": True, "transport": "http"}


def test_normal_parser_has_all_defaults():
    ns = vars(_build_parser().parse_args([]))
    assert ns["short"] is False and ns["transport"] is None and ns["today"] is False
    assert set(WINDOW_DESTS) <= set(ns)


def test_raising_parser_raises_instead_of_exiting():
    with pytest.raises(DefaultArgsError, match="not allowed with"):
        _build_parser(_RaisingParser).parse_args(["--today", "--week"])


def test_flags_can_be_negated():
    ns = _build_parser().parse_args(["--no-short", "--no-keep-raw", "--no-calendar-days",
                                     "--no-verbose"])
    assert not (ns.short or ns.keep_raw or ns.calendar_days or ns.verbose)


# --- _load_default_args --------------------------------------------------
@pytest.fixture
def no_env(monkeypatch):
    monkeypatch.delenv("UNTIS_DEFAULT_ARGS", raising=False)


def _config(tmp_path, data) -> str:
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data) if not isinstance(data, str) else data)
    return str(p)


def test_env_var_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("UNTIS_DEFAULT_ARGS", "-s --transport 'http'")
    cfg = _config(tmp_path, {"default_args": ["--week"]})
    assert _load_default_args(["--config", cfg]) == (["-s", "--transport", "http"],
                                                      "UNTIS_DEFAULT_ARGS")


def test_empty_env_var_means_no_defaults(monkeypatch):
    monkeypatch.setenv("UNTIS_DEFAULT_ARGS", "")
    assert _load_default_args([]) == ([], "UNTIS_DEFAULT_ARGS")


def test_list_from_config(no_env, tmp_path):
    cfg = _config(tmp_path, {"default_args": ["--short", "--transport", "http"]})
    assert _load_default_args(["--config", cfg]) == (["--short", "--transport", "http"], cfg)


def test_string_from_config_is_split_shell_style(no_env, tmp_path):
    cfg = _config(tmp_path, {"default_args": "-s --from 'mon' --to fri"})
    assert _load_default_args([f"--config={cfg}"])[0] == ["-s", "--from", "mon", "--to", "fri"]


@pytest.mark.parametrize("data", [{}, {"default_args": None}, "{broken json", "[1, 2]"])
def test_missing_or_unreadable_means_no_defaults(no_env, tmp_path, data):
    cfg = _config(tmp_path, data)
    assert _load_default_args(["--config", cfg])[0] == []


def test_missing_config_file(no_env, tmp_path):
    assert _load_default_args(["--config", str(tmp_path / "nope.json")])[0] == []


@pytest.mark.parametrize("value", [42, ["-s", 3], {"short": True}])
def test_invalid_type_is_an_error(no_env, tmp_path, value):
    cfg = _config(tmp_path, {"default_args": value})
    with pytest.raises(DefaultArgsError, match="list of strings or a string"):
        _load_default_args(["--config", cfg])


# --- merging in _parse_args ----------------------------------------------
def test_defaults_apply_without_explicit_args():
    args = parse([], ["-s", "--transport", "http", "--today"])
    assert args.short and args.transport == "http" and args.today
    assert args.default_args == ["-s", "--transport", "http", "--today"]


def test_no_defaults_is_unchanged_behaviour():
    a, b = parse(["--week"], []), _build_parser().parse_args(["--week"])
    assert {k: getattr(a, k) for k in vars(b)} == vars(b)


def test_explicit_value_replaces_default():
    assert parse(["--transport", "browser"], ["--transport", "http"]).transport == "browser"


def test_explicit_negation_turns_default_flag_off():
    assert parse(["--no-short"], ["--short"]).short is False


@pytest.mark.parametrize("explicit, check", [
    (["--week"], lambda a: a.week and not a.today),
    (["--days-forward", "3"], lambda a: a.days_forward == 3 and not a.today),
    (["--from", "mon", "--to", "fri"], lambda a: a.window and not a.today),
    (["--date", "12.10."], lambda a: a.date == date(2026, 10, 12) and not a.today),
])
def test_explicit_window_replaces_default_window(explicit, check):
    assert check(parse(explicit, ["-s", "--today"]))


def test_explicit_shortcut_replaces_default_days_forward():
    args = parse(["--tomorrow"], ["--days-forward", "5"])
    assert args.tomorrow and args.days_forward is None


def test_non_window_defaults_survive_an_explicit_window():
    args = parse(["--week"], ["-s", "--transport", "http", "--today"])
    assert args.short and args.transport == "http"


@pytest.mark.parametrize("defaults, needle", [
    (["--today", "--week"], "not allowed with"),
    (["--transport", "pigeon"], "invalid choice"),
    (["--bogus"], "unrecognized arguments"),
    (["--from", "16.10.", "--to", "12.10."], "before --from"),
])
def test_invalid_defaults_exit_2_with_source(capsys, defaults, needle):
    with pytest.raises(SystemExit) as exc:
        parse([], defaults)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert needle in err


def test_invalid_default_error_names_the_source(capsys):
    with pytest.raises(SystemExit):
        parse([], ["--bogus"])
    assert "default_args (default_args)" in capsys.readouterr().err


@pytest.mark.parametrize("arg", sorted(NOT_IN_DEFAULTS) + ["--config=x.json"])
def test_forbidden_defaults(capsys, arg):
    with pytest.raises(SystemExit) as exc:
        parse([], [arg])
    assert exc.value.code == 2 and "can't be used there" in capsys.readouterr().err


def test_explicit_errors_still_exit_2(capsys):
    with pytest.raises(SystemExit) as exc:
        parse(["--bogus"], ["-s"])
    assert exc.value.code == 2


def test_parse_args_reads_defaults_from_env(monkeypatch):
    monkeypatch.setenv("UNTIS_DEFAULT_ARGS", "-s")
    args = _parse_args([], today=WED)
    assert args.short and args.defaults_source == "UNTIS_DEFAULT_ARGS"


def test_parse_args_reports_invalid_config_type(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("UNTIS_DEFAULT_ARGS", raising=False)
    cfg = _config(tmp_path, {"default_args": 7})
    with pytest.raises(SystemExit) as exc:
        _parse_args(["--config", cfg], today=WED)
    assert exc.value.code == 2 and "list of strings" in capsys.readouterr().err


def test_main_logs_defaults_and_effective_args(monkeypatch, caplog):
    monkeypatch.setenv("UNTIS_DEFAULT_ARGS", "--transport http")

    async def fake_async_main(args):
        return 0
    monkeypatch.setattr(main_mod, "_async_main", fake_async_main)
    monkeypatch.setattr(sys, "argv", ["untis", "-v", "--today"])
    with caplog.at_level(logging.DEBUG, logger="untis.main"):
        assert main_mod.main() == 0
    msgs = [r.getMessage() for r in caplog.records]
    assert any("default_args from UNTIS_DEFAULT_ARGS: --transport http" in m for m in msgs)
    assert any("effective arguments" in m and "'transport': 'http'" in m for m in msgs)
