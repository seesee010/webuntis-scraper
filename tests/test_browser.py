"""Tests for BrowserSession's storage_state handling (no real browser)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src import browser as browser_mod
from src.browser import BrowserSession
from src.config import ScraperConfig


@pytest.fixture
def fake_playwright(monkeypatch) -> MagicMock:
    """Patch async_playwright() and return the fake browser."""
    context = MagicMock()
    context.storage_state = AsyncMock()
    context.close = AsyncMock()
    fake_browser = MagicMock()
    fake_browser.new_context = AsyncMock(return_value=context)
    fake_browser.close = AsyncMock()
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=fake_browser)
    pw.stop = AsyncMock()
    starter = MagicMock()
    starter.start = AsyncMock(return_value=pw)
    monkeypatch.setattr(browser_mod, "async_playwright", lambda: starter)
    return fake_browser


@pytest.fixture
def cfg(tmp_path: Path) -> ScraperConfig:
    state = tmp_path / "storage_state.json"
    state.write_text('{"cookies": [], "origins": []}')
    return ScraperConfig(server="s", school="sc", storage_state_path=str(state))


def _patch_stealth(session: BrowserSession) -> None:
    session.stealth = MagicMock()
    session.stealth.apply_stealth_async = AsyncMock()


async def test_reuses_saved_session(cfg, fake_playwright):
    session = BrowserSession(cfg)
    _patch_stealth(session)
    async with session:
        await session.start()
    kwargs = fake_playwright.new_context.call_args.kwargs
    assert kwargs["storage_state"] == Path(cfg.storage_state_path)


async def test_fresh_deletes_state_before_context(cfg, fake_playwright):
    state = Path(cfg.storage_state_path)

    async def new_context(**kwargs):
        # The file must already be gone when the context is created.
        assert not state.exists()
        return fake_playwright.new_context.return_value
    fake_playwright.new_context.side_effect = new_context

    session = BrowserSession(cfg, fresh=True)
    _patch_stealth(session)
    async with session:
        await session.start()
    assert fake_playwright.new_context.call_args.kwargs["storage_state"] is None


async def test_fresh_without_saved_state(cfg, fake_playwright):
    Path(cfg.storage_state_path).unlink()
    session = BrowserSession(cfg, fresh=True)
    _patch_stealth(session)
    async with session:
        await session.start()
    assert fake_playwright.new_context.call_args.kwargs["storage_state"] is None


async def test_entering_does_not_launch_browser(cfg, fake_playwright):
    session = BrowserSession(cfg)
    _patch_stealth(session)
    async with session:
        assert not session.started
    fake_playwright.new_context.assert_not_called()


async def test_fresh_deletes_state_even_without_browser(cfg, fake_playwright):
    async with BrowserSession(cfg, fresh=True):
        assert not Path(cfg.storage_state_path).exists()
