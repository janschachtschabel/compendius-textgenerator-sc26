# Technischer Service-Steckbrief

[Übergabe](README.md) · Stand 15.10.2026 · Release 2.23.0

Die Vorlage „Technischer Service-Steckbrief“ von Team 6, ausgefüllt. Die Antworten stehen ausführlich in
[anforderungen.md](anforderungen.md); hier stehen je Punkt der Stand und das Wichtigste dazu. Status wie in der
Vorlage: ungeprüft, offen, in Arbeit, erfüllt, nicht anwendbar.

| | |
|---|---|
| **Service** | Kompendiale Texte (`compendious-text-fastapi`) |
| **Technischer Owner** | Jan Schachtschabel |
| **Readiness Status** | Übergabeprüfung: der Dienst ist vollständig beschrieben, die offenen Punkte liegen überwiegend bei der b-api |
| **Offene Punkte** | 5 |
| **Kritische offene Punkte** | 1 (der Eintrag des Dienstes im Proxy der b-api) |
| **Jira** | GEN-357 |

## Stammdaten & API

| Punkt | Status | Information |
|---|---|---|
| Anzeigename und Beschreibung | erfüllt | `info.title` „Kompendiale Texte“; `info.summary` für den Produktkatalog: „Erstellt zu einem Thema einen kompendialen Text für Lehrende und Lernende: Weltwissen aus Wikipedia und Klexikon, Bezüge zu den Lehrplänen der Länder und die Materialien einer WLO-Sammlung, jede Aussage mit ihrer Quelle.“ `info.description` für Entwickler (D107) |
| Repository-Link | erfüllt | https://github.com/janschachtschabel/compendius-textgenerator-sc26, Branch `main`; für das interne GitLab liegt `.gitlab-ci.yml` nach dem Muster der Plattform bereit |
| OpenAPI Spec | erfüllt | OpenAPI 3.1 aus dem Code: `GET /openapi.json`, lesbar unter `/docs` und `/redoc`. Nur die öffentlichen Endpunkte, mit Beispielen und Fehlerantworten; Tests halten das vollständig |
| Pipeline und Git-Tags | erfüllt | GitHub Actions: ruff, mypy, Tests mit Abdeckung ≥ 90 %, Alarmregeln, `pip-audit`; baut das Image, prüft es gehärtet und veröffentlicht es auf GHCR. Tag `vX.Y.Z` → `:X.Y.Z` und `:X.Y`; `:latest` und `:main` für Staging |
| Endpunkte (öffentliche und Infrastruktur) | erfüllt | Port 8000 (`PUBLIC_PORT`): `/api/v2/compendium`, `/knowledge`, `/qa`, `/entities`, `/nodes/{id}`, `/collections/{id}/overview`, `/lehrplan/search`, `/templates`, `/matching/strategies`, `/openapi.json`, `/docs`, `/redoc`. Port 9000 (`INTERNAL_PORT`): `/health`, `/ready`, `/metrics`, `/api/v2/zim/status`, `/api/v2/lehrplan/status`; am Port 8000 antworten sie mit 404. Admin-Pfade nur mit `ADMIN_TOKEN`, nicht im Ingress ([betrieb.md](../betrieb.md#erreichbarkeit)) |
| Spezielle Header und Content-Types | erfüllt | Ein: `Authorization` (Schlüssel, den die b-api durchreicht), sonst `X-API-Key`; optional `X-Request-ID`, `x-client-trace-id`, B3, `traceparent`. Aus: `X-Request-ID`. Nur `application/json`; kein Streaming, keine Dateien |
| Asynchrone Job-Endpunkte | nicht anwendbar | Alles synchron: Ein Job über die Anfrage hinaus müsste den Schlüssel des Aufrufers halten, was die b-api ausschließt. Median 3 s (`llm-free`) bis 33 s (`best-coverage-generated`), Frist `REQUEST_TIMEOUT_S` 300 s; Ingress und Proxy mindestens 330 s |

## Architektur

| Punkt | Status | Information |
|---|---|---|
| Übersicht | erfüllt | Ein Image, fünf Container (API, vier Sidecars), zwei Volumes ([Bild](bilder/container.svg)); drei interaktive Diagramme mit Belegen im Code ([Architektur](../entwicklung/10-architektur.md)) |
| Zustandslos oder zustandsbehaftet | erfüllt | Zustandslos: keine Sitzungen, Historien oder Job-Status. Je Worker Caches, die nur Zeit sparen, und der Schutzschalter für die b-api; der Repository-Cache je Pod (SQLite, `WLO_CACHE_PATH`) |
| Horizontale Skalierbarkeit | erfüllt | Über Worker und Pods, je Worker rund 1,7 GiB; mehr CPU je Worker hilft nicht. Volumes `zim` und `state` ReadWriteMany, lesend geteilt; jeder Sidecar genau einmal (Lock-Dateien) |

## Deployment und Infrastruktur

| Punkt | Status | Information |
|---|---|---|
| Docker-Files | erfüllt, eine Abweichung | Mehrstufig auf `python:3.13-slim`, UID 10001, nur lesendes Dateisystem, keine Capabilities, Basis-Images per Digest; `docker-compose.yml` als Referenz. Abweichung: Model2Vec und spaCy (rund 380 MB der 1,1 GB) liegen im Image. Auf einem Volume hinge jeder Start an ihrer Quelle, und ihre Version müsste außerhalb des Images festgehalten werden |
| HELM-Chart und Beispiel-Values | erfüllt | [helm-values.example.yaml](helm-values.example.yaml): Image, Env, Secrets, Ressourcen, Proben am Port 9000, Volumes, Sidecars, Ingress-Pfade, PrometheusRule, ServiceMonitor. Das Chart selbst baut T6 nach seinem Muster |
| Abschaltbare Komponenten | erfüllt | Jeder der vier Sidecars, Prometheus, Prüfansicht (`UI_ENABLED`), API-Doku (`API_DOCS_ENABLED`), Metriken (`METRICS_ENABLED`), LLM (`LLM_ENABLED`; ohne läuft alles nach Regeln) |
| Datenbank | erfüllt | Keine PostgreSQL, MongoDB oder Redis. SQLite nur für Daten, die ein Sidecar liefert und die API nur liest (`lehrplan.db`, `wikidata.db`, `gnd.db`), und als Repository-Cache je Pod |
| Quelle und Volume-Größe für große Daten | erfüllt | Nicht im Image: Die Sidecars laden mit Prüfsumme auf die Volumes und tauschen jede Datei in einem Schritt, die API übernimmt sie ohne Neustart. `zim` 60 Gi (Wikipedia, Klexikon von Kiwix, rund 18,7 GB, beim Wechsel bis 38 GB), `state` 5 Gi (Lehrpläne von MEM, Wikidata- und GND-Index) |

## Security und Konfiguration

| Punkt | Status | Information |
|---|---|---|
| Authentifizierungskonzept | erfüllt | Beide Varianten in einem Dienst, umschaltbar per `B_API_KEY_SOURCE`; empfohlen über die b-api |
| Mit B-API: Modell fürs Routing | erfüllt | Vorgabe ohne Routing: Provider `openai` mit `gpt-6-luna`. Optional `B_API_PROVIDER=router` mit `B_API_ROUTE`; die Route legt ein Administrator der b-api global an (Vorschlag `gpt-6-luna`, Reserve `gpt-5.6-luna`) |
| Mit B-API: virtueller Key benötigt? | erfüllt | Ja, ab `balanced`. Der Schlüssel des Aufrufers aus `Authorization` geht unverändert nur an die b-api, ungespeichert und ungeloggt; `B_API_KEY` nur für Aufrufe ohne eigenen Schlüssel. Ein abgelehnter Schlüssel oder eine ausgesetzte Route lässt die Anfrage mit Grund nach den Regeln laufen (D106) |
| Mit B-API: Berechtigungen des Keys | erfüllt | Aufrufer: `/api/v1/llm/openai/chat/completions`, mit Routing `/api/v1/llm/router/…`; `B_API_KEY` dazu `/api/v1/llm/openai/models`. Keine Routenverwaltung, kein Admin |
| Ohne B-API: LLM-Keys und Authentifizierung | erfüllt | `B_API_KEY` (Secret), `B_API_KEY_SOURCE=env`; Aufrufer mit `X-API-Key` aus `API_KEYS` (je ≥ 16 Zeichen, Wechsel ohne Ausfall), `RATE_LIMIT` je Aufrufer, `ADMIN_TOKEN` für die Admin-Pfade |
| Env-Variablen inklusive Defaults | erfüllt | 83 Variablen mit Vorgabe und Empfehlung in [konfiguration.md](konfiguration.md), Vorlage `.env.example`; ohne Eintrag gilt die Vorgabe |
| Benötigte Secrets (ohne Werte) | erfüllt | `B_API_KEY`, `API_KEYS`, `ADMIN_TOKEN`, `METRICS_TOKEN`, `EDU_SHARING_USER`, `EDU_SHARING_PASSWORD` (Gastkonto der WLO, optional, D112); die Sidecars bekommen keines |

## Monitoring und Betrieb

| Punkt | Status | Information |
|---|---|---|
| Prometheus-Endpunkt | erfüllt | `GET /metrics` nur am Port 9000, Werte aller Worker; optional mit Bearer-Token (`METRICS_TOKEN`) |
| Applikationsmetriken und Alarmregeln | erfüllt | Anfragen, Phasen und Teile der Kompendien, LLM-Aufrufe, Tokens und Rückfälle, Stand von Archiven, Indexen, Lehrplänen und Sidecars, freier Platz. 25 Alarmregeln mit Tests (`monitoring/alerts.yml`) als `PrometheusRule`; der ServiceMonitor braucht den Job-Namen `kompendium` |
| Log-Format und x-client-trace-id | erfüllt | stdout; `LOG_FORMAT=json` mit `time`, `level`, `pid`, `logger`, `request_id`, `trace_id`, `message`; `LOG_LEVEL`. `x-client-trace-id`, B3 und `traceparent` gehen an b-api und edu-sharing weiter (D108) |

## Ressourcen und Kosten

| Punkt | Status | Information |
|---|---|---|
| CPU, RAM und Storage | erfüllt, Wiederholung offen | API: RAM 4 Gi Request, 6 Gi Limit (3,4 GiB warm, je weiterer Worker 1,7 GiB); CPU 2 / 4. Sidecars je rund 108 MiB. `zim` 60 Gi, `state` 5 Gi, keine GPU. Gemessen mit 2.5.0 am 29.09.; seitdem kamen das zehnfache Bausteinbudget und die Wikipedia 2026-10 dazu |
| Erwartete LLM-Kosten | erfüllt | Tokens je Kompendium (M91): `llm-free` 0, `balanced` rund 300, `best-quality` rund 52.000, `best-quality-generated` (Vorgabe) rund 89.000, `best-coverage-generated` rund 112.000; geschätzt unter einem Cent je Text. Hinter der b-api auf den Schlüssel des Aufrufers; die Limits setzt die b-api |
| Kosten externer APIs | erfüllt | Keine: Kiwix, Wikimedia, DNB, MEM und edu-sharing kosten nichts |

## Übergabe

| Punkt | Status | Information |
|---|---|---|
| Ansprechperson in T4 | erfüllt | Jan Schachtschabel |
| Bekannte Einschränkungen und offene Punkte | in Arbeit | Liste unten |
| Links zu Betriebsdokumentation und Nachweisen | erfüllt | [Übergabe](README.md), [Antworten für das IT-Team](anforderungen.md), [Konfiguration](konfiguration.md), [Aufrufe](aufrufe.md), [Beispiel-Values](helm-values.example.yaml), [Betrieb](../betrieb.md), [Audit vom 15.10.2026](../audits/2026-10-15-audit.md), [Änderungsprotokoll](../../CHANGELOG.md) |

## Offene Punkte

1. **Kritisch – Proxy-Eintrag `compendious-text-generator`:** zeigt womöglich auf eine alte Version des Dienstes;
   `baseUrl` (Port 8000), `forwardApiKey` und ein Timeout von mindestens 330 s prüft das Team der b-api. Ohne ihn lässt
   sich der durchgereichte Schlüssel nicht testen.
2. **Status der b-api bei erreichtem Limit:** nicht dokumentiert; der Dienst nimmt 401, 402, 403 und ein 429 nach den
   Versuchen als Ablehnung. Bestätigung durch das Team der b-api.
3. **Globale Route**, nur wenn Routing gewünscht ist: legt ein Administrator der b-api an. Ohne sie läuft der Dienst
   direkt mit `gpt-6-luna`.
4. **Lastmessung wiederholen:** die Baseline stammt aus 2.5.0; `lasttest.py` liegt bei.
5. **Modelle im Image:** bewusst so (oben); offen nur, falls der Betrieb es anders verlangt.

Aus dem Audit vom 15.10.2026 bleiben drei Punkte, die die Übergabe nicht blockieren: Die CI pusht ein neu gebautes
statt des geprüften Images, die Betriebssystem-Pakete des Images werden nicht gescannt, und das Build-Werkzeug liegt im
Laufzeit-Image ([Bericht](../audits/2026-10-15-audit.md), Abschnitt 5).
