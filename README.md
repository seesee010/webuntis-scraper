# WebUntis Scraper

![Made With:vibecoding](https://img.shields.io/badge/made%20with-vibecoding-blueviolet?style=plastic)

🇬🇧 [English](README.md) · 🇩🇪 [Deutsch](README.de.md) · 🇫🇷 [Français](README.fr.md) · 🇨🇳 [中文](README.zh.md)

Scraper for WebUntis (plain HTTP, with Playwright as a fallback). Fetches your timetable, exams,
homework, absences and messages and saves them as structured JSON.

## How it works

By default (`--transport auto`) no browser is needed:

1. **Login** by posting the WebUntis login form over plain HTTP
   (`/WebUntis/j_spring_security_check`), only when the saved session
   in `sessions/storage_state.json` has expired. WebUntis ends idle
   sessions after a while (~40 min observed), so this happens often.
2. **Session check**: `GET /WebUntis/api/token/new` only returns a JWT
   for a logged-in session. It provides the `person_id` and role.
3. **API calls** with the session cookie (and the JWT as Bearer token
   for REST v1):
   - Timetable: REST v1 `/api/rest/view/v1/timetable/entries`,
     fallback JSON-RPC `getTimetable`
   - Exams: `/api/exams`
   - Homework: `/api/homeworks/lessons`
   - Absences: `/api/classreg/absences/students`
   - Messages: REST v1 `/api/rest/view/v1/messages`

If the HTTP login gets an unexpected answer (e.g. a WAF block, 2FA or
SSO), `untis` falls back to a real **Chromium via Playwright**: it fills
in the login form and runs the API calls inside the page. Wrong
credentials are *not* retried in the browser (that would just be a
second failed login). Both transports share the same session file.

| `--transport` | Behaviour |
|---|---|
| `auto` (default) | HTTP, browser only as fallback |
| `http` | HTTP only, never starts a browser |
| `browser` | always Playwright (also implied by `--no-headless`) |

`playwright-stealth` patches common bot-detection vectors in browser
mode (`navigator.webdriver`, `navigator.plugins`, `navigator.languages`, …).

## Installation

### With pipx (recommended)

[pipx](https://pipx.pypa.io) installs `untis` as a command in its own isolated environment, so it can't conflict with other Python packages.

**1. Install pipx** (once):

```bash
sudo pacman -S python-pipx            # Arch / Omarchy
sudo apt install pipx                 # Debian / Ubuntu
brew install pipx                     # macOS
python -m pip install --user pipx     # everything else, incl. Windows

pipx ensurepath                       # adds ~/.local/bin to your PATH (open a new terminal afterwards)
```

> Only the Arch / Omarchy commands were tested here. The Debian / Ubuntu, macOS and
> Windows commands (and the Windows Chromium path below) come from the
> [official pipx documentation](https://pipx.pypa.io/stable/installation/) and weren't tested here.

**2. Install `untis`:**

```bash
pipx install git+https://github.com/seesee010/webuntis-scraper
untis --version
```

**3. Configure** your school and login, see [Configuration](#configuration). Then:

```bash
untis -s --today
```

**Optional: Chromium.** `untis` talks to WebUntis over plain HTTP and only needs a browser as a fallback (`--transport browser`, 2FA/SSO). To enable it (on Windows the path ends in `\webuntis-scraper\Scripts\playwright.exe`):

```bash
"$(pipx environment --value PIPX_LOCAL_VENVS)/webuntis-scraper/bin/playwright" install chromium
```

**Update / uninstall:**

```bash
pipx reinstall webuntis-scraper       # fetches the latest version from GitHub
pipx uninstall webuntis-scraper
```

`pipx upgrade` doesn't update installs from GitHub (it only checks package indexes), so use `pipx reinstall`.

If you also work on the code, use the setup below instead. Both want to be `~/.local/bin/untis`, so don't install both.

### From a checkout (development)

Linux / macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
pytest                     # run the tests
```

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
playwright install chromium
```

`bin/untis` runs the checkout with its `.venv` without installing anything. Link it
into a directory on your `PATH` (`~/.local/bin` is on the `PATH` of most Linux distros):

```bash
ln -s "$PWD/bin/untis" ~/.local/bin/untis
untis -s --today
```

## Configuration

Config files are looked up in `~/.config/untis/` (or
`$XDG_CONFIG_HOME/untis/`). Sessions, output and debug screenshots then
go to `~/.local/share/untis/`, so `untis` works from any directory.
Without `~/.config/untis/config.json`, the project folder is used for
everything instead (handy on Windows or for development).

1. Create the config directory and copy the example config:

   ```bash
   mkdir -p ~/.config/untis
   cp config.example.json ~/.config/untis/config.json
   ```

   Then adjust it:

   ```jsonc
   {
     "server": "nese",           // subdomain before .webuntis.com
     "school": "htbla_kaindorf", // value after ?school=
     "username": "max.muster"
   }
   ```

   To find `server` and `school`, search for your school on
   [webuntis.com](https://webuntis.com). The redirect URL contains
   both, e.g. `https://nese.webuntis.com/WebUntis/?school=htbla_kaindorf`.

2. Put your password into `~/.config/untis/.env`:

   ```bash
   cp .env.example ~/.config/untis/.env
   chmod 600 ~/.config/untis/.env
   ```

   ```ini
   UNTIS_PASSWORD=yourPassword
   ```

## Usage

```bash
# Default run (headless, reuses the saved session)
untis

# Ignore the saved session and log in again
untis --form-login --no-headless --clear-session

# Different time window: today plus the next 4 school days
# (weekends, holidays and fully cancelled days don't count)
untis -s --days-forward 4
untis -s --days-back 2 --days-forward 0    # the last 2 school days + today
untis -s --days-forward 4 --calendar-days  # count calendar days instead

# Date shortcuts (instead of --days-back / --days-forward)
untis -s --today
untis -s --tomorrow        # or the next school day if tomorrow is free
untis -s --next            # today while school runs, else the next school day
untis -s --week            # this week, Mon–Sun
untis -s --next-week
untis -s --date 12.10.     # also 12.10.2026 or 2026-10-12

# Also keep the raw API payloads
untis --keep-raw -v

# Compact day view in the terminal (JSON is still written)
untis --short                   # or -s
untis -s --days-forward 0       # today only
```

`--short` prints one block per school day: time, subject, teacher, room,
plus a marker for what happened to the lesson:

| Marker | Meaning |
|---|---|
| `cancelled` | the lesson doesn't take place |
| `removed` | the lesson takes place, but your class was taken out of it |
| `no teacher` | the teacher was removed and nobody replaces them yet |
| `changed` | something else changed, e.g. a substitute: `NEW (for OLD)` |
| `exam` | exam lesson |
| `event` | an event such as an excursion (`★ title`, with its teachers) |

Removed teachers are struck through (`~OLD~` without colors). Each day
header shows when school actually starts and ends that day, e.g.
`Mon 05.10.  07:50–13:25`.

For today, the day view also shows where you are right now: the running
lesson gets a `▶` and the time left, lessons that are over are dimmed, and
in a break or before school a "now" line shows when the next lesson starts.
Cancelled lessons are never marked as current, and after school nothing is
marked.

```
  07:50–09:35  MATH  TCH1  R101                       (dimmed: already over)
▶ 09:40–10:30  GER   TCH2  R101   now · 18 min left
  10:45–11:35  PROG  TCH3  R101

  ──── now 10:37 · next in 8 min ────                 (in a break)
```

`--tomorrow` and `--next` look at the real timetable, so weekends,
holidays and days where every lesson is cancelled are skipped; the day
header then says `(next school day)`.

Below the days come upcoming exams, open homework and a line with
absences and unread messages. Set `NO_COLOR=1` to disable colors.

Output goes to `out/untis_<timestamp>.json` and `out/latest.json`
inside the data directory (`~/.local/share/untis/`, or the project
folder). Cookies are stored in `sessions/storage_state.json` there, so
later runs don't need to log in again.

### Login problems?

If the login fails (`Form login did not redirect away from the login
page`) even though your credentials are correct, check:

1. **Correct server + slug?** Search for your school on `webuntis.com`;
   the redirect URL is `https://<server>.webuntis.com/WebUntis/?school=<slug>`.
2. **Special characters in the password?** `.env` supports `=` and
   quotes, but leading whitespace is trimmed.
3. **CAPTCHA / SSO / 2FA?** → `untis --transport browser --no-headless --form-login`
4. **Screenshot:** `logs/login_failed.png` (in the data directory) shows
   what the browser saw.
5. **Verbose output:** `untis -v`.

### Exit codes

Errors are reported as one line on stderr (`untis: login failed: …`);
add `-v` for the full traceback.

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | unexpected error (please report it) |
| `2` | config / setup problem (missing config, Chromium not installed) |
| `3` | login failed |
| `4` | WebUntis unreachable or returned an error |
| `130` | aborted with Ctrl-C |

## Output schema

```jsonc
{
  "meta": {
    "school": "...", "server": "...", "user": "...",
    "generated_at": "2026-06-02", "window": {"start": "...", "end": "..."}
  },
  "timetable": {
    "source": "rest_v1" | "jsonrpc",
    "start": "2026-06-02", "end": "2026-06-16",
    "own_classes": ["1AXYZ"],
    "days": [
      {"date": "2026-06-02", "entries": [
        {
          "start": "2026-06-02T08:00", "end": "2026-06-02T08:45",
          "status": "REGULAR" | "CHANGED" | "CANCELLED" | ...,
          "is_cancelled": false, "is_exam": false, "is_substitution": false,
          "is_event": false, "is_removed": false, "no_teacher": false,
          "lesson_text": "", "subjects": [{"short":"M","long":"Math"}],
          "teachers": [{"short":"NEW","long":"...","status":"ADDED","replaces":"OLD"}],
          "classes": [...], "rooms": [...]
        }
      ]}
    ],
    "lessons": [...]   // with the jsonrpc fallback
  },
  "exams": {
    "source": "api" | "timetable_fallback",
    "exams": [ { "date": "2026-06-10", "start_time": "10:45", "name": "Test", ... } ]
  },
  "homework":  { "items": [...] },
  "absences":  { "items": [...] },
  "messages":  { "items": [...] }
}
```

## Notes

- **2FA / CAPTCHA**: If your school requires OTP, run once with
  `--no-headless --clear-session`, enter the code, and run headless
  from then on.
- **Exams**: come from `/api/exams`. If that endpoint isn't available,
  exams are derived from the timetable (`source: "timetable_fallback"`).
- **Rate limit**: at most one request every 300 ms.
- **Raw data**: without `--keep-raw`, all `raw` fields are removed.
- **Storage**: in the project folder, `sessions/`, `out/`, `logs/`,
  `config.json` and `.env` are in `.gitignore`.

## Project structure

```
pyproject.toml      # package metadata, dependencies, `untis` command
bin/
  untis             # launcher for a dev checkout
src/untis/
  __init__.py       # version
  __main__.py       # python -m untis
  main.py           # CLI
  config.py         # load config.json + .env
  browser.py        # Playwright + stealth
  http_transport.py # plain HTTP login + requests (default)
  untis_client.py   # login (HTTP or browser) + session check + API calls
  normalize.py      # raw data -> clean dicts
  scraper.py        # orchestration
  exporter.py       # JSON output
  summary.py        # --short day view
```
