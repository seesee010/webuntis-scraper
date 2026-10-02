# WebUntis Scraper

Playwright-basierter Scraper für WebUntis. Lädt Stundenplan, Prüfungen /
Klausuren, Hausaufgaben, Absenzen und Nachrichten und speichert sie als
strukturiertes JSON.

## Wie es funktioniert

Vor dem JSON-RPC-Endpoint sitzt eine WAF, die Requests ohne echten
Browser-Kontext blockt. Deshalb läuft **alles** über Playwright:

1. **Login** über das echte Login-Formular (nur nötig, wenn keine gültige
   Session in `sessions/storage_state.json` liegt).
2. **Session-Check**: `GET /WebUntis/api/token/new` liefert nur bei
   eingeloggter Session ein JWT. Daraus kommen `person_id` und Rolle.
3. **Alle API-Calls** laufen per `page.evaluate(fetch(...))` im Browser:
   - Stundenplan: REST v1 `/api/rest/view/v1/timetable/entries`
     (braucht das JWT als Bearer), Fallback JSON-RPC `getTimetable`
   - Prüfungen: `/api/exams`
   - Hausaufgaben: `/api/homeworks/lessons`
   - Abwesenheiten: `/api/classreg/absences/students`
   - Nachrichten: REST v1 `/api/rest/view/v1/messages`

`playwright-stealth` patcht typische Bot-Detection-Vektoren
(`navigator.webdriver`, `navigator.plugins`, `navigator.languages`, …).

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

## Als `untis`-Befehl installieren (Linux / macOS)

`bin/untis` startet den Scraper mit dem `.venv` des Projekts. In ein
Verzeichnis im `PATH` verlinken (`~/.local/bin` ist bei den meisten
Linux-Distros im `PATH`):

```bash
ln -s "$PWD/bin/untis" ~/.local/bin/untis
untis -s --days-forward 0
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

## Nutzung

```powershell
# Standard-Lauf (headless, gespeicherte Session wird wiederverwendet)
python -m src

# Gespeicherte Session ignorieren und neu einloggen
python -m src --form-login --no-headless --clear-session

# Anderes Zeitfenster
python -m src --days-back 7 --days-forward 30

# Rohdaten der API zusätzlich behalten
python -m src --keep-raw -v

# Kompakte Tagesansicht im Terminal (JSON wird trotzdem geschrieben)
python -m src --short                   # oder -s
python -m src -s --days-forward 0       # nur heute
```

`--short` zeigt pro Schultag Uhrzeit, Fach, Lehrer und Raum, markiert
`changed` / `cancelled` / `exam`, Supplierungen als `NEU (for ALT)` und
entfernte Lehrer durchgestrichen (`~ALT~` ohne Farben). Darunter folgen
Prüfungen, offene Hausaufgaben, Abwesenheiten und ungelesene Nachrichten.
`NO_COLOR=1` schaltet Farben ab.

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
3. **CAPTCHA / SSO / 2FA?** → `python -m src --form-login --no-headless`
4. **Screenshot:** `logs/login_failed.png` zeigt, was der Browser sah.
5. **Verbose-Output:** `python -m src -v`.

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
    "days": [
      {"date": "2026-06-02", "entries": [
        {
          "start": "2026-06-02T08:00", "end": "2026-06-02T08:45",
          "status": "REGULAR" | "CHANGED" | "CANCELLED" | ...,
          "is_cancelled": false, "is_exam": false, "is_substitution": false,
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
bin/
  untis             # Launcher für den PATH
src/
  __init__.py
  main.py           # CLI
  config.py         # config.json + .env laden
  browser.py        # Playwright + stealth
  untis_client.py   # Login + Session-Check + API-Calls im Browser
  normalize.py      # Rohdaten -> saubere Dicts
  scraper.py        # Orchestrierung
  exporter.py       # JSON-Ausgabe
  summary.py        # --short Tagesansicht
```
