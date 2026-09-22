# Arbeiten an diesem Projekt

Notizen, die sich in der Arbeit an diesem Dienst als teuer erwiesen haben — jede steht hier, weil sie
mindestens einmal Zeit gekostet hat. Sie gelten für Menschen wie für Agenten.

## Prüfen, bevor etwas behauptet wird

```bash
uv run pytest                                   # die ganze Suite
uv run ruff check . && uv run ruff format --check .
uv run mypy app
```

Die Abdeckungsschwelle liegt bei 90 % (`uv run pytest --cov`). Ein Satz wie „müsste jetzt laufen" ist
kein Beleg; der Beleg ist die Ausgabe eines Befehls, der wirklich lief.

## Messen statt vermuten

Dieses Projekt schreibt **Messungen in die Docstrings**, nicht Absichten. Wer eine Regel ändert, nennt
dort, woran sie gemessen wurde und was dabei herauskam — mit Zahlen. `docs/umbau.md` führt dasselbe
ausführlicher: was probiert wurde, was daran gescheitert ist und warum es trotzdem so gebaut ist.

Das ist keine Formsache. `docs/umbau.md` verzeichnet mehrfach Ansätze, die naheliegend aussahen und an
den Zahlen scheiterten — die Wortart als Filter, die Worthäufigkeit, die reine Verankerung hinter der
Kopula, die Wortdeckung gegen erfundene Frageinhalte. Jeder davon wäre ohne Messung eingebaut worden.
Eine Regel ohne Messung ist eine Vermutung im Produktionscode.

Was sich **nicht** wiederholen lässt, gehört dazugesagt: `libzim`s `get_random_entry` lässt sich nicht
säen. Stichproben sind nur **innerhalb** eines Laufs vergleichbar, nicht zwischen zwei Läufen — wer
zwei Regeln vergleicht, muss beide im selben Durchlauf gegen dieselben Artikel laufen lassen.

## Backslashes in Werkzeug-Eingaben

Die teuerste Falle dieses Projekts, sechsmal an einem Tag zugeschlagen. Ein doppelter Backslash in der
Eingabe eines Werkzeugs (Heredoc, Suchmuster einer Ersetzung) **verliert eine Ebene**: `\\(` kommt als
`\(` an, `\\n` als echter Zeilenumbruch. Das Suchmuster passt dann nicht mehr, oder — schlimmer — es
passt auf etwas anderes.

„Keine Backslashes verwenden" hilft nicht, wenn der Zielcode selbst ein Muster ist. Zwei Wege tragen:

1. **Nach Zeilennummer ersetzen, nicht nach Inhalt.** Datei lesen, auf einer **backslashfreien** Marke
   prüfen (`lines[12].startswith("_PERSON_RE = re.compile(")`), dann `lines[12:15] = [...]` zuweisen.
   So muss keine Zeichenkette mit Backslash die Werkzeug-Eingabe als *Suchmuster* überleben.
2. **Backslashes mit `chr(92)` bauen**, wo einer unvermeidlich ist — und die Falle in der Falle
   beachten: `chr(92) + chr(92)` ergibt **zwei**. Einer je Backslash.

Danach die geschriebene Zeile ausgeben und ansehen. Immer.

## Docker: dem Protokoll nicht glauben

Ein Bau kann „DONE" melden und trotzdem alten Code ausliefern. Zwei belegte Wege dahin:

- `docker build … | tail` gibt den Exit-Code von `tail` zurück, also immer 0. Stattdessen in eine Datei
  umleiten und `echo "Exit: $?"` danach.
- `uv` legt das selbst gebaute Rad unter der **Projektversion** ab, und die ändert sich zwischen Commits
  nicht. Das Dockerfile erzwingt darum `--reinstall-package` und prüft mit einem `diff` gegen den
  kopierten Quellbaum, dass das installierte Paket wirklich der Quelle entspricht.

**Nach jedem Bau, von dem eine Aussage abhängt, im Image nachsehen:**

```bash
docker run --rm --entrypoint /bin/sh IMAGE -c \
  'grep -c NEUER_NAME /app/.venv/lib/python*/site-packages/app/…'
```

Unter Git Bash schreibt MSYS führende `/` in Windows-Pfade um und zerstört damit `-v`, `--entrypoint`
und Werte wie `ZIM_PATHS`. `MSYS_NO_PATHCONV=1` vor den `docker`-Aufruf setzen — sonst startet der
Dienst ohne sein Pflichtarchiv und die Worker sterben, was wie ein Speicherproblem aussieht.

## Geheimnisse

Keine Schlüssel, Token oder Passwörter im Quellcode, auch nicht als Rückfallwert. `.env` und
`docker-compose.override.yml` sind lokal und stehen in `.gitignore`; sie gehören nicht ins Repository und ihr
Inhalt nicht in Ausgaben, Protokolle oder Fehlermeldungen.

## Wo was steht

| Datei | Inhalt |
|---|---|
| `README.md` | Überblick, Installation, Endpunkte, Umgebungsvariablen |
| `docs/installation.md` | von der leeren Maschine bis zum ersten Kompendium, samt gemessener Anforderungen |
| `docs/betrieb.md` | Betrieb, Störungen, Wiederherstellung |
| `docs/umbau.md` | das laufende Protokoll: was gemessen wurde, was verworfen, was gebaut |
| `PLAN.md` | der Plan, gegen den gebaut wird |
