# Mitarbeit

Wie an diesem Dienst gearbeitet wird, für Menschen wie für Agenten. Die Fallen, die schon Zeit gekostet haben,
stehen in [CLAUDE.md](CLAUDE.md); was der Dienst kann, im [README](README.md); was sich je Release geändert hat, im
[Änderungsprotokoll](CHANGELOG.md).

## Einrichten

Python 3.13 und [uv](https://docs.astral.sh/uv/) in der Version, die CI und Image nutzen (0.12.19; ein Test hält die
Angaben in `Dockerfile`, CI und GitLab gleich):

```bash
uv sync --all-extras
cp .env.example .env    # nur für lokale Läufe von API und CLI; die Tests lesen weder .env noch die Shell
```

Für die Tests der Prüfansicht braucht es Node (ohne Paket, `node --test`); ohne Node überspringt `pytest` sie, in
der GitHub-CI schlagen sie dann fehl. Model2Vec läuft lokal mit der Hugging-Face-ID in `MODEL2VEC_PATH` und
`HF_HUB_OFFLINE=1` (README, „Matching bewerten“). ZIM-Archive für eigene Läufe: README, „ZIM-Archive betreiben“.

## Prüfen, bevor etwas als fertig gilt

Dieselben Prüfungen wie in der CI (`.github/workflows/ci.yml`, `.gitlab-ci.yml`):

```bash
uv run pytest --cov                                # Zweigabdeckung, Schwelle 90 %
uv run ruff check . && uv run ruff format --check .
uv run mypy app scripts tests
```

- Abhängigkeiten geändert: `uvx --from 'uv==0.12.19' uv lock --check`. Die CI installiert mit `--frozen` und prüft
  die Laufzeitpakete mit `pip-audit`.
- Antworten der API geändert, die die Prüfansicht liest: `UI_ANSWERS=write uv run pytest tests/test_ui_answers.py`
  schreibt `tests/ui/answers` neu; danach zeigen die Node-Tests, ob die Seite sie noch liest.
- Alarmregeln in `monitoring/` prüft `promtool` nur in der CI (`check config`, `test rules`).
- Ein Image, von dessen Bau eine Aussage abhängt: im Image nachsehen, ob der neue Code darin ist (CLAUDE.md,
  „Docker: dem Protokoll nicht glauben“). `scripts/smoke_image.py` fragt ein gebautes Image wie die CI.

Ein Test für einen Fehler entsteht vor dem Fix und schlägt zuerst fehl. Ein Test, der rot wird, wird nicht
abgeschwächt, damit die Suite grün ist; ist er falsch, steht im Commit, warum.

## Erst messen, dann bauen

Eine Änderung am Verhalten (Regel, Schwelle, Gewicht, Prompt, Profil, Zuordnung) wird zuerst gemessen, im Ablauf des
Dienstes selbst: am Goldstandard in `eval/gold` (`compendium eval run`, `eval/README.md`) oder an einer Themenliste
früherer Messungen, mit dem Korpus und der Strategie der Profile. Zahlen aus anderen Umgebungen werden nicht
danebengestellt.

- Das Messskript liegt unter `docs/entwicklung/messung/` (`mc_*.py`, im Kopf: Frage, Aufbau, Aufruf), die Rohdaten
  unter `docs/entwicklung/messung/ergebnisse/`, das Ergebnis mit M-Nummer in
  `docs/entwicklung/05-messprotokoll.md`.
- Die Zahl, die eine Regel trägt, steht im Docstring oder Kommentar daneben, mit der Messung, aus der sie kommt.
- Ein Vorher-Nachher-Vergleich läuft in einem Durchlauf gegen dieselben Artikel (CLAUDE.md, „Messen statt
  vermuten“); ein verhaltensgleicher Umbau wird byteweise gegen einen Referenzlauf verglichen.
- Messläufe mit LLM höchstens zu zweit bis viert gleichzeitig: Mehr drosselt der Anbieter, und die Läufe messen dann
  die Drosselung.
- Was gemessen und nicht gebaut wurde, bleibt im Protokoll und in der Entscheidung stehen.

## Regeln für den Code

- **Paketgrenzen:** Keine zwei Pakete unter `app/` importieren einander (`tests/test_architecture.py`). Unten liegen
  `app/domain`, `app/markup`, `app/prose.py`, `app/files.py` und `app/locks.py`; `app/wiring.py` baut den Dienst für
  API und CLI, `app/main.py` ist nur der Web-Eingang (`tests/test_wiring.py`).
- **Einstellungen bleiben einstellbar:** Eine neue Vorgabe ändert den Standardwert in `app/settings.py`, eine
  Variable wird nie entfernt. Ein leerer Eintrag `NAME=` gilt wie keine Zeile. Jede Variable steht in
  `.env.example` (`tests/test_env_example.py`), in der Tabelle „Konfiguration“ des README und in
  `docs/uebergabe/konfiguration.md`.
- **Texte für Endkunden:** Das angefragte Thema steht in jedem Profil in Prompts, Überschrift und `topic`, nie ein
  anderer Artikel an seiner Stelle (D72, D75). Fertige Texte tragen keine sichtbaren Vermerke des Apparats; solche
  Ausgaben gibt es nur auf Wunsch der Anfrage (D76).
- **Fehler** werden behandelt oder bewusst weitergegeben, nicht verschluckt; ein Rückfall nennt seinen Grund in der
  Antwort (`audit`), damit sichtbar ist, was wirklich lief.
- **Geheimnisse** nie im Code, auch nicht als Rückfallwert, und nie in Ausgaben, Protokollen oder Fehlermeldungen.
  `.env` und `docker-compose.override.yml` sind lokal.
- **Sprache:** Code, Kommentare und Commit-Nachrichten englisch, die Dokumentation unter `docs/` und das README
  deutsch. Kommentare sagen, warum, nicht was.

## Dokumentation im selben Commit

| Was sich ändert | Wo es nachgezogen wird |
|---|---|
| eine Einstellung | `app/settings.py` (Beschreibung), `.env.example`, README „Konfiguration“, `docs/uebergabe/konfiguration.md` (samt Anzahl) |
| ein Endpunkt oder eine Antwort | README „Endpunkte“, `docs/uebergabe/aufrufe.md`, Beispiele in `app/api/v2/routes_examples.py` |
| eine Entscheidung | `PLAN.md` mit D-Nummer, Messung mit M-Nummer im Messprotokoll |
| was ein Betreiber beim Update tun muss | `docs/betrieb.md`, Tabelle „Updates“, mit dem Release |
| ein Befund eines Audits | Stand je Befund am Ende des Berichts unter `docs/audits/` |

## Commits, Branches, Releases

- Ein Commit, eine logische Änderung, Nachrichten nach Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`,
  `docs:`, `chore:`), im Text das Warum. Agenten setzen ihre `Co-Authored-By`-Zeile.
- Es gibt nur `main` auf GitHub, keine Seitenbranches; Dependabot-PRs werden zeitnah übernommen. Gepusht wird nur,
  was auf dem aktuellen `main` aufsetzt (`git merge-base --is-ancestor origin/main HEAD`), nie mit `--force`.
- Versionen nach Semantic Versioning: neue Einstellung, neues Verhalten oder neue Vorgabe ergeben eine Minor-Version,
  Korrekturen eine Patch-Version.

Ein Release X.Y.Z:

1. Version in `pyproject.toml` und `app/__init__.py`, dann `uvx --from 'uv==0.12.19' uv lock`
   (`tests/test_version.py` verlangt dieselbe Version an allen drei Stellen).
2. `CHANGELOG.md`: der Abschnitt „Unveröffentlicht“ wird „X.Y.Z – Datum“; dazu der Absatz im README („Stand“), die
   Zeile in `docs/betrieb.md` („Updates“) und die Versionsangaben in `docs/installation.md` und `docs/uebergabe/`.
3. Alle Prüfungen oben, Commit `chore(release): X.Y.Z`, Push auf `main`, CI abwarten.
4. Tag `vX.Y.Z` (annotiert, „Release X.Y.Z“) und pushen. Die CI veröffentlicht das geprüfte Image als
   `ghcr.io/janschachtschabel/compendius-textgenerator-sc26:X.Y.Z`, `:X.Y` und `:<sha>`; `:latest` und `:main`
   bekommt nur der Commit, auf den `main` zeigt.
5. Auf dem Server nach `docs/betrieb.md`, „Updates“: Compose und Variablen abgleichen, danach `GET /health` lesen
   (`version`, `revision`).
