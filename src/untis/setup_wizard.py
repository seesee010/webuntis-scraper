"""`untis init`: set up config.json and .env from any WebUntis URL.

    untis init                                   # interactive
    untis init --url URL --username NAME < pw    # non-interactive

The login is tested (plain HTTP, with a throwaway session file) before
anything is saved. Existing config files are updated, not replaced, and
the password is never shown.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlsplit

import httpx

from .config import XDG_CONFIG_DIR, ScraperConfig
from .privacy import ensure_private_dir, write_private_text

SCHOOL_SEARCH_URL = "https://mobile.webuntis.com/ms/schoolquery2"
WEBUNTIS_DOMAIN = ".webuntis.com"

EXIT_OK, EXIT_USAGE, EXIT_LOGIN, EXIT_NETWORK = 0, 2, 3, 4


class SetupError(Exception):
    """A problem the user has to fix (bad URL, ambiguous school, …)."""


def parse_webuntis_url(url: str) -> tuple[str, Optional[str]]:
    """(server, school) from a WebUntis URL; school is None if the URL
    doesn't contain it (new UI pages like https://<server>.webuntis.com/today)."""
    text = url.strip()
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    host = (parts.hostname or "").lower()
    if not host.endswith(WEBUNTIS_DOMAIN) or host == WEBUNTIS_DOMAIN.lstrip("."):
        raise SetupError(f"not a WebUntis school URL: {url!r} "
                         "(expected https://<server>.webuntis.com/…)")
    server = host[: -len(WEBUNTIS_DOMAIN)]
    school = None
    for query in (parts.query, parts.fragment.partition("?")[2]):
        values = parse_qs(query).get("school")
        if values and values[0].strip():
            school = values[0].strip()
            break
    return server, school


def search_schools(term: str, transport: Optional[httpx.BaseTransport] = None) -> list[dict]:
    """WebUntis's public school search (no login needed)."""
    body = {"id": "untis-init", "method": "searchSchool", "params": [{"search": term}],
            "jsonrpc": "2.0"}
    with httpx.Client(timeout=20, transport=transport,
                      headers={"User-Agent": ScraperConfig().user_agent}) as client:
        r = client.post(SCHOOL_SEARCH_URL, json=body)
        r.raise_for_status()
        data = r.json()
    if data.get("error"):
        message = data["error"].get("message", data["error"])
        if "too many" in str(message):
            raise SetupError(f"too many schools match {term!r}; be more specific")
        raise SetupError(f"school search failed: {message}")
    return list((data.get("result") or {}).get("schools") or [])


def schools_on_server(schools: list[dict], server: str) -> list[dict]:
    host = f"{server}{WEBUNTIS_DOMAIN}"
    return [s for s in schools if (s.get("server") or "").lower() == host]


def describe_school(s: dict) -> str:
    where = s.get("address") or ""
    return f"{s.get('displayName') or s.get('loginName')}" + (f" ({where})" if where else "")


def update_config(directory: Path, server: str, school: str, username: str) -> Path:
    """Write server/school/username into config.json, keeping all other keys."""
    path = Path(directory) / "config.json"
    data: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            data = loaded if isinstance(loaded, dict) else {}
        except ValueError:
            raise SetupError(f"{path} isn't valid JSON; fix or remove it first") from None
    data.update(server=server, school=school, username=username)
    write_private_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return path


def update_env(directory: Path, password: str) -> Path:
    """Set UNTIS_PASSWORD in .env (mode 600), keeping other lines."""
    path = Path(directory) / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [l for l in lines if not l.strip().startswith("UNTIS_PASSWORD=")]
    quoted = '"' + password.replace("\\", "\\\\").replace('"', '\\"') + '"'
    lines.append(f"UNTIS_PASSWORD={quoted}")
    write_private_text(path, "\n".join(lines) + "\n")
    return path


async def verify_login(server: str, school: str, username: str, password: str) -> str:
    """Log in once over plain HTTP with a throwaway session file and
    return "<name>, <role>". Raises LoginError / WebUntisError / httpx errors."""
    from .browser import BrowserSession
    from .untis_client import WebUntisClient
    with tempfile.TemporaryDirectory(prefix="untis-init-") as tmp:
        cfg = ScraperConfig(server=server, school=school, username=username, password=password,
                            transport="http", storage_state_path=str(Path(tmp) / "state.json"))
        cfg.derived_urls()
        async with BrowserSession(cfg) as session:            # never started (HTTP only)
            client = WebUntisClient(cfg, session)
            try:
                await client.login()
                role = (client._resource_type or "user").lower()
                return f"{client.user_display}, {role}"
            finally:
                await client.close()


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="untis init",
        description="Set up ~/.config/untis/config.json and .env from any WebUntis URL "
                    "of your school. The login is tested before anything is saved.")
    ap.add_argument("--url", help="Any WebUntis page of your school (non-interactive).")
    ap.add_argument("--search", metavar="NAME", help="Find the school by name instead of a URL.")
    ap.add_argument("--username", help="Your WebUntis username (non-interactive). "
                                       "The password is then read from stdin.")
    ap.add_argument("--dir", type=Path, default=XDG_CONFIG_DIR,
                    help=f"Where to write config.json and .env (default: {XDG_CONFIG_DIR}).")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite server/school/username of an existing config without asking.")
    ap.add_argument("--no-verify", action="store_true",
                    help="Save without testing the login (e.g. for 2FA/SSO accounts).")
    return ap


def run(
    argv: list[str],
    ask: Callable[[str], str] = input,
    ask_secret: Callable[[str], str] = getpass.getpass,
    stdin=None,
    out: Callable[[str], None] = print,
    search: Callable[[str], list[dict]] = search_schools,
    verify: Callable[..., Any] = verify_login,
) -> int:
    """The `untis init` command (all I/O injectable for tests)."""
    stdin = stdin or sys.stdin
    args = _parser().parse_args(argv)
    interactive = not (args.url or args.search) or not args.username
    from .untis_client import LoginError, WebUntisError

    try:
        # --- school --------------------------------------------------------
        if args.search:
            server, school = _pick_from_search(args.search, search, ask, out,
                                               interactive and not args.username)
        else:
            url = args.url or ask("Paste any WebUntis URL of your school: ")
            server, school = parse_webuntis_url(url)
            if school is None:
                matches = schools_on_server(search(server), server)
                if len(matches) != 1:
                    raise SetupError(
                        f"couldn't tell which school on {server}{WEBUNTIS_DOMAIN} you mean "
                        f"({len(matches)} found); paste the login page URL (with ?school=) "
                        "or use --search NAME")
                school = matches[0].get("loginName")
        out(f"→ server: {server}   school: {school}")

        # --- existing config ------------------------------------------------
        config_path = Path(args.dir) / "config.json"
        if config_path.exists() and not args.force:
            if not interactive:
                raise SetupError(f"{config_path} already exists; use --force to update it")
            if ask(f"{config_path} exists. Update server/school/username? [y/N] ").strip().lower() \
                    not in ("y", "yes", "j", "ja"):
                out("Nothing changed.")
                return EXIT_OK

        # --- credentials ----------------------------------------------------
        username = args.username or ask("Username: ").strip()
        if args.username and not (stdin.isatty() if hasattr(stdin, "isatty") else False):
            password = stdin.readline().rstrip("\n")
        else:
            password = ask_secret("Password: ")
        if not username or not password:
            raise SetupError("username and password are required")

        # --- test + save ----------------------------------------------------
        if not args.no_verify:
            out("Testing login…")
            who = asyncio.run(verify(server, school, username, password))
            out(f"✓ logged in ({who})")
        ensure_private_dir(Path(args.dir))
        update_config(args.dir, server, school, username)
        update_env(args.dir, password)
        out(f"Saved to {args.dir}/ (config.json, .env with mode 600). Try: untis -s --today")
        return EXIT_OK
    except SetupError as exc:
        out(f"untis init: {exc}")
        return EXIT_USAGE
    except LoginError as exc:
        out(f"untis init: login failed: {str(exc).rstrip('.')}. Nothing was saved "
            "(for 2FA/SSO accounts add --no-verify).")
        return EXIT_LOGIN
    except (WebUntisError, httpx.HTTPError) as exc:
        out(f"untis init: couldn't reach WebUntis: {exc}. Nothing was saved.")
        return EXIT_NETWORK
    except (KeyboardInterrupt, EOFError):
        out("\nAborted, nothing was saved.")
        return 130


def _pick_from_search(term, search, ask, out, interactive) -> tuple[str, str]:
    schools = search(term)
    if not schools:
        raise SetupError(f"no school found for {term!r}")
    if len(schools) > 1:
        if not interactive:
            names = "; ".join(describe_school(s) for s in schools[:5])
            raise SetupError(f"{len(schools)} schools match {term!r} ({names}…); be more specific")
        for i, s in enumerate(schools[:20], 1):
            out(f"  {i:>2}. {describe_school(s)}")
        choice = ask("Which one? [number] ").strip()
        if not choice.isdigit() or not 1 <= int(choice) <= min(len(schools), 20):
            raise SetupError("no school selected")
        chosen = schools[int(choice) - 1]
    else:
        chosen = schools[0]
    server = (chosen.get("server") or "").lower()
    if not server.endswith(WEBUNTIS_DOMAIN):
        raise SetupError(f"unexpected server in the search result: {chosen.get('server')!r}")
    return server[: -len(WEBUNTIS_DOMAIN)], chosen.get("loginName")
