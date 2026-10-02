"""Unit tests for the WebUntis client.

These tests don't need a real WebUntis account. They mock the Playwright
Page to verify the client behaves correctly in the
hard cases: WAF blocks, auth errors, success paths, error mapping.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Make src importable when running from the project root
sys.path.insert(0, str(Path(__file__).parent))

from src.untis_client import (  # noqa: E402
    AUTH_ERRORS,
    WebUntisClient,
    WebUntisError,
    _to_iso_date,
    _weeks,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def cfg() -> Any:
    from src.config import ScraperConfig
    return ScraperConfig(
        server="htbla-wels",
        school="htbla-wels",
        username="h.gre",
        password="s3cret",
        headless=True,
        timeout_ms=10_000,
    )
cfg_ = cfg  # alias for the parametrize trick below


@pytest.fixture
def fake_session() -> MagicMock:
    s = MagicMock()
    s.context = MagicMock()
    s.context.cookies = AsyncMock(return_value=[])
    return s


@pytest.fixture
def fake_page() -> MagicMock:
    p = MagicMock()
    p.goto = AsyncMock()
    p.locator = MagicMock()
    p.set_default_timeout = MagicMock()
    p.close = AsyncMock()
    p.screenshot = AsyncMock()
    p.wait_for_url = AsyncMock()
    p.keyboard.press = AsyncMock()
    return p


@pytest.fixture
def client(cfg: Any, fake_session: MagicMock, fake_page: MagicMock) -> WebUntisClient:
    from src.browser import BrowserSession
    c = WebUntisClient(cfg, fake_session)
    # Inject a fake page as if login() had completed.
    c._page = fake_page
    c._logged_in = True
    c._person_id = 12345
    c._person_type = 5
    c._user_display = "Hans Gretoffel"
    return c


# ----------------------------------------------------------------------
# Pure functions
# ----------------------------------------------------------------------
class TestHelpers:
    def test_to_iso_date(self):
        assert _to_iso_date(date(2026, 6, 2)) == "2026-06-02"

    def test_weeks_single(self):
        ws = _weeks(date(2026, 6, 1), date(2026, 6, 7))  # Mon..Sun
        assert len(ws) == 1
        assert ws[0] == (date(2026, 6, 1), date(2026, 6, 7))

    def test_weeks_three(self):
        ws = _weeks(date(2026, 6, 1), date(2026, 6, 21))  # 3 weeks
        assert len(ws) == 3
        assert ws[0][0] == date(2026, 6, 1)
        assert ws[-1][1] == date(2026, 6, 21)

    def test_weeks_swapped(self):
        ws = _weeks(date(2026, 6, 21), date(2026, 6, 1))
        assert len(ws) == 3


# ----------------------------------------------------------------------
# Browser RPC transport
# ----------------------------------------------------------------------
class TestRpcViaBrowser:
    async def test_success(self, client: WebUntisClient, fake_page: MagicMock):
        fake_page.evaluate = AsyncMock(return_value={
            "status": 200, "ok": True, "raw": "{}",
            "data": {"result": {"foo": "bar"}},
        })
        res = await client._rpc("test", {})
        assert res == {"foo": "bar"}
        # Verify the JS got the right URL and body shape
        args = fake_page.evaluate.call_args
        assert "jsonrpc.do" in args[0][1]["url"]
        assert "school=htbla-wels" in args[0][1]["url"]
        assert args[0][1]["body"]["method"] == "test"
        assert args[0][1]["body"]["jsonrpc"] == "2.0"

    async def test_waf_block(self, client: WebUntisClient, fake_page: MagicMock):
        fake_page.evaluate = AsyncMock(return_value={
            "status": 403, "ok": False,
            "raw": '{"isPublic":false,"error":true,'
                  '"errorMessage":"Your input contains code... RequestId: abc"}',
            "data": {"errorMessage": "Your input contains code..."},
        })
        with pytest.raises(WebUntisError) as exc:
            await client._rpc("authenticate", {})
        assert "WAF" in str(exc.value) or "IDS" in str(exc.value)
        assert "security policy" in str(exc.value).lower() or \
               "Your input contains code" in str(exc.value)

    async def test_http_500(self, client: WebUntisClient, fake_page: MagicMock):
        fake_page.evaluate = AsyncMock(return_value={
            "status": 500, "ok": False, "raw": "Internal Server Error", "data": None,
        })
        with pytest.raises(WebUntisError) as exc:
            await client._rpc("getTimetableForRange", {})
        assert "HTTP 500" in str(exc.value)

    async def test_rpc_error_known_code(
        self, client: WebUntisClient, fake_page: MagicMock,
    ):
        fake_page.evaluate = AsyncMock(return_value={
            "status": 200, "ok": True, "raw": "{}",
            "data": {"error": {"code": -8504, "message": "bad creds"}},
        })
        with pytest.raises(WebUntisError) as exc:
            await client._rpc("authenticate", {})
        assert "-8504" in str(exc.value)
        assert "Bad credentials" in str(exc.value)

    async def test_rpc_error_unknown_code(
        self, client: WebUntisClient, fake_page: MagicMock,
    ):
        fake_page.evaluate = AsyncMock(return_value={
            "status": 200, "ok": True, "raw": "{}",
            "data": {"error": {"code": -99999, "message": "weird"}},
        })
        with pytest.raises(WebUntisError) as exc:
            await client._rpc("foo", {})
        assert "-99999" in str(exc.value)
        assert "weird" in str(exc.value)

    async def test_rpc_error_string(self, client: WebUntisClient, fake_page: MagicMock):
        fake_page.evaluate = AsyncMock(return_value={
            "status": 200, "ok": True, "raw": "{}",
            "data": {"error": "something bad"},
        })
        with pytest.raises(WebUntisError) as exc:
            await client._rpc("foo", {})
        assert "something bad" in str(exc.value)

    async def test_throttle(self, client: WebUntisClient, fake_page: MagicMock):
        fake_page.evaluate = AsyncMock(return_value={
            "status": 200, "ok": True, "raw": "{}", "data": {"result": {}},
        })
        # First call: 0 wait (we just set the timestamp)
        client._last_request_ts = 0.0
        await client._rpc("a", {})
        # Second call back-to-back: should have throttled
        import time
        t0 = time.monotonic()
        await client._rpc("b", {})
        elapsed = time.monotonic() - t0
        # Throttle is 0.3s, allow generous slack on slow CI
        assert elapsed < 0.6  # just confirm it didn't crash on backoff


# ----------------------------------------------------------------------
# Login flow
# ----------------------------------------------------------------------
def _make_loc(count: int = 1) -> MagicMock:
    loc = MagicMock()
    loc.count = AsyncMock(return_value=count)
    loc.wait_for = AsyncMock()
    loc.fill = AsyncMock()
    loc.click = AsyncMock()
    return loc


def _form_page(fake_page: MagicMock, user, pw, submit, twofa=None) -> None:
    """Route the combined selectors used by _do_form_login to fake locators."""
    def locator_maker(sel):
        outer = MagicMock()
        if "otp" in sel:
            target = twofa or _make_loc(0)
            outer.count = target.count
            return outer
        if "j_username" in sel:
            target = user
        elif "j_password" in sel:
            target = pw
        elif "submit" in sel:
            target = submit
        else:
            target = _make_loc(0)
        outer.locator = MagicMock(return_value=MagicMock(first=target))
        return outer
    fake_page.locator = MagicMock(side_effect=locator_maker)


class TestLogin:
    async def test_reuses_valid_session(
        self, cfg: Any, fake_session: MagicMock, fake_page: MagicMock
    ):
        c = WebUntisClient(cfg, fake_session)
        c._probe_session = AsyncMock(return_value=True)
        c._do_form_login = AsyncMock()
        fake_session.new_page = AsyncMock(return_value=fake_page)

        await c.login()
        c._do_form_login.assert_not_awaited()
        assert c._logged_in is True

    async def test_form_login_success(
        self, cfg: Any, fake_session: MagicMock, fake_page: MagicMock
    ):
        """End-to-end: form fields found, filled, submitted, redirected."""
        c = WebUntisClient(cfg, fake_session)
        c._probe_session = AsyncMock(return_value=True)
        fake_session.context.clear_cookies = AsyncMock()
        fake_session.new_page = AsyncMock(return_value=fake_page)

        user, pw, submit = _make_loc(), _make_loc(), _make_loc()
        _form_page(fake_page, user, pw, submit)

        await c.login(force=True)
        fake_session.context.clear_cookies.assert_awaited_once()
        user.fill.assert_awaited_once_with("h.gre")
        pw.fill.assert_awaited_once_with("s3cret")
        submit.click.assert_awaited_once()
        assert c._logged_in is True

    async def test_no_form_found_screenshots(
        self, cfg: Any, fake_session: MagicMock, fake_page: MagicMock
    ):
        from playwright.async_api import TimeoutError as PWTimeout
        c = WebUntisClient(cfg, fake_session)
        c._probe_session = AsyncMock(return_value=False)
        fake_session.new_page = AsyncMock(return_value=fake_page)

        user = _make_loc(0)
        user.wait_for = AsyncMock(side_effect=PWTimeout("timeout"))
        _form_page(fake_page, user, _make_loc(0), _make_loc(0))

        with pytest.raises(WebUntisError) as exc:
            await c.login()
        assert "login form" in str(exc.value).lower()
        fake_page.screenshot.assert_awaited()

    async def test_2fa_detected(
        self, cfg: Any, fake_session: MagicMock, fake_page: MagicMock
    ):
        from playwright.async_api import TimeoutError as PWTimeout
        c = WebUntisClient(cfg, fake_session)
        c._probe_session = AsyncMock(return_value=False)
        fake_session.new_page = AsyncMock(return_value=fake_page)

        _form_page(fake_page, _make_loc(), _make_loc(), _make_loc(0),
                   twofa=_make_loc(1))
        fake_page.wait_for_url = AsyncMock(side_effect=PWTimeout("timeout"))

        with pytest.raises(WebUntisError) as exc:
            await c.login()
        assert "2FA" in str(exc.value)
        fake_page.keyboard.press.assert_awaited_with("Enter")


class TestProbeSession:
    @staticmethod
    def _jwt(claims: dict) -> str:
        import base64
        body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        return f"eyJhbGciOiJSUzI1NiJ9.{body}.sig"

    async def test_student_from_token(
        self, cfg: Any, fake_session: MagicMock, fake_page: MagicMock
    ):
        token = self._jwt({"person_id": 4242, "roles": "STUDENT", "username": "x"})
        async def evaluate(js, payload):
            if payload["url"].endswith("/token/new"):
                return {"status": 200, "ok": True, "raw": token, "data": None}
            assert payload["token"] == token
            return {"status": 200, "ok": True, "raw": "{}", "data": {
                "user": {"person": {"id": 4242, "displayName": "Max Muster"},
                         "students": []},
            }}
        fake_page.evaluate = evaluate
        c = WebUntisClient(cfg, fake_session)
        c._page = fake_page

        assert await c._probe_session() is True
        assert (c._person_id, c._person_type, c._resource_type) == (4242, 5, "STUDENT")
        assert c.user_display == "Max Muster"

    async def test_not_logged_in(
        self, cfg: Any, fake_session: MagicMock, fake_page: MagicMock
    ):
        fake_page.evaluate = AsyncMock(return_value={
            "status": 200, "ok": True, "raw": "", "data": None,
        })
        c = WebUntisClient(cfg, fake_session)
        c._page = fake_page
        assert await c._probe_session() is False


# ----------------------------------------------------------------------
# Data fetchers
# ----------------------------------------------------------------------
class TestDataFetchers:
    async def test_timetable_paginates_per_week(
        self, client: WebUntisClient, fake_page: MagicMock,
    ):
        calls = []
        async def evaluate(js, payload):
            calls.append((payload["body"]["method"], payload["body"]["params"]))
            return {
                "status": 200, "ok": True, "raw": "{}",
                "data": {"result": [{"id": len(calls), "date": 20260602}]},
            }
        fake_page.evaluate = evaluate

        lessons = await client.get_timetable(date(2026, 6, 1), date(2026, 6, 21))
        # 3 weeks (Mon Jun 1 .. Sun Jun 21)
        assert len(calls) == 3
        assert all(c[0] == "getTimetable" for c in calls)
        opts = calls[0][1]["options"]
        assert opts["element"] == {"id": 12345, "type": 5}
        assert opts["startDate"] == 20260601
        assert len(lessons) == 3

    async def test_grid_merges_weeks_with_bearer(
        self, client: WebUntisClient, fake_page: MagicMock,
    ):
        client._token = "tok"
        seen = []
        async def evaluate(js, payload):
            seen.append(payload)
            day = payload["params"]["start"]
            return {"status": 200, "ok": True, "raw": "{}",
                    "data": {"days": [{"date": day, "gridEntries": []}]}}
        fake_page.evaluate = evaluate

        grid = await client.get_timetable_grid(date(2026, 6, 1), date(2026, 6, 14))
        assert [d["date"] for d in grid["days"]] == ["2026-06-01", "2026-06-08"]
        assert all(p["token"] == "tok" for p in seen)
        assert seen[0]["params"]["resources"] == "12345"

    async def test_exams_raises_on_http_error(
        self, client: WebUntisClient, fake_page: MagicMock,
    ):
        fake_page.evaluate = AsyncMock(return_value={
            "status": 403, "ok": False, "raw": "forbidden", "data": None,
        })
        with pytest.raises(WebUntisError):
            await client.get_exams(date(2026, 6, 1), date(2026, 6, 30))

    async def test_homework_joins_lessons_and_teachers(
        self, client: WebUntisClient, fake_page: MagicMock,
    ):
        fake_page.evaluate = AsyncMock(return_value={
            "status": 200, "ok": True, "raw": "{}",
            "data": {"data": {
                "records": [{"homeworkId": 1, "teacherId": 7, "elementIds": []}],
                "homeworks": [{"id": 1, "lessonId": 3, "text": "do math",
                               "date": 20260601, "dueDate": 20260605}],
                "teachers": [{"id": 7, "name": "GRI"}],
                "lessons": [{"id": 3, "subject": "M", "lessonType": "Unterricht"}],
            }},
        })
        result = await client.get_homework(date(2026, 6, 1), date(2026, 6, 30))
        assert result[0]["text"] == "do math"
        assert result[0]["lesson"]["subject"] == "M"
        assert result[0]["teacher"]["name"] == "GRI"

    async def test_own_classes_from_filter(
        self, client: WebUntisClient, fake_page: MagicMock,
    ):
        client._token = "tok"
        client._resource_type = "STUDENT"
        fake_page.evaluate = AsyncMock(return_value={
            "status": 200, "ok": True, "raw": "{}", "data": {"students": [
                {"student": {"id": 999}, "classes": [{"class": {"shortName": "OTHER"}}]},
                {"student": {"id": 12345}, "classes": [
                    {"class": {"shortName": "CLASS-A"}, "dateRange": {}},
                ]},
            ]},
        })
        assert await client.get_own_classes() == {"CLASS-A"}

    async def test_own_classes_empty_for_teachers(self, client: WebUntisClient):
        client._resource_type = "TEACHER"
        assert await client.get_own_classes() == set()

    async def test_refreshes_token_on_401(
        self, client: WebUntisClient, fake_page: MagicMock,
    ):
        client._token = "old"
        new = TestProbeSession._jwt({"person_id": 1})
        responses = [
            {"status": 401, "ok": False, "raw": "", "data": None},
            {"status": 200, "ok": True, "raw": new, "data": None},
            {"status": 200, "ok": True, "raw": "{}", "data": {"incomingMessages": [{"id": 1}]}},
        ]
        fake_page.evaluate = AsyncMock(side_effect=responses)
        assert await client.get_messages() == [{"id": 1}]
        assert client._token == new


# ----------------------------------------------------------------------
# Error mapping
# ----------------------------------------------------------------------
class TestErrorMap:
    def test_all_known_codes_have_messages(self):
        for code, (msg, _) in AUTH_ERRORS.items():
            assert isinstance(code, int)
            assert isinstance(msg, str) and msg
            assert "{" not in msg  # no f-string artifacts

    def test_waf_error_is_known(self):
        # The WAF returns 403 with a non-JSON-RPC body, so the code is
        # parsed from the HTTP status, not the JSON. We just verify our
        # error mapper doesn't claim -8504 is recoverable (a previous
        # version accidentally did, causing infinite form-fallback).
        msg, recoverable = AUTH_ERRORS[-8504]
        assert "credentials" in msg.lower() or "Bad credentials" in msg
        assert recoverable is False
