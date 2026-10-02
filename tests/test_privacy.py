"""Tests for keeping personal data private on disk (#20)."""
from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from untis import browser as browser_mod
from untis import config as config_mod
from untis import privacy
from untis.browser import chromium_args
from untis.config import ScraperConfig
from untis.exporter import write_json, write_latest
from conftest import REAL_SECURE_DATA_DIRS  # noqa: E402
from untis.privacy import (
    ensure_private_dir,
    is_readable_by_others,
    make_private,
    tighten_dir,
    write_private_text,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")


def mode(p: Path) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


# --- privacy helpers -----------------------------------------------------
def test_ensure_private_dir_creates_and_tightens(tmp_path):
    d = ensure_private_dir(tmp_path / "a" / "b")
    assert d.is_dir() and mode(d) == 0o700
    os.chmod(d, 0o755)
    ensure_private_dir(d)                               # existing dir
    assert mode(d) == 0o700


def test_make_private(tmp_path):
    f = tmp_path / "f"
    f.write_text("x")
    os.chmod(f, 0o644)
    make_private(f)
    assert mode(f) == 0o600
    make_private(tmp_path / "missing")                  # no error
    make_private(tmp_path)                              # directories are ignored
    assert mode(tmp_path) != 0o600


def test_tighten_dir(tmp_path):
    for name, m in (("a", 0o644), ("b", 0o600), ("c", 0o666)):
        (tmp_path / name).write_text(name)
        os.chmod(tmp_path / name, m)
    (tmp_path / "sub").mkdir()
    assert tighten_dir(tmp_path) == 2
    assert {mode(tmp_path / n) for n in "abc"} == {0o600}
    assert mode(tmp_path / "sub") != 0o600              # only files
    assert tighten_dir(tmp_path / "missing") == 0


def test_write_private_text(tmp_path):
    target = tmp_path / "new" / "x.json"
    write_private_text(target, "hello")
    assert target.read_text() == "hello" and mode(target) == 0o600
    os.chmod(target, 0o644)
    write_private_text(target, "again")                 # replaces, private again
    assert target.read_text() == "again" and mode(target) == 0o600
    assert not list(target.parent.glob("*.tmp"))


@pytest.mark.parametrize("m, expected", [(0o600, False), (0o400, False), (0o640, True),
                                         (0o604, True), (0o644, True)])
def test_is_readable_by_others(tmp_path, m, expected):
    f = tmp_path / ".env"
    f.write_text("UNTIS_PASSWORD=x")
    os.chmod(f, m)
    assert is_readable_by_others(f) is expected


def test_is_readable_by_others_missing(tmp_path):
    assert is_readable_by_others(tmp_path / "nope") is False


def test_helpers_are_noops_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(privacy, "_posix", lambda: False)
    f = tmp_path / "f"
    f.write_text("x")
    os.chmod(f, 0o644)
    make_private(f)
    assert mode(f) == 0o644
    assert tighten_dir(tmp_path) == 0
    assert is_readable_by_others(f) is False
    assert ensure_private_dir(tmp_path / "d").is_dir()


# --- Chromium flags ------------------------------------------------------
def test_chromium_keeps_sandbox_by_default(monkeypatch):
    monkeypatch.setattr(browser_mod.os, "geteuid", lambda: 1000, raising=False)
    args = chromium_args(ScraperConfig())
    assert "--no-sandbox" not in args
    assert not any("IsolateOrigins" in a for a in args)
    assert "--disable-blink-features=AutomationControlled" in args


def test_chromium_no_sandbox_opt_in(monkeypatch):
    monkeypatch.setattr(browser_mod.os, "geteuid", lambda: 1000, raising=False)
    args = chromium_args(ScraperConfig(browser_no_sandbox=True))
    assert "--no-sandbox" in args and any("IsolateOrigins" in a for a in args)


def test_chromium_no_sandbox_as_root(monkeypatch):
    monkeypatch.setattr(browser_mod.os, "geteuid", lambda: 0, raising=False)
    assert "--no-sandbox" in chromium_args(ScraperConfig())


# --- where the helpers are used ------------------------------------------
def test_exported_json_is_private(tmp_path):
    p1 = write_json({"meta": {"user": "Max Muster"}}, str(tmp_path))
    p2 = write_latest({"meta": {"user": "Max Muster"}}, str(tmp_path))
    assert mode(p1) == 0o600 and mode(p2) == 0o600
    assert json.loads(p2.read_text())["meta"]["user"] == "Max Muster"


async def test_browser_session_file_is_private(tmp_path, monkeypatch):
    state = tmp_path / "state.json"

    async def fake_storage_state(path):
        Path(path).write_text("{}")
        os.chmod(path, 0o644)                           # Playwright's default umask
    context = MagicMock()
    context.storage_state = AsyncMock(side_effect=fake_storage_state)
    context.close = AsyncMock()
    session = browser_mod.BrowserSession(ScraperConfig(storage_state_path=str(state)))
    session.context = context
    await session.__aexit__(None, None, None)
    assert mode(state) == 0o600


async def test_debug_screenshot_is_private(tmp_path, monkeypatch):
    from untis import untis_client
    monkeypatch.setattr(untis_client, "LOGS_DIR", tmp_path)

    async def fake_screenshot(path, full_page):
        Path(path).write_bytes(b"png")
        os.chmod(path, 0o644)
    client = untis_client.WebUntisClient(ScraperConfig(), MagicMock())
    client._page = MagicMock()
    client._page.screenshot = AsyncMock(side_effect=fake_screenshot)
    await client._screenshot("login_failed")
    assert mode(tmp_path / "login_failed.png") == 0o600


# --- config: securing the data dirs on startup ---------------------------
@pytest.fixture
def data_dirs(tmp_path, monkeypatch):
    dirs = {name: tmp_path / "data" / name for name in ("sessions", "out", "logs")}
    monkeypatch.setattr(config_mod, "SESSIONS_DIR", dirs["sessions"])
    monkeypatch.setattr(config_mod, "OUT_DIR", dirs["out"])
    monkeypatch.setattr(config_mod, "LOGS_DIR", dirs["logs"])
    for d in dirs.values():
        d.mkdir(parents=True)
        os.chmod(d, 0o755)
        (d / "old.json").write_text("{}")
        os.chmod(d / "old.json", 0o644)
    return dirs


def test_secure_data_dirs(data_dirs, tmp_path):
    env = tmp_path / ".env"
    env.write_text("UNTIS_PASSWORD=x")
    os.chmod(env, 0o600)
    cfg = ScraperConfig(output_dir=str(data_dirs["out"]),
                        storage_state_path=str(data_dirs["sessions"] / "old.json"))
    REAL_SECURE_DATA_DIRS(cfg, env)
    for d in data_dirs.values():
        assert mode(d) == 0o700 and mode(d / "old.json") == 0o600
    assert mode(tmp_path / "data") != 0o700             # parent (e.g. the repo) untouched


def test_custom_output_dir_is_not_chmodded(data_dirs, tmp_path):
    custom = tmp_path / "Documents"
    custom.mkdir()
    os.chmod(custom, 0o755)
    cfg = ScraperConfig(output_dir=str(custom), storage_state_path=str(tmp_path / "s.json"))
    REAL_SECURE_DATA_DIRS(cfg, tmp_path / ".env")
    assert mode(custom) == 0o755


def test_warns_when_env_is_readable_by_others(data_dirs, tmp_path, caplog):
    env = tmp_path / ".env"
    env.write_text("UNTIS_PASSWORD=x")
    os.chmod(env, 0o644)
    cfg = ScraperConfig(output_dir=str(data_dirs["out"]), storage_state_path=str(tmp_path / "s"))
    with caplog.at_level(logging.WARNING, logger="untis.config"):
        REAL_SECURE_DATA_DIRS(cfg, env)
    assert any("chmod 600" in r.getMessage() for r in caplog.records)
    assert mode(env) == 0o644                            # warn only, never change it


def test_browser_no_sandbox_from_config(tmp_path):
    js = tmp_path / "c.json"
    js.write_text(json.dumps({"server": "s", "school": "sc", "browser_no_sandbox": "true"}))
    env = tmp_path / ".env"
    env.write_text("")
    assert config_mod.load_config(js, env).browser_no_sandbox is True
