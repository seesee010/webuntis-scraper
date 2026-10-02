# WebUntis Scraper

![Made With:vibecoding](https://img.shields.io/badge/made%20with-vibecoding-blueviolet?style=plastic)

🇩🇪 [Deutsche Version](README.de.md)

Playwright-based scraper for WebUntis. Fetches your timetable, exams,
homework, absences and messages and saves them as structured JSON.

## How it works

The JSON-RPC endpoint sits behind a WAF that blocks requests without a
real browser context. That's why **everything** runs through Playwright:

1. **Login** through the real login form (only needed when there is no
   valid session in `sessions/storage_state.json`).
2. **Session check**: `GET /WebUntis/api/token/new` only returns a JWT
   for a logged-in session. It provides the `person_id` and role.
3. **All API calls** run in the browser via `page.evaluate(fetch(...))`:
   - Timetable: REST v1 `/api/rest/view/v1/timetable/entries`
     (needs the JWT as Bearer token), fallback JSON-RPC `getTimetable`
   - Exams: `/api/exams`
   - Homework: `/api/homeworks/lessons`
   - Absences: `/api/classreg/absences/students`
   - Messages: REST v1 `/api/rest/view/v1/messages`

`playwright-stealth` patches common bot-detection vectors
(`navigator.webdriver`, `navigator.plugins`, `navigator.languages`, …).

## Installation

Linux / macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

## Install as `untis` command (Linux / macOS)

`bin/untis` is a small launcher that runs the scraper with the
project's `.venv`. Link it into a directory on your `PATH`
(`~/.local/bin` is on the `PATH` of most Linux distros):

```bash
ln -s "$PWD/bin/untis" ~/.local/bin/untis
untis -s --days-forward 0
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
python -m src

# Ignore the saved session and log in again
python -m src --form-login --no-headless --clear-session

# Different time window
python -m src --days-back 7 --days-forward 30

# Also keep the raw API payloads
python -m src --keep-raw -v

# Compact day view in the terminal (JSON is still written)
python -m src --short                   # or -s
python -m src -s --days-forward 0       # today only
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

Removed teachers are struck through (`~OLD~` without colors). Below that come upcoming exams, open homework and a line with
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
3. **CAPTCHA / SSO / 2FA?** → `python -m src --form-login --no-headless`
4. **Screenshot:** `logs/login_failed.png` (in the data directory) shows
   what the browser saw.
5. **Verbose output:** `python -m src -v`.

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
bin/
  untis             # launcher for your PATH
src/
  __init__.py
  main.py           # CLI
  config.py         # load config.json + .env
  browser.py        # Playwright + stealth
  untis_client.py   # login + session check + in-browser API calls
  normalize.py      # raw data -> clean dicts
  scraper.py        # orchestration
  exporter.py       # JSON output
  summary.py        # --short day view
```
