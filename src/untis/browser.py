"""Browser setup with playwright-stealth.

Builds a Chromium context configured to look like a real user,
applies stealth evasions, and reuses storage_state when available
so we don't have to log in every run.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .config import ScraperConfig

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright
    from playwright_stealth import Stealth

log = logging.getLogger(__name__)


def async_playwright():
    """Import Playwright lazily: it takes ~0.5 s to import and is only
    needed when the browser transport is actually used."""
    from playwright.async_api import async_playwright as _async_playwright
    return _async_playwright()


def _build_stealth() -> Stealth:
    """Create a Stealth instance with sensible defaults for WebUntis.

    chrome.runtime is left disabled (default in v2.x) because some
    enterprise Single-Sign-On flows probe chrome.runtime and the
    patched shim can break them.
    """
    from playwright_stealth import Stealth
    return Stealth(
        navigator_languages_override=("de-DE", "de", "en-US", "en"),
    )


class BrowserSession:
    """Context manager wrapping a stealthy Playwright Chromium session."""

    def __init__(self, cfg: ScraperConfig, fresh: bool = False):
        """`fresh=True` discards the saved session before the browser
        context is created, forcing a new login."""
        self.cfg = cfg
        self.fresh = fresh
        self._pw: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.stealth: Optional[Stealth] = None   # built on start()

    async def __aenter__(self) -> "BrowserSession":
        state_path = Path(self.cfg.storage_state_path)
        if self.fresh and state_path.exists():
            # Must happen before anything loads the cookies; otherwise
            # deleting the file has no effect (and they'd be written back).
            state_path.unlink()
            log.info("Cleared saved session %s", state_path)
        return self

    @property
    def started(self) -> bool:
        return self.context is not None

    async def start(self) -> None:
        """Launch Chromium. Lazy, because the HTTP transport usually
        doesn't need a browser at all."""
        if self.started:
            return
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(
            headless=self.cfg.headless,
            slow_mo=self.cfg.slow_mo_ms,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )

        state_path = Path(self.cfg.storage_state_path)
        storage_state = state_path if state_path.exists() else None

        self.context = await self.browser.new_context(
            viewport=self.cfg.viewport,
            user_agent=self.cfg.user_agent,
            locale=self.cfg.locale,
            timezone_id=self.cfg.timezone,
            color_scheme="light",
            java_script_enabled=True,
            storage_state=storage_state,
        )
        if self.stealth is None:
            self.stealth = _build_stealth()
        await self.stealth.apply_stealth_async(self.context)
        log.info(
            "Browser ready (headless=%s, storage_state=%s)",
            self.cfg.headless, "yes" if storage_state else "no",
        )

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if self.context and self.cfg.storage_state_path:
                await self.context.storage_state(path=self.cfg.storage_state_path)
                log.debug("Saved storage_state to %s", self.cfg.storage_state_path)
        finally:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self._pw:
                await self._pw.stop()

    async def new_page(self) -> Page:
        await self.start()
        assert self.context is not None
        page = await self.context.new_page()
        page.set_default_timeout(self.cfg.timeout_ms)
        return page
