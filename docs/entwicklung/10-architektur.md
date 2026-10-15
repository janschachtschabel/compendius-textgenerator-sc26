# Architektur

[Übersicht](README.md) · Stand 15.10.2026 · Commit `9aa8980` (Release 2.23.0) · drei interaktive Diagramme, erzeugt
mit dem Skill archify 3.0.1

Drei Diagramme zeigen, woraus der Dienst besteht, wie eine Anfrage durch ihn läuft und wie die Sidecars die lokalen
Daten aktuell halten. Jeder Baustein nennt die Stellen im Code, die ihn belegen: Datei und Zeilen im Commit
`9aa8980`, in der HTML-Fassung als Kürzel „QUELLE“ mit Link auf GitHub. Die HTML-Seiten brauchen keine weiteren
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

- Aufrufende Systeme kommen über den Proxy der b-api (`/api/v1/proxy/<dienst>`), der den Schlüssel des Aufrufers
  weiterreicht, oder direkt mit `X-API-Key`; die Prüfansicht (`/ui/`, mit `UI_ENABLED`) spricht dieselben Endpunkte. Vor
  jedem Endpunkt prüft der Dienst am Port 8000 Schlüssel, Rate-Limit und Körpergrenze, bevor er den Körper liest.
- Der Container `api` (FastAPI unter uvicorn) liest die ZIM-Archive (Teil 1), den Lehrplan-Cache (Teil 2), die Wikidata-
  und GND-Indizes (`/entities`) und seinen Zustand (Templates, Status-Dateien, Repository-Cache). Nach außen fragt er
  edu-sharing (Teil 3 und Knoten; mit `EDU_SHARING_USER` und `EDU_SHARING_PASSWORD`, etwa dem Gastkonto der WLO, liest
  er das konfigurierte Repository mit dem Konto, jedes andere ohne, D112) und über das LLM-Gateway die b-api, mit dem Schlüssel der Anfrage oder `B_API_KEY`
  (D105) und der Spur der Anfrage (D108).
- Am internen Port 9000 antworten `/health`, `/ready`, `/metrics` und die Statusendpunkte (D110); beide Ports sind
  einstellbar (`PUBLIC_PORT`, `INTERNAL_PORT`, D111). Docker-Healthcheck und
  Kubernetes-Proben fragen dort, Prometheus (Profil `monitoring`) holt dort die Metriken.
- Vier Sidecars aus demselben Image halten die Daten aktuell: `zim-updater` (Kiwix), `lehrplan-updater` (MEM),
  `wikidata-updater` und `gnd-updater` (Abzüge von Wikimedia und der DNB).

## Eine Kompendium-Anfrage

- Der Endpunkt prüft Zugang und Profil und nimmt den Schlüssel der Anfrage für ihre LLM-Aufrufe. Ohne Profil gilt
  `PRESET_DEFAULT`; braucht das Profil ein LLM und ist keins eingerichtet, antwortet er mit 503.
- Der Service startet Teil 3 sofort und Teil 2, sobald das Thema vorbereitet ist; beide laufen neben Teil 1. Er wählt
  den Artikel (ab `balanced` per LLM), liest Hauptartikel und Korpus aus einer festen Sicht der Archive und baut Teil 1:
  die Zuordnung ab `best-quality` per LLM, den Text schreibt das LLM nur in `best-quality-generated` und
  `best-coverage-generated`. Ab `best-quality` prüft das LLM die Lehrplantreffer.
- Jeder LLM-Aufruf reserviert Tokens aus dem Budget der Anfrage; ein Tagesbudget gibt es nicht mehr (D104). Lehnt die
  b-api den Schlüssel ab oder setzt sie seine Route aus, läuft der Rest der Anfrage nach den Regeln, und die Antwort
  nennt den Grund (D106). Ohne
  Restzeit oder erreichbare b-api übernehmen ebenfalls die Regeln.

## Sidecars und lokale Daten

- Jeder Sidecar lädt aus seiner Quelle, prüft die Prüfsumme und ersetzt die Datei in einem Schritt: die ZIM-Archive
  (Wikipedia und Klexikon, D99) mit `active.json`, `lehrplan.db`, `wikidata.db` und `gnd.db`. Eine Lock-Datei je Sidecar
  verhindert einen zweiten Lauf.
- Der Dienst übernimmt neue Daten ohne Neustart: die Archive bei der nächsten Anfrage, den Lehrplan-Cache beim nächsten
  Aufruf, die Indizes nach höchstens 60 s. Sammlungen und Materialtexte liest er aus dem Repository und hält sie im
  Repository-Cache, je Pod an `WLO_CACHE_PATH` (D109).
- Jeder Sidecar schreibt Status- und Lebenszeichen-Dateien. `/metrics` am internen Port liest sie bei jeder Abfrage, und
  Alarme wie `KompendiumZimSyncSilent` melden einen stummen Sidecar. Die Schleifen der Sidecars loggen nach stdout.

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
   Commit, den die Datei nennt. `--out-dir` hält die Prüfquittungen aus dem Repository; sie enthalten lokale Pfade. Die Dateien
   `*.delivery.json` und `*.delivery-pending.json`, die archify trotzdem neben das HTML legt, nicht committen.
3. Die deutsche Oberfläche steht in `meta.translations` (aus `examples/locales/de.json` von archify). Meldet archify
   mit `meta.locale: "de"` nur „Renderer failed before emitting a structured diagnostic“, zeigt ein Lauf ohne
   `meta.locale` und `meta.translations` die eigentliche Meldung (archify 3.0.1).
