"""Tests for `untis init` (#14)."""
from __future__ import annotations

import io
import json
import os
import stat
import sys

import httpx
import pytest
from dotenv import dotenv_values

from untis import main as main_mod
from untis import setup_wizard as sw
from untis.setup_wizard import (
    SetupError,
    describe_school,
    parse_webuntis_url,
    schools_on_server,
    search_schools,
    update_config,
    update_env,
)
from untis.untis_client import LoginError, WebUntisError

SCHOOL = {"server": "demo.webuntis.com", "loginName": "demo-school",
          "displayName": "Demo School", "address": "1234 Town"}


# --- URL parsing -------------------------------------------------------------
@pytest.mark.parametrize("url, expected", [
    ("https://demo.webuntis.com/WebUntis/?school=demo-school#/basic/login", ("demo", "demo-school")),
    ("https://demo.webuntis.com/WebUntis/#/basic/login?school=demo-school", ("demo", "demo-school")),
    ("demo.webuntis.com/WebUntis/?school=demo-school", ("demo", "demo-school")),
    ("https://DEMO.WebUntis.com/today", ("demo", None)),
    ("https://nese.webuntis.com/WebUntis/?school=some+school", ("nese", "some school")),
    ("  https://demo.webuntis.com/WebUntis/?school=  ", ("demo", None)),
])
def test_parse_webuntis_url(url, expected):
    assert parse_webuntis_url(url) == expected


@pytest.mark.parametrize("url", ["https://example.com/?school=x", "https://webuntis.com/",
                                 "not a url", "https://webuntis.com.evil.org/?school=x"])
def test_parse_webuntis_url_rejects(url):
    with pytest.raises(SetupError, match="not a WebUntis school URL"):
        parse_webuntis_url(url)


# --- school search -----------------------------------------------------------
def _search_transport(result=None, error=None, status=200):
    def handler(request):
        body = json.loads(request.content)
        assert body["method"] == "searchSchool" and body["params"] == [{"search": "demo"}]
        payload = {"error": error} if error else {"result": {"schools": result or []}}
        return httpx.Response(status, json=payload)
    return httpx.MockTransport(handler)


def test_search_schools():
    assert search_schools("demo", _search_transport([SCHOOL])) == [SCHOOL]
    assert search_schools("demo", _search_transport([])) == []


def test_search_schools_errors():
    with pytest.raises(SetupError, match="too many schools match 'demo'"):
        search_schools("demo", _search_transport(error={"message": "too many results"}))
    with pytest.raises(SetupError, match="school search failed: nope"):
        search_schools("demo", _search_transport(error={"message": "nope"}))
    with pytest.raises(httpx.HTTPStatusError):
        search_schools("demo", _search_transport(status=500))


def test_schools_on_server_and_describe():
    other = {**SCHOOL, "server": "other.webuntis.com"}
    assert schools_on_server([SCHOOL, other], "demo") == [SCHOOL]
    assert describe_school(SCHOOL) == "Demo School (1234 Town)"
    assert describe_school({"loginName": "x"}) == "x"


# --- writing files -------------------------------------------------------------
def mode(p) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


def test_update_config_new_and_merge(tmp_path):
    p = update_config(tmp_path, "demo", "demo-school", "max")
    assert json.loads(p.read_text()) == {"server": "demo", "school": "demo-school", "username": "max"}
    assert mode(p) == 0o600
    p.write_text(json.dumps({"server": "old", "default_args": ["-s"], "days_forward": 5}))
    update_config(tmp_path, "demo", "demo-school", "max")
    data = json.loads(p.read_text())
    assert data["server"] == "demo" and data["default_args"] == ["-s"] and data["days_forward"] == 5


def test_update_config_refuses_broken_json(tmp_path):
    (tmp_path / "config.json").write_text("{broken")
    with pytest.raises(SetupError, match="isn't valid JSON"):
        update_config(tmp_path, "demo", "s", "u")


@pytest.mark.parametrize("password", ["simple", 'with "quotes"', "back\\slash", "sp ace = equals",
                                      "#hash", "ümläut$€"])
def test_update_env_roundtrip_and_keeps_other_lines(tmp_path, password):
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nUNTIS_PASSWORD=old\n")
    update_env(tmp_path, password)
    assert dotenv_values(env) == {"OTHER": "1", "UNTIS_PASSWORD": password}
    assert mode(env) == 0o600
    assert env.read_text().count("UNTIS_PASSWORD=") == 1


# --- verify_login --------------------------------------------------------------
def test_verify_login_uses_http_and_a_throwaway_session(monkeypatch):
    seen = {}

    class FakeClient:
        def __init__(self, cfg, session):
            seen["cfg"] = cfg
            self.user_display, self._resource_type = "Max Muster", "STUDENT"

        async def login(self):
            seen["logged_in"] = True

        async def close(self):
            seen["closed"] = True
    from untis import untis_client
    monkeypatch.setattr(untis_client, "WebUntisClient", FakeClient)
    import asyncio
    assert asyncio.run(sw.verify_login("demo", "demo-school", "max", "pw")) == "Max Muster, student"
    cfg = seen["cfg"]
    assert cfg.transport == "http" and "untis-init-" in cfg.storage_state_path
    assert cfg.base_url == "https://demo.webuntis.com" and seen["closed"]


# --- run() ---------------------------------------------------------------------
class Tty(io.StringIO):
    def isatty(self):
        return True


def run(tmp_path, argv, answers=(), password="s3cret", stdin=None, search=None, verify=None):
    out, asked = [], list(answers)
    calls = {}

    async def fake_verify(server, school, user, pw):
        calls["verify"] = (server, school, user, pw)
        return "Max Muster, student"
    code = sw.run(
        [*argv, "--dir", str(tmp_path)],
        ask=lambda prompt: asked.pop(0),
        ask_secret=lambda prompt: password,
        stdin=stdin or Tty(),
        out=out.append,
        search=search or (lambda term: [SCHOOL]),
        verify=verify or fake_verify,
    )
    return code, "\n".join(out), calls


URL = "https://demo.webuntis.com/WebUntis/?school=demo-school"


def test_interactive_happy_path(tmp_path):
    code, out, calls = run(tmp_path, [], answers=[URL, "max"])
    assert code == 0 and "✓ logged in (Max Muster, student)" in out
    assert calls["verify"] == ("demo", "demo-school", "max", "s3cret")
    assert json.loads((tmp_path / "config.json").read_text())["username"] == "max"
    assert dotenv_values(tmp_path / ".env")["UNTIS_PASSWORD"] == "s3cret"
    assert "s3cret" not in out                                  # never shown
    assert mode(tmp_path) == 0o700


def test_new_ui_url_resolves_school_via_search(tmp_path):
    code, out, calls = run(tmp_path, [], answers=["https://demo.webuntis.com/today", "max"])
    assert code == 0 and "school: demo-school" in out and calls["verify"][1] == "demo-school"


@pytest.mark.parametrize("found", [[], [SCHOOL, {**SCHOOL, "loginName": "second"}]])
def test_new_ui_url_ambiguous_or_unknown(tmp_path, found):
    code, out, _ = run(tmp_path, [], answers=["https://demo.webuntis.com/today"],
                       search=lambda term: found)
    assert code == 2 and "couldn't tell which school" in out
    assert not (tmp_path / "config.json").exists()


def test_non_interactive_reads_password_from_stdin(tmp_path):
    code, out, calls = run(tmp_path, ["--url", URL, "--username", "max"],
                           stdin=io.StringIO("from-stdin\n"))
    assert code == 0 and calls["verify"][3] == "from-stdin"


def test_existing_config_needs_force_when_non_interactive(tmp_path):
    (tmp_path / "config.json").write_text("{}")
    code, out, _ = run(tmp_path, ["--url", URL, "--username", "max"], stdin=io.StringIO("pw\n"))
    assert code == 2 and "--force" in out
    code, _, _ = run(tmp_path, ["--url", URL, "--username", "max", "--force"],
                     stdin=io.StringIO("pw\n"))
    assert code == 0


def test_existing_config_interactive_decline_and_accept(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"server": "keep"}))
    code, out, _ = run(tmp_path, [], answers=[URL, "n"])
    assert code == 0 and "Nothing changed" in out
    assert json.loads((tmp_path / "config.json").read_text()) == {"server": "keep"}
    code, _, _ = run(tmp_path, [], answers=[URL, "ja", "max"])
    assert code == 0 and json.loads((tmp_path / "config.json").read_text())["server"] == "demo"


def test_login_rejected_saves_nothing(tmp_path):
    async def bad(*a):
        raise LoginError("WebUntis rejected the username or password.")
    code, out, _ = run(tmp_path, [], answers=[URL, "max"], verify=bad)
    assert code == 3 and "Nothing was saved" in out and "--no-verify" in out
    assert not (tmp_path / ".env").exists()


@pytest.mark.parametrize("exc", [WebUntisError("HTTP 503"), httpx.ConnectError("no route")])
def test_network_problems_save_nothing(tmp_path, exc):
    async def broken(*a):
        raise exc
    code, out, _ = run(tmp_path, [], answers=[URL, "max"], verify=broken)
    assert code == 4 and "couldn't reach WebUntis" in out and not (tmp_path / ".env").exists()


def test_no_verify_skips_the_login(tmp_path):
    async def must_not_run(*a):
        raise AssertionError
    code, out, _ = run(tmp_path, ["--no-verify"], answers=[URL, "max"], verify=must_not_run)
    assert code == 0 and "Testing login" not in out and (tmp_path / ".env").exists()


def test_search_single_multiple_and_invalid(tmp_path):
    code, out, calls = run(tmp_path, ["--search", "demo"], answers=["max"])
    assert code == 0 and calls["verify"][:2] == ("demo", "demo-school")
    two = [SCHOOL, {**SCHOOL, "server": "nese.webuntis.com", "loginName": "two",
                    "displayName": "Second"}]
    code, out, calls = run(tmp_path, ["--search", "demo", "--force"], answers=["2", "max"],
                           search=lambda t: two)
    assert code == 0 and calls["verify"][:2] == ("nese", "two") and " 2. Second" in out
    code, out, _ = run(tmp_path, ["--search", "demo", "--force"], answers=["9"], search=lambda t: two)
    assert code == 2 and "no school selected" in out
    code, out, _ = run(tmp_path, ["--search", "demo", "--username", "u", "--force"],
                       search=lambda t: two, stdin=io.StringIO("pw\n"))
    assert code == 2 and "be more specific" in out
    code, out, _ = run(tmp_path, ["--search", "nothing"], search=lambda t: [])
    assert code == 2 and "no school found" in out


def test_search_result_with_odd_server(tmp_path):
    code, out, _ = run(tmp_path, ["--search", "demo"], search=lambda t: [{**SCHOOL, "server": "x.org"}])
    assert code == 2 and "unexpected server" in out


def test_missing_username_or_password(tmp_path):
    code, out, _ = run(tmp_path, [], answers=[URL, "  "])
    assert code == 2 and "required" in out
    code, out, _ = run(tmp_path, [], answers=[URL, "max"], password="")
    assert code == 2


def test_ctrl_c_and_bad_url(tmp_path):
    def interrupt(prompt):
        raise KeyboardInterrupt
    code = sw.run(["--dir", str(tmp_path)], ask=interrupt, out=lambda s: None)
    assert code == 130
    code, out, _ = run(tmp_path, [], answers=["https://example.com"])
    assert code == 2 and "not a WebUntis school URL" in out


def test_main_dispatches_init(monkeypatch):
    seen = {}
    monkeypatch.setattr(sw, "run", lambda argv: seen.setdefault("argv", argv) and 0)
    monkeypatch.setattr(sys, "argv", ["untis", "init", "--url", "x"])
    main_mod.main()
    assert seen["argv"] == ["--url", "x"]
