# Leitfaden: Dienste für die Plattform bauen

[Übergabe](README.md) · Stand 05.11.2026 · für Entwicklerinnen und Entwickler von Diensten, auch für Dritte.
Grundlage sind die Vorgaben von Team 6 („Was ein Dienst mitbringen muss“), die Dokumente der b-api zu Routing,
durchgereichtem Schlüssel und Flows, die Anmerkungen der Technik zur Übergabe und die Erfahrung aus dem Dienst
„Kompendiale Texte“, der als Muster dient (dieses Repository).

![Die b-api: Proxy für Dienste und für LLM](bilder/leitfaden_bapi.png)

**Ziel:** Team 6 betreibt den Dienst ohne Rückfragen, Kunden rufen ihn über die b-api auf, und er lässt sich mit
anderen Diensten kombinieren, unabhängig vom Repository eines Kunden.

## Die Kapitel

| Kapitel | Worum es geht |
|---|---|
| [1. API und Eingaben](leitfaden/01-api.md) | OpenAPI, öffentliche und interne Endpunkte, Eingaben als Text statt Knoten-ID, Antwortzeiten, Jobs |
| **2. Die b-api** | |
| [2.1 LLM und Routing](leitfaden/02-1-llm-routing.md) | LLM über die b-api, Routen, Parameterfamilien, Cache, Standardrouten, GWDG-Kontingent |
| [2.2 Dienst hinter der b-api](leitfaden/02-2-dienst-hinter-b-api.md) | Proxy-Eintrag, durchgereichter Schlüssel, Rückfall-Schlüssel, Tests, Sicherheit |
| [2.3 Logging und Tracing](leitfaden/02-3-logging-tracing.md) | JSON-Logs, Dienst-ID, B3-Trace-ID mit OpenTelemetry |
| [3. Betrieb](leitfaden/03-betrieb.md) | Ports und Metriken, Zustand und Skalierung, Datenbanken, Ressourcen, große Daten, Updates |
| [4. Build und Helm](leitfaden/04-build-helm.md) | Repo und CI, kleine Images, Helm-Chart je Tag, NetworkPolicy, Pull-Secrets |
| [5. Dienste kombinieren (Kestra)](leitfaden/05-kestra.md) | Flows über die b-api – Stand noch nicht final |
| [6. Übergabe und Wartung](leitfaden/06-uebergabe.md) | Übergabepaket, Steckbrief, Updates, Prototypen |

## Kurzcheckliste

- [ ] OpenAPI aus dem Code, mit Anzeigename, Beschreibung und Beispielen; nur öffentliche Pfade darin.
- [ ] Eingaben ohne Repository möglich (Text statt Knoten-ID); Ergebnisse als neutrales JSON.
- [ ] Hinter der b-api: Schlüssel aus `Authorization` lesen, unverändert an die b-api zurückgeben, nie loggen.
- [ ] LLM nur über die b-api, mit Routennamen statt fester Modelle; eine Parameterfamilie je Route.
- [ ] JSON-Logs nach stdout mit `service` (Dienst-ID), `trace_id`, `span_id`; B3 lesen, weitergeben, sonst anlegen.
- [ ] Zwei Ports: öffentlich die API, intern `/health`, `/ready`, `/metrics`.
- [ ] Zustandslos; keine SQLite für geteilte Daten; große Daten auf Volumes, nicht im Image.
- [ ] Ressourcen gemessen; Worker und Threads passend zum Limit des Containers.
- [ ] Helm-Chart je Tag mit kommentierten Values, NetworkPolicy und Alarmregeln; Docker Compose als Referenz.
- [ ] Steckbrief mit Laufzeit, Kosten, Ressourcen, Ansprechperson und Vertretung.

## Die Dienst-ID

Ein Name für alles, klein, mit Bindestrichen, etwa `compendious-text-generator`:

| Wo | Beispiel |
|---|---|
| Proxy-Eintrag der b-api | `/api/v1/proxy/compendious-text-generator` |
| Feld `service` jeder Logzeile, Spans | `OTEL_SERVICE_NAME=compendious-text-generator` |
| Helm-Chart und Release | `oci://…/charts/compendious-text-generator` |
| Image | `…/compendious-text-generator:X.Y.Z` |
| Route der b-api, falls eigene | `kompendium` (sprechend, je Dienst oder geteilt) |

So findet der Betrieb Logs, Metriken, Spans und Abrechnung desselben Dienstes unter einem Namen.
