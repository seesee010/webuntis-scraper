"""Export the scraped result to disk."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .privacy import write_private_text

log = logging.getLogger(__name__)


def _strip_raw(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_raw(v) for k, v in value.items() if k != "raw"}
    if isinstance(value, list):
        return [_strip_raw(v) for v in value]
    return value


def _maybe_strip_raw(payload: dict, keep_raw: bool) -> dict:
    return payload if keep_raw else _strip_raw(payload)


# The timestamped files written by write_json (untis_YYYYMMDD_HHMMSS.json).
_TIMESTAMPED = re.compile(r"untis_\d{8}_\d{6}\.json")


def dump_json(payload: dict[str, Any], pretty: bool = True, keep_raw: bool = False) -> str:
    """The payload as JSON text, as it is written to the files."""
    cleaned = _maybe_strip_raw(payload, keep_raw)
    if pretty:
        return json.dumps(cleaned, ensure_ascii=False, indent=2)
    return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))


def write_json(
    payload: dict[str, Any],
    out_dir: str,
    pretty: bool = True,
    keep_raw: bool = False,
) -> Path:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = out_path / f"untis_{ts}.json"
    text = dump_json(payload, pretty=pretty, keep_raw=keep_raw)
    write_private_text(target, text)       # name, absences, … -> mode 600
    log.info("Wrote %s (%.1f KB)", target, target.stat().st_size / 1024)
    return target


def write_latest(payload: dict[str, Any], out_dir: str, keep_raw: bool = False) -> Path:
    out_path = Path(out_dir) / "latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = _maybe_strip_raw(payload, keep_raw)
    write_private_text(out_path, json.dumps(cleaned, ensure_ascii=False, indent=2))
    return out_path


def prune(out_dir: str, keep: int | None) -> list[Path]:
    """Delete all but the newest `keep` timestamped files in `out_dir`
    (None: keep all). latest.json and other files are never touched.
    Returns the deleted files."""
    out_path = Path(out_dir)
    if keep is None or not out_path.is_dir():
        return []
    files = sorted(f for f in out_path.iterdir()
                   if f.is_file() and _TIMESTAMPED.fullmatch(f.name))
    old = files[:-keep] if keep else files
    for f in old:
        f.unlink()
    if old:
        log.info("Deleted %d old JSON file(s) in %s", len(old), out_path)
    return old


def export(
    payload: dict[str, Any],
    out_dir: str,
    pretty: bool = True,
    keep_raw: bool = False,
    keep: int | None = None,
) -> list[Path]:
    """Write latest.json and, unless `keep` is 0, a timestamped file;
    then keep only the newest `keep` timestamped files (None: all).
    Returns the written files."""
    written = []
    if keep != 0:
        written.append(write_json(payload, out_dir, pretty=pretty, keep_raw=keep_raw))
    written.append(write_latest(payload, out_dir, keep_raw=keep_raw))
    prune(out_dir, keep)
    return written
