"""Command-line entry point."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

import httpx

from .browser import BrowserSession
from .config import (
    DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH, TRANSPORTS, ConfigError, load_config,
)
from .dates import parse_date, week_range
from .exporter import write_json, write_latest
from .scraper import Scraper
from .summary import render_summary
from .untis_client import LoginError, WebUntisClient, WebUntisError

# Exit codes, so scripts and status bars can tell failures apart.
EXIT_ERROR = 1      # unexpected error (bug)
EXIT_CONFIG = 2     # missing/invalid config or setup (e.g. no Chromium)
EXIT_LOGIN = 3      # could not log in
EXIT_NETWORK = 4    # WebUntis unreachable or returned an error
EXIT_ABORTED = 130  # Ctrl-C


def _setup_logging(verbose: bool, quiet: bool = False) -> None:
    level = logging.DEBUG if verbose else (logging.WARNING if quiet else logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet down playwright's chatty loggers unless in debug mode.
    if not verbose:
        for noisy in ("playwright", "pyee"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="untis",
        description="Scrape WebUntis data via Playwright (timetable, exams, "
                    "homework, absences, messages).",
        epilog=f"exit codes: {EXIT_ERROR} unexpected error, {EXIT_CONFIG} config/setup, "
               f"{EXIT_LOGIN} login failed, {EXIT_NETWORK} network/WebUntis error, "
               f"{EXIT_ABORTED} aborted",
    )
    ap.add_argument(
        "--config", default=str(DEFAULT_CONFIG_PATH),
        help=f"Path to config.json (default: {DEFAULT_CONFIG_PATH})",
    )
    ap.add_argument(
        "--env", default=str(DEFAULT_ENV_PATH),
        help=f"Path to .env file (default: {DEFAULT_ENV_PATH})",
    )
    ap.add_argument(
        "--no-headless", action="store_true",
        help="Run browser with a visible window (useful for first login / 2FA).",
    )
    ap.add_argument(
        "--form-login", action="store_true",
        help="Ignore the saved session and always log in through the form.",
    )
    ap.add_argument(
        "--transport", choices=TRANSPORTS, default=None,
        help="How to talk to WebUntis: 'auto' (default) uses plain HTTP and "
             "only starts a browser if that fails; 'http'; 'browser'.",
    )
    ap.add_argument(
        "--clear-session", action="store_true",
        help="Delete the saved storage_state and force a fresh login.",
    )
    ap.add_argument(
        "--keep-raw", action="store_true",
        help="Include raw API payloads in the output JSON.",
    )
    ap.add_argument(
        "--days-back", type=int, default=None,
        help="Override config: how many days in the past to scrape.",
    )
    ap.add_argument(
        "--days-forward", type=int, default=None,
        help="Override config: how many days in the future to scrape.",
    )
    when = ap.add_argument_group(
        "date shortcuts", "Pick the window directly (instead of --days-back/--days-forward).",
    ).add_mutually_exclusive_group()
    when.add_argument("--today", action="store_true", help="Only today.")
    when.add_argument(
        "--tomorrow", action="store_true",
        help="Tomorrow, or the next school day if tomorrow has no lessons.",
    )
    when.add_argument(
        "--next", action="store_true",
        help="Today while school isn't over yet, otherwise the next school day.",
    )
    when.add_argument("--week", action="store_true", help="This week (Mon-Sun).")
    when.add_argument("--next-week", action="store_true", help="Next week (Mon-Sun).")
    when.add_argument(
        "--date", type=_date_arg, metavar="DATE",
        help="A specific day: YYYY-MM-DD, DD.MM.YYYY or DD.MM.",
    )
    ap.add_argument(
        "-s", "--short", action="store_true",
        help="Print a compact per-day overview (JSON is still written).",
    )
    ap.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    args = ap.parse_args()
    shortcut = (args.today or args.tomorrow or args.next or args.week
                or args.next_week or args.date)
    if shortcut and (args.days_back is not None or args.days_forward is not None):
        ap.error("date shortcuts can't be combined with --days-back/--days-forward")
    return args


def _date_arg(text: str) -> date:
    try:
        return parse_date(text, date.today())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _apply_date_shortcuts(cfg, args: argparse.Namespace, today: date) -> None:
    if args.today:
        cfg.start_date = cfg.end_date = today
    elif args.date:
        cfg.start_date = cfg.end_date = args.date
    elif args.week or args.next_week:
        cfg.start_date, cfg.end_date = week_range(today, 1 if args.next_week else 0)
    elif args.tomorrow:
        cfg.pick_day = "tomorrow"
    elif args.next:
        cfg.pick_day = "next"


async def _async_main(args: argparse.Namespace) -> int:
    cfg = load_config(args.config, args.env)
    if args.no_headless:
        cfg.headless = False
    if args.keep_raw:
        cfg.include_raw = True
    if args.transport:
        cfg.transport = args.transport
    if args.days_back is not None:
        cfg.days_back = args.days_back
    if args.days_forward is not None:
        cfg.days_forward = args.days_forward
    _apply_date_shortcuts(cfg, args, date.today())

    async with BrowserSession(cfg, fresh=args.clear_session) as session:
        client = WebUntisClient(cfg, session)
        try:
            await client.login(force=args.form_login)
            scraper = Scraper(cfg, client)
            payload = await scraper.run()
        finally:
            await client.close()

    write_json(
        payload,
        cfg.output_dir,
        pretty=cfg.pretty_json,
        keep_raw=cfg.include_raw,
    )
    write_latest(
        payload,
        cfg.output_dir,
        keep_raw=cfg.include_raw,
    )
    if args.short:
        print(render_summary(payload))
    return 0


def _describe_error(exc: BaseException, args: argparse.Namespace) -> tuple[int, str]:
    """Map an exception to (exit code, one-line message)."""
    first_line = (str(exc).strip().splitlines() or [""])[0]
    if isinstance(exc, ConfigError):
        return EXIT_CONFIG, f"config error: {exc}"
    if isinstance(exc, LoginError):
        return EXIT_LOGIN, (f"login failed: {exc} "
                            f"(username: {args.config}, password: {args.env})")
    if isinstance(exc, WebUntisError):
        return EXIT_NETWORK, f"WebUntis error: {exc}"
    if isinstance(exc, httpx.TransportError):
        return EXIT_NETWORK, f"could not reach WebUntis: {type(exc).__name__}: {first_line}"
    from playwright.async_api import Error as PlaywrightError   # lazy: slow import
    if isinstance(exc, PlaywrightError):
        if "Executable doesn't exist" in str(exc):
            return EXIT_CONFIG, ("Chromium is not installed for Playwright; "
                                 "run: .venv/bin/playwright install chromium")
        return EXIT_NETWORK, f"could not reach WebUntis: {first_line}"
    return EXIT_ERROR, (f"unexpected error: {type(exc).__name__}: {first_line} "
                        "(run with -v for the full traceback)")


def main() -> int:
    args = _parse_args()
    _setup_logging(args.verbose, quiet=args.short)
    try:
        return asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        print("\nAborted by user", file=sys.stderr)
        return EXIT_ABORTED
    except Exception as exc:
        if args.verbose:
            logging.exception("Fatal error")
        code, message = _describe_error(exc, args)
        print(f"untis: {message}", file=sys.stderr)
        return code


if __name__ == "__main__":
    sys.exit(main())
