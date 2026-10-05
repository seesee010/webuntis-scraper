"""--live: redraw the output every few minutes until Ctrl-C.

The loop itself lives in main (it reruns the normal CLI path); this
module holds the small pieces around it: the interval check, the footer
and how one refresh is drawn.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta

from . import cache

DEFAULT_INTERVAL = "5m"
MIN_INTERVAL = 60           # seconds; don't hammer the school's server

# Cursor home + clear screen: the new frame replaces the old one.
CLEAR = "\033[H\033[2J"


def parse_interval(text: str) -> int:
    """"5m" / "90s" / "2" (minutes) -> seconds, at least MIN_INTERVAL."""
    seconds = cache.parse_duration(text)
    if seconds < MIN_INTERVAL:
        raise ValueError(f"interval must be at least {MIN_INTERVAL}s, got {text!r}")
    return seconds


def color_mode(mode: str, isatty: bool, environ: Mapping[str, str]) -> str:
    """--color for the captured refreshes: "auto" would look at the
    capture buffer (never a terminal), so decide it once for the real
    output instead. "always"/"never" stay as they are."""
    if mode != "auto":
        return mode
    return "always" if isatty and "NO_COLOR" not in environ else "never"


def format_interval(seconds: int) -> str:
    """300 -> "5m", 90 -> "1m30s", 3600 -> "1h", 5400 -> "1h30m"."""
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts = [f"{v}{u}" for v, u in ((hours, "h"), (minutes, "m"), (secs, "s")) if v]
    return "".join(parts) or "0s"


def footer(updated: datetime | None, interval: int, now: datetime,
           error: str | None = None) -> str:
    """The status line under the output: when it was last updated, when
    the next refresh comes, and the last error (old data is kept then)."""
    nxt = (now + timedelta(seconds=interval)).strftime("%H:%M")
    when = f"updated {updated.strftime('%H:%M:%S')}" if updated else "not updated yet"
    line = f"{when} · every {format_interval(interval)}, next {nxt} · Ctrl-C to quit"
    if error:
        line = f"refresh failed: {error}\n{line}"
    return line


def frame(body: str, status: str, clear: bool) -> str:
    """One full redraw: optional clear-screen, the output, a blank line,
    the footer."""
    body = body.rstrip("\n")
    text = f"{body}\n\n{status}\n" if body else f"{status}\n"
    return (CLEAR if clear else "") + text
