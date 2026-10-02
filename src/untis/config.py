"""Configuration loader.

Reads settings from a JSON file and sensitive credentials from .env.
JSON keys mirror the env-style names for transparency.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from .privacy import ensure_private_dir, is_readable_by_others, make_private, tighten_dir

log = logging.getLogger(__name__)

def _project_root(module_file: Path) -> Path | None:
    """The repo checkout this module lives in (<root>/src/untis/config.py),
    or None when installed as a package (pip/pipx), where the "project
    folder" would be site-packages."""
    root = Path(module_file).resolve().parents[2]
    return root if (root / "pyproject.toml").exists() else None


def _xdg_dir(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback) / "untis"


def _pick_dirs(
    xdg_config: Path, xdg_data: Path, project_root: Path | None,
) -> tuple[Path, Path]:
    """(config dir, data dir).

    Normal use: config + .env in ~/.config/untis, sessions/out/logs in
    ~/.local/share/untis. Only a dev checkout without
    ~/.config/untis/config.json keeps everything in the project folder
    (handy for development and on Windows).
    """
    if project_root is None or (xdg_config / "config.json").exists():
        return xdg_config, xdg_data
    return project_root, project_root


PROJECT_ROOT = _project_root(Path(__file__))
XDG_CONFIG_DIR = _xdg_dir("XDG_CONFIG_HOME", ".config")
XDG_DATA_DIR = _xdg_dir("XDG_DATA_HOME", ".local/share")
CONFIG_DIR, DATA_DIR = _pick_dirs(XDG_CONFIG_DIR, XDG_DATA_DIR, PROJECT_ROOT)

DEFAULT_CONFIG_PATH = CONFIG_DIR / "config.json"
DEFAULT_ENV_PATH = CONFIG_DIR / ".env"
SESSIONS_DIR = DATA_DIR / "sessions"
OUT_DIR = DATA_DIR / "out"
LOGS_DIR = DATA_DIR / "logs"


TRANSPORTS = ("auto", "http", "browser")


class ConfigError(ValueError):
    """Raised when the configuration is missing or incomplete."""


@dataclass
class ScraperConfig:
    # WebUntis endpoints
    server: str = ""               # e.g. "mese"
    school: str = ""               # e.g. "htbla_kaindorf"
    base_url: str = ""             # derived
    login_url: str = ""            # derived

    # Credentials (sourced from .env)
    username: str = ""
    password: str = ""

    # Date range for timetable scraping
    days_back: int = 0
    days_forward: int = 14
    # Set by the CLI date shortcuts; override days_back/days_forward.
    start_date: date | None = None
    end_date: date | None = None
    pick_day: str | None = None    # "tomorrow" | "next": first school day
    # days_back/days_forward count school days; True = plain calendar days
    calendar_days: bool = False

    # Modules to enable
    scrape_timetable: bool = True
    scrape_exams: bool = True
    scrape_homework: bool = True
    scrape_absences: bool = True
    scrape_messages: bool = True

    # "auto": plain HTTP, browser only as fallback; "http"; "browser"
    transport: str = "auto"
    # Chromium's --no-sandbox etc. Only needed in some Docker/root setups;
    # enabled automatically when running as root.
    browser_no_sandbox: bool = False

    # Browser behaviour
    headless: bool = True
    slow_mo_ms: int = 0
    timeout_ms: int = 45000
    locale: str = "de-DE"
    timezone: str = "Europe/Berlin"
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    viewport: dict = field(
        default_factory=lambda: {"width": 1440, "height": 900}
    )

    # Output
    output_dir: str = str(OUT_DIR)
    pretty_json: bool = True
    include_raw: bool = False      # dump raw API responses

    # Storage state for session reuse
    storage_state_path: str = str(
        SESSIONS_DIR / "storage_state.json"
    )

    def derived_urls(self) -> None:
        if self.server and self.school:
            self.base_url = f"https://{self.server}.webuntis.com"
            self.login_url = (
                f"{self.base_url}/WebUntis/?school={self.school}"
                "#/basic/login"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            log.warning("Config file %s is not a JSON object, ignoring", path)
            return {}
        return data
    except json.JSONDecodeError as exc:
        log.error("Invalid JSON in %s: %s", path, exc)
        return {}


def _secure_data_dirs(cfg: ScraperConfig, env_path: Path) -> None:
    """Sessions, output and logs hold personal data: owner-only dirs
    (700) and files (600). Only our own sub-directories are touched, never
    the project folder itself or a custom output_dir chosen by the user."""
    for d in (SESSIONS_DIR, LOGS_DIR):
        ensure_private_dir(d)
        tighten_dir(d)
    out = Path(cfg.output_dir)
    if out.resolve() == OUT_DIR.resolve():
        ensure_private_dir(out)
        tighten_dir(out)
    else:
        out.mkdir(parents=True, exist_ok=True)
    make_private(Path(cfg.storage_state_path))
    if is_readable_by_others(env_path):
        log.warning("%s is readable by other users; run: chmod 600 %s", env_path, env_path)


def load_config(
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    env_path: Path | str = DEFAULT_ENV_PATH,
) -> ScraperConfig:
    """Build a ScraperConfig from config.json and .env.

    Priority: .env values override config.json values.
    """
    cfg = ScraperConfig()
    json_data = _load_json(Path(config_path))
    env_data = dotenv_values(Path(env_path)) if Path(env_path).exists() else {}

    # Map env-style names to the actual ScraperConfig field names so users
    # can use either UNTIS_PASSWORD (shell style) or password (config.json style).
    ENV_ALIASES = {
        "UNTIS_SERVER": "server",
        "UNTIS_SCHOOL": "school",
        "UNTIS_USERNAME": "username",
        "UNTIS_PASSWORD": "password",
    }

    for k, v in {**json_data, **env_data}.items():
        if v is None or v == "":
            continue
        # Resolve alias
        field_name = ENV_ALIASES.get(k, k)
        # boolean coercion
        if field_name in {
            "headless", "pretty_json", "include_raw",
            "scrape_timetable", "scrape_exams", "scrape_homework",
            "scrape_absences", "scrape_messages", "calendar_days",
            "browser_no_sandbox",
        }:
            current = getattr(cfg, field_name, False)
            setattr(cfg, field_name, _coerce_bool(v, current))
            continue
        if field_name in {"days_back", "days_forward", "slow_mo_ms", "timeout_ms"}:
            try:
                setattr(cfg, field_name, int(v))
                continue
            except (TypeError, ValueError):
                log.warning("Config key %s=%r is not an int, ignoring", k, v)
                continue
        if hasattr(cfg, field_name):
            setattr(cfg, field_name, v)
        else:
            log.debug("Unknown config key: %s", k)

    cfg.derived_urls()

    for key in ("days_back", "days_forward"):
        if getattr(cfg, key) < 0:
            raise ConfigError(f"{key} must be 0 or more, not {getattr(cfg, key)}")

    if cfg.transport not in TRANSPORTS:
        raise ConfigError(
            f"transport must be one of {', '.join(TRANSPORTS)}, not {cfg.transport!r}"
        )

    # A relative output_dir ("out") means relative to the data dir, not
    # to wherever the command happens to be run from.
    if not Path(cfg.output_dir).is_absolute():
        cfg.output_dir = str(DATA_DIR / cfg.output_dir)

    if not cfg.server or not cfg.school:
        raise ConfigError(
            f"server and school must be set in {config_path} or {env_path} "
            "(see config.example.json)"
        )

    if cfg.username and not cfg.password:
        log.warning(
            "Username is set (%r) but password is empty — "
            "check UNTIS_PASSWORD in .env",
            cfg.username,
        )
    elif cfg.password and not cfg.username:
        log.warning("Password is set but username is empty")

    _secure_data_dirs(cfg, Path(env_path))

    pw_set = bool(cfg.password)
    log.info(
        "Config loaded: server=%s school=%s user=%s password=%s "
        "days_back=%d days_forward=%d",
        cfg.server, cfg.school, cfg.username or "<empty>",
        "<set>" if pw_set else "<MISSING>",
        cfg.days_back, cfg.days_forward,
    )
    return cfg
