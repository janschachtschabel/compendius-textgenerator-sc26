# Technischer Service-Steckbrief

[Übergabe](README.md) · Stand 16.10.2026 · Release 2.23.0 · Vorlage „Technischer Service-Steckbrief“ von Team 6.
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
| Pipeline und Git-Tags | GitHub Actions prüft, baut und veröffentlicht auf GHCR; Tag `vX.Y.Z` → `:X.Y.Z`; aktuell `v2.23.0` ([ci.yml](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/.github/workflows/ci.yml)) | erfüllt |
| Endpunkte (öffentliche und Infrastruktur) | Port 8000: `/api/v2/…`, `/openapi.json`, `/docs`. Port 9000: `/health`, `/ready`, `/metrics`, Status ([betrieb.md](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/betrieb.md#erreichbarkeit)) | erfüllt |
| Spezielle Header und Content-Types | Ein: `Authorization` (Schlüssel aus der b-api), optional `x-client-trace-id`, B3. Aus: `X-Request-ID`. Nur `application/json` | erfüllt |
| Asynchrone Job-Endpunkte | Keine; synchron, 3 bis 33 s im Median, fünf gleichzeitig bis 86 s; Frist 300 s, Proxy-Timeout ≥ 330 s | nicht anwendbar |

## Architektur

| | | Status |
|---|---|---|
| Übersicht | Ein Image, fünf Container, zwei Volumes; drei interaktive Diagramme: [Systemübersicht](https://janschachtschabel.github.io/compendius-textgenerator-sc26/entwicklung/architektur/systemuebersicht.html), [Anfrage](https://janschachtschabel.github.io/compendius-textgenerator-sc26/entwicklung/architektur/kompendium-anfrage.html), [Sidecars und Daten](https://janschachtschabel.github.io/compendius-textgenerator-sc26/entwicklung/architektur/sidecars-und-daten.html) ([Erläuterung](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/entwicklung/10-architektur.md)) | erfüllt |
| zustandslos oder zustandsbehaftet | Zustandslos; nur Caches, Repository-Cache je Pod | erfüllt |
| Horizontale Skalierbarkeit | API-Pods über beliebige Nodes: jeder liest die SQLite-Indexe aus einer lokalen Kopie (`INDEX_COPY_DIR`), die Volumes nur lesend (D113); je Worker ~2 GiB; Updater genau einmal | erfüllt |

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
| CPU, RAM und Storage | API: Request 2 CPU / 5 Gi, Limit 4 CPU / 6 Gi (gemessen 16.10. mit 2.23.0: 4,02 GiB warm, Spitze 3,4 Kerne); je weiterer Worker +2 Gi. Sidecars: 128 Mi / 512 Mi, `wikidata-updater` 1,5 Gi (geschätzt). Volumes `zim` 60 Gi, `state` 5 Gi, `emptyDir` 1 Gi. Ein Host: 4 vCPU, 8–12 GB RAM, 60 GB SSD ([Lastmessung](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/README.md#lastmessung-vom-16102026)) | erfüllt |
| Erwartete LLM-Kosten | Je Kompendium 0 (`llm-free`) bis ~112.000 Tokens; Vorgabe ~89.000, geschätzt < 1 Cent; Abrechnung je Schlüssel in der b-api | erfüllt |
| Kosten externer APIs | Keine (Kiwix, Wikimedia, DNB, MEM, edu-sharing) | erfüllt |

## Übergabe

| | | Status |
|---|---|---|
| Ansprechperson in T4 | Jan Schachtschabel | erfüllt |
| Bekannte Einschränkungen und offene Punkte | Siehe unten; vier offen, drei davon bei der b-api | erfüllt |
| Links zu Betriebsdokumentation und Nachweisen | [Übergabe](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/README.md), [Betrieb](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/betrieb.md), [Audit 15.10.](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/audits/2026-10-15-audit.md), [Änderungen](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/CHANGELOG.md) | erfüllt |

## Offene Punkte

1. **Kritisch:** Proxy-Eintrag `compendious-text-generator` in der b-api prüfen (`baseUrl` auf Port 8000,
   `forwardApiKey`, Timeout ≥ 330 s) – Team der b-api.
2. Status der b-api bei erreichtem Limit bestätigen (der Dienst nimmt 401, 402, 403, 429) – Team der b-api.
3. Globale Route anlegen, nur wenn Routing gewünscht ist – Administrator der b-api.
4. Modelle im Image: bewusst so, offen nur, falls der Betrieb es anders verlangt.

**Hinweis zur Skalierung:** Die API-Pods sind für die Antworten zustandslos, brauchen keine Session-Affinity und
lassen sich über mehrere Nodes verteilen: Mit `INDEX_COPY_DIR` liest jeder Pod die SQLite-Indexe aus einer Kopie auf
seiner lokalen Platte und das geteilte Volume nur lesend (D113); die vier Updater laufen als eigene Deployments mit
genau einem Replikat, nicht im API-Pod, und die ZIM-Archive kommen weiter vom geteilten Volume (ReadWriteMany).
