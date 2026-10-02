"""Plain HTTP transport (no browser), used when it works.

Verified against a live UI2020 instance: with a valid session cookie,
every endpoint the scraper uses answers over plain HTTP, and the login
form endpoint (`j_spring_security_check`) isn't blocked by the WAF
either. Only the JSON-RPC `authenticate` method is, which isn't used.

Cookies are loaded from / saved to the same Playwright `storage_state`
file the browser uses, so both transports can pick up each other's
session.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import urlsplit

import httpx

from .config import ScraperConfig

log = logging.getLogger(__name__)

LOGIN_PATH = "/WebUntis/j_spring_security_check"

LoginOutcome = Literal["ok", "rejected", "unexpected"]


def _response_dict(r: httpx.Response) -> dict[str, Any]:
    """Same shape as the browser's fetch() helper returns."""
    raw = r.text
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        data = None
    return {"status": r.status_code, "ok": r.is_success, "data": data, "raw": raw}


class HttpTransport:
    def __init__(
        self,
        cfg: ScraperConfig,
        load_saved: bool = True,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.cfg = cfg
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": cfg.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": f"{cfg.locale},{cfg.locale.split('-')[0]};q=0.9",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=cfg.timeout_ms / 1000,
            # Not following redirects keeps "not logged in" visible: the
            # API answers with a 302 to the login page instead of data.
            follow_redirects=False,
            transport=transport,
        )
        if load_saved:
            self._load_cookies()

    # --- requests ------------------------------------------------------
    async def get(self, url: str, params: dict, token: Optional[str]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return _response_dict(await self._client.get(url, params=params, headers=headers))

    async def post_json(self, url: str, body: dict) -> dict[str, Any]:
        return _response_dict(await self._client.post(url, json=body))

    async def form_login(self, username: str, password: str) -> tuple[LoginOutcome, str]:
        """POST the login form like the web UI does.

        WebUntis answers with a redirect either way: to /WebUntis/index.do
        on success, back to /WebUntis/ when the credentials are rejected.
        Anything else (WAF, 2FA, SSO, errors) is "unexpected".
        """
        base = self.cfg.base_url
        # Fresh JSESSIONID / tenant cookies for the login itself.
        self._client.cookies.clear()
        await self._client.get(f"{base}/WebUntis/", params={"school": self.cfg.school})
        r = await self._client.post(
            f"{base}{LOGIN_PATH}",
            data={"school": self.cfg.school, "j_username": username,
                  "j_password": password, "token": ""},
            headers={"Origin": base, "Referer": f"{base}/WebUntis/?school={self.cfg.school}"},
        )
        location = urlsplit(r.headers.get("location", "")).path
        if r.is_redirect and location == "/WebUntis/index.do":
            return "ok", location
        if r.is_redirect and location.rstrip("/") == "/WebUntis":
            return "rejected", location
        return "unexpected", f"HTTP {r.status_code} {location or r.text[:120]!r}"

    # --- cookies -------------------------------------------------------
    def _load_cookies(self) -> None:
        path = Path(self.cfg.storage_state_path)
        if not path.exists():
            return
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.debug("Ignoring unreadable session file %s: %s", path, exc)
            return
        now = time.time()
        for c in state.get("cookies") or []:
            expires = c.get("expires", -1)
            if expires not in (-1, None) and expires < now:
                continue
            self._client.cookies.set(
                c["name"], c["value"], domain=c.get("domain", ""), path=c.get("path", "/"),
            )

    def save_cookies(self) -> None:
        """Write the cookies in Playwright's storage_state format (mode 600)."""
        path = Path(self.cfg.storage_state_path)
        origins: list = []
        try:
            origins = json.loads(path.read_text(encoding="utf-8")).get("origins") or []
        except (OSError, ValueError):
            pass
        cookies = [{
            "name": c.name,
            "value": c.value or "",
            "domain": c.domain,
            "path": c.path,
            "expires": float(c.expires) if c.expires else -1,
            "httpOnly": bool(c.has_nonstandard_attr("HttpOnly")),
            "secure": bool(c.secure),
            "sameSite": "Lax",
        } for c in self._client.cookies.jar]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"cookies": cookies, "origins": origins}, f)
        os.replace(tmp, path)
        log.debug("Saved %d cookies to %s", len(cookies), path)

    async def aclose(self) -> None:
        await self._client.aclose()
