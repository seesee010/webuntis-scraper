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
   `sessions/storage_state.json` a expiré. WebUntis termine les sessions inactives après 15
   minutes d'inactivité, donc cela arrive souvent.
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

### Avec pipx (recommandé)

[pipx](https://pipx.pypa.io) installe `untis` comme commande dans son propre environnement isolé, sans conflit avec d'autres paquets Python.

**1. Installer pipx** (une seule fois) :

```bash
sudo pacman -S python-pipx            # Arch / Omarchy
sudo apt install pipx                 # Debian / Ubuntu
brew install pipx                     # macOS
python -m pip install --user pipx     # tout le reste, y compris Windows

pipx ensurepath                       # ajoute ~/.local/bin au PATH (ouvre ensuite un nouveau terminal)
```

> Seules les commandes pour Arch / Omarchy ont été testées ici. Les commandes pour Debian / Ubuntu,
> macOS et Windows (ainsi que le chemin Windows pour Chromium plus bas) proviennent de la
> [documentation officielle de pipx](https://pipx.pypa.io/latest/how-to/install-pipx.html) et n'ont pas été testées ici.

**2. Installer `untis` :**

```bash
pipx install git+https://github.com/seesee010/webuntis-scraper
untis --version
```

**3. Configurer** ton école et ta connexion avec `untis init` (ou à la main, voir [Configuration](#configuration)). Ensuite :

```bash
untis -s --today
```

**Optionnel : Chromium.** `untis` communique avec WebUntis en HTTP simple et n'a besoin d'un navigateur qu'en secours (`--transport browser`, 2FA/SSO). Pour l'activer (sous Windows, le chemin se termine par `\webuntis-scraper\Scripts\playwright.exe`) :

```bash
"$(pipx environment --value PIPX_LOCAL_VENVS)/webuntis-scraper/bin/playwright" install chromium
```

**Mettre à jour / désinstaller :**

```bash
pipx reinstall webuntis-scraper       # récupère la dernière version depuis GitHub
pipx uninstall webuntis-scraper
```

`pipx upgrade` ne met pas à jour les installations depuis GitHub (il ne consulte que les index de paquets), utilise donc `pipx reinstall`.

Si tu travailles aussi sur le code, utilise plutôt l'installation ci-dessous. Les deux veulent être `~/.local/bin/untis`, n'installe donc pas les deux.

### Depuis une copie du dépôt (développement)

Linux / macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
pytest                     # lancer les tests
```

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
playwright install chromium
```

`pip install -e` crée aussi la commande `.venv/bin/untis`, qui exécute toujours le code de cette
copie du dépôt. Crée un lien vers elle dans un dossier de ton `PATH` (`~/.local/bin` est dans le
`PATH` de la plupart des distributions Linux) :

```bash
ln -s "$PWD/.venv/bin/untis" ~/.local/bin/untis
untis -s --today
```

## Configuration

Les fichiers de configuration sont cherchés dans `~/.config/untis/` (ou
`$XDG_CONFIG_HOME/untis/`). Les sessions, les fichiers de sortie et les captures d'écran
de débogage vont alors dans `~/.local/share/untis/`, si bien que `untis` fonctionne
depuis n'importe quel dossier. Sans `~/.config/untis/config.json`, c'est le dossier du
projet qui est utilisé pour tout (pratique sous Windows ou pour le développement).

**Configuration rapide :** `untis init` demande une URL WebUntis quelconque de ton école (la page de connexion, ou une page de la nouvelle interface comme `…/today` ; l'école est alors trouvée via la recherche publique d'écoles de WebUntis), ton identifiant et ton mot de passe, teste la connexion et écrit `config.json` et `.env` (mode `600`). Les fichiers existants sont mis à jour, pas remplacés, et le mot de passe n'est jamais affiché. Pour les comptes 2FA/SSO, ajoute `--no-verify`.

```bash
untis init                                         # interactif : URL de l'école, identifiant, mot de passe, test de connexion
untis init --search "School name"                  # chercher l'école par son nom
untis init --url URL --username NAME < password   # pour les scripts (mot de passe via stdin)
```

**Ou à la main :**

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

3. **Optionnel : arguments par défaut.** Les options que tu veux toujours peuvent aller dans `config.json` :

   ```jsonc
   {
     "default_args": ["--short"]
   }
   ```

   ```bash
   untis                                  # = untis --short
   untis --no-short                       # désactiver le défaut pour une exécution
   UNTIS_DEFAULT_ARGS="-s --today" untis   # pareil via l'environnement
   ```

   Les options explicites l'emportent : `untis --transport browser` remplace un `--transport http` par défaut, et une période explicite (`--week`, `--from`, `--days-forward`, …) remplace celle par défaut au lieu d'entrer en conflit. Les options booléennes se désactivent pour une exécution avec `--no-short`, `--no-keep-raw`, `--no-calendar-days` ou `--no-verbose`. `UNTIS_DEFAULT_ARGS` fonctionne de la même façon et l'emporte sur la configuration ; `--config`, `--env`, `--help` et `--version` ne sont pas autorisés par défaut. `untis -v` affiche les arguments réellement utilisés.

## Utilisation

```bash
# Exécution par défaut (sans fenêtre, réutilise la session enregistrée)
untis

# Ignorer la session enregistrée et se reconnecter
untis --form-login --no-headless --clear-session

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
untis -s --from mon --to fri     # cette semaine de cours
untis -s --from tue --to mon     # du mar. de cette semaine au lun. suivant
untis -s --to fri                # d'aujourd'hui à vendredi
untis -s --offline               # depuis les dernières données, sans réseau
untis -s --max-age 10m           # cache s'il a moins de 10 min, sinon charger

# Conserver aussi les données brutes de l'API
untis --keep-raw -v

# Vue compacte par jour dans le terminal (le JSON est quand même écrit)
untis --short                   # ou -s
untis -s --days-forward 0       # seulement aujourd'hui
untis --oneline --week          # une ligne par jour
untis --table --week            # grille de la semaine : jours en colonnes, heures en lignes
untis --start tomorrow           # premier cours qui a lieu demain, par ex. 07:50
untis --end                      # fin des cours aujourd'hui
untis --free next                # heures libres au prochain jour de cours
untis --start tomorrow || echo "sleep in"   # code de sortie 5 = pas de cours ce jour-là
untis --tests                    # tous les contrôles à venir jusqu'à la fin de l'année scolaire
untis -t --days-back 30 --days-forward 0   # contrôles des 30 derniers jours de cours (avec notes)
untis --homework                 # tous les devoirs de cette année scolaire
untis -H --days-forward 5        # devoirs à rendre dans les 5 prochains jours de cours
untis -t -H                      # les deux sections
untis --now                      # le cours actuel et le suivant
untis --now --format waybar      # JSON pour un module personnalisé Waybar
untis --changes                  # ce qui a changé depuis la dernière exécution de --changes
untis --changes --notify         # … et en notifications de bureau
```

`--from` / `--to` acceptent tout ce que `--date` accepte, plus `today`, `tomorrow` et les jours de la semaine en anglais ou en allemand (`mon`, `monday`, `mo`, `montag`, …). Un jour de la semaine désigne celui de cette semaine ; si `--to` tombait alors avant `--from`, c'est celui de la semaine suivante.

Chaque exécution réelle enregistre ses données dans `~/.local/share/untis/cache/last.json` (privé, sans `raw`). `--offline` répond uniquement à partir de là et n'utilise jamais le réseau ; si le cache ne couvre pas les jours demandés (ou vient d'un autre compte), il le dit et se termine avec le code 4. `--max-age` utilise le cache s'il est assez récent et couvre la demande, sinon il charge les données. Les réponses depuis le cache affichent leur âge dans l'en-tête, par ex. `(cached, 14 min old)`, et n'écrivent pas de nouveaux fichiers JSON.

`--short` affiche un bloc par jour de cours : heure, matière, enseignant, salle, et une
indication de ce qui est arrivé au cours :

| Indication | Couleur | Signification |
|---|---|---|
| `cancelled` | rouge, barré | le cours n'a pas lieu |
| `removed` | gris, barré | le cours a lieu, mais ta classe en a été retirée |
| `no teacher` | jaune | l'enseignant a été retiré et personne ne le remplace encore |
| `changed` | vert ; le remplaçant / la nouvelle salle en vert gras | autre changement, par exemple un remplaçant : `NOUVEAU (for ANCIEN)` |
| `exam` | magenta gras | examen |
| `event` | bleu gras | un événement, par exemple une sortie (`★ titre`, avec ses enseignants) |

Les enseignants retirés sont barrés (`~ANCIEN~` sans couleurs). L'en-tête de chaque jour
indique quand les cours commencent et finissent réellement ce jour-là, par exemple
`Mon 05.10.  07:50–13:25`.

Pour aujourd'hui, la vue par jour montre aussi où tu en es : le cours en
cours reçoit un `▶` et le temps restant, les cours terminés sont grisés, et
pendant une pause ou avant les cours, une ligne « now » indique quand le
prochain cours commence. Les cours annulés ne sont jamais marqués comme en
cours, et après les cours rien n'est marqué.

```
  07:50–09:35  MATH  TCH1  R101                       (dimmed: already over)
▶ 09:40–10:30  GER   TCH2  R101   now · 18 min left
  10:45–11:35  PROG  TCH3  R101

  ──── now 10:37 · next in 8 min ────                 (in a break)
```

`--tomorrow` et `--next` regardent le vrai emploi du temps : les week-ends, les vacances
et les jours où tous les cours sont annulés sont sautés ; l'en-tête du jour affiche alors
`(next school day)`.

Sous les jours apparaissent les examens à venir, les devoirs non faits et une ligne avec
les absences et les messages non lus. Les couleurs ne sont utilisées que dans un terminal ; `--color always` les force (par ex. pour `less -R`), `--color never` ou `NO_COLOR=1` les désactive. `untis --legend` affiche la signification de chaque couleur et indication.

Deux autres vues compactes. `--oneline` affiche une ligne par jour, avec un élément par heure de la grille horaire de l'école (un cours double apparaît deux fois, une heure libre comme `-`, les groupes parallèles comme `NET/PROG`). `--table` affiche une grille avec les jours en colonnes et les heures en lignes, un tableau par semaine, adapté à la largeur du terminal, suivi des examens et devoirs comme avec `-s`. Les deux utilisent les mêmes couleurs ; sans couleurs, `*` indique un changement, `~X~` un cours annulé ou retiré et `!` un examen.

```
Mon 05.10.  07:50–13:25  MATH MATH GER - ENG* PROG
Tue 06.10.  07:50–13:25  NET/PROG NET/PROG ~GEO~ MATH! SOC GEO
```

`--start`, `--end` et `--free` répondent à une question sur un jour et n'affichent que la réponse : `today` (par défaut), `tomorrow`, `next` (le prochain jour de cours), une date ou un jour de la semaine (le prochain). Les cours annulés et ceux dont ta classe a été retirée ne comptent pas ; un premier cours annulé décale donc `--start`. Les heures libres viennent de la grille horaire de l'école. S'il n'y a pas cours ce jour-là, `-` est affiché et le code de sortie est 5. `--format json` affiche `{"date", "start", "end", "first", "free"}`. Seul l'emploi du temps est chargé, et aucun fichier JSON n'est écrit.

`--tests` (aussi `-t` / `--exams`) n'affiche que les contrôles et examens, triés par date avec « in N days », la note si WebUntis en a une, et les contrôles passés grisés. Sans période, il couvre tout d'aujourd'hui à la fin de l'année scolaire (le `days_forward` de ta configuration ne s'applique pas ici) ; avec `--days-forward`, `--from`, `--week`, … seulement cette période. Seuls les examens sont chargés.

`--homework` (aussi `-H`) n'affiche que les devoirs : ceux à faire d'abord par date d'échéance (en retard en rouge), puis ceux terminés grisés avec un ✓, chacun avec son texte complet adapté à la largeur du terminal, une remarque et les pièces jointes s'il y en a. Sans période, il couvre toute l'année scolaire ; avec `--days-forward`, `--from`, … seulement les devoirs *à rendre* dans cette période (WebUntis filtre par le cours où ils ont été donnés, donc `untis` regarde plus loin en arrière et filtre lui-même par échéance). Avec `--tests`, les deux sections sont affichées.

`--now` affiche le cours en cours (avec le temps restant) et le suivant ; après les cours ou le week-end, le premier cours du prochain jour de cours. `--format json` affiche la même chose sous forme de données, `--format waybar` le JSON attendu par un module personnalisé [Waybar](https://github.com/Alexays/Waybar) (`text`, `tooltip`, `class`, où `class` est le statut du cours ou `idle`). `--idle-empty` n'affiche rien entre les cours pour que le module se masque. Avec `--max-age`, la barre est alimentée par le cache au lieu d'interroger WebUntis chaque minute :

```jsonc
// ~/.config/waybar/config.jsonc
"custom/untis": {
  "exec": "untis --now --format waybar --max-age 10m --idle-empty",
  "return-type": "json",
  "interval": 60
}
```

`--changes` compare l'emploi du temps, les examens et les devoirs avec l'état de l'exécution précédente de `--changes` (gardé en privé dans `~/.local/share/untis/state/`) et n'affiche que les changements : annulations, remplacements, changements de salle, cours dont ta classe a été retirée ou qui ont disparu, examens ajoutés ou supprimés, nouveaux devoirs. Seuls les jours présents dans les deux périodes sont comparés. La première exécution enregistre seulement l'état. Le code de sortie `10` signifie qu'il y a eu un changement, `0` aucun. `--notify` envoie aussi chaque changement en notification de bureau (`notify-send` sous Linux, `osascript` sous macOS). `contrib/systemd/` contient un minuteur utilisateur qui le fait toutes les 15 minutes les jours de cours :

```bash
cp contrib/systemd/untis-changes.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now untis-changes.timer
```

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
5. **Sortie détaillée :** `untis -v`.

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
| `5` | `--start` / `--end` / `--free` : pas de cours ce jour-là (affiche `-`) |
| `10` | `--changes` : quelque chose a changé depuis la dernière exécution |
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

## Sécurité

`untis` enregistre des données personnelles et les garde donc lisibles uniquement par ton compte :

- **Mot de passe :** `~/.config/untis/.env`. Rends-le lisible uniquement par toi (`chmod 600`). `untis` avertit si d'autres utilisateurs peuvent le lire.
- **Session de connexion :** avec les cookies de `~/.local/share/untis/sessions/storage_state.json`, toute personne qui possède le fichier peut agir en ton nom jusqu'à l'expiration de la session. Le fichier est créé avec le mode `600` dans un dossier `700`.
- **Sorties et fichiers de débogage :** `out/`, `cache/`, `state/` (ton nom, emploi du temps, absences) et `logs/` (captures de la page WebUntis) sont aussi privés, et les fichiers des anciennes versions sont corrigés à la prochaine exécution. Vérifie les captures avant de les partager.
- **Sandbox du navigateur :** Chromium tourne avec sa sandbox activée. Seulement dans Docker ou des environnements similaires qui en ont besoin, mets `"browser_no_sandbox": true` dans `config.json` (activé automatiquement en tant que root).

```bash
chmod 600 ~/.config/untis/.env                            # toi seul peux lire ton mot de passe
untis --clear-session                                     # se déconnecter : supprimer la session enregistrée
rm ~/.local/share/untis/sessions/storage_state.json       # pareil, à la main
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
pyproject.toml      # métadonnées du paquet, dépendances, commande `untis`
contrib/systemd/    # minuteur utilisateur pour --changes --notify
src/untis/
  __init__.py       # version
  __main__.py       # python -m untis
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
