"""Shared pytest config. `untis` is importable via `pythonpath = ["src"]`
in pyproject.toml, so no sys.path tweaks are needed here."""
from __future__ import annotations

import pytest

from untis import config as config_mod

# Kept for the tests of the function itself (tests/test_privacy.py).
REAL_SECURE_DATA_DIRS = config_mod._secure_data_dirs


@pytest.fixture(autouse=True)
def _never_touch_real_data_dirs(monkeypatch):
    """load_config() creates and chmods ~/.local/share/untis/{sessions,out,logs}.
    Tests must never touch the real user's data, so that step is a no-op
    in every test."""
    monkeypatch.setattr(config_mod, "_secure_data_dirs", lambda cfg, env_path: None)
