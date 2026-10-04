"""Keep personal data private on disk.

Sessions (login cookies), JSON output (name, timetable, absences) and
debug screenshots are personal data: directories get mode 700, files
mode 600. All helpers are no-ops on Windows, where POSIX modes don't
apply.
"""
from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

log = logging.getLogger(__name__)

PRIVATE_DIR = 0o700
PRIVATE_FILE = 0o600


def _posix() -> bool:
    return os.name == "posix"


def ensure_private_dir(path: Path) -> Path:
    """Create `path` (and parents) and make it accessible to the owner only."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if _posix():
        os.chmod(path, PRIVATE_DIR)
    return path


def make_private(path: Path) -> None:
    """chmod 600 an existing file (ignored if it doesn't exist)."""
    path = Path(path)
    if _posix() and path.is_file():
        os.chmod(path, PRIVATE_FILE)


def tighten_dir(path: Path) -> int:
    """Make every regular file directly in `path` private. Fixes files
    written by older versions with the default umask (usually 644).
    Returns how many files were changed."""
    path = Path(path)
    if not _posix() or not path.is_dir():
        return 0
    changed = 0
    for f in path.iterdir():
        if f.is_file() and stat.S_IMODE(f.stat().st_mode) != PRIVATE_FILE:
            os.chmod(f, PRIVATE_FILE)
            changed += 1
    return changed


def write_private_text(path: Path, text: str) -> None:
    """Atomically write `text` to `path` with mode 600 from the start
    (no window where the file is world-readable)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_FILE)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def is_readable_by_others(path: Path) -> bool:
    """True if group or others may read `path` (POSIX only)."""
    path = Path(path)
    if not _posix() or not path.is_file():
        return False
    return bool(stat.S_IMODE(path.stat().st_mode) & 0o077)
