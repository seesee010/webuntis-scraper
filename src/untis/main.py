"""Command-line entry point."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import logging
import os
import shlex
import sys
from datetime import date, datetime
from pathlib import Path

import httpx

from . import __version__, absences, cache, changes, dayinfo, live, setup_wizard
from . import now as now_mod
from .browser import BrowserSession
from .config import (
    CACHE_PATH,
    CHANGES_PATH,
    DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH, TRANSPORTS, ConfigError, load_config, parse_keep,
)
from .dates import parse_date, parse_day_spec, resolve_from_to, week_range
from .exporter import dump_json, export
from .scraper import Scraper
from .summary import (
    render_homework, render_legend, render_summary, render_tests, resolve_color,
)
from .untis_client import LoginError, WebUntisClient, WebUntisError

# Exit codes, so scripts and status bars can tell failures apart.
EXIT_ERROR = 1      # unexpected error (bug)
EXIT_CONFIG = 2     # missing/invalid config or setup (e.g. no Chromium)
EXIT_LOGIN = 3      # could not log in
EXIT_NETWORK = 4    # WebUntis unreachable or returned an error
EXIT_NO_SCHOOL = 5  # --start/--end/--free: no lessons that day
EXIT_CHANGES = 10   # --changes: something changed since the last run
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


# Options that pick the date window. An explicit one replaces all of them
# from default_args (instead of clashing with e.g. a default --today).
WINDOW_DESTS = ("today", "tomorrow", "next", "week", "next_week", "date",
                "from_", "to", "days_back", "days_forward", "start_q", "end_q", "free_q",
                "now")
# These make no sense as defaults (they decide where defaults come from,
# or print something and exit).
NOT_IN_DEFAULTS = ("--config", "--env", "-h", "--help", "-V", "--version", "--live")
# Options with their own output, which "--json -" replaces: from
# default_args they are dropped, given explicitly they are an error.
JSON_STDOUT_CONFLICTS = ("short", "oneline", "table", "legend", "now",
                         "start_q", "end_q", "free_q", "changes", "notify")


class DefaultArgsError(Exception):
    """Invalid default_args (config.json or UNTIS_DEFAULT_ARGS)."""


class _RaisingParser(argparse.ArgumentParser):
    """Parses default_args: errors are raised instead of printed + exit,
    so they can be reported together with where the defaults came from."""

    def error(self, message: str):
        raise DefaultArgsError(message)


def _build_parser(cls: type = argparse.ArgumentParser, suppress: bool = False):
    """The CLI parser. With `suppress`, options that weren't given are
    left out of the namespace, which shows what was given explicitly."""
    def dflt(value):
        return {} if suppress else {"default": value}

    ap = cls(
        prog="untis",
        description="Your WebUntis timetable, exams, homework, absences and "
                    "messages in the terminal (plain HTTP, Playwright as a fallback).",
        epilog=f"exit codes: {EXIT_ERROR} unexpected error, {EXIT_CONFIG} config/setup, "
               f"{EXIT_LOGIN} login failed, {EXIT_NETWORK} network/WebUntis error, "
               f"{EXIT_NO_SCHOOL} no school that day (--start/--end/--free), "
               f"{EXIT_CHANGES} changes found (--changes), "
               f"{EXIT_ABORTED} aborted. Default arguments can be set as "
               f"\"default_args\" in config.json (e.g. [\"--short\"]) or in "
               f"UNTIS_DEFAULT_ARGS; explicit options win, flags can be turned "
               f"off with --no-<flag>.",
        argument_default=argparse.SUPPRESS if suppress else None,
    )
    ap.add_argument(
        "-V", "--version", action="version", version=f"untis {__version__}",
    )
    ap.add_argument(
        "--config", **dflt(str(DEFAULT_CONFIG_PATH)),
        help=f"Path to config.json (default: {DEFAULT_CONFIG_PATH})",
    )
    ap.add_argument(
        "--env", **dflt(str(DEFAULT_ENV_PATH)),
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
        "--transport", choices=TRANSPORTS, **dflt(None),
        help="How to talk to WebUntis: 'auto' (default) uses plain HTTP and "
             "only starts a browser if that fails; 'http'; 'browser'.",
    )
    ap.add_argument(
        "--clear-session", action="store_true",
        help="Delete the saved storage_state and force a fresh login.",
    )
    ap.add_argument(
        "--keep-raw", action=argparse.BooleanOptionalAction, **dflt(False),
        help="Include raw API payloads in the output JSON.",
    )
    ap.add_argument(
        "--json", nargs="?", const=True, type=_json_target_arg, **dflt(None), metavar="-",
        help="Write out/untis_<timestamp>.json and out/latest.json (the default, "
             "unless \"write_json\": false in config.json). '--json -' prints the "
             "JSON to stdout instead of writing files, e.g. for jq.",
    )
    ap.add_argument(
        "--no-json", dest="json", action="store_const", const=False,
        help="Don't write any JSON files.",
    )
    ap.add_argument(
        "--keep", type=_keep_arg, **dflt(None), metavar="N",
        help="Only keep the newest N out/untis_<timestamp>.json files; 0 writes "
             "only latest.json, 'all' never deletes (default from config: 20).",
    )
    ap.add_argument(
        "--days-back", type=_non_negative_int, **dflt(None), metavar="N",
        help="Also show the previous N school days (default from config: 0).",
    )
    ap.add_argument(
        "--days-forward", type=_non_negative_int, **dflt(None), metavar="N",
        help="Show today plus the next N school days (default from config: 14). "
             "Weekends and holidays don't count.",
    )
    ap.add_argument(
        "--calendar-days", action=argparse.BooleanOptionalAction, **dflt(False),
        help="Count --days-back/--days-forward in calendar days instead of school days.",
    )
    dates_group = ap.add_argument_group(
        "date shortcuts", "Pick the window directly (instead of --days-back/--days-forward).",
    )
    when = dates_group.add_mutually_exclusive_group()
    when.add_argument("--today", action="store_true", help="Only today.")
    when.add_argument(
        "--tomorrow", action="store_true",
        help="Tomorrow, or the next school day if tomorrow has no lessons.",
    )
    when.add_argument(
        "--next", action="store_true",
        help="Today while school isn't over yet, otherwise the next school day.",
    )
    when.add_argument("--week", action="store_true", help="This school week (Mon-Fri, like --from mon --to fri).")
    when.add_argument("--next-week", action="store_true", help="Next school week (Mon-Fri).")
    when.add_argument(
        "--date", type=_date_arg, metavar="DATE",
        help="A specific day: YYYY-MM-DD, DD.MM.YYYY or DD.MM.",
    )
    dates_group.add_argument(
        "--from", dest="from_", type=_day_spec_arg, metavar="DAY",
        help="Start of the window: a date, today/tomorrow, or a weekday "
             "(mon..sun, mo..so; this week).",
    )
    dates_group.add_argument(
        "--to", type=_day_spec_arg, metavar="DAY",
        help="End of the window (same formats). A weekday that would be before "
             "--from means next week's. Without --from: from today.",
    )
    ap.add_argument(
        "-s", "--short", action=argparse.BooleanOptionalAction, **dflt(False),
        help="Print a compact per-day overview (JSON is still written, unless --no-json).",
    )
    ask = ap.add_argument_group(
        "questions", "Answer one question about a day (DAY: today (default), "
                     "tomorrow, next, a date or a weekday) and print only that.",
    ).add_mutually_exclusive_group()
    for flag, what in (("--start", "When does school start"),
                       ("--end", "When does school end"),
                       ("--free", "Free periods between lessons")):
        ask.add_argument(
            flag, dest=f"{flag[2:]}_q", nargs="?", const="today", type=_query_day_arg,
            metavar="DAY", **dflt(None),
            help=f"{what} on DAY? Cancelled/removed lessons don't count.",
        )
    ap.add_argument(
        "--format", choices=("text", "json", "waybar"), **dflt("text"),
        help="Answer format for --start/--end/--free and --now; 'waybar' "
             "(only with --now) prints a Waybar custom-module JSON.",
    )
    ap.add_argument(
        "--now", action=argparse.BooleanOptionalAction, **dflt(False),
        help="Show the current and the next lesson (the next school day's first "
             "lesson after school). Use --max-age for status bars.",
    )
    ap.add_argument(
        "--changes", action=argparse.BooleanOptionalAction, **dflt(False),
        help="Only print what changed since the last --changes run (cancellations, "
             "substitutions, room changes, new exams/homework); exit code 10 if anything did.",
    )
    ap.add_argument(
        "--notify", action=argparse.BooleanOptionalAction, **dflt(False),
        help="With --changes: also send each change as a desktop notification.",
    )
    ap.add_argument(
        "--live", nargs="?", const=live.DEFAULT_INTERVAL, type=_live_interval_arg,
        **dflt(None), metavar="INTERVAL",
        help=f"Keep running and redraw the output every INTERVAL (default "
             f"{live.DEFAULT_INTERVAL}, at least {live.MIN_INTERVAL}s) until Ctrl-C. "
             f"Without a view option it shows the -s overview; with --format "
             f"json/waybar one line is printed per refresh.",
    )
    ap.add_argument(
        "--idle-empty", action=argparse.BooleanOptionalAction, **dflt(False),
        help="With --now: print nothing (Waybar: empty text) when no lesson is "
             "running, so a status bar module hides.",
    )
    ap.add_argument(
        "-t", "--tests", "--exams", dest="tests", action=argparse.BooleanOptionalAction,
        **dflt(False),
        help="Only show tests/exams: all upcoming ones until the end of the school "
             "year, or those in the window given with --days-forward, --from, ….",
    )
    ap.add_argument(
        "-H", "--homework", action=argparse.BooleanOptionalAction, **dflt(False),
        help="Only show homework: all of this school year, or those due in the window "
             "given with --days-forward, --from, …. Combinable with --tests.",
    )
    ap.add_argument(
        "-A", "--absences", action=argparse.BooleanOptionalAction, **dflt(False),
        help="Only show absences with totals (days, lessons, not excused): all of "
             "this school year, or those in the window given with --days-back, --from, …. "
             "Combinable with --tests and --homework.",
    )
    ap.add_argument(
        "--oneline", action=argparse.BooleanOptionalAction, **dflt(False),
        help="Print one line per day instead of the day view "
             "(* changed, ~X~ cancelled/removed, ! exam).",
    )
    ap.add_argument(
        "--table", action=argparse.BooleanOptionalAction, **dflt(False),
        help="Print a week grid (days as columns, periods as rows) instead of the day view.",
    )
    ap.add_argument(
        "--color", choices=("auto", "always", "never"), **dflt("auto"),
        help="Colors in the day view: 'auto' (default: only on a terminal, "
             "respects NO_COLOR), 'always' (e.g. for less -R) or 'never'.",
    )
    ap.add_argument(
        "--legend", action=argparse.BooleanOptionalAction, **dflt(False),
        help="Print what the colors and markers in the day view mean.",
    )
    ap.add_argument(
        "--offline", action=argparse.BooleanOptionalAction, **dflt(False),
        help="Never fetch: answer from the data cached by the last run.",
    )
    ap.add_argument(
        "--max-age", type=_duration_arg, **dflt(None), metavar="DURATION",
        help="Use the cached data if it's younger than this (e.g. 90s, 10m, 2h) "
             "and covers the request; otherwise fetch.",
    )
    ap.add_argument("-v", "--verbose", action=argparse.BooleanOptionalAction, **dflt(False),
                    help="Debug logging.")
    return ap


def _load_default_args(argv: list[str]) -> tuple[list[str], str]:
    """default_args and where they come from: UNTIS_DEFAULT_ARGS wins
    over "default_args" in the config file (--config is honoured).
    A string is split shell-style; a list is used as is."""
    env = os.environ.get("UNTIS_DEFAULT_ARGS")
    if env is not None:
        return shlex.split(env), "UNTIS_DEFAULT_ARGS"
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    path = Path(pre.parse_known_args(argv)[0].config)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], str(path)            # load_config() reports a broken config
    raw = data.get("default_args") if isinstance(data, dict) else None
    if raw is None:
        return [], str(path)
    if isinstance(raw, str):
        return shlex.split(raw), str(path)
    if isinstance(raw, list) and all(isinstance(x, str) for x in raw):
        return list(raw), str(path)
    raise DefaultArgsError(f"\"default_args\" in {path} must be a list of strings or a string")


def _parse_args(
    argv: list[str] | None = None, today: date | None = None,
    default_args: list[str] | None = None,
) -> argparse.Namespace:
    """Parse default_args and the explicit arguments separately, then
    merge them: explicit options win, and an explicit date window replaces
    the default one. `argv`/`today`/`default_args` are set in tests."""
    argv = sys.argv[1:] if argv is None else list(argv)
    today = today or date.today()
    ap = _build_parser()
    source = "default_args"
    if default_args is None:
        try:
            default_args, source = _load_default_args(argv)
        except DefaultArgsError as exc:
            ap.error(str(exc))
    for arg in default_args:
        if arg.split("=", 1)[0] in NOT_IN_DEFAULTS:
            ap.error(f"default_args ({source}): {arg} can't be used there")
    try:
        merged = vars(_build_parser(_RaisingParser).parse_args(default_args))
    except DefaultArgsError as exc:
        ap.error(f"default_args ({source}): {exc}")
    explicit = vars(_build_parser(suppress=True).parse_args(argv))
    if set(explicit) & set(WINDOW_DESTS):
        plain = vars(ap.parse_args([]))
        for dest in WINDOW_DESTS:
            merged[dest] = plain[dest]
    merged.update(explicit)
    if merged["json"] == "-":
        given = [d for d in JSON_STDOUT_CONFLICTS if explicit.get(d) not in (None, False)]
        if given or "live" in explicit:
            ap.error("--json - can't be combined with -s, --oneline, --table, --legend, "
                     "--start/--end/--free, --now, --changes or --live")
        plain = vars(ap.parse_args([]))
        for dest in JSON_STDOUT_CONFLICTS:
            merged[dest] = plain[dest]
    args = argparse.Namespace(**merged)
    args.default_args, args.defaults_source = default_args, source

    shortcut = (args.today or args.tomorrow or args.next or args.week
                or args.next_week or args.date)
    from_to = args.from_ is not None or args.to is not None
    days = args.days_back is not None or args.days_forward is not None
    if (shortcut or from_to) and days:
        ap.error("date shortcuts can't be combined with --days-back/--days-forward")
    if from_to and shortcut:
        ap.error("--from/--to can't be combined with other date shortcuts")
    if args.oneline and args.table:
        ap.error("--oneline and --table can't be combined")
    args.query = next(((what, getattr(args, f"{what}_q")) for what in ("start", "end", "free")
                       if getattr(args, f"{what}_q") is not None), None)
    if args.query and (shortcut or from_to or days):
        ap.error("--start/--end/--free can't be combined with other date options")
    # --tests/--homework/--absences: only these sections instead of the day view.
    args.sections = bool(args.tests or args.homework or args.absences)
    if args.sections and (args.query or args.oneline or args.table):
        ap.error("--tests/--homework/--absences can't be combined with --start/--end/--free, "
                 "--oneline or --table")
    args.window_given = bool(shortcut or from_to or days)
    if args.now and (args.window_given or args.query or args.sections
                     or args.oneline or args.table):
        ap.error("--now can't be combined with date options, questions, --tests, "
                 "--homework, --absences, --oneline or --table")
    if args.format == "waybar" and not args.now:
        ap.error("--format waybar only works with --now")
    if args.changes and (args.query or args.now or args.sections
                         or args.oneline or args.table):
        ap.error("--changes can't be combined with questions, --now, --tests, "
                 "--homework, --absences, --oneline or --table")
    if args.notify and not args.changes:
        ap.error("--notify only works with --changes")
    if args.live is not None and args.changes:
        ap.error("--live can't be combined with --changes (use the systemd timer instead)")
    if args.live is not None and not (_layout(args) or args.query or args.now
                                      or args.sections):
        args.short = True                # otherwise there would be nothing to redraw
    args.window = None
    if from_to:
        try:
            args.window = resolve_from_to(args.from_, args.to, today)
        except ValueError as exc:
            ap.error(str(exc))
    return args


def _layout(args: argparse.Namespace) -> str | None:
    """Which terminal view to print: "oneline", "table", "days" (-s) or none."""
    if args.oneline:
        return "oneline"
    if args.table:
        return "table"
    return "days" if args.short else None


def _non_negative_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return value


def _duration_arg(text: str) -> int:
    try:
        return cache.parse_duration(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _live_interval_arg(text: str) -> int:
    try:
        return live.parse_interval(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _json_target_arg(text: str) -> str:
    """argparse type for --json's optional value: only "-" (stdout)."""
    if text != "-":
        raise argparse.ArgumentTypeError(
            f"only '-' (stdout) is supported, not {text!r}; files always go to output_dir")
    return text


def _keep_arg(text: str) -> int | str:
    """argparse type for --keep: a number, or "all" as is (None would
    look like "not given")."""
    try:
        n = parse_keep(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None
    return "all" if n is None else n


def _query_day_arg(text: str) -> str:
    """argparse type for --start/--end/--free DAY (syntax check only)."""
    try:
        dayinfo.query_day(text, date.today())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None
    return text


def _day_spec_arg(text: str) -> str:
    """argparse type for --from/--to: validate the syntax early (the window
    itself is resolved after parsing, when both values are known)."""
    try:
        parse_day_spec(text, date.today())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None
    return text


def _date_arg(text: str) -> date:
    try:
        return parse_date(text, date.today())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _apply_date_shortcuts(cfg, args: argparse.Namespace, today: date) -> None:
    if getattr(args, "window", None):
        cfg.start_date, cfg.end_date = args.window
    elif args.today:
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
    if args.calendar_days:
        cfg.calendar_days = True
    if args.keep is not None:
        cfg.keep_json = parse_keep(args.keep)
    today, now = date.today(), datetime.now()
    _apply_date_shortcuts(cfg, args, today)
    if args.query:
        return await _answer_question(cfg, args, today, now)
    if args.now:
        return await _answer_now(cfg, args, today, now)
    if args.changes:
        return await _answer_changes(cfg, args, today, now)
    if args.sections:
        _only_sections(cfg, args)

    payload, fetched = await _get_payload(cfg, args, today, now)
    if args.json == "-":
        print(dump_json(payload, pretty=cfg.pretty_json, keep_raw=cfg.include_raw))
        return 0
    if fetched and (cfg.write_json if args.json is None else args.json):
        # --live would write a file every refresh: only latest.json there.
        keep = 0 if args.live is not None else cfg.keep_json
        export(payload, cfg.output_dir, pretty=cfg.pretty_json,
               keep_raw=cfg.include_raw, keep=keep)
    color = resolve_color(args.color)
    layout = _layout(args)
    if args.sections:
        parts = []
        if args.tests:
            # Homework/absences start at the school year's beginning; tests
            # still only show the upcoming ones then.
            parts.append(render_tests(payload, color=color, today=today, now=now,
                                      upcoming_only=(args.homework or args.absences)
                                      and not args.window_given))
        if args.homework:
            parts.append(render_homework(payload, color=color, today=today, now=now))
        if args.absences:
            parts.append(absences.render_absences(payload, color=color, today=today, now=now))
        print("\n\n".join(parts))
    elif layout:
        print(render_summary(payload, color=color, layout=layout))
    if args.legend:
        print(("\n" if layout else "") + render_legend(color))
    return 0


def _only_sections(cfg, args: argparse.Namespace) -> None:
    """--tests/--homework/--absences: fetch only those modules. Without a
    window on the command line: tests from today, homework and absences
    from the start of the school year, all until its end (config
    days_forward is meant for the day view and is ignored). Homework is
    always kept by due date."""
    cfg.scrape_timetable = cfg.scrape_messages = False
    cfg.scrape_exams = bool(args.tests)
    cfg.scrape_homework = bool(args.homework)
    cfg.scrape_absences = bool(args.absences)
    cfg.homework_by_due_date = bool(args.homework)
    if not args.window_given:
        cfg.until_school_year_end = True
        cfg.from_school_year_start = bool(args.homework or args.absences)


async def _get_payload(cfg, args: argparse.Namespace, today: date, now: datetime) -> tuple[dict, bool]:
    """(payload, fetched): from the cache if allowed and possible, else
    fetched (and then saved to the cache)."""
    if args.offline or args.max_age is not None:
        payload = _from_cache(cfg, args, today, now)
        if payload is not None:
            return payload, False
    payload = await _fetch(cfg, args)
    cache.save(CACHE_PATH, payload, cfg, datetime.now())
    return payload, True


async def _answer_question(cfg, args: argparse.Namespace, today: date, now: datetime) -> int:
    """--start/--end/--free: print only the answer (no JSON files written)."""
    what, spec = args.query
    day = dayinfo.query_day(spec, today)
    cfg.start_date = cfg.end_date = cfg.pick_day = None
    if day == "next":
        cfg.pick_day = "next"
    else:
        cfg.start_date = cfg.end_date = day
    cfg.scrape_exams = cfg.scrape_homework = cfg.scrape_absences = cfg.scrape_messages = False
    payload, _ = await _get_payload(cfg, args, today, now)
    timetable = payload.get("timetable") or {}
    if "error" in timetable:
        raise WebUntisError(f"timetable: {timetable['error']}")
    target = date.fromisoformat(((payload.get("meta") or {}).get("window") or {}).get("start")
                                or today.isoformat())
    info = dayinfo.day_info(timetable, target)
    if args.format == "json":
        print(json.dumps(info or {"date": target.isoformat(), "start": None, "end": None,
                                  "first": None, "free": []}, ensure_ascii=False))
    else:
        answer = dayinfo.format_answer(info, what)
        if answer:
            print(answer)
    return EXIT_NO_SCHOOL if info is None else 0


async def _answer_now(cfg, args: argparse.Namespace, today: date, now: datetime) -> int:
    """--now: the current and next lesson in text, json or waybar format."""
    cfg.start_date = cfg.end_date = None
    cfg.pick_day = "next"
    cfg.scrape_exams = cfg.scrape_homework = cfg.scrape_absences = cfg.scrape_messages = False
    payload, _ = await _get_payload(cfg, args, today, now)
    timetable = payload.get("timetable") or {}
    if "error" in timetable:
        raise WebUntisError(f"timetable: {timetable['error']}")
    out, data = now_mod.answer(payload, args.format, today, now, idle_empty=args.idle_empty)
    if args.format == "waybar":
        print(out)                       # always valid JSON for the bar
        return 0
    if not now_mod.has_anything(data):
        print(out if args.format == "json" else "-")
        return EXIT_NO_SCHOOL
    if out:
        print(out)
    return 0


async def _answer_changes(cfg, args: argparse.Namespace, today: date, now: datetime) -> int:
    """--changes: compare with the snapshot of the last --changes run."""
    cfg.scrape_absences = cfg.scrape_messages = False
    payload, _ = await _get_payload(cfg, args, today, now)
    timetable = payload.get("timetable") or {}
    if "error" in timetable:
        raise WebUntisError(f"timetable: {timetable['error']}")
    new = changes.snapshot(payload, cache.account_key(cfg), datetime.now())
    old = changes.load(CHANGES_PATH)
    changes.save(CHANGES_PATH, new)
    if old is None or old.get("account") != new["account"]:
        print("No earlier snapshot yet; saved the current state for the next --changes run.")
        return 0
    found = changes.diff(old, new)
    if not found:
        print(f"No changes since {old['saved_at'].replace('T', ' ')[:16]}.")
        return 0
    for c in found:
        print(changes.format_change(c))
    if args.notify:
        changes.notify(found)
    return EXIT_CHANGES


# Errors that won't go away by retrying: stop --live instead of looping
# (repeated failed logins could also lock the account).
LIVE_FATAL = (EXIT_CONFIG, EXIT_LOGIN)


async def _live_loop(args: argparse.Namespace, out=None, now=datetime.now,
                     sleep=asyncio.sleep, rounds: int | None = None) -> int:
    """--live: rerun the normal output every args.live seconds. A failed
    refresh keeps the last output and shows the error; config and login
    errors end the loop. `out`/`now`/`sleep`/`rounds` are set in tests."""
    out = out or sys.stdout
    machine = args.format in ("json", "waybar")
    clear = not machine and out.isatty()
    # Each refresh is printed into a buffer, so "--color auto" must be
    # decided here, against the real output.
    args.color = live.color_mode(args.color, out.isatty(), os.environ)
    body, updated, done = "", None, 0
    while True:
        buf, error = io.StringIO(), None
        try:
            with contextlib.redirect_stdout(buf):
                await _async_main(args)
            body, updated = buf.getvalue(), now()
        except Exception as exc:
            if args.verbose:
                logging.exception("Refresh failed")
            code, error = _describe_error(exc, args)
            if code in LIVE_FATAL:
                print(f"untis: {error}", file=sys.stderr)
                return code
        # Only the first round may force a new login/session.
        args.clear_session = args.form_login = False
        if machine:
            if error:
                print(f"untis: {error}", file=sys.stderr)
            else:
                out.write(body if body.endswith("\n") else body + "\n")
        else:
            out.write(live.frame(body, live.footer(updated, args.live, now(), error), clear))
        out.flush()
        done += 1
        if rounds is not None and done >= rounds:
            return 0
        await sleep(args.live)


async def _fetch(cfg, args: argparse.Namespace) -> dict:
    async with BrowserSession(cfg, fresh=args.clear_session) as session:
        client = WebUntisClient(cfg, session)
        try:
            await client.login(force=args.form_login)
            return await Scraper(cfg, client).run()
        finally:
            await client.close()


def _from_cache(cfg, args: argparse.Namespace, today: date, now: datetime) -> dict | None:
    """The payload from the cache, or None to fetch. With --offline a
    cache miss is an error instead (nothing may be fetched)."""
    entry = cache.load(CACHE_PATH)
    try:
        if entry is None:
            raise cache.CacheMiss("no cached data yet; run untis once without --offline")
        return cache.from_cache(cfg, entry, today, now,
                                None if args.offline else args.max_age)
    except cache.CacheMiss as exc:
        if args.offline:
            raise
        logging.getLogger(__name__).info("Not using the cache: %s", exc)
        return None


def _describe_error(exc: BaseException, args: argparse.Namespace) -> tuple[int, str]:
    """Map an exception to (exit code, one-line message)."""
    first_line = (str(exc).strip().splitlines() or [""])[0]
    if isinstance(exc, cache.CacheMiss):
        return EXIT_NETWORK, f"offline: {exc}"
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
    if sys.argv[1:2] == ["init"]:
        return setup_wizard.run(sys.argv[2:])
    args = _parse_args()
    if args.legend and not _layout(args):
        # Only the legend: no login, no network.
        print(render_legend(resolve_color(args.color)))
        return 0
    _setup_logging(args.verbose,
                   quiet=bool(_layout(args) or args.query or args.sections or args.now
                              or args.changes or args.live is not None or args.json == "-"))
    if args.default_args:
        logging.getLogger(__name__).debug(
            "default_args from %s: %s", args.defaults_source, " ".join(args.default_args))
    logging.getLogger(__name__).debug(
        "effective arguments: %s",
        {k: v for k, v in sorted(vars(args).items()) if v not in (None, False, [])})
    try:
        if args.live is not None:
            return asyncio.run(_live_loop(args))
        return asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        if args.live is not None:
            return 0                     # Ctrl-C is how --live is meant to end
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
