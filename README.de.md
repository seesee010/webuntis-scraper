# WebUntis Scraper

🇬🇧 [English](README.md) · 🇩🇪 [Deutsch](README.de.md) · 🇫🇷 [Français](README.fr.md) · 🇨🇳 [中文](README.zh.md)

Scraper für WebUntis (per HTTP, mit Playwright als Fallback). Lädt Stundenplan, Prüfungen /
Klausuren, Hausaufgaben, Absenzen und Nachrichten und speichert sie als
strukturiertes JSON.

## Wie es funktioniert

Standardmäßig (`--transport auto`) wird kein Browser gebraucht:

1. **Login** per HTTP über das WebUntis-Login-Formular
   (`/WebUntis/j_spring_security_check`), nur wenn die gespeicherte
   Session in `sessions/storage_state.json` abgelaufen ist. WebUntis
   beendet inaktive Sessions nach einer Weile (beobachtet: ~40 min),
   das passiert also oft.
2. **Session-Check**: `GET /WebUntis/api/token/new` liefert nur bei
   eingeloggter Session ein JWT. Daraus kommen `person_id` und Rolle.
3. **API-Calls** mit dem Session-Cookie (und dem JWT als Bearer für
   REST v1):
   - Stundenplan: REST v1 `/api/rest/view/v1/timetable/entries`,
     Fallback JSON-RPC `getTimetable`
   - Prüfungen: `/api/exams`
   - Hausaufgaben: `/api/homeworks/lessons`
   - Abwesenheiten: `/api/classreg/absences/students`
   - Nachrichten: REST v1 `/api/rest/view/v1/messages`

Bekommt der HTTP-Login eine unerwartete Antwort (z.B. WAF, 2FA oder
SSO), weicht `untis` auf einen echten **Chromium über Playwright** aus:
Der füllt das Login-Formular aus und führt die API-Calls in der Seite
aus. Falsche Zugangsdaten werden im Browser *nicht* erneut versucht
(das wäre nur ein zweiter Fehlversuch). Beide Wege nutzen dieselbe
Session-Datei.

| `--transport` | Verhalten |
|---|---|
| `auto` (Standard) | HTTP, Browser nur als Fallback |
| `http` | nur HTTP, startet nie einen Browser |
| `browser` | immer Playwright (auch bei `--no-headless`) |

`playwright-stealth` patcht im Browser-Modus typische
Bot-Detection-Vektoren (`navigator.webdriver`, `navigator.plugins`,
`navigator.languages`, …).

## Installation

### Mit pipx (empfohlen)

[pipx](https://pipx.pypa.io) installiert `untis` als Befehl in einer eigenen, abgeschotteten Umgebung, so dass es nicht mit anderen Python-Paketen kollidiert.

**1. pipx installieren** (einmalig):

```bash
sudo pacman -S python-pipx            # Arch / Omarchy
sudo apt install pipx                 # Debian / Ubuntu
brew install pipx                     # macOS
python -m pip install --user pipx     # alles andere, auch Windows

pipx ensurepath                       # nimmt ~/.local/bin in den PATH auf (danach neues Terminal öffnen)
```

> Getestet wurden hier nur die Befehle für Arch / Omarchy. Die Befehle für Debian / Ubuntu,
> macOS und Windows (und der Windows-Pfad für Chromium weiter unten) stammen aus der
> [offiziellen pipx-Dokumentation](https://pipx.pypa.io/latest/how-to/install-pipx.html) und wurden hier nicht getestet.

**2. `untis` installieren:**

```bash
pipx install git+https://github.com/seesee010/webuntis-scraper
untis --version
```

**3. Schule und Login einrichten**, siehe [Konfiguration](#konfiguration). Danach:

```bash
untis -s --today
```

**Optional: Chromium.** `untis` spricht per HTTP mit WebUntis und braucht einen Browser nur als Fallback (`--transport browser`, 2FA/SSO). So wird er eingerichtet (unter Windows endet der Pfad auf `\webuntis-scraper\Scripts\playwright.exe`):

```bash
"$(pipx environment --value PIPX_LOCAL_VENVS)/webuntis-scraper/bin/playwright" install chromium
```

**Aktualisieren / deinstallieren:**

```bash
pipx reinstall webuntis-scraper       # holt die neueste Version von GitHub
pipx uninstall webuntis-scraper
```

`pipx upgrade` aktualisiert Installationen von GitHub nicht (es prüft nur Paket-Indizes), deshalb `pipx reinstall` verwenden.

Wenn du auch am Code arbeitest, nimm stattdessen das Setup unten. Beide wollen `~/.local/bin/untis` sein, also nicht beides installieren.

### Aus einem Checkout (Entwicklung)

Linux / macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
pytest                     # Tests ausführen
```

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
playwright install chromium
```

`bin/untis` startet den Checkout mit seinem `.venv`, ohne etwas zu installieren. In ein
Verzeichnis im `PATH` verlinken (`~/.local/bin` ist bei den meisten Linux-Distros im `PATH`):

```bash
ln -s "$PWD/bin/untis" ~/.local/bin/untis
untis -s --today
```

## Konfiguration

Die Config wird in `~/.config/untis/` (bzw. `$XDG_CONFIG_HOME/untis/`)
gesucht. Sessions, Output und Debug-Screenshots landen dann in
`~/.local/share/untis/` - `untis` funktioniert so aus jedem Ordner.
Ohne `~/.config/untis/config.json` wird für alles der Projektordner
verwendet (z.B. unter Windows oder zum Entwickeln).

1. Config-Ordner anlegen und Beispiel-Config kopieren:

   ```bash
   mkdir -p ~/.config/untis
   cp config.example.json ~/.config/untis/config.json
   ```

   Dann anpassen:

   ```jsonc
   {
     "server": "nese",           // Subdomain vor .webuntis.com
     "school": "htbla_kaindorf", // Wert hinter ?school=
     "username": "max.muster"
   }
   ```

   `server` + `school` findest du, indem du auf
   [webuntis.com](https://webuntis.com) deine Schule suchst - die
   Redirect-URL enthält beides, z.B.
   `https://nese.webuntis.com/WebUntis/?school=htbla_kaindorf`.

2. Passwort in `~/.config/untis/.env` eintragen:

   ```bash
   cp .env.example ~/.config/untis/.env
   chmod 600 ~/.config/untis/.env
   ```

   ```ini
   UNTIS_PASSWORD=deinPasswort
   ```

3. **Optional: Standard-Argumente.** Optionen, die du immer willst, kommen in die `config.json`:

   ```jsonc
   {
     "default_args": ["--short"]
   }
   ```

   ```bash
   untis                                  # = untis --short
   untis --no-short                       # Standard für einen Lauf abschalten
   UNTIS_DEFAULT_ARGS="-s --today" untis   # dasselbe über die Umgebung
   ```

   Explizite Optionen gewinnen: `untis --transport browser` ersetzt ein voreingestelltes `--transport http`, und ein explizites Zeitfenster (`--week`, `--from`, `--days-forward`, …) ersetzt das voreingestellte, statt mit ihm zu kollidieren. Schalter lassen sich für einen Lauf mit `--no-short`, `--no-keep-raw`, `--no-calendar-days` oder `--no-verbose` abschalten. `UNTIS_DEFAULT_ARGS` funktioniert genauso und hat Vorrang vor der Config; `--config`, `--env`, `--help` und `--version` sind als Standard nicht erlaubt. `untis -v` zeigt die tatsächlich verwendeten Argumente.

## Nutzung

```powershell
# Standard-Lauf (headless, gespeicherte Session wird wiederverwendet)
untis

# Gespeicherte Session ignorieren und neu einloggen
untis --form-login --no-headless --clear-session

# Anderes Zeitfenster: heute plus die nächsten 4 Schultage
# (Wochenenden, Ferien und komplett entfallene Tage zählen nicht)
untis -s --days-forward 4
untis -s --days-back 2 --days-forward 0    # die letzten 2 Schultage + heute
untis -s --days-forward 4 --calendar-days  # stattdessen Kalendertage zählen

# Datums-Kürzel (statt --days-back / --days-forward)
untis -s --today
untis -s --tomorrow        # bzw. der nächste Schultag, wenn morgen frei ist
untis -s --next            # heute, solange Schule ist, sonst der nächste Schultag
untis -s --week            # diese Woche, Mo–So
untis -s --next-week
untis -s --date 12.10.     # auch 12.10.2026 oder 2026-10-12
untis -s --from mon --to fri     # diese Schulwoche
untis -s --from tue --to mon     # Di dieser Woche bis Mo nächster Woche
untis -s --to fri                # ab heute bis Freitag
untis -s --offline               # aus den zuletzt geladenen Daten, ohne Netzwerk
untis -s --max-age 10m           # Cache, wenn jünger als 10 min, sonst laden

# Rohdaten der API zusätzlich behalten
untis --keep-raw -v

# Kompakte Tagesansicht im Terminal (JSON wird trotzdem geschrieben)
untis --short                   # oder -s
untis -s --days-forward 0       # nur heute
untis --oneline --week          # eine Zeile pro Tag
untis --table --week            # Wochenraster: Tage als Spalten, Stunden als Zeilen
untis --start tomorrow           # erste Stunde morgen, die stattfindet, z.B. 07:50
untis --end                      # wann die Schule heute aus ist
untis --free next                # Freistunden am nächsten Schultag
untis --start tomorrow || echo "sleep in"   # Exit-Code 5 = an dem Tag keine Schule
untis --tests                    # alle kommenden Tests bis Schuljahresende
untis -t --days-back 30 --days-forward 0   # Tests der letzten 30 Schultage (mit Noten)
```

`--from` / `--to` verstehen alles, was `--date` versteht, dazu `today`/`heute`, `tomorrow`/`morgen` und Wochentage auf Englisch oder Deutsch (`mon`, `monday`, `mo`, `montag`, …). Ein Wochentag meint den dieser Woche; läge `--to` dadurch vor `--from`, den der nächsten Woche.

Jeder echte Lauf speichert seine Daten in `~/.local/share/untis/cache/last.json` (privat, ohne `raw`). `--offline` antwortet nur von dort und greift nie aufs Netzwerk zu; deckt der Cache die gewünschten Tage nicht ab (oder stammt er von einem anderen Account), sagt es das und beendet sich mit Code 4. `--max-age` nutzt den Cache, wenn er jung genug ist und die Anfrage abdeckt, sonst wird geladen. Antworten aus dem Cache zeigen ihr Alter im Kopf, z.B. `(cached, 14 min old)`, und schreiben keine neuen JSON-Dateien.

`--short` zeigt pro Schultag Uhrzeit, Fach, Lehrer und Raum und markiert,
was mit der Stunde passiert ist:

| Markierung | Farbe | Bedeutung |
|---|---|---|
| `cancelled` | rot, durchgestrichen | Entfall, die Stunde findet nicht statt |
| `removed` | grau, durchgestrichen | die Stunde findet statt, aber deine Klasse ist ausgetragen |
| `no teacher` | gelb | Lehrer ausgetragen, (noch) keine Supplierung |
| `changed` | grün; Ersatzlehrer / neuer Raum fett grün | sonstige Änderung, z.B. Supplierung: `NEU (for ALT)` |
| `exam` | fett magenta | Prüfung |
| `event` | fett blau | Veranstaltung, z.B. Exkursion (`★ Titel`, mit Lehrern) |

Entfernte Lehrer werden durchgestrichen (`~ALT~` ohne Farben). Der
Tageskopf zeigt, wann die Schule an dem Tag wirklich beginnt und endet,
z.B. `Mon 05.10.  07:50–13:25`.

Für heute zeigt die Tagesansicht außerdem, wo du gerade bist: Die laufende
Stunde bekommt ein `▶` und die Restzeit, vergangene Stunden werden
abgedunkelt, und in der Pause oder vor Schulbeginn zeigt eine „now“-Linie,
wann die nächste Stunde beginnt. Entfallene Stunden werden nie als aktuell
markiert, nach Schulschluss wird nichts markiert.

```
  07:50–09:35  MATH  TCH1  R101                       (dimmed: already over)
▶ 09:40–10:30  GER   TCH2  R101   now · 18 min left
  10:45–11:35  PROG  TCH3  R101

  ──── now 10:37 · next in 8 min ────                 (in a break)
```

`--tomorrow` und `--next` schauen in den echten Stundenplan: Wochenenden,
Ferien und Tage, an denen alles entfällt, werden übersprungen; im
Tageskopf steht dann `(next school day)`.

Unter den Tagen folgen Prüfungen, offene Hausaufgaben, Abwesenheiten und
ungelesene Nachrichten. Farben gibt es nur im Terminal; `--color always` erzwingt sie (z.B. für `less -R`), `--color never` oder `NO_COLOR=1` schaltet sie ab. `untis --legend` zeigt, was jede Farbe und Markierung bedeutet.

Zwei weitere kompakte Ansichten. `--oneline` zeigt eine Zeile pro Tag, mit einem Eintrag pro Stunde des Zeitrasters der Schule (eine Doppelstunde erscheint zweimal, eine Freistunde als `-`, parallele Gruppen als `NET/PROG`). `--table` zeigt ein Raster mit den Tagen als Spalten und den Stunden als Zeilen, eine Tabelle pro Woche, passend zur Terminalbreite, danach wie bei `-s` Prüfungen und Hausaufgaben. Beide verwenden dieselben Farben; ohne Farben markiert `*` eine Änderung, `~X~` eine entfallene oder ausgetragene Stunde und `!` eine Prüfung.

```
Mon 05.10.  07:50–13:25  MATH MATH GER - ENG* PROG
Tue 06.10.  07:50–13:25  NET/PROG NET/PROG ~GEO~ MATH! SOC GEO
```

`--start`, `--end` und `--free` beantworten eine Frage zu einem Tag und geben nur die Antwort aus: `today` (Standard), `tomorrow`, `next` (der nächste Schultag), ein Datum oder ein Wochentag (der nächste). Entfallene Stunden und Stunden, aus denen deine Klasse ausgetragen ist, zählen nicht; eine entfallene erste Stunde verschiebt `--start` also nach hinten. Freistunden kommen aus dem Zeitraster der Schule. Ist an dem Tag keine Schule, wird `-` ausgegeben und mit Code 5 beendet. `--format json` gibt `{"date", "start", "end", "first", "free"}` aus. Es wird nur der Stundenplan geladen, und es werden keine JSON-Dateien geschrieben.

`--tests` (auch `-t` / `--exams`) zeigt nur Tests und Prüfungen, sortiert nach Datum mit „in N days“, der Note, falls WebUntis eine hat, und vergangenen Tests abgedunkelt. Ohne Zeitraum reicht es von heute bis zum Ende des Schuljahrs (das `days_forward` aus deiner Config gilt hier nicht); mit `--days-forward`, `--from`, `--week`, … nur dieser Zeitraum. Es werden nur die Prüfungen geladen.

Output landet in `out/untis_<timestamp>.json` sowie `out/latest.json`
im Datenordner (`~/.local/share/untis/` bzw. Projektordner). In
`sessions/storage_state.json` werden dort Cookies gespeichert, damit
Folge-Läufe kein erneutes Login brauchen.

### Login-Fehler?

Falls der Login fehlschlägt (`Form login did not redirect away from the
login page`), obwohl die Credentials stimmen, prüfe:

1. **Server + Slug korrekt?** Auf `webuntis.com` deine Schule suchen -
   die Redirect-URL lautet `https://<server>.webuntis.com/WebUntis/?school=<slug>`.
2. **Sonderzeichen im Passwort?** `.env` unterstützt `=` und Quotes,
   aber führende Whitespaces werden getrimmt. Test mit `python -c "import
   os; print(repr(os.environ['UNTIS_PASSWORD']))"`.
3. **CAPTCHA / SSO / 2FA?** → `untis --transport browser --no-headless --form-login`
4. **Screenshot:** `logs/login_failed.png` zeigt, was der Browser sah.
5. **Verbose-Output:** `untis -v`.

### Exit-Codes

Fehler erscheinen als eine Zeile auf stderr (`untis: login failed: …`);
mit `-v` gibt es den vollen Traceback.

| Code | Bedeutung |
|---|---|
| `0` | Erfolg |
| `1` | unerwarteter Fehler (bitte melden) |
| `2` | Config-/Setup-Problem (Config fehlt, Chromium nicht installiert) |
| `3` | Login fehlgeschlagen |
| `4` | WebUntis nicht erreichbar oder Fehler vom Server |
| `5` | `--start` / `--end` / `--free`: an dem Tag keine Schule (gibt `-` aus) |
| `130` | mit Strg-C abgebrochen |

## Output-Schema

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
          "teachers": [{"short":"NEU","long":"...","status":"ADDED","replaces":"ALT"}],
          "classes": [...], "rooms": [...]
        }
      ]}
    ],
    "lessons": [...]   // bei jsonrpc-Fallback
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

## Sicherheit

`untis` speichert persönliche Daten und hält sie deshalb nur für dein Benutzerkonto lesbar:

- **Passwort:** `~/.config/untis/.env`. Nur für dich lesbar machen (`chmod 600`). `untis` warnt, wenn andere Nutzer die Datei lesen können.
- **Login-Session:** Mit den Cookies in `~/.local/share/untis/sessions/storage_state.json` kann jeder, der die Datei hat, bis zum Ablauf der Session als du auftreten. Die Datei wird mit Rechten `600` in einem `700`-Ordner angelegt.
- **Output und Debug-Dateien:** `out/` und `cache/` (dein Name, Stundenplan, Abwesenheiten) und `logs/` (Screenshots der WebUntis-Seite) sind ebenfalls privat, Dateien älterer Versionen werden beim nächsten Lauf korrigiert. Screenshots vor dem Teilen prüfen.
- **Browser-Sandbox:** Chromium läuft mit eingeschalteter Sandbox. Nur in Docker oder ähnlichen Umgebungen, die es brauchen, `"browser_no_sandbox": true` in `config.json` setzen (als root wird es automatisch aktiviert).

```bash
chmod 600 ~/.config/untis/.env                            # nur du kannst dein Passwort lesen
untis --clear-session                                     # abmelden: gespeicherte Session verwerfen
rm ~/.local/share/untis/sessions/storage_state.json       # dasselbe von Hand
```

## Hinweise

- **2FA / Captcha**: Falls deine Schule OTP verlangt, einmalig mit
  `--no-headless --clear-session` laufen lassen, Code eintippen, dann
  ab sofort headless.
- **Prüfungen**: kommen aus `/api/exams`. Falls der Endpoint nicht
  verfügbar ist, werden Prüfungen aus dem Stundenplan abgeleitet
  (`source: "timetable_fallback"`).
- **Rate-Limit**: Wir senden höchstens eine Anfrage alle 300 ms.
- **Rohdaten**: ohne `--keep-raw` werden alle `raw`-Felder entfernt.
- **Speicherort**: `sessions/` und `out/` sind in `.gitignore`.

## Projektstruktur

```
pyproject.toml      # Paket-Metadaten, Abhängigkeiten, `untis`-Befehl
bin/
  untis             # Launcher für einen Dev-Checkout
src/untis/
  __init__.py       # Version
  __main__.py       # python -m untis
  main.py           # CLI
  config.py         # config.json + .env laden
  browser.py        # Playwright + stealth
  http_transport.py # Login + Requests per HTTP (Standard)
  untis_client.py   # Login (HTTP oder Browser) + Session-Check + API-Calls
  normalize.py      # Rohdaten -> saubere Dicts
  scraper.py        # Orchestrierung
  exporter.py       # JSON-Ausgabe
  summary.py        # --short Tagesansicht
```
