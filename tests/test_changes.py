"""Tests for --changes, the snapshot and desktop notifications (#9)."""
from __future__ import annotations

import json
import os
import stat
from datetime import date, datetime
from pathlib import Path

import pytest

from untis import changes
from untis import main as main_mod
from untis.changes import _lesson_key, diff, format_change, notify, snapshot
from untis.config import ScraperConfig

NOW = datetime(2026, 10, 3, 9, 0)
MON, TUE = "2026-10-05", "2026-10-06"


def _e(day, start, end, subject, teacher="TCH1", room="R101", **flags):
    return {"start": f"{day}T{start}", "end": f"{day}T{end}", "status": "REGULAR",
            "subjects": [{"short": subject}], "teachers": [{"short": teacher}],
            "rooms": [{"short": room}], "info": "", "lesson_text": "", "substitution_text": "",
            "is_cancelled": False, "is_exam": False, **flags}


def payload(entries_mon, entries_tue=(), exams=(), homework=(), start=MON, end=TUE):
    return {"meta": {"window": {"start": start, "end": end}},
            "timetable": {"days": [{"date": MON, "entries": list(entries_mon)},
                                   {"date": TUE, "entries": list(entries_tue)}]},
            "exams": {"exams": list(exams)}, "homework": {"items": list(homework)}}


BASE = [_e(MON, "07:50", "08:40", "MATH"), _e(MON, "08:45", "09:35", "GER"),
        _e(MON, "09:40", "10:30", "PROG")]


def snap(p, account="a"):
    return snapshot(p, account, NOW)


# --- snapshot / load / save ------------------------------------------------
def test_lesson_key():
    assert _lesson_key(MON, {"start": "07:50", "end": "08:40", "subject": "MATH", "title": ""}) \
        == "2026-10-05|07:50|08:40|MATH"
    assert _lesson_key(MON, {"start": "07:50", "end": "17:05", "subject": "", "title": "TRIP"}) \
        .endswith("|TRIP")


def test_snapshot_contents():
    p = payload(BASE + [_e(MON, "10:45", "11:35", "ENG", is_cancelled=True, status="CANCELLED")],
                exams=[{"date": "2026-10-19", "name": "Test", "subjects": [{"short": "PROG"}],
                        "start_time": "10:45"}],
                homework=[{"due_date": MON, "text": "p.  42", "subjects": [{"short": "MATH"}]}])
    s = snap(p)
    assert s["window"] == {"start": MON, "end": TUE} and s["account"] == "a"
    assert s["lessons"][f"{MON}|07:50|08:40|MATH"] == {"status": "regular", "teachers": "TCH1",
                                                      "rooms": "R101"}
    assert s["lessons"][f"{MON}|10:45|11:35|ENG"]["status"] == "cancelled"
    assert s["exams"]["2026-10-19|PROG|Test"]["start"] == "10:45"
    (hw,) = s["homework"].values()
    assert hw == {"due": MON, "subject": "MATH", "text": "p. 42"}


def test_save_and_load(tmp_path):
    path = tmp_path / "state" / "changes.json"
    changes.save(path, snap(payload(BASE)))
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert changes.load(path)["lessons"]
    for bad in ("{broken", json.dumps({"version": 99})):
        path.write_text(bad)
        assert changes.load(path) is None
    assert changes.load(tmp_path / "missing.json") is None


# --- diff --------------------------------------------------------------------
def _texts(found):
    return [(c["date"], c["time"], c["subject"], c["text"]) for c in found]


def test_no_changes():
    assert diff(snap(payload(BASE)), snap(payload(BASE))) == []


def test_status_teacher_and_room_changes():
    new = [_e(MON, "07:50", "08:40", "MATH", is_cancelled=True, status="CANCELLED"),
           _e(MON, "08:45", "09:35", "GER", teacher="TCH4"),
           _e(MON, "09:40", "10:30", "PROG", room="R205")]
    assert _texts(diff(snap(payload(BASE)), snap(payload(new)))) == [
        (MON, "07:50", "MATH", "cancelled"),
        (MON, "08:45", "GER", "teacher TCH1 → TCH4"),
        (MON, "09:40", "PROG", "room R101 → R205"),
    ]


def test_back_to_normal_and_combined():
    old = [_e(MON, "07:50", "08:40", "MATH", is_cancelled=True, status="CANCELLED", room="R1")]
    new = [_e(MON, "07:50", "08:40", "MATH", room="R2")]
    assert _texts(diff(snap(payload(old)), snap(payload(new)))) == [
        (MON, "07:50", "MATH", "back to normal, room R1 → R2")]


def test_new_and_vanished_lessons():
    new = BASE[:2] + [_e(MON, "12:35", "13:25", "EXTRA")]
    found = _texts(diff(snap(payload(BASE)), snap(payload(new))))
    assert (MON, "09:40", "PROG", "no longer in the timetable") in found
    assert (MON, "12:35", "EXTRA", "new lesson") in found
    cancelled_new = [_e(MON, "12:35", "13:25", "X", is_cancelled=True, status="CANCELLED")]
    assert _texts(diff(snap(payload([])), snap(payload(cancelled_new))))[0][3] == \
        "new lesson (cancelled)"


def test_only_the_overlapping_window_is_compared():
    old = snap(payload(BASE, start=MON, end=MON))          # knew only Monday
    new = snap(payload([], [_e(TUE, "07:50", "08:40", "NET")], start=TUE, end=TUE))
    assert diff(old, new) == []                            # no shared day -> nothing


def test_exams_and_homework():
    exam = {"date": "2026-10-06", "name": "Vocab", "subjects": [{"short": "ENG"}],
            "start_time": "08:45"}
    old = snap(payload(BASE, exams=[{"date": MON, "name": "Old", "subjects": [{"short": "GEO"}]}]))
    new = snap(payload(BASE, exams=[exam],
                       homework=[{"due_date": TUE, "text": "Essay " * 30,
                                  "subjects": [{"short": "GER"}]}]))
    found = _texts(diff(old, new))
    assert (MON, "", "GEO", "exam removed: Old") in found
    assert (TUE, "08:45", "ENG", "new exam: Vocab") in found
    hw = next(f for f in found if f[3].startswith("new homework"))
    assert hw[:3] == (TUE, "", "GER") and len(hw[3]) <= len("new homework: ") + 60


def test_diff_is_sorted():
    new = [_e(MON, "09:40", "10:30", "PROG", room="R9"), _e(MON, "07:50", "08:40", "MATH", room="R8"),
           _e(MON, "08:45", "09:35", "GER")]
    times = [c["time"] for c in diff(snap(payload(BASE)), snap(payload(new)))]
    assert times == sorted(times)


def test_format_change():
    assert format_change({"date": MON, "time": "07:50", "subject": "MATH", "text": "cancelled"}) \
        == "Mon 05.10. 07:50  MATH    cancelled"
    assert format_change({"date": "", "time": "", "subject": "X", "text": "y"}).startswith("?")


# --- notify ------------------------------------------------------------------
CHANGE = {"date": MON, "time": "07:50", "subject": "MATH", "text": "cancelled"}


def test_notify_linux(monkeypatch):
    calls = []
    monkeypatch.setattr(changes.sys, "platform", "linux")
    monkeypatch.setattr(changes.shutil, "which", lambda name: "/usr/bin/" + name
                        if name == "notify-send" else None)
    monkeypatch.setattr(changes.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    assert notify([CHANGE, CHANGE]) == 2
    assert calls[0][:3] == ["notify-send", "--app-name=untis", "untis"]
    assert "MATH    cancelled" in calls[0][3]


def test_notify_macos(monkeypatch):
    calls = []
    monkeypatch.setattr(changes.sys, "platform", "darwin")
    monkeypatch.setattr(changes.shutil, "which", lambda name: "/usr/bin/osascript")
    monkeypatch.setattr(changes.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    assert notify([CHANGE]) == 1
    assert calls[0][0] == "osascript" and "display notification" in calls[0][2]


def test_notify_without_tool_or_failing(monkeypatch, caplog):
    monkeypatch.setattr(changes.sys, "platform", "linux")
    monkeypatch.setattr(changes.shutil, "which", lambda name: None)
    assert notify([CHANGE]) == 0
    assert any("notify-send" in r.getMessage() for r in caplog.records)
    monkeypatch.setattr(changes.shutil, "which", lambda name: "/usr/bin/notify-send")

    def boom(cmd, **kw):
        raise OSError("no display")
    monkeypatch.setattr(changes.subprocess, "run", boom)
    assert notify([CHANGE]) == 0


# --- CLI / _answer_changes -------------------------------------------------
def parse(argv, defaults=()):
    return main_mod._parse_args(argv, today=date(2026, 10, 3), default_args=list(defaults))


def test_changes_flags_and_errors(capsys):
    a = parse(["--changes", "--notify"])
    assert a.changes and a.notify
    for argv in (["--notify"], ["--changes", "--now"], ["--changes", "-t"],
                 ["--changes", "--oneline"], ["--changes", "--start"]):
        with pytest.raises(SystemExit) as exc:
            parse(argv)
        assert exc.value.code == 2


def test_changes_with_a_window_is_allowed():
    assert parse(["--changes", "--week"]).week


async def _run(monkeypatch, tmp_path, capsys, p, argv=("--changes",), notified=None):
    monkeypatch.setattr(main_mod, "CHANGES_PATH", tmp_path / "changes.json")

    async def fake_get_payload(c, args, today, now):
        return p, True
    monkeypatch.setattr(main_mod, "_get_payload", fake_get_payload)
    if notified is not None:
        monkeypatch.setattr(changes, "notify", lambda found: notified.extend(found) or len(found))
    cfg = ScraperConfig(server="s", school="sc", username="u")
    code = await main_mod._answer_changes(cfg, parse(list(argv)), date(2026, 10, 3), NOW)
    return code, capsys.readouterr().out, cfg


async def test_first_run_saves_snapshot(monkeypatch, tmp_path, capsys):
    code, out, cfg = await _run(monkeypatch, tmp_path, capsys, payload(BASE))
    assert code == 0 and out.startswith("No earlier snapshot yet")
    assert (tmp_path / "changes.json").exists()
    assert not (cfg.scrape_absences or cfg.scrape_messages) and cfg.scrape_exams


async def test_no_changes_then_changes(monkeypatch, tmp_path, capsys):
    await _run(monkeypatch, tmp_path, capsys, payload(BASE))
    code, out, _ = await _run(monkeypatch, tmp_path, capsys, payload(BASE))
    assert code == 0 and out.startswith("No changes since")
    new = [_e(MON, "07:50", "08:40", "MATH", is_cancelled=True, status="CANCELLED")] + BASE[1:]
    notified = []
    code, out, _ = await _run(monkeypatch, tmp_path, capsys, payload(new),
                              ("--changes", "--notify"), notified)
    assert code == main_mod.EXIT_CHANGES == 10
    assert out == "Mon 05.10. 07:50  MATH    cancelled\n"
    assert [c["text"] for c in notified] == ["cancelled"]


async def test_no_notification_without_flag(monkeypatch, tmp_path, capsys):
    await _run(monkeypatch, tmp_path, capsys, payload(BASE))
    notified = []
    new = [_e(MON, "07:50", "08:40", "MATH", room="R9")] + BASE[1:]
    code, _, _ = await _run(monkeypatch, tmp_path, capsys, payload(new), notified=notified)
    assert code == 10 and notified == []


async def test_other_account_counts_as_first_run(monkeypatch, tmp_path, capsys):
    changes.save(tmp_path / "changes.json", snapshot(payload(BASE), "x/y/z", NOW))
    code, out, _ = await _run(monkeypatch, tmp_path, capsys, payload([]))
    assert code == 0 and out.startswith("No earlier snapshot yet")


async def test_timetable_error(monkeypatch, tmp_path, capsys):
    with pytest.raises(main_mod.WebUntisError, match="HTTP 500"):
        await _run(monkeypatch, tmp_path, capsys, {"timetable": {"error": "HTTP 500"}})


def test_systemd_units_match_exit_code():
    root = Path(__file__).resolve().parent.parent / "contrib" / "systemd"
    service = (root / "untis-changes.service").read_text()
    timer = (root / "untis-changes.timer").read_text()
    assert f"SuccessExitStatus={main_mod.EXIT_CHANGES}" in service
    assert "untis --changes --notify" in service and "OnCalendar=Mon..Fri" in timer
