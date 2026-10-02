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
   sessions after 15 minutes of inactivity, so this happens often.
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
> [official pipx documentation](https://pipx.pypa.io/latest/how-to/install-pipx.html) and weren't tested here.

**2. Install `untis`:**

```bash
pipx install git+https://github.com/seesee010/webuntis-scraper
untis --version
```

**3. Configure** your school and login with `untis init` (or by hand, see [Configuration](#configuration)). Then:

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

`pip install -e` also creates the command `.venv/bin/untis`, which always runs the code of this
checkout. Link it into a directory on your `PATH` (`~/.local/bin` is on the `PATH` of most Linux
distros):

```bash
ln -s "$PWD/.venv/bin/untis" ~/.local/bin/untis
untis -s --today
```

## Configuration

Config files are looked up in `~/.config/untis/` (or
`$XDG_CONFIG_HOME/untis/`). Sessions, output and debug screenshots then
go to `~/.local/share/untis/`, so `untis` works from any directory.
Without `~/.config/untis/config.json`, the project folder is used for
everything instead (handy on Windows or for development).

**Quick setup:** `untis init` asks for any WebUntis URL of your school (the login page, or any page of the new UI such as `…/today`; the school is then looked up via the public WebUntis school search), your username and password, tests the login, and writes `config.json` and `.env` (mode `600`). Existing files are updated, not replaced, and the password is never shown. For 2FA/SSO accounts, add `--no-verify`.

```bash
untis init                                         # interactive: school URL, username, password, login test
untis init --search "School name"                  # find the school by name instead
untis init --url URL --username NAME < password   # for scripts (password from stdin)
```

**Or by hand:**

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

3. **Optional: default arguments.** Options you always want can go into `config.json`:

   ```jsonc
   {
     "default_args": ["--short"]
   }
   ```

   ```bash
   untis                                  # = untis --short
   untis --no-short                       # turn the default off for one run
   UNTIS_DEFAULT_ARGS="-s --today" untis   # same via the environment
   ```

   Explicit options win: `untis --transport browser` replaces a default `--transport http`, and an explicit date window (`--week`, `--from`, `--days-forward`, …) replaces a default one instead of clashing with it. Flags can be turned off for one run with `--no-short`, `--no-keep-raw`, `--no-calendar-days` or `--no-verbose`. `UNTIS_DEFAULT_ARGS` works the same way and wins over the config; `--config`, `--env`, `--help` and `--version` aren't allowed as defaults. `untis -v` logs the effective arguments.

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
untis -s --from mon --to fri     # this school week
untis -s --from tue --to mon     # Tue this week to Mon next week
untis -s --to fri                # from today until Friday
untis -s --offline               # from the last fetched data, no network
untis -s --max-age 10m           # cached data if younger than 10 min, else fetch

# Also keep the raw API payloads
untis --keep-raw -v

# Compact day view in the terminal (JSON is still written)
untis --short                   # or -s
untis -s --days-forward 0       # today only
untis --oneline --week          # one line per day
untis --table --week            # week grid: days as columns, periods as rows
untis --start tomorrow           # first lesson that takes place tomorrow, e.g. 07:50
untis --end                      # when school ends today
untis --free next                # free periods on the next school day
untis --start tomorrow || echo "sleep in"   # exit code 5 = no school that day
untis --tests                    # all upcoming tests until the end of the school year
untis -t --days-back 30 --days-forward 0   # tests of the last 30 school days (with grades)
untis --homework                 # all homework of this school year
untis -H --days-forward 5        # homework due in the next 5 school days
untis -t -H                      # both sections
untis --now                      # the current and the next lesson
untis --now --format waybar      # JSON for a Waybar custom module
untis --changes                  # what changed since the last --changes run
untis --changes --notify         # … and as desktop notifications
```

`--from` / `--to` accept everything `--date` does, plus `today`, `tomorrow` and weekday names in English or German (`mon`, `monday`, `mo`, `montag`, …). A weekday means this week's; if `--to` would end up before `--from`, it means next week's.

Every real run saves its data in `~/.local/share/untis/cache/last.json` (private, without `raw`). `--offline` answers only from there and never touches the network; if the cache doesn't cover the requested days (or is from another account), it says so and exits with code 4. `--max-age` uses the cache when it is recent enough and covers the request, and fetches otherwise. Answers from the cache show their age in the header, e.g. `(cached, 14 min old)`, and don't write new JSON files.

`--short` prints one block per school day: time, subject, teacher, room,
plus a marker for what happened to the lesson:

| Marker | Color | Meaning |
|---|---|---|
| `cancelled` | red, struck through | the lesson doesn't take place |
| `removed` | gray, struck through | the lesson takes place, but your class was taken out of it |
| `no teacher` | yellow | the teacher was removed and nobody replaces them yet |
| `changed` | green; the substitute / new room in bold green | something else changed, e.g. a substitute: `NEW (for OLD)` |
| `exam` | bold magenta | exam lesson |
| `event` | bold blue | an event such as an excursion (`★ title`, with its teachers) |

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
absences and unread messages. Colors are only used on a terminal; `--color always` forces them (e.g. for `less -R`), `--color never` or `NO_COLOR=1` turns them off. `untis --legend` prints what each color and marker means.

Two more compact layouts. `--oneline` prints one line per day, with one token per period of the school's time grid (a double lesson appears twice, a free period as `-`, parallel groups as `NET/PROG`). `--table` prints a grid with the days as columns and the periods as rows, one table per week, fitted to the terminal width, followed by the exams/homework part like `-s`. Both use the same colors; without colors, `*` marks a change, `~X~` a cancelled or removed lesson and `!` an exam.

```
Mon 05.10.  07:50–13:25  MATH MATH GER - ENG* PROG
Tue 06.10.  07:50–13:25  NET/PROG NET/PROG ~GEO~ MATH! SOC GEO
```

`--start`, `--end` and `--free` answer one question about a day and print only the answer: `today` (the default), `tomorrow`, `next` (the next school day), a date, or a weekday (the next one). Cancelled lessons and lessons your class was removed from don't count, so a cancelled first period moves `--start` later. Free periods come from the school's time grid. With no school that day they print `-` and exit with code 5. `--format json` prints `{"date", "start", "end", "first", "free"}`. Only the timetable is fetched, and no JSON files are written.

`--tests` (also `-t` / `--exams`) shows only tests and exams, sorted by date with "in N days", the grade if WebUntis has one, and past tests dimmed. Without a window it covers everything from today until the end of the school year (the `days_forward` from your config doesn't apply here); with `--days-forward`, `--from`, `--week`, … only that window. Only the exams are fetched.

`--homework` (also `-H`) shows only homework: open ones first by due date (overdue ones in red), then completed ones dimmed with a ✓, each with its full text wrapped to the terminal, a note and attachments if there are any. Without a window it covers the whole school year; with `--days-forward`, `--from`, … only homework *due* in that window (WebUntis filters by the lesson it was given in, so `untis` looks further back and filters by due date itself). Together with `--tests` both sections are shown.

`--now` shows the lesson running right now (with the time left) and the next one; after school or on a weekend, the first lesson of the next school day. `--format json` prints the same as data, `--format waybar` the JSON a [Waybar](https://github.com/Alexays/Waybar) custom module expects (`text`, `tooltip`, `class`, where `class` is the lesson's status or `idle`). `--idle-empty` prints nothing between lessons so the module hides. With `--max-age` the bar is fed from the cache instead of hitting WebUntis every minute:

```jsonc
// ~/.config/waybar/config.jsonc
"custom/untis": {
  "exec": "untis --now --format waybar --max-age 10m --idle-empty",
  "return-type": "json",
  "interval": 60
}
```

`--changes` compares the timetable, exams and homework with the snapshot of the previous `--changes` run (kept privately in `~/.local/share/untis/state/`) and prints only what changed: cancellations, substitutions, room changes, lessons your class was removed from or that disappeared, new or removed exams, new homework. Only days in both windows are compared. The first run just saves the snapshot. Exit code `10` means something changed, `0` nothing. `--notify` also sends each change as a desktop notification (`notify-send` on Linux, `osascript` on macOS). `contrib/systemd/` has a user timer that does this every 15 minutes on school days:

```bash
cp contrib/systemd/untis-changes.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now untis-changes.timer
```

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
| `5` | `--start` / `--end` / `--free`: no school that day (prints `-`) |
| `10` | `--changes`: something changed since the last run |
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

## Security

`untis` stores personal data, so it keeps it private to your user account:

- **Password:** `~/.config/untis/.env`. Make it readable only by you (`chmod 600`). `untis` warns if other users can read it.
- **Login session:** the cookies in `~/.local/share/untis/sessions/storage_state.json` let anyone with the file act as you until the session expires. The file is created with mode `600` in a `700` directory.
- **Output and debug files:** `out/`, `cache/`, `state/` (your name, timetable, absences) and `logs/` (screenshots of the WebUntis page) are private as well, and files from older versions are fixed on the next run. Check screenshots before sharing them.
- **Browser sandbox:** Chromium runs with its sandbox enabled. Only in Docker or similar setups that need it, set `"browser_no_sandbox": true` in `config.json` (it is enabled automatically when running as root).

```bash
chmod 600 ~/.config/untis/.env                            # only you can read your password
untis --clear-session                                     # log out: drop the saved session
rm ~/.local/share/untis/sessions/storage_state.json       # the same, by hand
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
contrib/systemd/    # user timer for --changes --notify
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
