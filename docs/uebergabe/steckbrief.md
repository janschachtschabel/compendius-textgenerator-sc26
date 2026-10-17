# Technischer Service-Steckbrief

[Übergabe](README.md) · Stand 17.10.2026 · Release 2.25.0 · Vorlage „Technischer Service-Steckbrief“ von Team 6.
Ausführlich: [Antworten für das IT-Team](anforderungen.md).

| | |
|---|---|
| **Service** | Kompendiale Texte (`compendious-text-fastapi`) |
| **Technischer Owner** | Jan Schachtschabel |
| **Readiness Status** | Übergabeprüfung |
| **Offene Punkte** | 4 |
| **Kritische Offene Punkte** | 1 |
| **Jira** | [GEN-357](https://edu-sharing.atlassian.net/browse/GEN-357) |

## Stammdaten & API

| | | Status |
|---|---|---|
| Anzeigename und Beschreibung | „Kompendiale Texte“; Kurztext für den Katalog in `info.summary` der Spec ([Abschnitt 1](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/anforderungen.md#1-api-und-endpunkte)) | erfüllt |
| Repository-Link | https://github.com/janschachtschabel/compendius-textgenerator-sc26 (`main`) | erfüllt |
| OpenAPI Spec | `GET /openapi.json` (OpenAPI 3.1, aus dem Code), lesbar unter `/docs`; nur öffentliche Endpunkte | erfüllt |
| Pipeline und Git-Tags | GitHub Actions prüft, baut und veröffentlicht auf GHCR; Tag `vX.Y.Z` → `:X.Y.Z`; aktuell `v2.25.0` ([ci.yml](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/.github/workflows/ci.yml)) | erfüllt |
| Endpunkte (öffentliche und Infrastruktur) | Port 8000: `/api/v2/…`, `/openapi.json`, `/docs`. Port 9000: `/health`, `/ready`, `/metrics`, Status ([betrieb.md](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/betrieb.md#erreichbarkeit)) | erfüllt |
| Spezielle Header und Content-Types | Ein: `Authorization` (Schlüssel aus der b-api), optional `x-client-trace-id`, B3. Aus: `X-Request-ID`. Nur `application/json` | erfüllt |
| Asynchrone Job-Endpunkte | Keine; synchron, 3 bis 33 s im Median, fünf gleichzeitig bis 86 s; Frist 300 s, Proxy-Timeout ≥ 330 s | nicht anwendbar |

## Architektur

| | | Status |
|---|---|---|
| Übersicht | Ein Image, fünf Container, zwei Volumes; drei interaktive Diagramme: [Systemübersicht](https://janschachtschabel.github.io/compendius-textgenerator-sc26/entwicklung/architektur/systemuebersicht.html), [Anfrage](https://janschachtschabel.github.io/compendius-textgenerator-sc26/entwicklung/architektur/kompendium-anfrage.html), [Sidecars und Daten](https://janschachtschabel.github.io/compendius-textgenerator-sc26/entwicklung/architektur/sidecars-und-daten.html) ([Erläuterung](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/entwicklung/10-architektur.md)) | erfüllt |
| zustandslos oder zustandsbehaftet | Zustandslos; nur Caches, Repository-Cache je Pod | erfüllt |
| Horizontale Skalierbarkeit | API-Pods über beliebige Nodes: jeder liest die SQLite-Indexe aus einer lokalen Kopie (`INDEX_COPY_DIR`), die Volumes nur lesend, mit `WLO_CACHE_PATH` im `emptyDir` und leerem `ADMIN_TOKEN` (D113); je Worker ~2 GiB; Updater genau einmal ([Skalierbarkeit](#skalierbarkeit): Stufe 1 umgesetzt, Stufe 2 optional) | erfüllt |

## Deployment und Infrastruktur

| | | Status |
|---|---|---|
| Docker-Files | Mehrstufig, `python:3.13-slim`, nicht root, nur lesend ([Dockerfile](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/Dockerfile), [Compose](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docker-compose.yml)). Abweichung: zwei Modelle (380 MB) im Image, bewusst | erfüllt |
| HELM-Chart und Beispiel-Values | [helm-values.example.yaml](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/helm-values.example.yaml): Image, Env, Secrets, Ressourcen (API und Sidecars), Proben, Volumes, Ingress, NetworkPolicy, Monitoring; die Templates des Charts baut T6 | erfüllt |
| Abschaltbare Komponenten | Vier Sidecars, Prometheus, Prüfansicht, API-Doku, Metriken, LLM | erfüllt |
| Datenbank | Keine; SQLite nur lesend (Sidecar-Daten, mit `INDEX_COPY_DIR` als lokale Kopie je Pod) und als Cache je Pod | erfüllt |
| Quelle und Volume-Größe für große Daten | Sidecars laden auf Volumes: `zim` 60 Gi (Kiwix), `state` 5 Gi (MEM, Wikimedia, DNB) | erfüllt |

## Security und Konfiguration

| | | Status |
|---|---|---|
| Authentifizierungskonzept – mit oder ohne B-API | Beides, umschaltbar (`B_API_KEY_SOURCE`); empfohlen über die b-api ([Abschnitt 2](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/anforderungen.md#2-b-api-integration-und-authentifizierung)) | erfüllt |
| Mit B-API: Modell fürs Routing, virtueller Key, Berechtigungen | `openai` mit `gpt-6-luna` (Routing optional, globale Route durch b-api-Admin); virtueller Key ab `balanced`, durchgereicht; Rechte: `chat/completions`, für `B_API_KEY` dazu `models` | erfüllt |
| Ohne B-API: LLM-Keys und Authentifizierung | `B_API_KEY` als Secret; Aufrufer mit `X-API-Key` aus `API_KEYS`; Admin mit `ADMIN_TOKEN` | erfüllt |
| Env-Variablen inklusive Defaults | 85 Variablen mit Vorgabe ([konfiguration.md](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/konfiguration.md), [.env.example](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/.env.example)) | erfüllt |
| Benötigte Secrets (ohne Werte) | `B_API_KEY`, `API_KEYS`, `ADMIN_TOKEN`, `METRICS_TOKEN`, `EDU_SHARING_USER`, `EDU_SHARING_PASSWORD` | erfüllt |

## Monitoring und Betrieb

| | | Status |
|---|---|---|
| Prometheus-Endpunkt | `GET /metrics` am internen Port 9000, optional mit `METRICS_TOKEN` | erfüllt |
| Applikationsmetriken und Alarmregeln | Anfragen, LLM, Tokens, Rückfälle, Daten und Sidecars; 25 Regeln mit Tests ([alerts.yml](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/monitoring/alerts.yml)) | erfüllt |
| Log-Format und x-client-trace-id | JSON nach stdout (`LOG_FORMAT=json`, `trace_id`); Trace-Header gehen an b-api und edu-sharing weiter | erfüllt |

## Ressourcen und Kosten

| | | Status |
|---|---|---|
| CPU, RAM und Storage | API: Request 2 CPU / 5 Gi, Limit 4 CPU / 6 Gi (gemessen 16.10. mit `:latest` auf `cdc96d6`, nach dem Update der Abhängigkeiten: 4,02 GiB warm, Spitze 3,4 Kerne; seit 2.24.0 im Leerlauf 1,41 statt 1,79 GiB je Worker, im Container gemessen, unter Last nicht nachgemessen); je weiterer Worker +2 Gi. Sidecars: 128 Mi / 1 Gi, `wikidata-updater` 2 Gi (großzügig geschätzt, nach den ersten Läufen messen). Volumes `zim` 60 Gi, `state` 5 Gi, `emptyDir` 2 Gi (mit den Kopien der Indexe, D113). Ein Host: 4 vCPU, 8–12 GB RAM, 60 GB SSD ([Lastmessung](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/README.md#lastmessung-vom-16102026)) | erfüllt |
| Erwartete LLM-Kosten | Je Kompendium 0 (`llm-free`) bis ~112.000 Tokens; Vorgabe ~89.000, geschätzt < 1 Cent; Abrechnung je Schlüssel in der b-api | erfüllt |
| Kosten externer APIs | Keine (Kiwix, Wikimedia, DNB, MEM, edu-sharing) | erfüllt |

## Übergabe

| | | Status |
|---|---|---|
| Ansprechperson in T4 | Jan Schachtschabel | erfüllt |
| Bekannte Einschränkungen und offene Punkte | Siehe unten; vier offen, drei davon bei der b-api | erfüllt |
| Links zu Betriebsdokumentation und Nachweisen | [Übergabe](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/README.md), [Betrieb](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/betrieb.md), [Audit 16.10.](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/audits/2026-10-16-audit.md), [Änderungen](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/CHANGELOG.md) | erfüllt |

## Offene Punkte

1. **Kritisch:** Proxy-Eintrag `compendious-text-generator` in der b-api prüfen (`baseUrl` auf Port 8000,
   `forwardApiKey`, Timeout ≥ 330 s) – Team der b-api.
2. Status der b-api bei erreichtem Limit bestätigen (der Dienst nimmt 401, 402, 403, 429) – Team der b-api.
3. Globale Route anlegen, nur wenn Routing gewünscht ist – Administrator der b-api.
4. Modelle im Image: bewusst so, offen nur, falls der Betrieb es anders verlangt.

## Skalierbarkeit

Die API-Pods sind für die Antworten zustandslos und brauchen keine Session-Affinity; die vier Updater laufen als eigene
Deployments mit genau einem Replikat. Seit Release 2.24.0 lassen sich die API-Pods über beliebige Nodes verteilen:
Ausbaustufe 1 ist umgesetzt (D113). Ohne ihre Einstellungen arbeitet der Dienst wie bisher, etwa mit Compose auf
einem Host.

**Ausbaustufe 1: umgesetzt in 2.24.0**

- Indexe lokal je Pod (`INDEX_COPY_DIR`, ein `emptyDir`): Findet die API auf dem Volume eine neue Fassung von
  `lehrplan.db`, `wikidata.db` oder `gnd.db`, kopiert sie die Datei vollständig ins `emptyDir` und tauscht sie dort
  atomar aus; die vorige Kopie bleibt, bis die nächste Fassung kommt. Kein Pod liest SQLite über das Netz, und der
  Tausch durch einen Updater trifft keine Anfrage. Misslingt eine Kopie, liest der Pod die Datei vom Volume und
  versucht es nach 15 Minuten erneut. Die Proben (`/health`, `/ready`) kopieren nie. Das Log nennt jede Kopie mit
  ihrer Dauer.
- Templates nur lesend: Die eingebauten liegen im Image, eigene kommen per ConfigMap (`TEMPLATES_DIR`). Mit leerem
  `ADMIN_TOKEN` gibt es keine Schreib-Endpunkte (sie antworten 404), damit entfällt die Template-Sperre über das Netz.
- Die API hängt `zim` und `state` nur lesend ein; ihren Repository-Cache legt sie dafür ins `emptyDir`
  (`WLO_CACHE_PATH`).
- Die Updater als eigene Deployments mit genau einem Replikat (`replicas: 1`, `strategy: Recreate`), festgehalten im
  [Helm-Beispiel](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/helm-values.example.yaml)
  und in der Doku.

Voraussetzungen: `INDEX_COPY_DIR` und `WLO_CACHE_PATH` im `emptyDir` (2 Gi), `TEMPLATES_DIR` auf der ConfigMap,
`ADMIN_TOKEN` leer; `zim` und `state` als ReadWriteMany-Volume (NFSv4.1 oder CephFS) mit synchronen Uhren (NTP), weil
die Updater ihre Sperrdateien nach dem Alter beurteilen.

Es bleiben: die ZIM-Archive über das Netz (die API liest sie nur, eine Frage der Leistung) und die Sperrdateien der
Updater, unkritisch, weil jeder Updater nur einmal läuft. Noch nicht auf echtem Cluster-Speicher gemessen ist, wie lange
eine Kopie dauert; das Log nennt es.

**Ausbaustufe 2: ganz cloud-nativ (nicht gebaut; nur bei vielen Pods über viele Nodes oder ohne ReadWriteMany-Volume)**

- Updater als CronJobs (`concurrencyPolicy: Forbid`, damit sind keine Sperrdateien nötig). Sie laden Archive,
  Lehrpläne und Abzüge, bauen die Indexe und legen sie versioniert mit Prüfsumme in einen Objektspeicher
  (S3-kompatibel, etwa MinIO oder Ceph RGW), dazu ein Manifest mit dem aktuellen Stand.
- API-Pods ziehen sich neue Fassungen aus dem Objektspeicher: die Indexe ins `emptyDir` (das Kopieren aus Stufe 1
  bleibt), die ZIM-Archive in einen Cache je Node, damit die rund 19 GB nicht in jeden Pod einzeln wandern. Das
  gemeinsame Volume entfällt.
- Templates in PostgreSQL (falls sie im Betrieb änderbar sein sollen), Status über Job-Metriken statt Dateien,
  Alarmregeln entsprechend umgebaut.
- Die Compose-Variante muss parallel weiter funktionieren: zwei Betriebsarten im Code.
