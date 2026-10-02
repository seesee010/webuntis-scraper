# WebUntis Scraper

🇬🇧 [English](README.md) · 🇩🇪 [Deutsch](README.de.md) · 🇫🇷 [Français](README.fr.md) · 🇨🇳 [中文](README.zh.md)

> ⚠️ Cette traduction a été réalisée par une IA (Anthropic Claude Opus 5.5) et peut contenir
> des erreurs ou des formulations maladroites. En cas de doute, la [version anglaise](README.md)
> fait foi.
>
> *This translation was made with AI and may be inaccurate. The English version is authoritative.*

Scraper pour WebUntis (en HTTP simple, avec Playwright en secours). Il récupère ton emploi du temps, tes examens,
tes devoirs, tes absences et tes messages, et les enregistre en JSON structuré.

## Fonctionnement

Par défaut (`--transport auto`), aucun navigateur n'est nécessaire :

1. **Connexion** en envoyant le formulaire de connexion de WebUntis en HTTP simple
   (`/WebUntis/j_spring_security_check`), seulement quand la session enregistrée dans
   `sessions/storage_state.json` a expiré. WebUntis termine les sessions inactives après un
   moment (environ 40 min observées), donc cela arrive souvent.
2. **Vérification de la session** : `GET /WebUntis/api/token/new` ne renvoie un JWT que
   pour une session connectée. Il fournit le `person_id` et le rôle.
3. **Appels à l'API** avec le cookie de session (et le JWT comme jeton Bearer pour
   REST v1) :
   - Emploi du temps : REST v1 `/api/rest/view/v1/timetable/entries`,
     repli sur JSON-RPC `getTimetable`
   - Examens : `/api/exams`
   - Devoirs : `/api/homeworks/lessons`
   - Absences : `/api/classreg/absences/students`
   - Messages : REST v1 `/api/rest/view/v1/messages`

Si la connexion HTTP reçoit une réponse inattendue (par exemple un blocage du WAF, une 2FA
ou un SSO), `untis` passe à un vrai **Chromium via Playwright** : il remplit le formulaire
de connexion et exécute les appels à l'API dans la page. Des identifiants incorrects ne
sont *pas* réessayés dans le navigateur (ce ne serait qu'un deuxième échec de connexion).
Les deux modes partagent le même fichier de session.

| `--transport` | Comportement |
|---|---|
| `auto` (par défaut) | HTTP, navigateur seulement en secours |
| `http` | HTTP uniquement, ne lance jamais de navigateur |
| `browser` | toujours Playwright (aussi avec `--no-headless`) |

En mode navigateur, `playwright-stealth` masque les indices courants de détection de bots
(`navigator.webdriver`, `navigator.plugins`, `navigator.languages`, …).

## Installation

Linux / macOS :

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Windows (PowerShell) :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

## Installer la commande `untis` (Linux / macOS)

`bin/untis` est un petit lanceur qui exécute le scraper avec le `.venv` du projet.
Crée un lien vers ce fichier dans un dossier de ton `PATH` (`~/.local/bin` est dans le
`PATH` de la plupart des distributions Linux) :

```bash
ln -s "$PWD/bin/untis" ~/.local/bin/untis
untis -s --days-forward 0
```

## Configuration

Les fichiers de configuration sont cherchés dans `~/.config/untis/` (ou
`$XDG_CONFIG_HOME/untis/`). Les sessions, les fichiers de sortie et les captures d'écran
de débogage vont alors dans `~/.local/share/untis/`, si bien que `untis` fonctionne
depuis n'importe quel dossier. Sans `~/.config/untis/config.json`, c'est le dossier du
projet qui est utilisé pour tout (pratique sous Windows ou pour le développement).

1. Crée le dossier de configuration et copie l'exemple :

   ```bash
   mkdir -p ~/.config/untis
   cp config.example.json ~/.config/untis/config.json
   ```

   Puis adapte-le :

   ```jsonc
   {
     "server": "nese",           // sous-domaine avant .webuntis.com
     "school": "htbla_kaindorf", // valeur après ?school=
     "username": "max.muster"
   }
   ```

   Pour trouver `server` et `school`, cherche ton école sur
   [webuntis.com](https://webuntis.com). L'URL de redirection contient les deux, par
   exemple `https://nese.webuntis.com/WebUntis/?school=htbla_kaindorf`.

2. Mets ton mot de passe dans `~/.config/untis/.env` :

   ```bash
   cp .env.example ~/.config/untis/.env
   chmod 600 ~/.config/untis/.env
   ```

   ```ini
   UNTIS_PASSWORD=tonMotDePasse
   ```

## Utilisation

```bash
# Exécution par défaut (sans fenêtre, réutilise la session enregistrée)
python -m src

# Ignorer la session enregistrée et se reconnecter
python -m src --form-login --no-headless --clear-session

# Autre période : aujourd'hui plus les 4 prochains jours de cours
# (les week-ends, les vacances et les jours entièrement annulés ne comptent pas)
untis -s --days-forward 4
untis -s --days-back 2 --days-forward 0    # les 2 derniers jours de cours + aujourd'hui
untis -s --days-forward 4 --calendar-days  # compter en jours calendaires

# Raccourcis de date (au lieu de --days-back / --days-forward)
untis -s --today
untis -s --tomorrow        # ou le prochain jour de cours si demain est libre
untis -s --next            # aujourd'hui tant qu'il y a cours, sinon le prochain jour de cours
untis -s --week            # cette semaine, du lundi au dimanche
untis -s --next-week
untis -s --date 12.10.     # aussi 12.10.2026 ou 2026-10-12

# Conserver aussi les données brutes de l'API
python -m src --keep-raw -v

# Vue compacte par jour dans le terminal (le JSON est quand même écrit)
python -m src --short                   # ou -s
python -m src -s --days-forward 0       # seulement aujourd'hui
```

`--short` affiche un bloc par jour de cours : heure, matière, enseignant, salle, et une
indication de ce qui est arrivé au cours :

| Indication | Signification |
|---|---|
| `cancelled` | le cours n'a pas lieu |
| `removed` | le cours a lieu, mais ta classe en a été retirée |
| `no teacher` | l'enseignant a été retiré et personne ne le remplace encore |
| `changed` | autre changement, par exemple un remplaçant : `NOUVEAU (for ANCIEN)` |
| `exam` | examen |
| `event` | un événement, par exemple une sortie (`★ titre`, avec ses enseignants) |

Les enseignants retirés sont barrés (`~ANCIEN~` sans couleurs). L'en-tête de chaque jour
indique quand les cours commencent et finissent réellement ce jour-là, par exemple
`Mon 05.10.  07:50–13:25`.

`--tomorrow` et `--next` regardent le vrai emploi du temps : les week-ends, les vacances
et les jours où tous les cours sont annulés sont sautés ; l'en-tête du jour affiche alors
`(next school day)`.

Sous les jours apparaissent les examens à venir, les devoirs non faits et une ligne avec
les absences et les messages non lus. `NO_COLOR=1` désactive les couleurs.

La sortie est écrite dans `out/untis_<timestamp>.json` et `out/latest.json` dans le
dossier de données (`~/.local/share/untis/`, ou le dossier du projet). Les cookies y
sont enregistrés dans `sessions/storage_state.json`, pour que les exécutions suivantes
n'aient pas besoin de se reconnecter.

### Problèmes de connexion ?

Si la connexion échoue (`Form login did not redirect away from the login page`) alors
que tes identifiants sont corrects, vérifie :

1. **Serveur et identifiant d'école corrects ?** Cherche ton école sur `webuntis.com` ;
   l'URL de redirection est `https://<server>.webuntis.com/WebUntis/?school=<slug>`.
2. **Caractères spéciaux dans le mot de passe ?** `.env` accepte `=` et les guillemets,
   mais les espaces au début sont supprimés.
3. **CAPTCHA / SSO / 2FA ?** → `untis --transport browser --no-headless --form-login`
4. **Capture d'écran :** `logs/login_failed.png` (dans le dossier de données) montre ce
   que le navigateur a vu.
5. **Sortie détaillée :** `python -m src -v`.

### Codes de sortie

Les erreurs sont affichées sur une seule ligne dans stderr (`untis: login failed: …`) ;
ajoute `-v` pour voir la trace complète.

| Code | Signification |
|---|---|
| `0` | succès |
| `1` | erreur inattendue (merci de la signaler) |
| `2` | problème de configuration / d'installation (config manquante, Chromium non installé) |
| `3` | échec de la connexion |
| `4` | WebUntis injoignable ou a renvoyé une erreur |
| `130` | interrompu avec Ctrl-C |

## Format de sortie

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
    "lessons": [...]   // avec le repli jsonrpc
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

## Remarques

- **2FA / CAPTCHA** : si ton école demande un code à usage unique (OTP), lance une fois
  avec `--no-headless --clear-session`, saisis le code, puis utilise le mode sans fenêtre
  ensuite.
- **Examens** : ils viennent de `/api/exams`. Si ce point d'accès n'est pas disponible,
  les examens sont déduits de l'emploi du temps (`source: "timetable_fallback"`).
- **Limite de requêtes** : au maximum une requête toutes les 300 ms.
- **Données brutes** : sans `--keep-raw`, tous les champs `raw` sont supprimés.
- **Stockage** : dans le dossier du projet, `sessions/`, `out/`, `logs/`, `config.json`
  et `.env` sont dans `.gitignore`.

## Structure du projet

```
bin/
  untis             # lanceur pour ton PATH
src/
  __init__.py
  main.py           # ligne de commande
  config.py         # charge config.json + .env
  browser.py        # Playwright + stealth
  http_transport.py # connexion + requêtes en HTTP simple (par défaut)
  untis_client.py   # connexion (HTTP ou navigateur) + vérification de session + appels API
  normalize.py      # données brutes -> dictionnaires propres
  scraper.py        # orchestration
  exporter.py       # sortie JSON
  summary.py        # vue par jour --short
```
