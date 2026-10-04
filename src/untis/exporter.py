"""Export the scraped result to disk."""
from __future__ import annotations

import json
import logging
import os
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
    cleaned = _maybe_strip_raw(payload, keep_raw)
    if pretty:
        text = json.dumps(cleaned, ensure_ascii=False, indent=2)
    else:
        text = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
    write_private_text(target, text)       # name, absences, … -> mode 600
    log.info("Wrote %s (%.1f KB)", target, target.stat().st_size / 1024)
    return target


def write_latest(payload: dict[str, Any], out_dir: str, keep_raw: bool = False) -> Path:
    out_path = Path(out_dir) / "latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = _maybe_strip_raw(payload, keep_raw)
    write_private_text(out_path, json.dumps(cleaned, ensure_ascii=False, indent=2))
    return out_path
