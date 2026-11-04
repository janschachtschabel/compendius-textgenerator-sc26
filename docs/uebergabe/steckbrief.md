# Technischer Service-Steckbrief

[Übergabe](README.md) · Stand 04.11.2026 · Release 2.26.0 · Vorlage „Technischer Service-Steckbrief“ von Team 6.
Ausführlich: [Antworten für das IT-Team](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/anforderungen.md), [Konfiguration](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/konfiguration.md), [Aufrufe](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/aufrufe.md).

| | |
|---|---|
| **Service** | Kompendiale Texte (`compendious-text-generator`) |
| **Zweck** | Schreibt zu einem Thema einen belegten Sachtext für Lehrkräfte (Teil 1), nennt passende Lehrplanelemente (Teil 2) und gibt einen Überblick über eine edu-sharing-Sammlung (Teil 3); dazu Fragen und Antworten, Entitäten mit Wikidata- und GND-Kennung und die Wissenstexte eines Themas |
| **Quellen** | Lokale Kiwix-Archive (Wikipedia, Klexikon), Lehrplan-Cache (MEM), Wikidata und GND als lokale Indexe; edu-sharing nur, wenn ein Knoten oder eine Sammlung angefragt ist |
| **Technischer Owner** | Jan Schachtschabel · Vertretung: *offen, bitte benennen* |
| **Readiness Status** | Übergabeprüfung |
| **Offene Punkte** | 4, davon 1 kritisch (siehe unten) |
| **Jira** | [GEN-323](https://edu-sharing.atlassian.net/browse/GEN-323) & [GEN-346](https://edu-sharing.atlassian.net/browse/GEN-346) |

## Funktionen: Laufzeit und Kosten

Ein Profil (`preset`) wählt je Anfrage zwischen Tempo und Qualität; ohne LLM läuft alles mit `llm-free`. Gemessen
allein im Median (M82, M91), Kosten mit `gpt-6-luna` über die b-api. Standard mit LLM: `best-quality-generated`.

| Funktion | Endpunkt | `llm-free` | Standard (`best-quality-generated`) | `best-coverage-generated` |
|---|---|---|---|---|
| Kompendium, Teil 1 und 2 | `POST /api/v2/compendium` | 2,9 s · 0 Tokens | 27,5 s · 89.000 Tokens (< 1 Cent) | 32,5 s · 112.000 Tokens |
| Fragen und Antworten zu einem Thema | `POST /api/v2/qa` | 3,4 s · 0 | 8,7 s · 3.200 | wie Standard |
| Fragen und Antworten zu einem Text | `POST /api/v2/qa` | 0,5 s · 0 | 5,8 s · 8.200 | wie Standard |
| Entitäten mit Kennungen (1.500 Zeichen) | `POST /api/v2/entities` | 2,4 s · 0 | 5,8 s · 1.200 | wie Standard |
| Wissenstexte eines Themas | `POST /api/v2/knowledge` | 0,6 s · 0 | 3,6 s · 750 | wie Standard |
| Lehrplansuche | `GET /api/v2/lehrplan/search` | 0,02 bis 0,6 s · 0 | 2,7 bis 4,4 s · 4.500 bis 4.900 | wie Standard |
| Knoten lesen, als Text ausgeben | `GET /api/v2/nodes/{id}` | nicht gemessen, hängt an edu-sharing · 0 | – | – |

Unter Last, auf dem Testserver: fünf Kompendien zugleich im Standard 36 bis 86 s (die Zeit liegt bei der b-api), in
`llm-free` 17,5 bis 26,5 s;
Frist 300 s. Profile `balanced` (3,8 s, 320 Tokens) und `best-quality` (14,9 s, 52.000 Tokens) liegen dazwischen.

## Eingaben

Alles geht auch ohne Repository, nur mit Text (D114): Thema (`topic`), ein Material (`material`) oder eine Sammlung mit
ihrem Ort im Themenbaum (`collection_context`) als Text, eigene Texte als Quellen (`sources`). `GET /api/v2/nodes/{id}`
liefert einen Knoten fertig als Text. Nur Teil 3 braucht das Repository (`collection_id`).

## Stammdaten & API

| | | Status |
|---|---|---|
| Repository | GitLab (Produktiv): `scm.edu-sharing.com/edu-sharing/projects/wlo/compendious-text-generator`; GitHub (Entwicklung): [compendius-textgenerator-sc26](https://github.com/janschachtschabel/compendius-textgenerator-sc26) | erfüllt |
| OpenAPI | `GET /openapi.json` (3.1), lesbar unter `/docs`, mit Beispielen je Endpunkt | erfüllt |
| Tags, Images, Charts | Tag `vX.Y.Z` → Image `ghcr.io/janschachtschabel/compendius-textgenerator-sc26:X.Y.Z` und Helm-Chart `oci://ghcr.io/janschachtschabel/charts/compendious-text-generator` in derselben Version | erfüllt |
| Ports | 8000 öffentlich: `/api/v2/…`, `/docs`, `/openapi.json`. 9000 nur im Cluster: `/health`, `/ready`, `/metrics`, Status | erfüllt |
| Header | Ein: `Authorization: Bearer <b-api-Schlüssel>`, B3 (`X-B3-*`, `b3`), `traceparent`, `x-client-trace-id`. Aus: `X-Request-ID`, `X-B3-TraceId`. Nur `application/json` | erfüllt |
| Asynchrone Jobs | Keine; synchron, siehe Laufzeiten; Proxy-Timeout ≥ 330 s | nicht anwendbar |

## B-API

| | | Status |
|---|---|---|
| Authentifizierung | Mit b-api (empfohlen): Der Dienst nimmt den Schlüssel des Aufrufers und reicht ihn an die b-api weiter; Abrechnung und Fehlersuche je Schlüssel. Ohne b-api: eigener `B_API_KEY`, Aufrufer mit `X-API-Key` aus `API_KEYS` (`B_API_KEY_SOURCE`) | erfüllt |
| Proxy-Eintrag | `compendious-text-generator` auf Port 8000, `forwardApiKey`, Timeout ≥ 330 s | **offen (kritisch)** |
| Rechte des Schlüssels | `chat/completions`; für einen eigenen `B_API_KEY` dazu `models` | erfüllt |
| Modell heute | Provider `openai`, `gpt-6-luna`; eine Route bündelt nur Modelle derselben Parameterfamilie | erfüllt |
| Empfohlene Route | Ebene 0 `openai/gpt-6-luna`, Ebene 1 `openai/gpt-5.6-luna` (gleiche Parameter). Ebene 2 academiccloud mit einem schnellen Qwen-Modell (etwa Qwen 3.5 35B) nur nach einer Probe: Die Route reicht die GPT-Parameter (`max_completion_tokens`, `reasoning_effort`) unverändert weiter, und Qwen denkt ohne `enable_thinking: false` lange; academiccloud hat heute zu knappe Grenzen. Ohne LLM bleibt `llm-free` | Vorschlag |
| Prompt-Caching | Feste Teile (Bausteinkatalog, Überblick) stehen vorn in der System-Nachricht; OpenAI rechnet gecachte Eingabe günstiger ab, Schreiben in den Cache kostet dort nichts extra. Bei Anbietern mit Aufschlag für das Schreiben (Anthropic +25 %) neu rechnen | erfüllt |
| Andere Anbieter | Das Modell ist einstellbar (`B_API_MODEL`, `B_API_ROUTE`); ein Kunde ohne OpenAI nutzt eine Route seines Anbieters oder `llm-free` | erfüllt |

## Deployment

| | | Status |
|---|---|---|
| Helm-Chart | Im Repository: [`deploy/helm/compendious-text-generator`](https://github.com/janschachtschabel/compendius-textgenerator-sc26/tree/main/deploy/helm/compendious-text-generator), je Tag veröffentlicht; Values mit Kommentar je Wert: Image, Ressourcen, Proben, Ingress, NetworkPolicy, PVCs, Secrets, ServiceMonitor, PrometheusRule | erfüllt |
| Docker Compose | `docker-compose.yml` für einen Host, mit demselben Image; wird weiter gepflegt und bei jedem Release mitgetestet | erfüllt |
| Image | Mehrstufig, `python:3.13-slim`, nicht root, nur lesend; zwei Modelle (380 MB) bewusst im Image | erfüllt |
| Updates der Daten | Vier Updater (Kiwix, Lehrpläne, Wikidata, GND). Helm: CronJobs gestaffelt nachts (GND 01:15 täglich, Wikidata 02:15 täglich, Lehrpläne sonntags 03:15, Kiwix sonntags 04:15); Compose: Container mit Schleife | erfüllt |
| Netz | NetworkPolicy im Chart. API: ein nur von der b-api (8000) und vom Monitoring (9000); aus DNS und HTTPS (443), mit Sammler auch dessen Port. Updater: nichts ein, aus DNS und HTTPS. Eine NetworkPolicy kennt keine Hostnamen: Ziele auf b-api, edu-sharing und die Downloadquellen begrenzen per `ipBlock` oder FQDN-Regeln des CNI | erfüllt |
| Skalierung | API-Pods zustandslos, beliebig viele; Indexe als lokale Kopie je Pod, Volumes nur lesend (D113); Updater je genau einmal | erfüllt |
| Datenbank | Keine; SQLite nur lesend und als Cache je Pod | erfüllt |
| Volumes | `zim` 60 Gi und `state` 5 Gi (ReadWriteMany), `emptyDir` 2 Gi je API-Pod | erfüllt |

## Security und Konfiguration

| | | Status |
|---|---|---|
| Env-Variablen | 87 mit Vorgabe ([konfiguration.md](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/konfiguration.md), [.env.example](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/.env.example)) | erfüllt |
| Secrets (ohne Werte) | `B_API_KEY`, `API_KEYS`, `ADMIN_TOKEN`, `METRICS_TOKEN`, `EDU_SHARING_USER`, `EDU_SHARING_PASSWORD`; alle optional | erfüllt |
| WLO und edu-sharing | Läuft mit jedem edu-sharing (Standardfelder); WLO-eigen sind nur das Fachvokabular und der Themenbaum. Ohne Repository über Text-Input | erfüllt |

## Monitoring und Betrieb

| | | Status |
|---|---|---|
| Metriken | `GET /metrics` am Port 9000, optional mit `METRICS_TOKEN`; 25 Alarmregeln mit Tests, im Chart als PrometheusRule | erfüllt |
| Logs | JSON nach stdout: `service`, `trace_id` und `span_id` im B3-Format, `request_id` | erfüllt |
| Tracing | B3 mit OpenTelemetry: TraceId vom Aufrufer oder neu, eigener Span, Weitergabe als `X-B3-*` an b-api und edu-sharing; Spans an Jaeger mit `OTEL_EXPORTER_OTLP_ENDPOINT` | erfüllt |

## Ressourcen

| | | Status |
|---|---|---|
| API | Request 2 CPU / 5 Gi, Limit 4 CPU / 6 Gi bei zwei Workern; Speicher fest (4,0 GiB warm, unter Last +0,2 GiB), je weiterer Worker +2 Gi | erfüllt |
| Updater | 128 Mi bis 1 Gi, Wikidata 2 Gi (großzügig, nach den ersten Läufen senken); als CronJob nur während des Laufs | erfüllt |
| Ein Host | 4 vCPU, 8 bis 12 GB RAM, 60 GB SSD | erfüllt |
| Externe Kosten | Keine außer LLM-Tokens über die b-api | erfüllt |

## Offene Punkte

1. **Kritisch:** Proxy-Eintrag `compendious-text-generator` in der b-api (Port 8000, `forwardApiKey`, Timeout ≥ 330 s) –
   Team der b-api.
2. Status der b-api bei erreichtem Limit bestätigen (der Dienst nimmt 401, 402, 403, 429) – Team der b-api.
3. Route anlegen, falls Routing gewünscht; Ebene 2 vorher proben – Administrator der b-api.
4. Werte des Clusters fürs Chart: StorageClass mit ReadWriteMany, Selektoren der NetworkPolicy, Host des Ingress, Name
   des Secrets – T4.

Links: [Übergabe](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/README.md) · [Betrieb](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/betrieb.md) · [Audit 16.10.](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/audits/2026-10-16-audit.md) ·
[Änderungen](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/CHANGELOG.md) · [Architektur](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/entwicklung/10-architektur.md)
