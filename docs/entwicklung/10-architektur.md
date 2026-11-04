# Architektur

[Übersicht](README.md) · Stand 04.11.2026 · Commit `454bdaf` (Release 2.26.0 in Vorbereitung) · drei interaktive
Diagramme, erzeugt mit dem Skill archify 3.2.0

Drei Diagramme zeigen, woraus der Dienst besteht, wie eine Anfrage durch ihn läuft und wie die Updater die lokalen
Daten aktuell halten. Jeder Baustein nennt die Stellen im Code, die ihn belegen: Datei und Zeilen im Commit
`454bdaf`, in der HTML-Fassung im semantischen Pass des Bausteins als verifizierter Quellnachweis mit Link auf GitHub.
Die HTML-Seiten brauchen keine weiteren Dateien und laden nichts nach; die Schriften sind eingebettet.

| Diagramm | Inhalt |
|---|---|
| [Systemübersicht](https://janschachtschabel.github.io/compendius-textgenerator-sc26/entwicklung/architektur/systemuebersicht.html) | Aufrufer, Zugangsprüfung, API-Dienst, Volumes, Updater, externe Quellen, Trace-Collector und Monitoring; Betrieb mit Docker Compose oder dem Helm-Chart |
| [Eine Kompendium-Anfrage](https://janschachtschabel.github.io/compendius-textgenerator-sc26/entwicklung/architektur/kompendium-anfrage.html) | der Weg von `POST /api/v2/compendium` durch die drei Teile: Eingabe als Thema, Knoten oder Text, die LLM-Aufrufe je Profil und der Trace der Anfrage |
| [Updater und lokale Daten](https://janschachtschabel.github.io/compendius-textgenerator-sc26/entwicklung/architektur/sidecars-und-daten.html) | Quellen, Updater mit Termin (CronJob) und Intervall (Schleife), Volumes, die Leser im Dienst und die Überwachung |

Die Links führen auf GitHub Pages (aus dem Ordner `docs/`): Im Repository zeigt GitHub eine HTML-Datei nur als
Quelltext. Die Quellen liegen daneben in `architektur/*.html` und `*.json`.

## Systemübersicht

- Aufrufende Systeme kommen über den Proxy der b-api (`/api/v1/proxy/<dienst>`), der den Schlüssel des Aufrufers
  weiterreicht, oder direkt mit `X-API-Key`; die Prüfansicht (`/ui/`, mit `UI_ENABLED`) spricht dieselben Endpunkte. Vor
  jedem Endpunkt prüft der Dienst am Port 8000 Schlüssel, Rate-Limit und Körpergrenze, bevor er den Körper liest.
- Der Container `api` (FastAPI unter uvicorn) liest die ZIM-Archive (Teil 1), den Lehrplan-Cache (Teil 2), die Wikidata-
  und GND-Indizes (`/entities`) und seinen Zustand (Templates, Status-Dateien, Repository-Cache). Nach außen fragt er
  über das LLM-Gateway die b-api, mit dem Schlüssel der Anfrage oder `B_API_KEY` (D105), und edu-sharing.
- edu-sharing ist optional (D114): `material` und `collection_context` bringen einen Knoten als Text statt `node_id`
  (für `compendium`, `/knowledge` und `/qa`), `sources` bringt Texte für Teil 1, gereiht wie die Materialien von
  `knowledge_collection_id` unter `CORPUS_MAX_CHUNKS`. Das Repository braucht der Dienst nur noch für `node_id`,
  `collection_id`, `knowledge_collection_id` und Teil 3; mit `EDU_SHARING_USER` und `EDU_SHARING_PASSWORD`, etwa dem
  Gastkonto der WLO, liest er das konfigurierte Repository mit dem Konto, jedes andere ohne (D112).
  `GET /api/v2/nodes/{id}` liefert einen Knoten als `text_input`, fertig zum Senden.
- Je Anfrage öffnet der Dienst einen Span (OpenTelemetry, D115): als Kind des Kontexts des Aufrufers (B3 vor W3C),
  sonst als neuen Trace; die Proben laufen ohne. An b-api und edu-sharing gehen `X-B3-TraceId`, `X-B3-SpanId`,
  `X-B3-Sampled` und `traceparent` mit dem eigenen Span, dazu `x-client-trace-id` und `X-Request-ID`; die Antwort nennt
  den Trace in `X-B3-TraceId`, die JSON-Logzeilen tragen `service`, `trace_id`, `span_id` und `client_trace_id`. Spans
  gehen nur mit `OTEL_EXPORTER_OTLP_ENDPOINT` per OTLP/HTTP an einen Collector wie Jaeger; die Vorgabe ist leer.
  Im Helm-Chart setzt `tracing.otlpEndpoint` die Variable und öffnet in der NetworkPolicy der API den Port des
  Collectors (`tracing.collectorPort`, Vorgabe 4318).
- Am internen Port 9000 antworten `/health`, `/ready`, `/metrics` und die Statusendpunkte (D110); beide Ports sind
  einstellbar (`PUBLIC_PORT`, `INTERNAL_PORT`, D111). Docker-Healthcheck und Kubernetes-Proben fragen dort, Prometheus
  (Compose-Profil `monitoring` oder ein ServiceMonitor des Helm-Charts) holt dort die Metriken.
- Vier Updater aus demselben Image halten die Daten aktuell: `zim-updater` (Kiwix), `lehrplan-updater` (MEM),
  `wikidata-updater` und `gnd-updater` (Abzüge von Wikimedia und der DNB). Zwei Betriebswege (D116): Docker Compose
  bleibt unverändert, dort laufen sie als Container mit `--loop`; das Helm-Chart (je Versions-Tag als OCI-Chart
  veröffentlicht) bringt das API-Deployment mit den Ports 8000 und 9000, NetworkPolicy, PVCs `zim` und `state`,
  optional ServiceMonitor und PrometheusRule, und die Updater als CronJobs (oder mit `updaters.mode=deployment` als
  Deployments mit `--loop`).

## Eine Kompendium-Anfrage

- Die Anfrage nennt das Thema (`topic`), einen Knoten (`node_id`, den der Dienst aus edu-sharing liest) oder denselben
  Knoten als Text (`material` oder `collection_context`, ohne Aufruf des Repositorys, D114); `sources` ergänzen den
  Korpus von Teil 1.
- Der Endpunkt prüft Zugang und Profil und nimmt den Schlüssel der Anfrage für ihre LLM-Aufrufe. Ohne Profil gilt
  `PRESET_DEFAULT`; braucht das Profil ein LLM und ist keins eingerichtet, antwortet er mit 503.
- Der Service startet Teil 3 sofort (mit `collection_id` oder einer Sammlung in `node_id`) und Teil 2, sobald das
  Thema vorbereitet ist; beide laufen neben Teil 1. Er wählt den Artikel (ab `balanced` per LLM), liest Hauptartikel
  und Korpus aus einer festen Sicht der Archive und baut Teil 1: die Zuordnung ab `best-quality` per LLM, den Text
  schreibt das LLM nur in `best-quality-generated` und `best-coverage-generated`. Ab `best-quality` prüft das LLM die
  Lehrplantreffer.
- Jeder Aufruf an b-api und edu-sharing trägt die B3-Header des Spans der Anfrage (D115); die Antwort nennt den Trace
  in `X-B3-TraceId`.
- Jeder LLM-Aufruf reserviert Tokens aus dem Budget der Anfrage; ein Tagesbudget gibt es nicht mehr (D104). Lehnt die
  b-api den Schlüssel ab oder setzt sie seine Route aus, läuft der Rest der Anfrage nach den Regeln, und die Antwort
  nennt den Grund (D106). Ohne Restzeit oder erreichbare b-api übernehmen ebenfalls die Regeln.

## Updater und lokale Daten

- Jeder Updater lädt aus seiner Quelle, prüft die Prüfsumme und ersetzt die Datei in einem Schritt: die ZIM-Archive
  (Wikipedia und Klexikon, D99) mit `active.json`, `lehrplan.db`, `wikidata.db` und `gnd.db`. Eine Lock-Datei je
  Updater verhindert einen zweiten Lauf. Auch ein einmaliger Lauf (CronJob, dort PID 1) nimmt SIGTERM an, etwa bei
  Fristende oder gelöschtem Pod: Er schreibt seinen Status, gibt die Sperre frei und endet mit 1 (D116).
- Takt (D116): Im Helm-Chart (Vorgabe `updaters.mode=cronjob`) läuft jeder Updater als CronJob einmal je Termin, ohne
  `--loop`, nachts versetzt (Europe/Berlin): GND 01:15 und Wikidata 02:15 täglich, Lehrpläne 03:15 und ZIM 04:15
  sonntags; bei `helm install` startet je Updater gleich ein erster Lauf. In Docker Compose (und mit
  `updaters.mode=deployment`) laufen sie als Schleifen mit `--loop`: ZIM alle 30 Tage, Lehrpläne alle 7 Tage, Wikidata
  und GND täglich. Das Diagramm nennt je Updater zuerst den Termin, dann das Intervall.
- Der Dienst übernimmt neue Daten ohne Neustart: die Archive bei der nächsten Anfrage, den Lehrplan-Cache beim nächsten
  Aufruf, die Indizes nach höchstens 60 s. Sammlungen und Materialtexte liest er aus dem Repository und hält sie im
  Repository-Cache, je Pod an `WLO_CACHE_PATH` (D109); mit Texteingabe (D114) liest er kein Repository.
- Mit `INDEX_COPY_DIR` kopiert jeder API-Pod `lehrplan.db`, `wikidata.db` und `gnd.db` je Fassung auf seine lokale
  Platte (etwa ein `emptyDir`) und liest dort; mit `TEMPLATES_DIR` kommen die eigenen Templates aus einem eigenen
  Verzeichnis, etwa einer ConfigMap. Dann mountet die API die geteilten Volumes nur lesend (D113).
- Jeder Updater schreibt Status-Dateien, eine Schleife zudem Lebenszeichen. `/metrics` am internen Port liest sie bei
  jeder Abfrage. Alarme wie `KompendiumZimSyncSilent` melden eine stumme Schleife; im Helm-Chart mit CronJobs fallen
  diese Alarme weg, dort meldet `KompendiumUpdaterRunFailed` einen gescheiterten Lauf (über kube-state-metrics). Die
  Schleifen loggen nach stdout, ein einmaliger Lauf wie der eines CronJobs nach stderr.

## Neu erzeugen

Die Diagramme entstehen aus den JSON-Dateien daneben (`architektur/*.json`) mit dem Skill archify. Nach einer
Änderung am Code:

1. In der JSON-Datei `meta.repository.revision` auf den neuen Commit setzen (alle 40 Zeichen) und die betroffenen
   Bausteine und Belege anpassen (höchstens drei je Baustein). Der Commit muss auf GitHub liegen, sonst führen die
   Links der Belege ins Leere.
2. Aus dem Wurzelverzeichnis des Repositorys erzeugen, `sequence` für `kompendium-anfrage` und `dataflow` für
   `sidecars-und-daten`:

   ```bash
   node <archify>/bin/archify.mjs finalize architecture docs/entwicklung/architektur/systemuebersicht.json docs/entwicklung/architektur/systemuebersicht.html --repo-root <checkout> --quality showcase --out-dir <temp>
   ```

   `--repo-root` braucht einen Checkout, dessen `origin` auf
   `https://github.com/janschachtschabel/compendius-textgenerator-sc26.git` zeigt: archify prüft jeden Beleg an dem
   Commit, den die Datei nennt. Zeigt `origin` woandershin (etwa auf GitLab), genügt ein Klon mit
   `git clone --no-local`, dessen `origin` per `git remote set-url` auf GitHub gesetzt und der Commit ausgecheckt ist.
   `--out-dir` hält die Prüfquittungen aus dem Repository; sie enthalten lokale Pfade. Die Dateien `*.delivery.json`
   und `*.delivery-pending.json`, die archify trotzdem neben das HTML legt, nicht committen.
3. Die deutsche Oberfläche steht in `meta.translations`: `examples/locales/de.json` von archify 3.2.0 und 25 eigene
   Übersetzungen der Schlüssel, die dort fehlen (das Paket bringt kein eingebautes `de`); archify meldet fehlende
   Schlüssel als Warnung `i18n/*`. Meldet archify mit `meta.locale: "de"` nur „Renderer failed before emitting a
   structured diagnostic“ oder `internal/unclassified`, zeigt ein Lauf ohne `meta.locale` und `meta.translations` die
   eigentliche Meldung.
4. Die Kompendium-Anfrage muss mindestens 1,55-mal so breit wie hoch bleiben (1080 × 690), sonst ragt sie über ein
   Fenster von 1440 × 900; Notizen an den Nachrichten bleiben eine Zeile kurz, Einzelheiten stehen in den Karten.
