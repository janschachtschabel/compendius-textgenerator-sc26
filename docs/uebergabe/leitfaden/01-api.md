# 1. API und Eingaben

[Leitfaden](../leitfaden-dienste.md) · weiter: [2.1 LLM und Routing](02-1-llm-routing.md)

## Vorgaben

- [ ] **OpenAPI** liefern, Pfad dokumentiert (etwa `/openapi.json`, lesbar unter `/docs`). Voraussetzung für die
      Einbindung in die b-api.
- [ ] **Anzeigename und Beschreibung** für Endnutzende in der Spec (`info.title`, `info.description`): was der Dienst
      kann. Grundlage für einen künftigen Produktkatalog.
- [ ] **Nur öffentliche Endpunkte** in der Spec. `/health`, `/ready`, `/metrics` stehen nicht darin und sind von außen
      nicht erreichbar (Kapitel 3).
- [ ] **Header:** Standard ist keiner vom Client und keiner zurück. Benötigte Header benennen und begründen.
- [ ] **Content-Types:** Standard `application/json`. Streaming (SSE), Dateien, Bilder vorab abstimmen.
- [ ] **Antwortzeiten** angeben, damit Proxy und Ingress passende Timeouts bekommen.

## Empfehlungen

- **Spec aus dem Code erzeugen** (FastAPI, Springdoc …). Eine veraltete Spec ist schlimmer als eine fehlende. Zu
  jedem Endpunkt ein kurzes und ein vollständiges Beispiel und eine Erklärung jedes Parameters.
- **Repo-neutral:** Jede Funktion auch mit Text als Eingabe anbieten, nicht nur mit einer Knoten-ID eines
  Repositorys. Wer den Knoten lesen will, liefert dazu eine Hilfe, die ihn als Text ausgibt. Ergebnisse als neutrales
  JSON (oder Markdown im JSON), ohne Annahmen über Metadatensätze eines Kunden. WLO ist nicht jedes edu-sharing:
  WLO-eigene Felder (etwa `ccm:oeh_*`, Fachportale) nur optional nutzen.
- **Lang laufende Verarbeitung** (über etwa 30 s) asynchron: Job anlegen, ID zurück, Status abfragen. Oder als
  Kestra-Flow anbieten (Kapitel 5).
- **Fehler** als JSON mit verständlicher Meldung und der Anfrage-ID; 4xx für Fehler des Aufrufers, 5xx nur für eigene.

## Praxis aus „Kompendiale Texte“

- Die Spec entsteht aus FastAPI; je Endpunkt Beispiele vom kürzesten bis zum vollständigen Aufruf; ein Test prüft,
  dass jedes Feld in einem Beispiel vorkommt und jeder Wert erklärt ist.
- Eingaben ohne Repository: `topic`, `material` (Titel, Beschreibung, Schlagwörter), `collection_context` (eine
  Sammlung mit ihrem Ort im Themenbaum), `sources` (eigene Texte). `GET /api/v2/nodes/{id}` gibt einen Knoten als
  genau diese Felder aus (`text_input`). Tests zeigen: Text und Knoten-ID geben dasselbe Ergebnis.
- Synchron mit Frist 300 s; das Kompendium braucht im Standard 28 s, fünf zugleich bis 86 s. Proxy-Timeout ≥ 330 s.

Muster: [aufrufe.md](../aufrufe.md), `app/api/v2/`.
