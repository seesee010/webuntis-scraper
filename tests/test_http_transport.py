"""Tests for the plain-HTTP transport and the client's transport choice.

A small fake WebUntis (httpx.MockTransport) mimics what was observed on a
live instance: the login form redirects to /WebUntis/index.do on success
and back to /WebUntis/ on bad credentials; API calls without a valid
session answer with a 302 to the login page.
"""
from __future__ import annotations

import base64
import json
import os
import stat
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.config import ScraperConfig
from src.http_transport import HttpTransport
from src.untis_client import LoginError, WebUntisClient


def _jwt(claims: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJSUzI1NiJ9.{body}.sig"


class FakeUntis:
    def __init__(self, password: str = "s3cret", login_status: int | None = None):
        self.password = password
        self.login_status = login_status     # force e.g. 403 (WAF)
        self.valid: set[str] = set()
        self.counter = 0
        self.login_posts = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        sid = request.headers.get("cookie", "")
        sid = dict(p.strip().split("=", 1) for p in sid.split(";") if "=" in p).get("JSESSIONID")
        if path == "/WebUntis/" and request.method == "GET":
            self.counter += 1
            return httpx.Response(200, text="<html>",
                                  headers={"set-cookie": f"JSESSIONID=s{self.counter}; Path=/WebUntis; HttpOnly"})
        if path == "/WebUntis/j_spring_security_check":
            self.login_posts += 1
            if self.login_status:
                return httpx.Response(self.login_status, text="blocked")
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            if form.get("j_password") == self.password and sid:
                self.valid.add(sid)
                return httpx.Response(302, headers={"location": "/WebUntis/index.do"})
            return httpx.Response(302, headers={"location": "/WebUntis/"})
        if sid not in self.valid:
            return httpx.Response(302, headers={"location": "https://x.webuntis.com/WebUntis/index.do"})
        if path == "/WebUntis/api/token/new":
            return httpx.Response(200, text=_jwt({"person_id": 4242, "roles": "STUDENT"}))
        if path == "/WebUntis/api/rest/view/v1/app/data":
            assert request.headers["authorization"].startswith("Bearer ")
            return httpx.Response(200, json={"user": {"person": {"id": 4242, "displayName": "Max Muster"}}})
        return httpx.Response(404, json={"errorCode": "NOT_FOUND"})


@pytest.fixture
def cfg(tmp_path: Path) -> ScraperConfig:
    return ScraperConfig(server="x", school="x", base_url="https://x.webuntis.com",
                         username="u", password="s3cret", transport="auto",
                         storage_state_path=str(tmp_path / "state.json"))


def _client(cfg, fake: FakeUntis) -> tuple[WebUntisClient, MagicMock]:
    session = MagicMock()
    session.new_page = AsyncMock(side_effect=AssertionError("browser must not start"))
    client = WebUntisClient(cfg, session)
    client._min_interval = 0
    client._http_factory = lambda c, load_saved=True: HttpTransport(
        c, load_saved=load_saved, transport=httpx.MockTransport(fake.handler))
    return client, session


# ----------------------------------------------------------------------
# HttpTransport
# ----------------------------------------------------------------------
async def test_form_login_outcomes(cfg):
    ok = HttpTransport(cfg, transport=httpx.MockTransport(FakeUntis().handler))
    assert (await ok.form_login("u", "s3cret"))[0] == "ok"
    bad = HttpTransport(cfg, transport=httpx.MockTransport(FakeUntis().handler))
    assert (await bad.form_login("u", "wrong"))[0] == "rejected"
    waf = HttpTransport(cfg, transport=httpx.MockTransport(FakeUntis(login_status=403).handler))
    outcome, detail = await waf.form_login("u", "s3cret")
    assert outcome == "unexpected" and "403" in detail


async def test_cookies_roundtrip_in_playwright_format(cfg):
    Path(cfg.storage_state_path).write_text(json.dumps({
        "cookies": [
            {"name": "JSESSIONID", "value": "old", "domain": "x.webuntis.com",
             "path": "/WebUntis", "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax"},
            {"name": "gone", "value": "1", "domain": "x.webuntis.com",
             "path": "/", "expires": 1.0, "httpOnly": False, "secure": True, "sameSite": "Lax"},
        ],
        "origins": [{"origin": "https://x.webuntis.com", "localStorage": []}],
    }))
    t = HttpTransport(cfg, transport=httpx.MockTransport(FakeUntis().handler))
    assert t._client.cookies.get("JSESSIONID") == "old"
    assert t._client.cookies.get("gone") is None          # expired
    await t.form_login("u", "s3cret")
    t.save_cookies()

    path = Path(cfg.storage_state_path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    saved = json.loads(path.read_text())
    jsid = next(c for c in saved["cookies"] if c["name"] == "JSESSIONID")
    assert jsid["value"] == "s1" and jsid["path"] == "/WebUntis"
    assert set(jsid) == {"name", "value", "domain", "path", "expires",
                         "httpOnly", "secure", "sameSite"}
    assert saved["origins"] == [{"origin": "https://x.webuntis.com", "localStorage": []}]


# ----------------------------------------------------------------------
# Client transport choice
# ----------------------------------------------------------------------
async def test_reuses_saved_session_without_browser(cfg):
    fake = FakeUntis()
    fake.valid.add("alive")
    Path(cfg.storage_state_path).write_text(json.dumps({"cookies": [
        {"name": "JSESSIONID", "value": "alive", "domain": "x.webuntis.com",
         "path": "/WebUntis", "expires": -1}]}))
    client, session = _client(cfg, fake)
    await client.login()
    assert client._logged_in and client._person_id == 4242
    assert client.user_display == "Max Muster"
    assert fake.login_posts == 0
    session.new_page.assert_not_called()


async def test_expired_session_logs_in_over_http(cfg):
    fake = FakeUntis()
    client, session = _client(cfg, fake)
    await client.login()
    assert client._logged_in and fake.login_posts == 1
    session.new_page.assert_not_called()
    await client.close()
    assert json.loads(Path(cfg.storage_state_path).read_text())["cookies"]


async def test_rejected_credentials_do_not_retry_in_browser(cfg):
    fake = FakeUntis(password="other")
    client, session = _client(cfg, fake)
    client._login_browser = AsyncMock()
    with pytest.raises(LoginError, match="rejected"):
        await client.login()
    assert fake.login_posts == 1
    client._login_browser.assert_not_awaited()


@pytest.mark.parametrize("mode, falls_back", [("auto", True), ("http", False)])
async def test_unexpected_answer(cfg, mode, falls_back):
    cfg.transport = mode
    client, _ = _client(cfg, FakeUntis(login_status=403))
    client._login_browser = AsyncMock()
    if falls_back:
        await client.login()
        client._login_browser.assert_awaited_once()
        assert client._http is None          # browser handles the rest
    else:
        with pytest.raises(LoginError, match="HTTP login failed"):
            await client.login()
        client._login_browser.assert_not_awaited()


async def test_network_error_is_not_retried_in_browser(cfg):
    def boom(request):
        raise httpx.ConnectError("no route", request=request)
    client, _ = _client(cfg, FakeUntis())
    client._http_factory = lambda c, load_saved=True: HttpTransport(
        c, load_saved=load_saved, transport=httpx.MockTransport(boom))
    client._login_browser = AsyncMock()
    with pytest.raises(httpx.ConnectError):
        await client.login()
    client._login_browser.assert_not_awaited()


@pytest.mark.parametrize("change", [{"transport": "browser"}, {"headless": False}])
async def test_browser_only_modes_skip_http(cfg, change):
    for k, v in change.items():
        setattr(cfg, k, v)
    client, _ = _client(cfg, FakeUntis())
    client._login_browser = AsyncMock()
    client._http_factory = MagicMock(side_effect=AssertionError("no HTTP"))
    await client.login()
    client._login_browser.assert_awaited_once()


async def test_force_ignores_saved_cookies(cfg):
    fake = FakeUntis()
    fake.valid.add("alive")
    Path(cfg.storage_state_path).write_text(json.dumps({"cookies": [
        {"name": "JSESSIONID", "value": "alive", "domain": "x.webuntis.com",
         "path": "/WebUntis", "expires": -1}]}))
    client, _ = _client(cfg, fake)
    await client.login(force=True)
    assert fake.login_posts == 1                # logged in again via the form
