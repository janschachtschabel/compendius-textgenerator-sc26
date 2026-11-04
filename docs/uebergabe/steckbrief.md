# Steckbrief: Kompendiale Texte

[Übergabe](README.md) · Stand 05.11.2026 · Release 2.26.0 · Vorlage „Technischer Service-Steckbrief“ von Team 6

| | |
|---|---|
| **Service** | Kompendiale Texte (`compendious-text-generator`) |
| **Zweck** | Belegter Sachtext zu einem Thema für Lehrkräfte (Teil 1), passende Lehrplanelemente (Teil 2), Überblick über eine edu-sharing-Sammlung (Teil 3); dazu Fragen und Antworten, Entitäten mit Wikidata- und GND-Kennung, Wissenstexte |
| **Owner** | Jan Schachtschabel · Vertretung: *offen* |
| **Status** | Übergabeprüfung · 4 offene Punkte, davon 1 kritisch |
| **Jira** | [GEN-323](https://edu-sharing.atlassian.net/browse/GEN-323), [GEN-346](https://edu-sharing.atlassian.net/browse/GEN-346) |
| **Repository** | GitLab (Produktion): `scm.edu-sharing.com/edu-sharing/projects/wlo/compendious-text-generator` · GitHub (Entwicklung): [compendius-textgenerator-sc26](https://github.com/janschachtschabel/compendius-textgenerator-sc26) |

![Kompendiale Texte im Kontext](bilder/steckbrief_kontext.png)

## Funktionen

![Funktionen: Sekunden je Aufruf, llm-free und Standard](bilder/steckbrief_funktionen.png)

- `preset` wählt je Anfrage zwischen Tempo und Qualität; ohne LLM läuft alles mit `llm-free`.
- Eingaben auch ohne Repository, als Text: `topic`, `material`, `collection_context`, `sources`.
- API-Doku: `/docs` am Port 8000, mit Beispielen je Endpunkt.

## Betrieb

| | |
|---|---|
| Image | `ghcr.io/janschachtschabel/compendius-textgenerator-sc26:X.Y.Z` · nicht root, nur lesend |
| Helm-Chart | `oci://ghcr.io/janschachtschabel/charts/compendious-text-generator` in derselben Version, je Git-Tag |
| Compose | `docker-compose.yml` für einen Host, dasselbe Image |
| Ports | **8000** API, `/docs` (über die b-api) · **9000** intern: `/health`, `/ready`, `/metrics` |
| Updater | CronJobs nachts: GND 01:15 und Wikidata 02:15 täglich, Lehrpläne 03:15 und Kiwix 04:15 sonntags |
| Volumes | `zim` 60 Gi, `state` 5 Gi (ReadWriteMany) · `emptyDir` 2 Gi je API-Pod |
| Ressourcen API | 2 Worker: Request 2 CPU / 5 Gi, Limit 4 CPU / 6 Gi; je weiterer Worker +2 Gi |
| Skalierung | API-Pods zustandslos, beliebig viele · Updater je genau einmal |
| Datenbank | keine (SQLite nur lesend und als Cache) |
| Netz | NetworkPolicy: ein nur von b-api (8000) und Monitoring (9000) · aus DNS, HTTPS, ggf. Trace-Sammler |

## B-API

| | |
|---|---|
| Rolle | Dienst-Proxy: die b-api prüft den Schlüssel und reicht ihn weiter; der Dienst prüft nicht selbst |
| Proxy-Eintrag | Port 8000, `forwardApiKey`, Timeout ≥ 330 s · **offen, kritisch** |
| LLM | über die b-api mit dem Schlüssel des Aufrufers: `openai` / `gpt-6-luna` |
| Route (Vorschlag) | `gpt-6-luna` → Reserve `gpt-5.6-luna` · Qwen über academiccloud erst nach einer Probe |
| Kosten | Standard < 1 Cent je Kompendium · `llm-free` 0 · keine weiteren externen Kosten |

## Monitoring

| | |
|---|---|
| Metriken | `/metrics` am Port 9000 · 25 Alarmregeln, im Chart als PrometheusRule |
| Logs | JSON nach stdout: `service`, `trace_id`, `span_id`, `request_id` |
| Tracing | B3 (`X-B3-*`) mit OpenTelemetry · Spans optional an Jaeger |

## Konfiguration

| | |
|---|---|
| Env | 87 Variablen, alle mit Vorgabe ([Konfiguration](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/konfiguration.md)) |
| Secrets | `B_API_KEY`, `API_KEYS`, `ADMIN_TOKEN`, `METRICS_TOKEN`, `EDU_SHARING_USER`, `EDU_SHARING_PASSWORD` · alle optional |

## Offene Punkte

1. **Kritisch:** Proxy-Eintrag in der b-api anlegen – Team der b-api.
2. Status der b-api bei erreichtem Limit bestätigen (der Dienst nimmt 401, 402, 403, 429) – Team der b-api.
3. Route anlegen, falls gewünscht; Ebene 2 vorher proben – Administrator der b-api.
4. Werte des Clusters fürs Chart: StorageClass (RWX), Selektoren der NetworkPolicy, Ingress-Host, Secret – T4.

Mehr: [Antworten für das IT-Team](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/anforderungen.md) ·
[Aufrufe](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/aufrufe.md) ·
[Betrieb](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/betrieb.md) ·
[Leitfaden für Dienste](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/uebergabe/leitfaden-dienste.md) ·
[Architektur](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/entwicklung/10-architektur.md) ·
[Änderungen](https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/CHANGELOG.md)
