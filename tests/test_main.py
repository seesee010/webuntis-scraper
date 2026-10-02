"""Tests for the CLI's error handling and exit codes."""
from __future__ import annotations

import sys

import pytest
from playwright.async_api import Error as PlaywrightError

from src import main as main_mod
from src.config import ConfigError
from src.untis_client import LoginError, WebUntisError


def _run(monkeypatch, capsys, exc: BaseException, *argv: str) -> tuple[int, str]:
    async def boom(args):
        raise exc
    monkeypatch.setattr(main_mod, "_async_main", boom)
    monkeypatch.setattr(sys, "argv", ["untis", *argv])
    code = main_mod.main()
    return code, capsys.readouterr().err


@pytest.mark.parametrize("exc, code, needle", [
    (ConfigError("server and school must be set"), main_mod.EXIT_CONFIG, "config error"),
    (LoginError("Form login did not redirect"), main_mod.EXIT_LOGIN, "login failed"),
    (WebUntisError("HTTP 503 from ..."), main_mod.EXIT_NETWORK, "WebUntis error"),
    (PlaywrightError("net::ERR_NAME_NOT_RESOLVED at https://x\n=== logs ===\n..."),
     main_mod.EXIT_NETWORK, "could not reach WebUntis: net::ERR_NAME_NOT_RESOLVED"),
    (PlaywrightError("Executable doesn't exist at /x/chrome\n..."),
     main_mod.EXIT_CONFIG, "playwright install chromium"),
    (KeyError("boom"), main_mod.EXIT_ERROR, "unexpected error: KeyError"),
])
def test_one_line_message_and_exit_code(monkeypatch, capsys, exc, code, needle):
    got_code, err = _run(monkeypatch, capsys, exc, "-s")
    assert got_code == code
    assert needle in err
    assert err.startswith("untis: ")
    assert len(err.strip().splitlines()) == 1      # no traceback, no log noise
    assert "Traceback" not in err


def test_login_error_points_to_config_files(monkeypatch, capsys):
    _, err = _run(monkeypatch, capsys, LoginError("bad"),
                  "--config", "/c/config.json", "--env", "/c/.env")
    assert "/c/config.json" in err and "/c/.env" in err


def test_verbose_logs_traceback(monkeypatch, capsys, caplog):
    # logging.basicConfig only binds stderr once per process, so check the
    # log record instead of the captured stream.
    code, err = _run(monkeypatch, capsys, KeyError("boom"), "-v")
    assert code == main_mod.EXIT_ERROR
    assert any(r.exc_info and r.exc_info[0] is KeyError for r in caplog.records)
    assert "untis: unexpected error" in err


def test_no_traceback_logged_without_verbose(monkeypatch, capsys, caplog):
    _run(monkeypatch, capsys, KeyError("boom"))
    assert not any(r.exc_info for r in caplog.records)


def test_keyboard_interrupt(monkeypatch, capsys):
    code, _ = _run(monkeypatch, capsys, KeyboardInterrupt())
    assert code == main_mod.EXIT_ABORTED
