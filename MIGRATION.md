# Umstieg vom alten Kompendium-Dienst

Der Neubau bedient dieselben Endpunkte unter denselben Pfaden (`/health`, `/api/v1/…`). Anfragen des alten
Dienstes laufen unverändert weiter: Feldnamen, Standardwerte und Grenzen sind gleich geblieben. Was sich im
Verhalten ändert, steht hier. Die neuen Endpunkte (`/api/v2/…`) sind in der [README](README.md) beschrieben.

## Das Wichtigste in drei Sätzen

1. Der Text entsteht aus lokalen Wissensarchiven (Kiwix-ZIM) statt aus einem Sprachmodell; ein LLM ist
   optional und nur für zwei Schalter und drei Nebenfunktionen nötig.
2. Fehler kommen als HTTP-Status zurück, nicht mehr als HTTP 200 mit einem Fehlertext im Feld.
3. Jede Aussage im Kompendium trägt eine Belegnummer; die Quellenliste steht im Text und in `bibliography`.

## Was ein Aufrufer merkt

| Endpunkt | Vorher | Jetzt |
|---|---|---|
| `POST /api/v1/compendium` | ein LLM-Aufruf, `markdown` war der erzeugte Text | Themenauflösung in den Archiven, `markdown` ist das vollständige Kompendium (Teil 1 Weltwissen, Teil 2 Lehrplanbezüge, Teil 3 Sammlung, soweit eingerichtet), `bibliography` ist der Baustein Quellen |
| `POST /api/v1/pipeline-compendium-only` | Linker, dann LLM-Text | Themenauflösung, dann Kompendium; `linker_output` nennt die verwendeten Artikel |
| `POST /api/v1/pipeline` | Linker, Text, QA (alle per LLM) | wie oben, die Frage-Antwort-Paare entstehen aus dem Kompendium (mit LLM formuliert, sonst aus Fragevorlagen) |
| `POST /api/v1/linker` | LLM-Entitäten plus Wikipedia-API | Artikel der Archive: Titel, Link, Lead als `extract`; `MODE=generate` nimmt die Nachbarartikel dazu |
| `POST /api/v1/qa` | nur mit LLM | mit LLM wie bisher, ohne LLM aus Fragevorlagen über die Sätze des Textes |
| `POST /api/v1/utils/split` | `chunk_size` der Anfrage wurde ignoriert (fest 800 Zeichen) | `chunk_size` gilt; Sätze bleiben ganz, solange sie passen |
| `POST /api/v1/utils/synonyms` | LLM, bei Fehler leere Liste | Titel, Weiterleitungen und Vorschläge der Archive |
| `POST /api/v1/utils/translate` | LLM, bei Fehler `"[en translation of]: <Original>"` | mit LLM die Übersetzung, ohne LLM 503, bei Fehler 502 |
| `GET /health` | status, service, version, timestamp | dieselben Felder plus `components` (Archive, Lehrplan-Cache, LLM, edu-sharing); neu `GET /ready` |

## Fehler statt Fehlertexte

Der alte Dienst gab Fehler des Sprachmodells als HTTP 200 zurück: `markdown` begann dann mit
„# Fehler bei der Generierung“, `translation` mit `[en translation of]:`, `synonyms` war leer. Das gibt es nicht
mehr. Stattdessen:

| Lage | Status |
|---|---|
| Anfrage unvollständig oder außerhalb der Grenzen | 422 |
| leerer Text (nur Leerzeichen) | 400, wie bisher |
| Thema in keinem Archiv gefunden | 404 mit `resolution` (Alternativen, falls vorhanden) |
| edu-sharing nicht erreichbar | 502 |
| kein angefragter Teil erzeugbar (z. B. Teil 3 ohne Repository), Übersetzung ohne LLM | 503 |
| zu viele Anfragen | 429 mit `Retry-After` (`RATE_LIMIT`, wie bisher) |

Es gibt weiterhin keine Anmeldung und kein CORS; beides gehört wie bisher vor den Dienst.

## Optionen, die anders wirken

- `config.language` bzw. `config.compendium.language`: Der Dienst erzeugt nur Deutsch. Ein anderer Wert ist 422
  statt stillschweigend englischer Prompts.
- `config.enable_citations=false` und `config.educational_mode=false`: Belege und das kompendiale Template
  gehören zum Ergebnis. Die Anfrage wird angenommen, und `statistics.notes` sagt, dass die Option nichts ändert.
- `config.length` außerhalb von 2.000 bis 60.000 Zeichen wird auf diesen Bereich geklemmt, ebenfalls mit Notiz.
- `config.linker.MODE`, `MAX_ENTITIES`, `ALLOWED_ENTITY_TYPES`: Die Artikel kommen aus den Archiven. `MODE`
  entscheidet nur, ob die Nachbarartikel mitgenannt werden; die übrigen Werte steuern nichts und werden in
  `statistics.notes` benannt.
- `num_pairs` und die übrigen QA-Felder auf oberster Ebene von `/api/v1/pipeline` werden wie bisher geprüft, aber
  nicht verwendet; es gilt `config.qa`.

## Felder, die anders gefüllt sind

- `linker_output.entities[].id` ist die stabile Artikel-ID statt einer neuen UUID je Anfrage.
- `details.typ` ist `TOPIC` für den Artikel des Themas (und seinen Zwilling in einem zweiten Archiv) und
  `RELATED` für Nachbarartikel; die Typen des alten Sprachmodells (`PERSON`, `LOCATION` …) gibt es nicht mehr.
- `sources.wikipedia.wikidata_id`, `categories`, `thumbnail_url`, `geo_lat`, `geo_lon`, `infobox_type`,
  `dbpedia_uri` bleiben leer: Die Archive führen diese Angaben nicht. `source` ist `zim`.
- `statistics` behält die alten Schlüssel (`topic`, `input_type`, `input_length` bzw. `entities_count`,
  `output_length`, `references_count`, `educational_mode`, `citations_enabled`) und bekommt `notes` und `audit`
  (Template, Matcher, Schalter, Teile, Zeiten, Bausteine, Belege, LLM-Tokens).
- `qa_pairs`, `relationships` und die zugehörigen Zähler bleiben leer, wie schon im alten Dienst.

## Neue Möglichkeiten in der alten Anfrage

`config.compendium` (bzw. `config` bei `/api/v1/compendium`) nimmt zusätzlich:

| Feld | Bedeutung |
|---|---|
| `template_id` | anderes Template (Standard aus der Konfiguration) |
| `collection_id` | edu-sharing-Sammlung; ein `text`, der eine nodeId ist, wird ebenfalls so gelesen |
| `knowledge_collection_id` | Sammlung, deren OER-Materialien Teil 1 als zusätzliche Quellen speisen |
| `subject` | Fach für die Lehrplanbezüge |
| `parts` | Auswahl aus `world`, `curricula`, `collection` |
| `extraction` | `rule-based` (Standard) oder `llm`: das LLM wählt die Sätze, der Wortlaut bleibt der Quelle |
| `generation` | `rule-based` (Standard), `llm-fast` oder `llm`: das LLM formuliert die Bausteine |

## Noch nicht da

- `write_back` gibt es nicht: Der Dienst schreibt nichts in edu-sharing zurück, der Aufrufer speichert (D11).
- Teil-Regeneration (`existing_markdown`, `regenerate_sections`) und ein 504 bei erschöpftem Zeitbudget sind
  vorgesehen, aber noch nicht umgesetzt (PLAN.md 8, Phase 6).
