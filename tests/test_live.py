"""Tests for --live (helpers in untis.live, the loop in untis.main)."""
from __future__ import annotations

import io
import sys
from datetime import date, datetime

import pytest

from untis import live
from untis import main as main_mod
from untis.config import ConfigError
from untis.untis_client import LoginError, WebUntisError

NOW = datetime(2026, 10, 5, 9, 58, 0)


# --- parse_interval ---------------------------------------------------------
@pytest.mark.parametrize("text, seconds", [
    ("5m", 300), ("60s", 60), ("2", 120), ("1h", 3600), ("1.5m", 90),
])
def test_parse_interval(text, seconds):
    assert live.parse_interval(text) == seconds


@pytest.mark.parametrize("text", ["59s", "0", "0m", "30s"])
def test_parse_interval_below_minimum(text):
    with pytest.raises(ValueError, match="at least 60s"):
        live.parse_interval(text)


@pytest.mark.parametrize("text", ["", "abc", "5x", "-5m"])
def test_parse_interval_invalid(text):
    with pytest.raises(ValueError, match="invalid duration"):
        live.parse_interval(text)


def test_default_interval_is_valid():
    assert live.parse_interval(live.DEFAULT_INTERVAL) == 300


# --- format_interval --------------------------------------------------------
@pytest.mark.parametrize("seconds, text", [
    (60, "1m"), (90, "1m30s"), (300, "5m"), (3600, "1h"), (5400, "1h30m"),
    (3661, "1h1m1s"), (0, "0s"),
])
def test_format_interval(seconds, text):
    assert live.format_interval(seconds) == text


# --- footer / frame ---------------------------------------------------------
def test_footer_after_an_update():
    line = live.footer(datetime(2026, 10, 5, 9, 57, 30), 300, NOW)
    assert line == "updated 09:57:30 · every 5m, next 10:03 · Ctrl-C to quit"


def test_footer_before_the_first_update():
    assert live.footer(None, 60, NOW).startswith("not updated yet · every 1m, next 09:59")


def test_footer_with_error_keeps_status_line():
    text = live.footer(NOW, 300, NOW, error="could not reach WebUntis: ConnectError")
    first, second = text.splitlines()
    assert first == "refresh failed: could not reach WebUntis: ConnectError"
    assert second.startswith("updated 09:58:00")


def test_footer_next_crosses_midnight():
    assert "next 00:03" in live.footer(None, 300, datetime(2026, 10, 5, 23, 58))


def test_frame_with_clear():
    assert live.frame("Mon\nTue\n", "status", clear=True) == live.CLEAR + "Mon\nTue\n\nstatus\n"


def test_frame_without_clear():
    assert live.frame("Mon", "status", clear=False) == "Mon\n\nstatus\n"


def test_frame_empty_body():
    assert live.frame("", "status", clear=False) == "status\n"
    assert live.frame("\n\n", "status", clear=False) == "status\n"


# --- argument parsing -------------------------------------------------------
def parse(argv, defaults=()):
    return main_mod._parse_args(argv, today=date(2026, 10, 5), default_args=list(defaults))


def test_live_interval_arg():
    assert main_mod._live_interval_arg("2m") == 120
    for bad in ("10s", "nope"):
        with pytest.raises(main_mod.argparse.ArgumentTypeError):
            main_mod._live_interval_arg(bad)


def test_live_off_by_default():
    assert parse([]).live is None


def test_live_without_value_uses_default():
    assert parse(["--live"]).live == 300


def test_live_with_value():
    assert parse(["--live", "10m", "--now"]).live == 600
    assert parse(["--live=90s", "--now"]).live == 90


def test_live_implies_short_without_a_view():
    args = parse(["--live"])
    assert args.short and main_mod._layout(args) == "days"


@pytest.mark.parametrize("argv", [
    ["--live", "--now"], ["--live", "--oneline"], ["--live", "--table"],
    ["--live", "-t"], ["--live", "-H"], ["--live", "--start"],
])
def test_live_keeps_an_explicit_view(argv):
    assert not parse(argv).short


@pytest.mark.parametrize("argv", [
    ["--live", "--changes"], ["--live", "--changes", "--notify"], ["--live", "30s"],
    ["--live", "x"],
])
def test_live_errors(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        parse(argv)
    assert exc.value.code == 2


def test_live_not_allowed_in_default_args(capsys):
    with pytest.raises(SystemExit) as exc:
        parse([], defaults=["--live"])
    assert exc.value.code == 2 and "--live can't be used there" in capsys.readouterr().err


# --- _live_loop -------------------------------------------------------------
class FakeOut(io.StringIO):
    def __init__(self, tty: bool):
        super().__init__()
        self._tty = tty

    def isatty(self):
        return self._tty


async def _loop(monkeypatch, results, argv=("--live", "--now"), tty=True, rounds=None):
    """Run the loop with _async_main returning/raising the given results
    one after another. Returns (code, output, sleeps, seen args)."""
    results = list(results)
    seen = []

    async def fake_async_main(args):
        seen.append((args.clear_session, args.form_login))
        r = results.pop(0)
        if isinstance(r, BaseException):
            raise r
        print(r)
        return 0
    monkeypatch.setattr(main_mod, "_async_main", fake_async_main)
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
    out = FakeOut(tty)
    code = await main_mod._live_loop(parse(list(argv)), out=out, now=lambda: NOW,
                                     sleep=fake_sleep,
                                     rounds=rounds if rounds is not None else len(results))
    return code, out.getvalue(), sleeps, seen


async def test_loop_redraws_each_round(monkeypatch):
    code, out, sleeps, _ = await _loop(monkeypatch, ["Math 1", "Math 2"])
    assert code == 0
    assert out.count(live.CLEAR) == 2
    assert out.index("Math 1") < out.index("Math 2")
    assert "updated 09:58:00 · every 5m, next 10:03" in out
    assert sleeps == [300]                  # no sleep after the last round


async def test_loop_no_clear_when_not_a_tty(monkeypatch):
    _, out, _, _ = await _loop(monkeypatch, ["Math"], tty=False)
    assert live.CLEAR not in out and out.startswith("Math\n\nupdated")


async def test_loop_uses_given_interval(monkeypatch):
    _, out, sleeps, _ = await _loop(monkeypatch, ["a", "b", "c"],
                                    argv=("--live", "2m", "--now"))
    assert sleeps == [120, 120] and "every 2m" in out


async def test_loop_keeps_last_output_on_network_error(monkeypatch):
    code, out, _, _ = await _loop(monkeypatch, ["Math", WebUntisError("HTTP 503")])
    assert code == 0
    last = out.split(live.CLEAR)[-1]
    assert "Math" in last
    assert "refresh failed: WebUntis error: HTTP 503" in last


async def test_loop_recovers_after_an_error(monkeypatch):
    _, out, _, _ = await _loop(monkeypatch, [WebUntisError("down"), "Art"])
    first, second = out.split(live.CLEAR)[1:]
    assert "not updated yet" in first and "refresh failed" in first
    assert "Art" in second and "refresh failed" not in second


@pytest.mark.parametrize("exc, code", [
    (ConfigError("server must be set"), main_mod.EXIT_CONFIG),
    (LoginError("bad password"), main_mod.EXIT_LOGIN),
])
async def test_loop_stops_on_fatal_errors(monkeypatch, capsys, exc, code):
    got, out, sleeps, _ = await _loop(monkeypatch, ["Math", exc, "never"], rounds=3)
    assert got == code and sleeps == [300]
    assert "never" not in out
    assert capsys.readouterr().err.startswith("untis: ")


async def test_loop_unexpected_error_is_retried(monkeypatch):
    code, out, _, _ = await _loop(monkeypatch, [KeyError("x"), "ok"])
    assert code == 0 and "unexpected error: KeyError" in out and "ok" in out


async def test_loop_forces_new_session_only_once(monkeypatch):
    _, _, _, seen = await _loop(monkeypatch, ["a", "b"],
                                argv=("--live", "--now", "--clear-session", "--form-login"))
    assert seen == [(True, True), (False, False)]


@pytest.mark.parametrize("fmt", ["json", "waybar"])
async def test_loop_machine_formats_print_one_line_per_round(monkeypatch, fmt):
    _, out, _, _ = await _loop(monkeypatch, ['{"text": "a"}', '{"text": "b"}'],
                               argv=("--live", "--now", "--format", fmt))
    assert out == '{"text": "a"}\n{"text": "b"}\n'      # no clear, no footer


async def test_loop_machine_format_error_goes_to_stderr(monkeypatch, capsys):
    _, out, _, _ = await _loop(monkeypatch, ['{"text": "a"}', WebUntisError("down")],
                               argv=("--live", "--now", "--format", "waybar"))
    assert out == '{"text": "a"}\n'
    assert "untis: WebUntis error: down" in capsys.readouterr().err


# --- main() -----------------------------------------------------------------
def test_main_runs_the_loop_and_ctrl_c_exits_cleanly(monkeypatch, capsys):
    async def fake_loop(args):
        assert args.live == 300
        raise KeyboardInterrupt
    monkeypatch.setattr(main_mod, "_live_loop", fake_loop)
    monkeypatch.setattr(sys, "argv", ["untis", "--live"])
    assert main_mod.main() == 0
    assert "Aborted" not in capsys.readouterr().err


def test_main_without_live_does_not_loop(monkeypatch):
    async def fake_loop(args):
        raise AssertionError("loop must not run")

    async def fake_async_main(args):
        return 0
    monkeypatch.setattr(main_mod, "_live_loop", fake_loop)
    monkeypatch.setattr(main_mod, "_async_main", fake_async_main)
    monkeypatch.setattr(sys, "argv", ["untis", "-s"])
    assert main_mod.main() == 0
