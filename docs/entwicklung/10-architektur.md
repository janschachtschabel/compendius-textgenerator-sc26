# Architektur

[Übersicht](README.md) · Stand 29.09.2026 · Commit `b95a546` (Release 2.5.0 und die zwei Fixes danach) · drei
interaktive Diagramme, erzeugt mit dem Skill archify 3.0.1

Drei Diagramme zeigen, woraus der Dienst besteht, wie eine Anfrage durch ihn läuft und wie die Sidecars die lokalen
Daten aktuell halten. Jeder Baustein nennt die Stellen im Code, die ihn belegen: Datei und Zeilen im Commit
`b95a546`, in der HTML-Fassung als Kürzel „QUELLE“ mit Link auf GitHub. Die HTML-Seiten brauchen keine weiteren
Dateien und laden nichts nach; die Schriften sind eingebettet.

| Diagramm | Inhalt |
|---|---|
| [Systemübersicht](architektur/systemuebersicht.html) | Aufrufer, Zugangsprüfung, API-Dienst, Volumes, Sidecars, externe Quellen und Monitoring |
| [Eine Kompendium-Anfrage](architektur/kompendium-anfrage.html) | der Weg von `POST /api/v2/compendium` durch die drei Teile, mit den LLM-Aufrufen je Profil |
| [Sidecars und lokale Daten](architektur/sidecars-und-daten.html) | Quellen, Sidecars, Volumes, die Leser im Dienst und die Überwachung |

Im Browser liegen sie unter
https://janschachtschabel.github.io/compendius-textgenerator-sc26/entwicklung/architektur/systemuebersicht.html,
`…/kompendium-anfrage.html` und `…/sidecars-und-daten.html` (GitHub Pages aus dem Ordner `docs/`).

## Systemübersicht

- Aufrufende Systeme und die Prüfansicht (`/ui/`, mit `UI_ENABLED`) sprechen dieselben Endpunkte unter `/api/v2`
  an. Vor jedem Endpunkt prüft der Dienst API-Schlüssel, Rate-Limit und Körpergrenze, bevor er den Körper liest.
- Der Container `api` (FastAPI unter uvicorn) liest die ZIM-Archive (Teil 1), den Lehrplan-Cache (Teil 2), die
  Wikidata- und GND-Indizes (`/entities`) und seinen Zustand (Templates, Tokenbudget, Status-Dateien). Nach außen
  fragt er edu-sharing (Teil 3 und Knoten) und über das LLM-Gateway die b-api.
- Vier Sidecars aus demselben Image halten die Daten aktuell: `zim-updater` (Kiwix), `lehrplan-updater` (MEM),
  `wikidata-updater` und `gnd-updater` (Abzüge von Wikimedia und der DNB). Prometheus (Profil `monitoring`) fragt
  `/metrics` ab.

## Eine Kompendium-Anfrage

- Der Endpunkt prüft Zugang und Profil. Braucht das Profil ein LLM und ist keins konfiguriert, antwortet er mit 503.
- Der Service wählt den Artikel (ab `balanced` per LLM), liest Hauptartikel und Korpus aus einer festen Sicht der
  Archive (404, wenn es das Thema nicht gibt) und baut Teil 1: die Zuordnung ab `best-quality` per LLM, den Text
  schreibt das LLM nur in `best-quality-generated`.
- Teil 2 sucht im Lehrplan-Cache, ab `best-quality` prüft das LLM die Treffer. Teil 3 liest die Sammlung aus
  edu-sharing, nur mit `collection_id` und nur bis zur Frist (`REQUEST_TIMEOUT_S`).
- Jeder LLM-Aufruf reserviert Tokens und rechnet danach ab. Ohne Restzeit, Budget oder erreichbare b-api übernehmen
  die Regeln.

## Sidecars und lokale Daten

- Jeder Sidecar lädt aus seiner Quelle, prüft die Prüfsumme und ersetzt die Datei atomar: die ZIM-Archive mit
  `active.json`, `lehrplan.db`, `wikidata.db` und `gnd.db`.
- Der Dienst übernimmt neue Daten ohne Neustart: die Archive bei der nächsten Anfrage, den Lehrplan-Cache beim
  nächsten Aufruf, die Indizes nach höchstens 60 s.
- Jeder Sidecar schreibt Status- und Lebenszeichen-Dateien. `/metrics` liest sie bei jeder Abfrage, und Alarme wie
  `KompendiumZimSyncSilent` melden einen stummen Sidecar.

## Neu erzeugen

Die Diagramme entstehen aus den JSON-Dateien daneben (`architektur/*.json`) mit dem Skill archify. Nach einer
Änderung am Code:

1. In der JSON-Datei `meta.repository.revision` auf den neuen Commit setzen (alle 40 Zeichen) und die betroffenen
   Bausteine und Belege anpassen. Der Commit muss auf GitHub liegen, sonst führen die Links der Belege ins Leere.
2. Aus dem Wurzelverzeichnis des Repositorys erzeugen, `sequence` für `kompendium-anfrage` und `dataflow` für
   `sidecars-und-daten`:

   ```bash
   node <archify>/bin/archify.mjs finalize architecture docs/entwicklung/architektur/systemuebersicht.json docs/entwicklung/architektur/systemuebersicht.html --repo-root <checkout> --quality showcase --out-dir <temp>
   ```

   `--repo-root` braucht einen Checkout, dessen `origin` auf
   `https://github.com/janschachtschabel/compendius-textgenerator-sc26.git` zeigt: archify prüft jeden Beleg an dem
   Commit, den die Datei nennt. `--out-dir` hält die Prüfquittungen aus dem Repository; sie enthalten lokale Pfade.
3. Die deutsche Oberfläche steht in `meta.translations` (aus `examples/locales/de.json` von archify). Meldet archify
   mit `meta.locale: "de"` nur „Renderer failed before emitting a structured diagnostic“, zeigt ein Lauf ohne
   `meta.locale` und `meta.translations` die eigentliche Meldung (archify 3.0.1).
