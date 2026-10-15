# Checkliste des Technik-Teams

Stand 15.10.2026 · Release 2.21.0 (D104 bis D108)

Team 6 hat festgelegt, was ein Dienst bei der Übergabe mitbringen muss („Übergaben an den Maschinenraum“). Diese
Seite beantwortet die Checkliste Punkt für Punkt und verweist auf die Stellen, an denen es ausführlich steht. Offen
Gebliebenes steht am Ende.

## 1. Repository, CI und Images

| Anforderung | Stand |
|---|---|
| Repo mit Zugriff für T6 | GitHub `janschachtschabel/compendius-textgenerator-sc26`, Branch `main`; für das interne GitLab liegt `.gitlab-ci.yml` nach dem Muster der Plattform bereit ([README](README.md), „CI im internen GitLab“) |
| CI baut Images automatisch | GitHub Actions (`ci.yml`) und GitLab-Pipeline: prüfen, bauen, veröffentlichen |
| Produktion nur mit Tags | Ein Tag `v2.20.0` baut `:2.20.0` und `:2.20`; `:latest` und `:main` zeigen nur auf den letzten geprüften Commit von `main` |
| Schlanke Images | Mehrstufiger Bau auf `python:3.13-slim`, Laufzeit ohne Bauwerkzeuge, Benutzer `app` (UID 10001) statt root, `.dockerignore` ohne Tests, Daten und Doku. Das Image ist 1,1 GB groß; darin stecken die Modelle für Absätze (Model2Vec, 322 MB) und Entitäten (spaCy, rund 60 MB), siehe offene Punkte |

## 2. OpenAPI

| Anforderung | Stand |
|---|---|
| Pfad der Spezifikation | `GET /openapi.json`, aus dem Code erzeugt (FastAPI); lesbar unter `/docs` und `/redoc` (`API_DOCS_ENABLED`) |
| Anzeigename und Text für Endnutzende | `info.title` „Kompendiale Texte“, `info.summary` ein Satz für Endnutzende; `info.description` für Entwickler (D107) |
| Nutzung vollständig beschrieben | Jeder Endpunkt mit Kurztitel, Beschreibung, Beispielen von der kürzesten Anfrage bis zu allen Parametern und den Fehlerantworten; jede Gruppe mit Beschreibung |
| Öffentlich und intern getrennt | `/openapi.json` beschreibt nur die öffentlichen Endpunkte. Die internen - `/health`, `/ready`, `/metrics`, die Statusendpunkte von Archiven und Lehrplänen und die Admin-Pfade - stehen nicht darin und sind in [betrieb.md, „Erreichbarkeit“](../betrieb.md#erreichbarkeit) dokumentiert; ein Test hält die Liste vollständig (D107) |

## 3. Erreichbarkeit, Header, Formate, Antwortzeiten

- **Pfade öffentlich und intern:** Tabelle in [betrieb.md, „Erreichbarkeit“](../betrieb.md#erreichbarkeit). Der Dienst
  hat einen Port (8000); Ingress und Proxy der b-api geben `/openapi.json`, `/docs`, `/redoc` und `/api/v2/` ohne die
  internen Pfade frei. Proben und Metriken laufen am Pod. Einen zweiten Port gibt es nicht; `METRICS_TOKEN` und
  `ADMIN_TOKEN` gehören gesetzt, damit ihre Pfade auch geschützt sind, wenn ein Proxy sie durchreicht.
- **Header vom Aufrufer:** hinter der b-api `Authorization` oder `X-API-Key`, der Schlüssel, den die b-api vom Aufrufer
  weiterreicht (D105); mit gesetztem `API_KEYS` trägt `X-API-Key` dessen Schlüssel; optional `X-Request-ID`,
  `x-client-trace-id` und die B3-Header (D108); `X-Admin-Token` nur für die Admin-Pfade.
- **Header zurück:** `X-Request-ID` an jeder Antwort; `Retry-After` bei 429 (nur mit `RATE_LIMIT` über 0), `ETag` beim
  Lesen eines Templates, `WWW-Authenticate` bei 401.
- **Content-Types:** Anfragen und Antworten `application/json`. Anderes liefern nur `/metrics` (Text für Prometheus),
  `/docs` und `/redoc` (HTML) und die Prüfansicht `/ui/` (HTML, JavaScript, CSS; im Betrieb aus).
- **Antwortzeiten:** Ein Kompendium (Teil 1 und 2) brauchte im Median 3 s (`llm-free`), 4 s (`balanced`), 15 s
  (`best-quality`), 28 s (`best-quality-generated`) und 33 s (`best-coverage-generated`, M91, neun Themen). Mit Teil 3
  und Materialtexten kommt das Lesen des Repositorys dazu. Die Frist einer Anfrage ist `REQUEST_TIMEOUT_S`, mit OpenAI
  300 s: Timeouts an Ingress und am Proxy der b-api darum auf mindestens 330 s setzen.
- **Asynchrone Jobs:** gibt es nicht. Ein Job, der nach der Anfrage weiterläuft, müsste den Schlüssel des Aufrufers über
  die Anfrage hinaus halten, was die b-api ausschließt, und bräuchte eine Warteschlange. Die Anfragen bleiben synchron.

## 4. B-API

- **Variante A, über die b-api** (empfohlen): `B_API_KEY_SOURCE=request`, `API_KEYS` leer, `RATE_LIMIT=0`. Der Dienst
  nimmt den Schlüssel, den die b-api vom Aufrufer weiterreicht, für seine LLM-Aufrufe, schickt ihn unverändert und nur
  an die b-api zurück und hält ihn nur für die Anfrage (D105); ein Wert unter 16 Zeichen ist kein Schlüssel (401). Am
  Proxy-Dienst muss „API-Key des Aufrufers weiterreichen“ (`forwardApiKey`) gesetzt sein. `B_API_KEY` ist dann optional:
  Er gilt nur für Anfragen ohne Schlüssel (Direktaufrufe im Cluster); ohne ihn laufen solche Anfragen nach den Regeln.
- **Variante B, direkt erreichbar:** Vorgabe `B_API_KEY_SOURCE=env`, `B_API_KEY` als Secret, `API_KEYS` als eigene
  Schlüssel der aufrufenden Systeme.
- **Virtueller Schlüssel nötig:** ja, ab dem Profil `balanced` ruft der Dienst selbst ein LLM.
- **Rechte des Schlüssels:** LLM-Aufrufe an `/api/v1/llm/openai/chat/completions` und `/models`, mit Routing an
  `/api/v1/llm/router/…`; keine Routenverwaltung (`LLM_ROUTE_MANAGE`).
- **Modelle:** Vorgabe ohne Routing: `openai` mit `gpt-6-luna`. Eine Route (etwa `gpt-6-luna` mit `gpt-5.6-luna` als
  Reserve, eine Parameterfamilie) legt ein Administrator der b-api an; hinter dem Proxy eine globale, denn eine Route
  für einen Schlüssel sehen die Schlüssel der Aufrufer nicht. Dann `B_API_PROVIDER=router` und `B_API_ROUTE` setzen.
- **Limits:** setzt die b-api je Schlüssel. Ist eines erreicht, läuft die Anfrage ohne LLM nach den Regeln weiter, und
  das Log sagt es einmal je Anfrage (D106). Lehnt die b-api `B_API_KEY` ab, laufen die Anfragen ohne eigenen Schlüssel
  zehn Minuten ohne LLM; Anfragen mit eigenem Schlüssel behalten es. Der Dienst hat kein eigenes Tagesbudget mehr
  (D104).

## 5. Monitoring und Logging

- **Prometheus:** `GET /metrics` (Bibliothek `prometheus_client`, Werte aller Worker zusammen), Zugriff mit
  `METRICS_TOKEN`. Applikationsmetriken: Anfragen und Dauer je Route, Kompendien, Phasen, Teile, LLM-Aufrufe und Tokens
  je Route, Rückfälle, Stand von Archiven, Indexen, Lehrplan-Cache und Sidecars, freier Platz auf den Volumes
  ([README](../../README.md), „Metriken“).
- **Alarmregeln:** 25 Regeln in `monitoring/alerts.yml`, mit `promtool`-Tests in `monitoring/alerts_test.yml`; für Helm
  als `PrometheusRule` übernehmen (der Inhalt von `groups` gehört unter `spec`). Die Regeln fragen `job="kompendium"`:
  Ein ServiceMonitor braucht diesen Job-Namen (`jobLabel` oder Relabeling), sonst meldet `KompendiumDown` nie.
- **Logs:** eine Zeile je Ereignis nach stdout (D109; einmalige Befehle der Kommandozeile nach stderr), `LOG_FORMAT=json` für einen
  Log-Sammler, `LOG_LEVEL` für die Stufe. Jede Zeile nennt die Anfrage (`request_id`), JSON-Zeilen auch die Spur
  (`trace_id` aus `x-client-trace-id`, sonst der B3-Trace-ID).
- **Tracing:** `x-client-trace-id`, die B3-Header und `traceparent` gehen unverändert mit jedem Aufruf an die b-api und
  an edu-sharing weiter, dazu `X-Request-ID` (D108).

## 6. Zustand, Skalierung, Datenbanken

- **Zustand:** Eine Anfrage hält keinen Zustand über sich hinaus; es gibt keine Sitzungen. Jeder Worker hat eigene
  Caches im Speicher (gelesene Artikel), den Schutzschalter der b-api und, wenn gesetzt, sein Rate-Limit.
- **Daten:** Zwei Volumes ([Aufbau](README.md#aufbau)). `zim` (Archive, mindestens 50 GB) schreibt der `zim-updater`,
  `state` (Lehrpläne, Indexe, Caches, eigene Templates) die anderen drei Sidecars; die API liest die SQLite-Dateien nur.
  Selbst schreibt sie den Sammlungs-Cache `wlo_cache.db` (ein Cache, verzichtbar) und über die Admin-Pfade eigene
  Templates, Auftragsdateien für Sync und Harvest und das Löschen eines Archivs: `zim` und `state` müssen für die API
  darum schreibbar sein, wenn die Admin-Pfade genutzt werden.
- **Mehrere Pods:** möglich, wenn `zim` und `state` als gemeinsames Volume (ReadWriteMany) bei allen Pods liegen und
  jeder Sidecar genau einmal läuft. Den Repository-Cache bekommt jeder Pod an einem eigenen Pfad (`WLO_CACHE_PATH` in
  einem `emptyDir`, D109), damit nicht mehrere Pods eine SQLite-Datei über das Netz schreiben. Eigene Templates schreibt
  man über einen Pod.
- **Datenbanken:** keine PostgreSQL, MongoDB oder Redis nötig. SQLite nur für Daten, die ein Sidecar liefert und die API
  liest (nach der Tabelle des Technik-Teams zulässig), und für den Cache.
- **Abschaltbare Teile:** die vier Sidecars (wer Archive, Lehrpläne oder Indexe anders liefert, braucht ihren Sidecar
  nicht) und Prometheus (`docker compose --profile monitoring`).

## 7. Ressourcen und große Daten

- **Baseline:** gemessen am 29.09.2026 ([README](README.md#ressourcen)): API nach dem Aufwärmen 3,4 GiB, je weiterer
  Worker rund 1,7 GiB, Grenze 6 GiB bei zwei Workern; 2 bis 4 vCPU; Platte 50 bis 60 GB. Seitdem nicht neu gemessen,
  siehe offene Punkte.
- **Große Daten:** liegen nicht im Image. Die Sidecars laden Archive (Kiwix, Prüfsumme SHA-256), Lehrpläne (MEM),
  Wikidata- und GND-Abzüge und tauschen die Dateien in einem Schritt; die API übernimmt neue Daten ohne Neustart. Im
  Kubernetes entspricht das Jobs oder Sidecars auf einem gemeinsamen Volume.

## 8. Konfiguration und Helm

- **Variablen mit Vorgaben:** [Konfiguration](konfiguration.md), alle mit Vorgabe und Empfehlung; `.env.example` als
  Vorlage. `docker-compose.yml` und das `Dockerfile` sind die Referenz für fünf Container, zwei Volumes, Grenzen und
  Härtung.
- **Beispiel-Values:** [helm-values.example.yaml](helm-values.example.yaml), auf die Variablen abgebildet.
- **Secrets:** `B_API_KEY`, `API_KEYS`, `ADMIN_TOKEN`, `METRICS_TOKEN`, `EDU_SHARING_USER`, `EDU_SHARING_PASSWORD`. Die
  Sidecars bekommen keines davon.

## 9. Kosten, Ansprechperson, Wartung

- **Kosten:** Tokens je Kompendium (Teil 1 und 2, M91): `llm-free` 0, `balanced` rund 300, `best-quality` rund 52.000,
  `best-quality-generated` rund 89.000, `best-coverage-generated` rund 112.000; nach Jans Rechnung unter einem Cent je
  Text (07-entscheidungsvorlage, M91). Die Quellen (Kiwix, Wikimedia, DNB, MEM) kosten nichts.
- **Ansprechperson T4:** Jan Schachtschabel.
- **Wartung:** Dependabot und ein wöchentlicher Abhängigkeits-Audit auf GitHub; im GitLab eine geplante Pipeline. Wer
  Updates anstößt und ob der Dienst dauerhaft läuft, ist zu vereinbaren.

## Offene Punkte

- **Status der b-api bei erreichtem Limit:** nicht dokumentiert. Der Dienst nimmt 401, 402 und 403 als Ablehnung, beim
  Schlüssel einer Anfrage auch ein 429 nach den möglichen Versuchen; das sollte das Team der b-api bestätigen.
- **Proxy-Eintrag `compendious-text-generator`:** zeigt womöglich noch auf eine alte Version des Dienstes; vor dem Test
  des durchgereichten Schlüssels `baseUrl` und `forwardApiKey` prüfen lassen.
- **Lastmessung wiederholen:** Die Baseline stammt aus 2.5.0 (29.09.2026); seitdem kamen das zehnfache Bausteinbudget
  (D102) und die Wikipedia-Ausgabe 2026-10 dazu. `lasttest.py` liegt bei.
- **Modelle im Image:** rund 380 MB der 1,1 GB. Sie ließen sich auf ein Volume legen, das ein Init-Container füllt, wenn
  der Betrieb das verlangt.
- **Zweiter Port:** nicht gebaut (siehe „Erreichbarkeit“); nachrüstbar, wenn der Betrieb ihn verlangt.
