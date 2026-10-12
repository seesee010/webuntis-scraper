"""Tests for --completion bash|zsh|fish (#16)."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from untis import completion, setup_wizard
from untis import main as main_mod
from untis.completion import Option


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="demo")
    ap.add_argument("-V", "--version", action="version", version="1")
    ap.add_argument("--config", help="Path to config.json (default: /home/x/config.json).")
    ap.add_argument("--color", choices=("auto", "never"), help="Colors. More text here.")
    ap.add_argument("-s", "--short", action=argparse.BooleanOptionalAction, help="Short view.")
    ap.add_argument("--json", nargs="?", const=True, help="JSON, e.g. for jq.")
    ap.add_argument("--no-json", dest="json", action="store_const", const=False)
    ap.add_argument("--days", type=int, metavar="N", help=argparse.SUPPRESS)
    ap.add_argument("--today", action="store_true", help="Only today.")
    ap.add_argument("--dir", type=Path)
    ap.add_argument("name", nargs="?")
    return ap


def _by_flag(opts: list[Option]) -> dict[str, Option]:
    return {f: o for o in opts for f in o.flags}


# --- short_help -----------------------------------------------------------------
@pytest.mark.parametrize("text, out", [
    (None, ""), ("", ""), (argparse.SUPPRESS, ""),
    ("Only today.", "Only today"),
    ("Colors. More text here.", "Colors"),
    ("Save without testing (e.g. for 2FA). Second.", "Save without testing (e.g. for 2FA)"),
    ("Print it, e.g. untis --x. Then more.", "Print it, e.g. untis --x"),
    ("Path to config.json (default: /home/x/.config/untis/config.json).", "Path to config.json"),
    ("Spread\n   over   lines.", "Spread over lines"),
])
def test_short_help(text, out):
    assert completion.short_help(text) == out


def test_short_help_is_cut():
    out = completion.short_help("x" * 100, limit=10)
    assert out == "x" * 9 + "…" and len(out) == 10


# --- options ---------------------------------------------------------------------------
def test_options_reads_the_parser():
    opts = completion.options(_parser())
    flags = _by_flag(opts)
    assert "-h" not in flags and "name" not in flags          # help, positionals
    assert flags["--config"].takes_value and flags["--config"].kind == "file"
    assert flags["--config"].help == "Path to config.json"
    assert flags["--color"].choices == ["auto", "never"]
    assert flags["-s"] is flags["--no-short"] and not flags["-s"].takes_value
    assert flags["--json"].takes_value and flags["--json"].optional_value
    assert not flags["--no-json"].takes_value
    assert not flags["--version"].takes_value and not flags["--today"].takes_value
    assert flags["--days"].takes_value and flags["--days"].help == ""
    assert flags["--dir"].kind == "dir"


def test_option_long_and_short():
    o = Option(flags=["-s", "--short", "--no-short"])
    assert o.long == ["short", "no-short"] and o.short == ["s"]
    assert Option(flags=["--x"]).short == []


def test_options_of_the_real_parsers_cover_every_flag():
    flags = _by_flag(completion.options(main_mod._build_parser()))
    for flag in ("--short", "-s", "--holidays", "--only", "--lang", "--completion", "--tests",
                 "--no-tests", "--exams", "--table", "--live", "--max-age"):
        assert flag in flags, flag
    assert flags["--lang"].choices == ["en", "de"]
    assert flags["--completion"].choices == list(completion.SHELLS)
    init = _by_flag(completion.options(setup_wizard._parser()))
    assert set(init) == {"--url", "--search", "--username", "--dir", "--force", "--no-verify"}


# --- bash ------------------------------------------------------------------------------
def test_bash_value_cases():
    cases = completion._bash_value_cases(completion.options(_parser()))
    text = "\n".join(cases)
    assert '--color) COMPREPLY=($(compgen -W "auto never" -- "$cur")); return 0;;' in text
    assert "--config) COMPREPLY=($(compgen -f" in text
    assert "--dir) COMPREPLY=($(compgen -d" in text
    assert "--days) return 0;;" in text
    assert "--json)" not in text                 # optional value: options still complete


def _real(shell: str) -> str:
    return completion.script(shell, main_mod._build_parser(), setup_wizard._parser())


def test_bash_script_lists_all_flags():
    text = _real("bash")
    assert text.startswith("# bash completion for untis")
    assert "complete -F _untis untis" in text
    for flag in ("--holidays", "--no-holidays", "--only", "--except", "--force", "--no-verify"):
        assert f"{flag} " in text or f"{flag}\"" in text


@pytest.mark.skipif(not shutil.which("bash"), reason="bash not installed")
@pytest.mark.parametrize("words, expected", [
    (["untis", "--tran"], {"--transport"}),
    (["untis", "--transport", ""], {"auto", "http", "browser"}),
    (["untis", "--lang", ""], {"en", "de"}),
    (["untis", "--completion", "z"], {"zsh"}),
    (["untis", "i"], {"init"}),
    (["untis", "init", "--u"], {"--url", "--username"}),
    (["untis", "-s", "--days-"], {"--days-back", "--days-forward"}),
    (["untis", "--days-back", ""], set()),
])
def test_bash_completes(tmp_path, words, expected):
    script = tmp_path / "untis.bash"
    script.write_text(_real("bash"))
    quoted = " ".join(f"'{w}'" for w in words)
    probe = (f"source {script}; COMP_WORDS=({quoted}); COMP_CWORD={len(words) - 1}; "
             "_untis; printf '%s\\n' \"${COMPREPLY[@]}\"")
    out = subprocess.run(["bash", "-c", probe], capture_output=True, text=True, check=True)
    assert set(filter(None, out.stdout.splitlines())) == expected


@pytest.mark.skipif(not shutil.which("bash"), reason="bash not installed")
def test_bash_syntax(tmp_path):
    script = tmp_path / "untis.bash"
    script.write_text(_real("bash"))
    subprocess.run(["bash", "-n", str(script)], check=True)


# --- zsh -------------------------------------------------------------------------------
@pytest.mark.parametrize("text, out", [
    ("plain", "plain"), ("a [b] c", "a (b) c"), ("it's", "its"), ("x: y", "x - y"),
    ("back\\slash", "backslash"),
])
def test_zsh_escape(text, out):
    assert completion._zsh_escape(text) == out


@pytest.mark.parametrize("option, spec", [
    (Option(["--today"], "Only today"), "'--today[Only today]'"),
    (Option(["--x"]), "'--x'"),
    (Option(["-s", "--short"], "Short"), "'(-s --short)'{-s,--short}'[Short]'"),
    (Option(["--color"], "C", True, choices=["a", "b"]), "'--color[C]:value:(a b)'"),
    (Option(["--config"], "", True, kind="file"), "'--config:value:_files'"),
    (Option(["--dir"], "", True, kind="dir"), "'--dir:value:_files -/'"),
    (Option(["--json"], "J", True, optional_value=True), "'--json[J]::value: '"),
    (Option(["--days"], "", True), "'--days:value: '"),
])
def test_zsh_spec(option, spec):
    assert completion._zsh_spec(option) == spec


def test_zsh_script_structure():
    text = _real("zsh")
    assert text.startswith("#compdef untis\n")
    assert "'1:: :(init)'" in text and '_untis "$@"' in text
    assert "'--lang[" in text and ":value:(en de)'" in text


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh not installed")
def test_zsh_syntax(tmp_path):
    script = tmp_path / "_untis"
    script.write_text(_real("zsh"))
    subprocess.run(["zsh", "-n", str(script)], check=True)


# --- fish ------------------------------------------------------------------------------
@pytest.mark.parametrize("text, out", [("plain", "'plain'"), ("it's", "'it\\'s'"),
                                       ("a\\b", "'a\\\\b'")])
def test_fish_quote(text, out):
    assert completion._fish_quote(text) == out


def test_fish_line():
    cond = "not __fish_seen_subcommand_from init"
    assert completion._fish_line(Option(["-s", "--short", "--no-short"], "Short"), cond) == (
        "complete -c untis -n 'not __fish_seen_subcommand_from init' "
        "-s s -l short -l no-short -d 'Short'")
    assert completion._fish_line(Option(["--color"], "", True, choices=["a", "b"]), cond) \
        .endswith("-l color -x -a 'a b'")
    assert completion._fish_line(Option(["--config"], "", True, kind="file"), cond) \
        .endswith("-l config -r -F")
    assert completion._fish_line(Option(["--dir"], "", True, kind="dir"), cond) \
        .endswith("-l dir -x -a '(__fish_complete_directories)'")
    assert completion._fish_line(Option(["--days"], "", True), cond).endswith("-l days -x")


def test_fish_script_structure():
    lines = _real("fish").splitlines()
    assert lines[1] == "complete -c untis -f"
    assert any("__fish_use_subcommand' -a init" in l for l in lines)
    assert any(l.startswith("complete -c untis -n '__fish_seen_subcommand_from init'")
               and "-l no-verify" in l for l in lines)
    assert all(l.startswith(("#", "complete -c untis")) for l in lines)


@pytest.mark.skipif(not shutil.which("fish"), reason="fish not installed")
def test_fish_syntax(tmp_path):
    script = tmp_path / "untis.fish"
    script.write_text(_real("fish"))
    subprocess.run(["fish", "-n", str(script)], check=True)


# --- script / CLI ----------------------------------------------------------------------
def test_script_unknown_shell():
    with pytest.raises(ValueError, match="unknown shell"):
        completion.script("tcsh", _parser(), _parser())


def test_no_local_paths_in_scripts():
    for shell in completion.SHELLS:
        assert str(Path.home()) not in _real(shell)


@pytest.mark.parametrize("shell", completion.SHELLS)
def test_main_prints_the_script(monkeypatch, capsys, shell):
    monkeypatch.setattr(sys, "argv", ["untis", "--completion", shell])
    assert main_mod.main() == 0
    assert capsys.readouterr().out == _real(shell)


def test_completion_not_allowed_in_default_args():
    with pytest.raises(SystemExit):
        main_mod._parse_args([], default_args=["--completion", "zsh"])


def test_completion_rejects_unknown_shell():
    with pytest.raises(SystemExit):
        main_mod._parse_args(["--completion", "tcsh"], default_args=[])
