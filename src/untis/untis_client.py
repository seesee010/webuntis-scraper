"""WebUntis client.

Architecture decision (learned the hard way):

The school's WebUntis instance runs a WAF/IDS in front of the JSON-RPC
endpoint. Direct calls from `httpx` (no `Origin`/`Referer`/browser-bound
cookies) are rejected with `HTTP 403 — Your input contains code that
does not match the security policy`.

Two transports (`cfg.transport`, default "auto"):

- **HTTP** (`http_transport.py`, no browser): log in by POSTing the
  login form (`j_spring_security_check`, not blocked by the WAF) and
  call every endpoint with the session cookie. Fast (well under a
  second instead of 2-12 s for Chromium + form login).
- **Browser** (Playwright): fill in the real login form and run API
  calls via `page.evaluate(fetch(...))`. Used for `--transport browser`,
  `--no-headless`, and as a fallback in "auto" mode when the HTTP login
  gets an unexpected answer (WAF, 2FA, SSO, ...).

Both read and write the same `storage_state` file, so a session from
one transport is reused by the other. Sessions expire on the server
after a while of inactivity (~40 min observed), so most runs log in.

Which API serves what (verified against a live UI2020 instance):

- `GET /WebUntis/api/token/new` (cookie auth) returns a JWT. Its claims
  carry `person_id` and `roles`; it doubles as the session probe.
- `/WebUntis/api/rest/view/v1/...` (timetable, app data, messages)
  needs that JWT as `Authorization: Bearer`, otherwise it answers 404.
- `/WebUntis/api/exams`, `/api/homeworks/lessons`,
  `/api/classreg/absences/students` work with the session cookie.
- JSON-RPC only exposes the classic public methods (`getTimetable`,
  `getSchoolyears`, ...). There is no `getUserData`, `getHomeWorkForRange`
  etc. — those return `Method not found`.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from datetime import date
from typing import Any, Optional

from typing import TYPE_CHECKING

import httpx

from .browser import BrowserSession
from .config import LOGS_DIR, ScraperConfig
from .http_transport import HttpTransport

if TYPE_CHECKING:       # Playwright is imported lazily (slow import)
    from playwright.async_api import Page

log = logging.getLogger(__name__)

JSONRPC_PATH = "/WebUntis/jsonrpc.do"
API_BASE = "/WebUntis/api"
REST_BASE = "/WebUntis/api/rest/view/v1"
TOKEN_PATH = "/WebUntis/api/token/new"
# Plain JSON page on the WebUntis origin. API fetches are run from here
# because the SPA pages keep redirecting, which kills the JS context.
ANCHOR_PATH = "/WebUntis/api/app/config"

# WebUntis element types (JSON-RPC `type` / REST `resourceType`).
ELEMENT_TYPES: dict[str, tuple[int, str]] = {
    "STUDENT": (5, "STUDENT"),
    "TEACHER": (2, "TEACHER"),
}


# JSON-RPC error code -> (message, requires_interactive_retry)
AUTH_ERRORS: dict[int, tuple[str, bool]] = {
    -1:  ("Invalid username or password", False),
    -2:  ("Account is locked / too many attempts", False),
    -3:  ("Login not yet started or already ended", False),
    -4:  ("Invalid school", False),
    -5:  ("Invalid client", False),
    -6:  ("Wrong user agent", False),
    -7:  ("OTP required (2FA) — complete login in the browser", True),
    -8:  ("Captcha required — complete login in the browser", True),
    -9:  ("No OTP secret set on account", False),
    -10: ("School not active / not allowed", False),
    -50: ("Server temporarily unavailable", True),
    -100: ("Network error", True),
    -200: ("Session expired", True),
    -1010: ("Login not possible (maintenance)", True),
    -8504: ("Bad credentials", False),
    -8509: ("No permission for this method", False),
    -32601: ("Method not found", False),
}

# JavaScript that runs inside the page context. Wraps fetch with
# credentials: 'include' so cookies are sent, returns status+body.
_FETCH_JS = """
async ({url, body}) => {
    const r = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/plain, */*',
            'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify(body),
        credentials: 'include',
        mode: 'cors'
    });
    const text = await r.text();
    let data = null;
    try { data = JSON.parse(text); } catch (_) { /* keep null */ }
    return { status: r.status, ok: r.ok, data, raw: text };
}
"""

_GET_JS = """
async ({url, params, token}) => {
    const qs = new URLSearchParams(params).toString();
    const headers = {
        'Accept': 'application/json, text/plain, */*',
        'X-Requested-With': 'XMLHttpRequest'
    };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const r = await fetch(url + (qs ? '?' + qs : ''), {
        credentials: 'include',
        headers
    });
    const text = await r.text();
    let data = null;
    try { data = JSON.parse(text); } catch (_) {}
    return { status: r.status, ok: r.ok, data, raw: text };
}
"""


def _to_iso_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _to_untis_date(d: date) -> int:
    return int(d.strftime("%Y%m%d"))


def _weeks(start: date, end: date) -> list[tuple[date, date]]:
    if end < start:
        start, end = end, start
    cur = start
    out: list[tuple[date, date]] = []
    while cur <= end:
        monday = cur.fromordinal(cur.toordinal() - cur.weekday())
        sunday = monday.fromordinal(monday.toordinal() + 6)
        out.append((max(monday, start), min(sunday, end)))
        cur = monday.fromordinal(monday.toordinal() + 7)
    return out


def _decode_jwt_claims(token: str) -> Optional[dict[str, Any]]:
    """Return the (unverified) claims of a JWT, or None if it isn't one."""
    parts = (token or "").strip().split(".")
    if len(parts) != 3:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    return claims if isinstance(claims, dict) else None


class WebUntisError(RuntimeError):
    """Raised when WebUntis returns an error or auth fails."""


class LoginError(WebUntisError):
    """Raised when no logged-in session could be established."""


class WebUntisClient:
    def __init__(self, cfg: ScraperConfig, session: BrowserSession):
        self.cfg = cfg
        self.session = session
        self._page: Optional[Page] = None
        self._http: Optional[HttpTransport] = None
        self._http_factory = HttpTransport      # replaced in tests
        self._person_id: Optional[int] = None
        self._person_type: Optional[int] = None
        self._resource_type: Optional[str] = None
        self._user_display: Optional[str] = None
        self._token: Optional[str] = None
        self._logged_in = False
        self._rpc_id = 0
        self._last_request_ts = 0.0
        self._min_interval = 0.3

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------
    def _transport_mode(self) -> str:
        # A visible browser means the user wants to watch/interact.
        if not self.cfg.headless:
            return "browser"
        return self.cfg.transport

    async def login(self, force: bool = False) -> None:
        if self._logged_in and not force:
            return
        mode = self._transport_mode()
        if mode != "browser":
            try:
                await self._login_http(force)
                return
            except (LoginError, httpx.TransportError):
                # Rejected credentials: a browser retry would just be a
                # second failed attempt (lockout risk). Network errors
                # would fail in the browser too.
                await self._close_http(save=False)
                raise
            except WebUntisError as exc:
                await self._close_http(save=False)
                if mode == "http":
                    raise LoginError(f"HTTP login failed: {exc}") from exc
                log.info("HTTP login not possible (%s); falling back to the browser", exc)
        await self._login_browser(force)

    async def _login_http(self, force: bool) -> None:
        self._http = self._http_factory(self.cfg, load_saved=not force)
        if not force and await self._probe_session():
            log.info("Reusing existing session (HTTP)")
            self._logged_in = True
            return
        outcome, detail = await self._http.form_login(self.cfg.username, self.cfg.password)
        if outcome == "rejected":
            raise LoginError(
                "WebUntis rejected the username or password. If your account "
                "uses 2FA or SSO, try --transport browser --no-headless"
            )
        if outcome != "ok" or not await self._probe_session():
            raise WebUntisError(f"unexpected login response ({detail})")
        log.info("Login successful via HTTP")
        self._logged_in = True

    async def _login_browser(self, force: bool) -> None:
        self._page = await self.session.new_page()
        assert self.session.context is not None

        if force:
            # Drop the saved session, otherwise WebUntis redirects the
            # login URL straight to the dashboard and there is no form.
            await self.session.context.clear_cookies()
        else:
            if await self._probe_session():
                log.info("Reusing existing session (storage_state still valid)")
                self._logged_in = True
                return

        await self._do_form_login()
        if not await self._probe_session():
            raise LoginError(
                "Form login did not produce a valid session. "
                "Check credentials / 2FA / school+server config."
            )
        self._logged_in = True
        log.info("Login successful via form")

    async def _do_form_login(self) -> None:
        from playwright.async_api import TimeoutError as PWTimeout
        assert self._page is not None
        page = self._page
        await page.goto(self.cfg.login_url, wait_until="domcontentloaded")

        # The login URL is the React SPA shell — wait for the form to
        # actually render.
        user_selectors = [
            'input[name="j_username"]',
            'input[name="username"]',
            'input[name="user"]',
            'input[autocomplete="username"]',
            'input[type="text"]',
        ]
        pw_selectors = [
            'input[name="j_password"]',
            'input[name="password"]',
            'input[type="password"]',
        ]
        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Anmelden")',
            'button:has-text("Login")',
            'button:has-text("Log in")',
            'button:has-text("Sign in")',
        ]

        user_loc = page.locator(", ".join(user_selectors)).locator("visible=true").first
        try:
            await user_loc.wait_for(state="visible", timeout=self.cfg.timeout_ms)
        except PWTimeout:
            await self._screenshot("login_no_form")
            raise LoginError(
                "Could not find login form. Run with --no-headless to debug. "
                f"Screenshot saved to {LOGS_DIR / 'login_no_form.png'}"
            )
        await user_loc.fill(self.cfg.username)

        pw_loc = page.locator(", ".join(pw_selectors)).locator("visible=true").first
        try:
            await pw_loc.wait_for(state="visible", timeout=5_000)
        except PWTimeout:
            raise LoginError("Password field not found")
        await pw_loc.fill(self.cfg.password)

        submit_loc = page.locator(", ".join(submit_selectors)).locator("visible=true").first
        if await submit_loc.count() > 0:
            await submit_loc.click()
        else:
            await page.keyboard.press("Enter")

        # UI2020 lands on e.g. https://<server>.webuntis.com/today after
        # login — no "/WebUntis" in the URL any more.
        try:
            await page.wait_for_url(
                lambda url: "login" not in url.lower(),
                timeout=self.cfg.timeout_ms,
            )
        except PWTimeout:
            if await self._has_2fa_field():
                raise LoginError(
                    "2FA required. Run with --no-headless and complete it once; "
                    "the session will be saved for next time."
                )
            err_text = await self._read_error_text()
            await self._screenshot("login_failed")
            raise LoginError(
                f"Form login did not redirect away from the login page. "
                f"Server message: {err_text or 'none'}. "
                f"Screenshot: {LOGS_DIR / 'login_failed.png'}"
            )

    async def _has_2fa_field(self) -> bool:
        assert self._page is not None
        return await self._page.locator(
            'input[name="otp"], input[name="code"], input[name="token"], '
            'input[autocomplete="one-time-code"]'
        ).count() > 0

    async def _read_error_text(self) -> str:
        assert self._page is not None
        for sel in [
            '.error', '.login-error', '[class*="error"]',
            '[role="alert"]', '.message',
        ]:
            loc = self._page.locator(sel).first
            if await loc.count() > 0:
                txt = (await loc.inner_text() or "").strip()
                if txt:
                    return txt
        return ""

    async def _screenshot(self, name: str) -> None:
        if not self._page:
            return
        try:
            path = LOGS_DIR / f"{name}.png"
            await self._page.screenshot(path=str(path), full_page=True)
            log.info("Saved debug screenshot to %s", path)
        except Exception:
            pass

    async def _probe_session(self) -> bool:
        """Return True if the browser holds a logged-in session.

        Fetches a JWT (only issued to authenticated sessions) and reads
        the person id/role from it, then the display name from /app/data.
        """
        if self._http is None:
            assert self._page is not None
            await self._page.goto(
                f"{self.cfg.base_url}{ANCHOR_PATH}", wait_until="domcontentloaded",
            )
        try:
            await self._refresh_token()
        except WebUntisError as exc:
            log.debug("Session probe failed: %s", exc)
            return False

        claims = _decode_jwt_claims(self._token or "") or {}
        roles = str(claims.get("roles") or "").upper()
        person_id = claims.get("person_id")

        app_data: dict[str, Any] = {}
        try:
            app_data = await self._rest_get("/app/data", {})
        except WebUntisError as exc:
            log.debug("REST /app/data failed: %s", exc)
        user = app_data.get("user") or {}
        person = user.get("person") or {}
        students = user.get("students") or []

        if "STUDENT" in roles:
            kind = "STUDENT"
        elif "TEACHER" in roles:
            kind = "TEACHER"
        elif students:
            # Parent accounts: scrape the first linked child.
            kind = "STUDENT"
            person_id = students[0].get("id")
            person = students[0]
        else:
            kind = "STUDENT"

        person_id = person_id or person.get("id")
        if not person_id:
            log.debug("Session probe: token has no person id (claims=%s)", list(claims))
            return False

        self._person_id = int(person_id)
        self._person_type, self._resource_type = ELEMENT_TYPES[kind]
        self._user_display = person.get("displayName") or claims.get("username")
        log.debug(
            "Session belongs to %s (person_id=%s, type=%s)",
            self._user_display, self._person_id, kind,
        )
        return True

    async def _refresh_token(self) -> None:
        await self._throttle()
        result = await self._send_get(f"{self.cfg.base_url}{TOKEN_PATH}", {}, None)
        token = (result.get("raw") or "").strip()
        if not result["ok"] or _decode_jwt_claims(token) is None:
            self._token = None
            raise WebUntisError(
                f"No bearer token (HTTP {result['status']}); not logged in"
            )
        self._token = token

    # ------------------------------------------------------------------
    # Transports
    # ------------------------------------------------------------------
    def _next_id(self) -> str:
        self._rpc_id += 1
        return f"scraper-{self._rpc_id}-{uuid.uuid4().hex[:8]}"

    async def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_request_ts = time.monotonic()

    async def _send_get(self, url: str, params: dict, token: Optional[str]) -> dict[str, Any]:
        """GET via the active transport -> {status, ok, data, raw}."""
        if self._http is not None:
            return await self._http.get(url, params, token)
        assert self._page is not None
        return await self._page.evaluate(
            _GET_JS, {"url": url, "params": params, "token": token})

    async def _send_post(self, url: str, body: dict) -> dict[str, Any]:
        """JSON POST via the active transport -> {status, ok, data, raw}."""
        if self._http is not None:
            return await self._http.post_json(url, body)
        assert self._page is not None
        return await self._page.evaluate(_FETCH_JS, {"url": url, "body": body})

    async def _rpc_call(self, method: str, params: dict) -> Any:
        await self._throttle()
        url = f"{self.cfg.base_url}{JSONRPC_PATH}?school={self.cfg.school}"
        body = {
            "id": self._next_id(),
            "method": method,
            "params": params,
            "jsonrpc": "2.0",
        }
        result = await self._send_post(url, body)

        # WAF / IDS block: HTTP 403 with "security policy" message.
        if result["status"] == 403:
            msg = (result.get("data") or {}).get("errorMessage", "") or result["raw"][:200]
            raise WebUntisError(
                f"WAF/IDS blocked {method} (HTTP 403): {msg}"
            )
        if not result["ok"]:
            raise WebUntisError(
                f"HTTP {result['status']} from JSON-RPC {method}: "
                f"{result['raw'][:200]}"
            )

        data = result.get("data") or {}
        if "error" in data and data["error"]:
            err = data["error"]
            if isinstance(err, dict):
                code = err.get("code")
                msg, _ = AUTH_ERRORS.get(code, (err.get("message", "RPC error"), False))
                raise WebUntisError(f"{method} failed: {msg} (code={code})")
            raise WebUntisError(f"{method} error: {err}")
        return data.get("result") or {}

    async def _rpc(self, method: str, params: dict) -> Any:
        return await self._rpc_call(method, params)

    async def _get(self, url: str, params: dict, *, bearer: bool) -> Any:
        str_params = {k: str(v) for k, v in params.items()}
        for attempt in range(2):
            await self._throttle()
            result = await self._send_get(url, str_params, self._token if bearer else None)
            # Bearer tokens are short-lived; refresh once on 401.
            if bearer and result["status"] == 401 and attempt == 0:
                await self._refresh_token()
                continue
            break
        if not result["ok"]:
            raise WebUntisError(
                f"HTTP {result['status']} from {url}: {result['raw'][:200]}"
            )
        return result["data"] or {}

    async def _rest_get(self, path: str, params: dict) -> Any:
        """GET on the UI2020 REST v1 API (bearer auth)."""
        if self._token is None:
            await self._refresh_token()
        return await self._get(f"{self.cfg.base_url}{REST_BASE}{path}", params, bearer=True)

    async def _api_get(self, path: str, params: dict) -> Any:
        """GET on the legacy /WebUntis/api endpoints (cookie auth)."""
        return await self._get(f"{self.cfg.base_url}{API_BASE}{path}", params, bearer=False)

    def _require_person(self) -> tuple[int, int]:
        if self._person_id is None or self._person_type is None:
            raise WebUntisError("No person id/type known; did login succeed?")
        return self._person_id, self._person_type

    # ------------------------------------------------------------------
    # Public data fetchers
    # ------------------------------------------------------------------
    async def get_schoolyears(self) -> list[dict]:
        return await self._rpc("getSchoolyears", {})

    async def get_timetable_grid(self, start: date, end: date) -> dict[str, Any]:
        """Timetable from the UI2020 REST API, merged across weeks."""
        pid, _ = self._require_person()
        days: list[dict] = []
        for week_start, week_end in _weeks(start, end):
            res = await self._rest_get("/timetable/entries", {
                "start": _to_iso_date(week_start),
                "end": _to_iso_date(week_end),
                "format": "1",
                "resourceType": self._resource_type or "STUDENT",
                "resources": str(pid),
                "periodTypes": "",
                "timetableType": "MY_TIMETABLE",
                "layout": "START_TIME",
            })
            days.extend(res.get("days") or [])
        return {"days": days}

    async def get_own_classes(self) -> set[str]:
        """Short names of the classes the user belongs to (students only).

        Needed to tell "your class was removed from a lesson" apart from
        "another class was removed". Empty set if unknown.
        """
        if self._resource_type != "STUDENT":
            return set()
        pid, _ = self._require_person()
        res = await self._rest_get("/timetable/filter", {
            "resourceType": "STUDENT",
            "timetableType": "MY_TIMETABLE",
        })
        own: set[str] = set()
        for student in res.get("students") or []:
            if (student.get("student") or {}).get("id") != pid:
                continue
            for entry in student.get("classes") or []:
                name = (entry.get("class") or {}).get("shortName")
                if name:
                    own.add(name)
        return own

    async def get_timetable(self, start: date, end: date) -> list[dict]:
        """Timetable from JSON-RPC `getTimetable` (fallback path)."""
        pid, ptype = self._require_person()
        fields = ["id", "name", "longname"]
        all_lessons: list[dict] = []
        for week_start, week_end in _weeks(start, end):
            res = await self._rpc("getTimetable", {"options": {
                "element": {"id": pid, "type": ptype},
                "startDate": _to_untis_date(week_start),
                "endDate": _to_untis_date(week_end),
                "showInfo": True,
                "showSubstText": True,
                "showLsText": True,
                "klasseFields": fields,
                "roomFields": fields,
                "subjectFields": fields,
                "teacherFields": fields,
            }})
            all_lessons.extend(res or [])
        all_lessons.sort(key=lambda x: (x.get("date") or 0, x.get("startTime") or 0))
        return all_lessons

    async def get_exams(self, start: date, end: date) -> list[dict]:
        pid, _ = self._require_person()
        res = await self._api_get("/exams", {
            "startDate": _to_untis_date(start),
            "endDate": _to_untis_date(end),
            "studentId": pid,
            "klasseId": -1,
            "withGrades": "true",
        })
        return (res.get("data") or {}).get("exams") or []

    async def get_homework(self, start: date, end: date) -> list[dict]:
        """Homework items joined with their lesson/teacher lookups."""
        res = await self._api_get("/homeworks/lessons", {
            "startDate": _to_untis_date(start),
            "endDate": _to_untis_date(end),
        })
        data = res.get("data") or {}
        lessons = {x.get("id"): x for x in data.get("lessons") or []}
        teachers = {x.get("id"): x for x in data.get("teachers") or []}
        teacher_by_hw = {
            r.get("homeworkId"): teachers.get(r.get("teacherId"))
            for r in data.get("records") or []
        }
        out = []
        for hw in data.get("homeworks") or []:
            out.append({
                **hw,
                "lesson": lessons.get(hw.get("lessonId")),
                "teacher": teacher_by_hw.get(hw.get("id")),
            })
        return out

    async def get_absences(self, start: date, end: date) -> list[dict]:
        pid, _ = self._require_person()
        res = await self._api_get("/classreg/absences/students", {
            "startDate": _to_untis_date(start),
            "endDate": _to_untis_date(end),
            "studentId": pid,
            "excuseStatusId": -1,
        })
        return (res.get("data") or {}).get("absences") or []

    async def get_messages(self) -> list[dict]:
        res = await self._rest_get("/messages", {})
        return list(res.get("incomingMessages") or [])

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def _close_http(self, save: bool) -> None:
        if self._http is None:
            return
        try:
            if save:
                self._http.save_cookies()
        finally:
            await self._http.aclose()
            self._http = None

    async def close(self) -> None:
        await self._close_http(save=self._logged_in)
        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
            self._page = None
        self._logged_in = False

    @property
    def user_display(self) -> Optional[str]:
        return self._user_display or self.cfg.username
