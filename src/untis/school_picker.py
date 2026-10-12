"""`untis init`: find your school while typing (#76).

An fzf-like picker: every keystroke (after a short pause) asks the
public WebUntis school search, the matches are listed below the input,
↑/↓ picks one, Enter takes it. A pasted WebUntis URL works in the same
field. No extra dependency: a raw-mode terminal loop with ANSI codes,
only used on a real terminal (POSIX); otherwise `untis init` asks for
the URL as before.

The search API refuses broad terms ("too many schools match"), so short
queries show a "keep typing" hint instead of a list.
"""
from __future__ import annotations

import codecs
import os
import shutil
import sys
import time
from typing import Callable, Optional

import httpx

MIN_QUERY = 2           # shorter queries aren't sent
DEBOUNCE = 0.25         # seconds without typing before searching
MAX_ROWS = 10           # matches shown at once

UP, DOWN, ENTER, BACKSPACE, CANCEL, CLEAR = "up", "down", "enter", "backspace", "cancel", "clear"
_KEYS = {
    "\r": ENTER, "\n": ENTER, "\x7f": BACKSPACE, "\x08": BACKSPACE, "\x03": CANCEL,
    "\x1b": CANCEL, "\x04": CANCEL, "\x10": UP, "\x0e": DOWN, "\x15": CLEAR,
    "\x1b[A": UP, "\x1b[B": DOWN, "\x1bOA": UP, "\x1bOB": DOWN,
}


def looks_like_url(text: str) -> bool:
    t = text.strip().lower()
    return "://" in t or ".webuntis.com" in t


def describe(s: dict) -> str:
    where = s.get("address") or ""
    return f"{s.get('displayName') or s.get('loginName') or '?'}" + (f" ({where})" if where else "")


class Picker:
    """The picker's state, without any terminal I/O (tested directly)."""

    def __init__(self, search: Callable[[str], list[dict]], query: str = ""):
        self.search = search
        self.query = query
        self.results: list[dict] = []
        self.selected = 0
        self.message = ""
        self._cache: dict[str, tuple[list[dict], str]] = {}
        self._searched: Optional[str] = None

    # --- editing -------------------------------------------------------------
    def type(self, text: str) -> None:
        self.query += "".join(ch for ch in text if ch.isprintable())

    def backspace(self) -> None:
        self.query = self.query[:-1]

    def clear(self) -> None:
        self.query = ""

    def move(self, delta: int) -> None:
        if self.results:
            self.selected = (self.selected + delta) % len(self.results)

    @property
    def stale(self) -> bool:
        """The list doesn't belong to the current query yet."""
        return self._searched != self.query.strip()

    # --- searching -----------------------------------------------------------
    def refresh(self) -> None:
        """Search for the current query (cached per query)."""
        from .setup_wizard import SetupError
        term = self.query.strip()
        self._searched = term
        self.selected = 0
        if looks_like_url(term):
            self.results, self.message = [], "Enter: use this URL"
            return
        if len(term) < MIN_QUERY:
            self.results = []
            self.message = "Keep typing…" if term else ""
            return
        if term not in self._cache:
            try:
                found = self.search(term)
                msg = "" if found else f"No school matches {term!r}"
            except SetupError as exc:
                found = []
                msg = ("Too many schools match, keep typing…" if "too many" in str(exc)
                       else str(exc))
            except (httpx.HTTPError, ValueError) as exc:
                found, msg = [], f"Search failed: {exc}"
            self._cache[term] = (found, msg)
        self.results, self.message = self._cache[term]

    def choice(self) -> Optional[tuple[str, object]]:
        """What Enter means now: ("url", text), ("school", dict) or None."""
        term = self.query.strip()
        if looks_like_url(term):
            return "url", term
        if self.results and not self.stale:
            return "school", self.results[self.selected]
        return None

    # --- drawing -------------------------------------------------------------
    def render(self, width: int = 80, rows: int = MAX_ROWS) -> list[str]:
        """The lines to show: hint/matches first, the input line last."""
        lines = []
        if self.results:
            first = min(max(self.selected - rows + 1, 0), max(len(self.results) - rows, 0))
            for i, s in enumerate(self.results[first:first + rows], first):
                mark = "▸ " if i == self.selected else "  "
                lines.append(_cut(mark + describe(s), width))
            more = len(self.results) - rows
            footer = f"{len(self.results)} found · ↑/↓ choose · Enter select · Esc cancel"
            lines.append(_cut(footer if more <= 0 else f"(+{more} more) " + footer, width))
        if self.message:
            lines.append(_cut(self.message, width))
        lines.append(_cut("School: " + self.query, width))
        return lines


def _cut(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(width - 1, 0)] + "…"


def parse_keys(text: str) -> list[str]:
    """Split typed input into keys: escape sequences and control keys as
    names (UP, ENTER, …), other characters as themselves."""
    keys, i = [], 0
    while i < len(text):
        for seq in ("\x1b[A", "\x1b[B", "\x1bOA", "\x1bOB"):
            if text.startswith(seq, i):
                keys.append(_KEYS[seq])
                i += len(seq)
                break
        else:
            if text.startswith("\x1b[", i):              # other escape sequence: skip it
                j = i + 2
                while j < len(text) and not text[j].isalpha() and text[j] != "~":
                    j += 1
                i = j + 1
                continue
            keys.append(_KEYS.get(text[i], text[i]))
            i += 1
    return keys


def run(picker: Picker, read: Callable[[Optional[float]], Optional[str]],
        write: Callable[[str], None], width: int = 80,
        clock: Callable[[], float] = time.monotonic) -> tuple[str, object]:
    """The interactive loop. `read(timeout)` returns typed text or None
    after the timeout; `write` prints. Returns ("url", text) or
    ("school", dict); Esc / Ctrl-C raise KeyboardInterrupt."""
    drawn = 0

    def draw() -> None:
        nonlocal drawn
        lines = picker.render(width)
        up = f"\x1b[{drawn - 1}A" if drawn > 1 else ""
        write("\r" + up + "\x1b[J" + "\r\n".join(lines))
        drawn = len(lines)

    if picker.query:
        picker.refresh()
    draw()
    typed_at: Optional[float] = None
    while True:
        timeout = None if typed_at is None else max(DEBOUNCE - (clock() - typed_at), 0)
        text = read(timeout)
        if text is None:                                  # pause: search now
            if typed_at is not None and picker.stale:
                picker.refresh()
                draw()
            typed_at = None
            continue
        for key in parse_keys(text):
            if key == CANCEL:
                write("\r\n")
                raise KeyboardInterrupt
            if key == ENTER:
                if picker.stale:
                    picker.refresh()
                chosen = picker.choice()
                if chosen:
                    write("\r\n")
                    return chosen
            elif key == UP:
                picker.move(-1)
            elif key == DOWN:
                picker.move(1)
            elif key == BACKSPACE:
                picker.backspace()
                typed_at = clock()
            elif key == CLEAR:
                picker.clear()
                typed_at = clock()
            else:
                picker.type(key)
                typed_at = clock()
        draw()


def available(stdin=None, stdout=None) -> bool:
    """Only on a real terminal with termios (not on Windows, not piped)."""
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    try:
        import termios  # noqa: F401
    except ImportError:
        return False
    try:
        return stdin.isatty() and stdout.isatty()
    except (AttributeError, ValueError):
        return False


def pick(search: Callable[[str], list[dict]], query: str = "") -> tuple[str, object]:
    """Run the picker on the real terminal (raw mode, restored on exit)."""
    import select
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    decoder = codecs.getincrementaldecoder("utf-8")(errors="ignore")

    def read(timeout: Optional[float]) -> Optional[str]:
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return None
        return decoder.decode(os.read(fd, 1024))

    def write(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    width = shutil.get_terminal_size((80, 24)).columns
    try:
        tty.setraw(fd)
        return run(Picker(search, query), read, write, width)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
