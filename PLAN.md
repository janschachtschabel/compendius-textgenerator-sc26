# Plan: Kompendium-API v2 (`compendious-text-fastapi`)

Stand: 2026-09-19, Fassung v16 (siehe Änderungsprotokoll) · Status: Phasen 0 bis 5 umgesetzt (Phase 2
teilweise), Phasen 6 und 7 offen (aus Phase 7 vorgezogen: CI mit Image-Build, Prometheus-Überwachung); Code in `github.com/janschachtschabel/compendius-textgenerator-sc26`.
Abschnitte, die noch nicht Umgesetztes beschreiben, sind als „geplant“ markiert · Grundlage: Code-Analyse von
`alterCode/compendious` (alter Dienst), `../kompendium-test` (ZIM-/Matching-Prototyp),
`../mem-schule-optik` und `../mem-schule-abruf` (gezielter Abruf von Lehrplanelementen zu einem
Thema per MEM-SPARQL), `../lehrplan-ontologien` (nur die Notizen zum MEM-Import: RDF-Struktur,
gemessene Lehrplanzahlen, Landesklassen) sowie der WLO-Skills zu b-api und edu-sharing-REST.

---

## 0. Kurzfassung

**Empfehlung: sauberer Neubau in diesem Repo, aber nicht auf der grünen Wiese.**
Der fachliche Kern wird der in `kompendium-test` erprobte Offline-Pfad
(Kiwix-ZIM → Segmentierung → Slot-Matching → extraktive Synthese mit Zitationen).
Der alte Dienst bleibt ausschließlich als **Schnittstellen-Vertrag** erhalten
(Pfade, Request- und Response-Schemata), sein Innenleben (LLM-Linker → Wikipedia-Live-API →
ein großer LLM-Prompt) wird vollständig ersetzt.

Warum Neubau statt Überarbeitung:

1. Die alte Architektur ist um das LLM herum gebaut (Entities → Prompt → Freitext). Die
   Zielstruktur (drei Teile, 13 Bausteine, Facetten, Belegpflicht) hat mit diesem Datenmodell
   nichts gemeinsam.
2. Die Wikipedia-Live-API ist Single Point of Failure (Notschalter `WIKIPEDIA_ENABLED`, Commit
   `6b302ba "disable wikipedia requests via env (GEN-314)"`).
3. Das README erklärt die Codebasis selbst zum KI-generierten Proof of Concept.
4. Der Prototyp liefert bereits 7 s Laufzeit, 0 € LLM-Kosten und 100 % Belegquote — er muss
   gehärtet, entkoppelt und um Teil 2 und Teil 3 ergänzt werden, nicht neu erfunden.

| Kriterium | Alt (`alterCode`) | Neu (v2, Regelmodus) |
|---|---|---|
| Laufzeit je Kompendium | 45–90 s (README) | ca. 5–10 s (Prototyp: 7 s mit ZIM) |
| LLM-Aufrufe je Kompendium | 2–15 (Linker, Synonym-Fallbacks, Text, ggf. QA) | 0 im Standard; optional (D33) `extraction=llm` einer je Baustein, `generation` 2–3 (`llm-fast`) bis 10 (`llm`); beide auf `llm` bei Optik 20 |
| Externe Live-Abhängigkeit zur Inferenzzeit | Wikipedia-API, b-api | keine; edu-sharing (eigene Infrastruktur) und b-api nur optional |
| Quellenbindung | 10 Wikipedia-Extracts im Prompt, kein Nachweis je Aussage | jede Aussage mit Zitationsnummer, Quelle, Revisionsstand, Lizenz |
| Struktur | vom LLM frei gewählt | Template-gesteuert (SC26, 13 Bausteine, editierbar) |
| Teile | nur Weltwissen | Weltwissen + Lehrplanbezüge + Sammlungsüberblick |

Startkonfiguration: deutsche Wikipedia (`nopic`, ca. 14 GB) und Klexikon (ca. 130 MB); weitere
Kiwix-Archive sind über das Abo-Manifest zuschaltbar. Eingabe ist ein Thema oder die nodeId einer
Sammlung, deren Metadaten dann das Thema liefern. Lehrpläne werden wöchentlich, ZIM-Dumps monatlich
geprüft; zur Inferenzzeit wird nichts von Dritten abgerufen.

---

## 1. Ausgangslage und Befunde

### 1.1 Alter Dienst (`alterCode/compendious`)

Endpunkte: `GET /health`, `POST /api/v1/linker`, `POST /api/v1/compendium`, `POST /api/v1/qa`,
`POST /api/v1/pipeline`, `POST /api/v1/pipeline-compendium-only`,
`POST /api/v1/utils/{split,synonyms,translate}`, Swagger unter `/docs`.

Pipeline: Linker (LLM `generate`/`extract` → Wikipedia-Batch-API → Fallbacks: Namensvarianten,
LLM-Synonyme) → Compendium (ein LLM-Aufruf, System-Prompt 665–805 Tokens, `max_tokens=4000`,
`temperature=0.7`) → optional QA (LLM).

Befunde im Code:

- Fehler werden als Markdown `# Fehler bei der Generierung …` mit HTTP 200 zurückgegeben
  (`core/compendium.py`, `generate_compendium_via_llm`). Konsumenten können Fehler nicht erkennen.
- Themenheuristik `extract_topic_from_text` nimmt den ersten Satz bis zum Punkt (bricht bei
  „10. Klasse", eigener ToDo-Kommentar im Code).
- Synchroner OpenAI-Client in `async`-Endpunkten blockiert den Event-Loop.
- Rate-Limiter drosselt eingehende Requests pro IP, nicht die Upstreams (ToDo im Code).
- Logging auf DEBUG in Datei innerhalb des Containers.
- Tests decken nur gemockte LLM-Pfade ab; die Kernlogik (Prompting) ist nicht testbar.
- Kostentreiber laut `scripts/cost_report_compendium.py`: Output-Deckel 4.000 Tokens je Aufruf.

Erhaltenswert: Endpunkt-Vertrag und Pydantic-Modelle, uv-/Dockerfile-/GitLab-CI-Gerüst,
b-api-Anbindung per `X-API-KEY`, Hilfsfunktion `split_text`.

### 1.2 Prototyp `kompendium-test`

Funktioniert: ZIM-Adapter (libzim), Multi-ZIM (Wikipedia + Klexikon + Wikibooks + Wikiversity),
Segmentierung nach Überschriften, SQLite-FTS5-Wissensbasis, acht Matching-Strategien mit Registry
und Comparator, Template-Manager (`standard`, `sc26`, `mindmap16`, Custom-CRUD, LLM-Kurztexte),
extraktive Synthese mit Zitationen, Claim-Verifier, Markdown/HTML/JSON, ZIM-Manager
(OPDS-Katalog, Download mit Fortschritt, aktive Archive). Messwerte aus
`scratch/after_optimization_report.json`: 6,9–7,4 s mit ZIM gegenüber 12,6–28,9 s Live-API,
15–16 von 16 Slots belegt.

Was noch nicht trägt:

1. **Overfitting auf das Testthema Optik.** Harte Signalwörter in fünf Matchern, im Planner und
   in der Segmentierung („optotechniker", „feinoptiker", „ernst abbe", „kepler", „visby",
   „sehhilfen", „wellenoptik", „brechungsgesetz" …). Bei jedem anderen Thema greifen diese
   Regeln ins Leere oder verzerren die Zuordnung.
2. **Regel-Duplikation.** Dieselben Slot-Guardrails (Akteure, Beruf, Regularien) sind fünfmal
   kopiert. Sie gehören in einen einzigen, template-gesteuerten Policy-Layer.
3. **Matching-Qualität nicht belegt.** Eigener Befund (`user_msg_optik.txt`): Zuordnungen passen
   auch mit Cross-Encoder nicht zuverlässig zu den Überschriften. Es gibt keinen Goldstandard,
   nur Slot-Abdeckung und Jaccard zwischen Matchern.
4. **Dünne Abschnitte.** Fest `top_k=3` Chunks je Slot; Korpus nur Hauptartikel plus zwei bis drei
   verlinkte Artikel. Die Xapian-Volltextsuche des ZIM bleibt ungenutzt, obwohl sie in 49 ms
   passende Artikel liefert (Test am 14-GB-Dump: „Optik Brechung Linse" → „Linse (Optik)",
   „Brechung (Physik)", „Brennweite", „Matrizenoptik").
5. **Facetten** sind Heuristiken im Synthesizer, nicht deklariert und nicht prüfbar.
6. **Betriebsfähigkeit.** Globale Singletons beim Import (`ZimManager("data")`,
   `TemplateManager("data")`), `print()` statt Logging, keine Authentifizierung für Download
   und Löschen, `templates.json` wird bei jedem Start überschrieben, Hugging-Face-Modelle werden
   zur Laufzeit aus dem Netz geladen.
7. **Schwergewicht ohne Nachweis.** torch (507 MB) plus Modelle (rund 1,3 GB) für
   `extractive_qa` und `cross_encoder`, ohne Beleg, dass sie BM25 + Char-TF-IDF + Model2Vec
   schlagen.
8. **Generierte Bausteine** sind schwach: Glossar per Regex auf „ist ein/bezeichnet", kein
   Akteursverzeichnis.
9. **Satzsplitting** zerreißt Ordnungszahlen („Visby-Linsen aus dem 11. Einige dieser Linsen …",
   sichtbar in `output/optik_kompendium.md`).

### 1.3 Rahmenbedingungen (geprüft am 2026-09-17)

| Bereich | Befund |
|---|---|
| ZIM-Dumps lokal | `wikipedia_de_all_nopic_2026-01` 14 GB, 5,04 Mio. Artikel; `klexikon_de_all_maxi_2026-08` 129 MB, 5.664 Artikel; `wikibooks_de_all_nopic_2026-01` 2,7 GB; `wikiversity_de_all_nopic_2026-07` 1,2 GB. Alle mit Volltext- und Titelindex (`_ftindex:yes`). |
| libzim | Volltextsuche 49 ms, Titel-Suggestion 269 ms (kalt), Python 3.13 läuft. |
| b-api | Header `X-API-KEY`, Provider `academiccloud` und `openai`, Limits instabil (21.08.: ~6 req/s, 26 parallel; 12.08.: 2 parallel). Reasoning-Modelle brauchen `enable_thinking:false` bzw. `max_completion_tokens`. Modell-IDs ändern sich ohne Ankündigung. |
| MEM-Triplestore | `https://sparql.mem.edufeed.org/sparql/`, Virtuoso ohne Reasoning. 2.514 Lehrpläne: BY 1707, SN 532, RP 229, BB 46, BE im BB-Graphen (gemessen 2026-09-02). Client mit geprüften IRIs und 49 Offline-Tests liegt in `mem-schule-optik`. Fallen dokumentiert: keine `*`/`+`-Pfade (Speicherfehler), `BFO_0000051` transitiv über-asserted, Labels ohne Sprachtag. |
| edu-sharing | Kompendium-Property `ccm:oeh_collection_compendium_text` (Liste mit einem Markdown-Eintrag), Schreiben nur per `POST …/property?property=…` (PUT /metadata verwirft still). Sammlung: `GET /collection/v1/collections/-home-/{id}` (+ `childReferencesCount`), `…/children/references`, `…/children/collections`. Volltext: `GET /node/v1/nodes/-home-/{id}/textContent`, Median 4,6 s, max 9,2 s. Öffentliche Sammlungen anonym lesbar. |
| Zielstruktur bestätigt | Das WLO-MCP-Tool `get_compendium_text` beschreibt den Text bereits als „(1) Weltwissen in Facetten, (2) Kompetenzen und Lehrplanbezüge nach Bildungsstufe und Bundesland, (3) kurze Vorstellung der Sammlungsinhalte". |
| MEM-Import-Wissen | `lehrplan-ontologien/docs/mem-schule-rdf-struktur.md` und `docs/plans/2026-09-02-mem-import-und-export-konsistenz.md`: sieben CE-Basistypen mit Klassen- und Funktions-IRIs, Baumabruf mit Rekonstruktion der echten Eltern, Zuordnung Endpunkt-Klasse → CE-Typ (13 von 20 tatsächlich genutzten Landesklassen fehlten in der generierten Tabelle, z. B. `Kompetenzerwartung (BY)` 54.307, `Lernziel und Lerninhalt (SN)` 106.334, `Kompetenz (RP)` 20.694 Knoten). Nur dieser Import-Teil ist für v2 relevant. |
| Deployment | GitLab `scm.edu-sharing.com`, Image `…/projects/wlo/compendious-text-fastapi:<branch|tag>`, uv + Python 3.13, Ruff, mypy strict, pytest. |

---

## 2. Ziele und Nicht-Ziele

Ziele (prüfbar):

- **Z1 Drop-in.** Alle bisherigen Pfade antworten mit kompatiblem Schema. Nachweis: Contract-Tests
  gegen die alten Pydantic-Modelle.
- **Z2 Ohne KI vollständig.** Ein Kompendium mit allen drei Teilen entsteht im Regelmodus mit
  0 LLM-Tokens; Laufzeit p95 ≤ 15 s bei warmem Betriebssystem-Cache.
- **Z3 Keine Live-Abhängigkeit von Dritten zur Inferenzzeit.** Wikipedia, Kiwix-Katalog und MEM
  werden nur in Hintergrundjobs angesprochen. edu-sharing (eigene Infrastruktur) und b-api
  (optional) sind zur Inferenzzeit erlaubt.
- **Z4 Editierbare Kategorien.** Bausteine, Facetten, Ein-/Ausschlüsse und Überschriften-Muster
  liegen als versionierte Templates vor; einzelne Abschnitte lassen sich nachträglich neu erzeugen,
  redaktionell geprüfte bleiben erhalten.
- **Z5 Belegpflicht.** Jede Aussage in Teil 1 trägt Zitationsnummer, Quelle, Revisionsstand und
  Lizenz; das Dokument trägt Governance-Frontmatter.
- **Z6 Betrieb.** ZIM-Abonnement per Manifest, automatische Aktualisierung mit atomarem Wechsel,
  Volume-Sizing, Health- und Readiness-Endpunkte.
- **Z7 Messbare Qualität.** Goldstandard und Metriken existieren, bevor der Standard-Matcher
  festgelegt wird.

Nicht-Ziele (dieser Ausbaustufe): Web-Dashboard des Prototyps (nur Swagger; Redaktions-UI
gehört in die edu-sharing-Oberfläche), englische Kompendien (technisch über `wikipedia_en`-ZIM
später möglich), Bilder, QA-Generierung ohne LLM.

---

## 3. Zielarchitektur

### 3.1 Übersicht

```
Client (edu-sharing KI-Workflow, Redaktion, Skripte)
  │  POST /api/v1/pipeline-compendium-only  (Legacy-Vertrag)
  │  POST /api/v2/compendium                 (strukturierter Vertrag)
  ▼
FastAPI ── Legacy-Adapter v1 ──► Orchestrator (3 Teile, Ergebnis-Cache)
  │
  ├─ Teil 1 Weltwissen   ZimRegistry ─► Korpus ─► Segmentierung ─► KnowledgeStore (SQLite FTS5)
  │                       ─► Slot-Matching (Lexikon → Ranking → Policy) ─► Synthese (extraktiv | LLM)
  │                       ─► Facetten + Lint ─► Sections
  ├─ Teil 2 Lehrpläne    LehrplanCache (SQLite, aus MEM-Harvest) ─► Themen-Match ─► Rendering
  ├─ Teil 3 Sammlung     edu-sharing REST (Sammlung, Referenzen, Untersammlungen) ─► Überblick
  │                       optional: Wissens-Sammlung ─► zusätzliche Quellen für Teil 1
  ▼
Assembler ─► Markdown (Frontmatter + Teil 1–3 + Quellen + Glossar) + JSON (outline, sources, audit)

Jobs (Sidecar oder CronJob, gleiches Image):
  compendium zim sync          monatlich: Kiwix-OPDS prüfen, laden, verifizieren, atomar aktivieren
  compendium lehrplan check    wöchentlich: Zählabfrage je Land und Fach gegen MEM, Vergleich mit Cache
  compendium lehrplan harvest  Vollabzug MEM-SPARQL in den LehrplanCache (bei Änderung, sonst monatlich)
  compendium cache prune       Ergebnis- und Volltext-Cache aufräumen

Volumes: /data/zim (Archive, active.json)   /data/state (SQLite: lehrplan.db, cache.db, templates/)
```

### 3.2 Paketstruktur

```
compendious-text-fastapi/
├── pyproject.toml            uv; Extras: [ml] (torch, sentence-transformers), [dev]
├── Dockerfile                Multi-Stage; Build-Arg PROFILE=base|ml; Modelle im Image
├── compose.yml               api + zim-updater (Sidecar) + Volumes
├── config/
│   ├── zim_subscriptions.yaml   Abo-Manifest (Profile compact|full)
│   ├── facets.yaml              Facetten-Deklaration (11 Facetten, Zulässigkeit, Kardinalität)
│   ├── heading_lexicon.yaml     Wikipedia-Überschriften → Bausteine
│   └── subjects.yaml            WLO-Fach-Vokabular → MEM-Schulfach-Labels
├── app/
│   ├── main.py, settings.py, logging.py, deps.py
│   ├── api/v1/                Legacy-Router (Schemata unverändert) → Adapter auf Orchestrator
│   ├── api/v2/                compendium, templates, zim, lehrplan, matching, collections, admin
│   ├── domain/                Source, Chunk, Slot, Section, Facet, Compendium (Pydantic)
│   ├── sources/
│   │   ├── zim/               archive (libzim), html (HTML→Abschnitte), registry (Auflösung, Korpus), subscriptions, catalog, downloader, active, refresh
│   │   ├── wlo/               edu-sharing-Client (Sammlung, Referenzen, textContent), Lizenz-Policy
│   │   └── lehrplan/          vocab, sparql, queries, tree, store (SQLite+FTS5), harvest, stufen, matcher, render, subjects, part
│   ├── knowledge/             store (FTS5), segmentation, related (Linkranking), aliases
│   ├── matching/              lexicon, lexical (BM25, Char-TF-IDF), embeddings (Model2Vec), rerank (optional), policy, registry, eval
│   ├── templates/             manager, schema, builtin/{standard,sc26}.json, validation
│   ├── synthesis/             writer (Bausteine schreiben), extractive, extraction und selection (LLM-Satzauswahl, D33), llm (Evidenzblock, LLM-Baustein), citations (Belegprüfung), actors, glossary, sources_section, facets, lint
│   ├── compose/               assembler, frontmatter, markdown, partial_regeneration
│   ├── llm/                   client (b-api), prompts (IDs, Versionen), budget, budget_store (Tageszähler in STATE_DIR), deadline (Anfragefrist), gateway (Verfügbarkeit, Modi), report (Audit, Frontmatter)
│   ├── jobs/                  runner (--loop, Trigger-Datei), zim_sync; später lehrplan_harvest, cache_prune
│   └── cli.py, cli_zim.py, cli_eval.py, cli_lehrplan.py   argparse: generate, templates, zim …, eval …, lehrplan status|check|harvest|search
├── tests/                     unit, integration (Sample-ZIM offline), contract (v1), golden
├── eval/                      gold/*.jsonl, run_eval.py, reports/
└── docs/                      PLAN.md (dieses Dokument), MIGRATION.md, ADRs, RUNBOOK.md
```

### 3.3 Übernahme aus dem Prototyp

| Quelle (`kompendium-test`) | Ziel | Änderung |
|---|---|---|
| `zim_manager.py` (Katalog, Download, aktive Dateien) | `sources/zim/catalog.py`, `downloader.py`, `registry.py` | Manifest statt Kuratierungsliste im Code, Resume und Hash-Prüfung, `active.json` atomar, kein Singleton |
| `adapters/zim.py` (HTML-Parser, Linkranking) | `sources/zim/reader.py`, `knowledge/related.py` | Tabellen als Chunk-Typ, Boilerplate-Filter konfigurierbar, Volltextsuche ergänzt |
| `segmentation.py` | `knowledge/segmentation.py` | Optik-Keywords raus, Kategorie über Überschriften-Lexikon, Abkürzungsliste im Satzsplitter |
| `storage.py` | `knowledge/store.py` | unverändert im Kern, plus Metadaten-Spalten |
| `matching/{bm25,char_tfidf,model2vec}` | `matching/lexical.py`, `embeddings.py` | Guardrails entfernt, nur noch Scoring |
| `matching/hybrid_pipeline.py` | `matching/registry.py` + `policy.py` | RRF bleibt; Policy einmalig; Cross-Encoder und QA-Filter optional (Extra `ml`) |
| `matching/extractive_qa_matcher.py`, `cross_encoder_matcher.py`, `e5_onnx_matcher.py` | `matching/rerank.py` (optional) | nur wenn Evaluation Mehrwert zeigt |
| `matching/llm_matcher.py` | `synthesis/selection.py`, `synthesis/extraction.py` | über b-api-Client und Budget: das LLM wählt je Baustein Sätze unter den Kandidaten der Policy (`extraction=llm`, D33); der zuerst gebaute Router für Zweifelsfälle ist entfallen |
| `matching/comparator.py` | `matching/eval.py` | plus Goldstandard-Metriken |
| `template_manager.py` | `templates/` | JSON-Schema, Versionierung, Facetten, Budgets, Heading-Patterns |
| `synthesizer.py` | `synthesis/` | Facetten deklarativ, Akteure und Glossar neu |
| `verifier.py`, `formatter.py` | `synthesis/lint.py`, `compose/` | Lint-Regeln, Frontmatter, drei Teile |
| `llm_client.py` | `llm/client.py` | b-api-Eigenheiten (siehe Abschnitt 7) |
| `server.py` (Endpunkte ZIM, Templates, Matching) | `api/v2/*` | Admin-Token, Pydantic-Modelle |

### 3.4 Kern-Datenmodell

- **Source**: `source_id`, `project` (wikipedia, klexikon, wikibooks, wikiversity, wlo_material),
  `title`, `url` (Permalink-Rekonstruktion), `zim_file`, `zim_uuid`, `zim_date`, `entry_path`,
  `license`, `language`, `content`, `authority_score`, `role` (leitquelle, einfache_sprache,
  lehrbuch, hochschule, material).
- **Chunk**: `chunk_id`, `source_id`, `heading_path` (Liste), `heading_level`, `is_lead`,
  `is_section_lead`, `kind` (paragraph, table, list), `text`, `lexicon_slot` (aus Überschrift),
  `facets` (Dict).
- **Slot** (aus Template): `id`, `slot`, `title`, `description`, `inclusions`, `exclusions`,
  `sub_items`, `search_queries`, `heading_patterns`, `facets` {allowed, required, defaults},
  `budget` {min_chunks, max_chunks, target_chars, weight}, `generated`, `source_preference`.
- **Section**: `slot_id`, `chunks`, `text`, `citations`, `facets`, `governance` {status,
  generated_at, model, prompt_id, hash}.
- **Compendium**: `topic` (aufgelöst), `resolution` (Alternativen), `frontmatter`, `parts`
  (world, curricula, collection), `sources`, `audit` (matching, lint, timings, tokens).

### 3.5 Konfiguration (Auszug)

| Variable | Standard | Bedeutung |
|---|---|---|
| `ZIM_DIR` | `/data/zim` | Archive und `active.json` |
| `ZIM_PROFILE` | `standard` | `compact`, `standard` oder `extended` (siehe 4.1) |
| `ZIM_REQUIRED` | leer (aus Manifest und `ZIM_PROFILE` abgeleitet) | Readiness-Bedingung, übersteuert das Manifest |
| `ZIM_BOOTSTRAP_DOWNLOAD` | `false` | Updater lädt fehlende Pflicht-Archive beim ersten Start |
| `ZIM_SYNC_INTERVAL` | `30d` | Katalogprüfung und Update der abonnierten Archive (monatlich) |
| `ZIM_CATALOG_URL` | leer (= `https://opds.library.kiwix.org/catalog/v2/entries`) | Kiwix-OPDS-Katalog |
| `ZIM_DOWNLOAD_HOSTS` | `download.kiwix.org,lb.download.kiwix.org,mirror.download.kiwix.org` | Allowlist für Download-Start-URLs |
| `ZIM_RETENTION_HOURS` | `24` | Karenz vor dem Löschen abgelöster Archive |
| `STATE_DIR` | `/data/state` | SQLite-Datenbanken, Templates |
| `TEMPLATE_DEFAULT` | `sc26` | Standard-Template |
| `FACETS_LEVEL` | `minimal` | `minimal` (Zeitbezug, Bildungsstufe, Evidenzgrad) oder `full` (alle elf), siehe 4.6 |
| `FACETS_VISIBLE` | `false` | sichtbare Kurzform `[Facette: Wert]` zusätzlich zu den Markern |
| `MATCHER_DEFAULT` | `hybrid_light` | festgelegt nach Evaluation (4.5): Lexikon + BM25 + Char-TF-IDF + Model2Vec + Policy |
| `MODEL2VEC_PATH` | `/models/m2v` im Image, sonst leer | statisches Embedding-Modell für `hybrid_light` (D20) |
| `POLICY_CONFIDENT_SCORE` | `0.65` | Trefferstärke, ab der ein Ranker-Treffer zählt; darunter Standardbaustein (bis 2026-09-18: 0,45, siehe D28) |
| `POLICY_SECTION_SMOOTHING` | `0.5` | Anteil des Abschnittsmittels an jedem Score; 0 schaltet die Glättung ab (D28) |
| `LLM_ENABLED` | `false` | b-api-Nutzung insgesamt |
| `B_API_KEY` | – | Schlüssel, Header `X-API-KEY` |
| `B_API_BASE_URL` | `https://b-api.staging.openeduhub.net` | nur der Host; der Pfad `/api/v1/llm/{provider}/…` wird aus dem Provider gebildet |
| `B_API_PROVIDER` | `openai` | `openai` oder `academiccloud`, zur Laufzeit umschaltbar (Entscheidung D19) |
| `B_API_MODEL` | `gpt-5.6-luna` | Modell-ID beim gewählten Provider; wird beim Start gegen `/models` geprüft |
| `LLM_EXTRACTION_DEFAULT` | `rule-based` | `rule-based` oder `llm` (siehe 4.7, D33) |
| `LLM_GENERATION_DEFAULT` | `rule-based` | `rule-based`, `llm-fast` oder `llm` (siehe 4.7, D33) |
| `LLM_EXTRACTION_CANDIDATES` | `8` | Absätze je Baustein, die `extraction=llm` anbietet: die der Policy, dann die nächstbesten nach ihrem Score |
| `LLM_FAST_SECTIONS` | `sc26_1,sc26_11` | Abschnitte, die `generation=llm-fast` per LLM formuliert |
| `LLM_MAX_TOKENS_PER_REQUEST`, `LLM_DAILY_TOKEN_BUDGET` | 40000 / 2 Mio. | Kostenschutz je Kompendium und je Tag; der Tageszähler liegt in `STATE_DIR/llm_budget.db`, gilt für alle Worker und übersteht Neustarts |
| `LLM_UNSUPPORTED_SENTENCES` | `drop` | Sätze ohne gültigen, deckenden Beleg verwerfen oder mit `mark` als Schlussfolgerung kennzeichnen (4.7) |
| `LLM_REASONING_EFFORT`, `LLM_VERBOSITY` | `low` / `low` | GPT-5- und o-Serie (D25); klassische Modelle nutzen `LLM_TEMPERATURE` (`0.2`) |
| `LLM_TIMEOUT_S`, `LLM_MAX_CONCURRENCY`, `LLM_ATTEMPTS` | `120` / `4` / `3` | Timeout, parallele Aufrufe (Semaphore), Versuche bei 429/502/503/504 und Verbindungsfehlern |
| `EDU_SHARING_BASE_URL` | `https://redaktion.openeduhub.net/edu-sharing/rest` | Repository für Teil 3 und Wissens-Sammlung; leer = aus |
| `EDU_SHARING_USER`, `EDU_SHARING_PASSWORD` | – | optional Basic-Auth; ohne Zugangsdaten anonym (öffentliche Sammlungen) |
| `EDU_SHARING_TIMEOUT_S` | `30` | Timeout je Repository-Anfrage |
| `COLLECTION_CACHE_TTL_S` | `3600` | Cache für Sammlungsmetadaten und Listen (`STATE_DIR/wlo_cache.db`) |
| `COLLECTION_MAX_ITEMS` | `0` (= alle) | optionale Kappung der Inhaltslisten in Teil 3 (D23) |
| `MATERIAL_TEXT_CACHE_TTL_S` | `604800` | Cache der extrahierten Materialtexte (7 Tage) |
| `KNOWLEDGE_MAX_MATERIALS`, `KNOWLEDGE_MAX_CHARS`, `KNOWLEDGE_CONCURRENCY` | `30` / `20000` / `4` | Budget der Wissens-Sammlung |
| `LEHRPLAN_ENDPOINT` | `https://sparql.mem.edufeed.org/sparql/` | MEM-SPARQL-Endpunkt, nur vom Harvest genutzt |
| `LEHRPLAN_CHECK_INTERVAL` | `7d` | wöchentliche Zählprüfung gegen MEM (`compendium lehrplan harvest --loop`) |
| `LEHRPLAN_HARVEST_MAX_AGE` | `30d` | Vollabzug bei geänderter Zählung oder spätestens nach diesem Alter |
| `LEHRPLAN_REQUEST_PAUSE_S` | `0.5` | Pause zwischen SPARQL-Anfragen im Harvest |
| `LEHRPLAN_MAX_GROUPS_PER_LAND` | `0` (= alle) | optionale Kappung von Teil 2 je Bundesland und Bildungsstufe; Standard ohne Kappung (D23) |
| ~~`LEHRPLAN_LIVE_FALLBACK`~~ | – | gestrichen (D22): ohne Cache Hinweistext, nie SPARQL zur Inferenzzeit |
| `RESULT_CACHE_TTL_H` | `168` | geplant, nicht umgesetzt: Ergebnis-Cache (8.3) |
| `ADMIN_TOKEN` | – | Admin-Endpunkte (ZIM, Harvest-Anstoß, Matching-Vergleich; Templates schreiben ist geplant) |
| `RATE_LIMIT` | `60` | Anfragen je Minute und Client auf den erzeugenden Endpunkten, je Worker; 0 = aus (D30) |
| `API_DOCS_ENABLED` | `true` | `/docs`, `/redoc`, `/openapi.json` ausliefern |
| `METRICS_ENABLED`, `METRICS_TOKEN` | `true` / – | Prometheus-Endpunkt `/metrics`, optional nur mit Bearer-Token (D31) |
| `REQUEST_TIMEOUT_S` | `120` | Frist je Anfrage für die LLM-Arbeit (jeder Aufruf bekommt höchstens die Restzeit, unter 5 s Rest entsteht der Baustein extraktiv) und das Lesen der Materialtexte und der Listen von Teil 3 (dann `summary.incomplete` mit Hinweis); keine harte Gesamtfrist (geplant: 504, 8.1) |

---

## 4. Teil 1 — Weltwissen aus Kiwix-ZIM

### 4.1 ZIM-Verwaltung: Abonnieren, Laden, Aktualisieren

**Manifest** `config/zim_subscriptions.yaml`: je Eintrag `id` (= Katalogname plus Flavour, z. B.
`wikipedia_de_all_nopic`, identisch mit dem Dateinamen ohne Datum), `name`, `flavour`, `project`,
`required`, `profiles` (compact, standard, extended). Der Katalog wird nicht mehr im Code kuratiert
(`sources/zim/subscriptions.py`).

| Profil | Archive | Größe (Stand der geprüften Dumps) | Einsatz |
|---|---|---|---|
| `compact` | `wikipedia_de_top_nopic` (Top-Artikel, Volltext) + `klexikon_de_all_maxi` | ca. 1,1 GB + 0,13 GB | Entwicklung, CI, kleine Hosts |
| `standard` | `wikipedia_de_all_nopic` + `klexikon_de_all_maxi` | 14 GB + 0,13 GB ≈ 14,1 GB | **Produktion zum Start** (Entscheidung D9) |
| `extended` | `standard` + `wikibooks_de_all_nopic` + `wikiversity_de_all_nopic` + beliebige weitere Manifest-Einträge | + 2,7 GB + 1,2 GB ≈ 18,1 GB | optional, per Abo-Manifest zuschaltbar |

**Ablauf `zim sync`** (Updater-Sidecar mit demselben Image, `compendium zim sync --loop`, Intervall
**monatlich** (`ZIM_SYNC_INTERVAL=30d`, Entscheidung D16), Poll alle 60 s auf die Trigger-Datei
`sync.request`; umgesetzt in `jobs/zim_sync.py` und `jobs/runner.py`):

1. Lokale Dateien übernehmen (`adopt`): eine `*.zim`, deren Name ohne Datum einer Abo-ID entspricht
   und die nicht in `active.json` steht, wird registriert (neuester Dump gewinnt). Damit funktioniert
   auch der Weg „Dateien einmalig auf das Volume kopieren“.
2. Kiwix-OPDS-Katalog abfragen (`opds.library.kiwix.org/catalog/v2/entries?lang=deu&name=<name>`;
   `library.kiwix.org` leitet dorthin um). Der Filter `name` ist exakt (`klexikon_de_all`), der Filter
   `flavour` wird vom Server ignoriert und clientseitig angewendet; der Dump-Monat steht im Dateinamen
   (`_2026-08.zim`). Das Attribut `length` im Katalog ist nur gerundet.
3. Ist der Katalog-Dump neuer als der aktive (Vergleich `YYYY-MM` aus dem Dateinamen) oder fehlt ein
   Pflichtarchiv bei `ZIM_BOOTSTRAP_DOWNLOAD=true`: Metalink (`.meta4`) lesen, dort stehen exakte
   Größe, SHA-256 und Spiegel. Download von `lb.download.kiwix.org` (301/302 auf einen Spiegel, HTTP
   206 für Range) in eine `.part`-Datei mit Range-Resume; die SHA-256 wird beim Streamen gebildet,
   bei Abweichung wird die Datei verworfen. Geprüft am 2026-09-17 mit Abbruch bei 25 MB und
   Fortsetzung („resuming at 25165824 of 135008418 bytes“).
4. Archiv mit libzim öffnen und Metadaten lesen (UUID, Datum, Projekt, Größe).
5. `active.json` atomar per `rename` ersetzen; die abgelöste Datei wandert nach `retired` und wird
   nach `ZIM_RETENTION_HOURS` (24 h) gelöscht. Jede erfolgreiche Aktivierung wird sofort geschrieben,
   ein Abbruch hinterlässt einen gültigen Stand.
6. API-Prozesse prüfen `active.json` bei jeder Anfrage per `stat` (mtime, Größe) und öffnen neue
   Archive lazy (`sources/zim/refresh.py`, Middleware in `main.py`). Kein Download zur Inferenzzeit.
   `GET /ready` ist erst grün, wenn alle Pflichtarchive vorhanden sind; sie ergeben sich aus dem
   Manifest für `ZIM_PROFILE` (`ZIM_REQUIRED` übersteuert). Der Stand des Jobs steht in
   `sync_status.json` (`GET /api/v2/zim/status`, `GET /api/v2/zim/progress`).

**Plattenbedarf** = Summe der Archive + größtes Archiv als Update-Puffer: Profil `standard`
≈ 14,1 GB + 14 GB Puffer ≈ 28 GB; geplant wird mit **40 GB Volume** (Entscheidung D18), damit
Wachstum der Dumps und ein bis zwei zusätzliche Abo-Archive ohne Umzug Platz haben; `compact`
≈ 3 GB.

**Leseschicht** `ZimRegistry`: hält je aktivem Archiv ein `libzim.Archive` (lesend thread-safe
laut libzim; im Spike bestätigen), erzeugt `Searcher`/`SuggestionSearcher` je Anfrage, liefert
Metadaten für Frontmatter und Quellenangabe. Revisionsstand einer Quelle = ZIM-Datum + UUID +
Eintragspfad; Permalink rekonstruiert (`https://de.wikipedia.org/wiki/<Pfad>`) mit Hinweis
„Stand des Dumps".

Admin-Endpunkte (`X-Admin-Token` = `ADMIN_TOKEN`, ohne Token deaktiviert): `GET /api/v2/zim/catalog`,
`GET /api/v2/zim/progress`, `POST /api/v2/zim/sync` (legt die Trigger-Datei für den Updater ab, die
API lädt nie selbst, damit es nur einen Schreiber für das Archivverzeichnis gibt),
`DELETE /api/v2/zim/{datei}` (nur nicht aktive Dateien samt `.part`). Downloads starten nur von
Kiwix-Hosts (Allowlist `ZIM_DOWNLOAD_HOSTS`; die Weiterleitung auf Spiegel ist durch die Prüfsumme
abgesichert), Dateinamen ohne Pfadanteile (`validate_file_name`).

### 4.2 Themenauflösung und Korpusaufbau

Eingabe ist ein Thema (`topic` bzw. `text`) oder eine Sammlung (`collection_id`), auch beides
(Entscheidung D12).

0. **Normalisierung.** Kompendien sind bildungsbereichsübergreifend und bilden Weltwissen ab.
   Stufen-, Klassen- und Fachzusätze werden deshalb vor der Auflösung abgetrennt und nur als
   Kontext behalten: „Optik in Klasse 7" → Thema „Optik", Kontext `Klassenstufe 7`; „Physik:
   Optik (Sek I)" → „Optik", Kontext `Fach Physik`, `Sek I`. Muster: „in Klasse n", „Klasse n",
   „Jahrgang n", „Sek I/II", „Grundschule", „Primarstufe", „für die …", vorangestelltes Fach mit
   Doppelpunkt. Bei einer Sammlung liefert `cclom:title` das Thema (gleiche Normalisierung),
   `ccm:taxonid` das Fach (Auflösung über `config/subjects.yaml`, z. B. `discipline/460` → Physik),
   `ccm:educationalcontext`, Beschreibung und Schlagwörter den Kontext für die Disambiguierung.
   Kontext ist nie ein Filter auf den Inhalt.
1. Exakter Titel (`get_entry_by_title`), Redirect folgen.
2. Sonst Titel-Suggestion (Titelindex). Begriffsklärungsseiten erkennen (Titel „(Begriffsklärung)"
   oder BKL-Hinweis im Lead). Bei Mehrdeutigkeit mit `subject` (Fach aus Anfrage oder Sammlung)
   disambiguieren, sonst erster Nicht-BKL-Treffer. Alternativen werden im Ergebnis gemeldet
   (`resolution.alternatives`), damit die Redaktion korrigieren kann.
3. Aliase offline aus dem Lead-Absatz („auch Lehre vom Licht genannt", Klammerzusätze,
   Fettdruck-Synonyme) plus Suggestion-Treffer mit gleichem Ziel. Aliase fließen in Teil 2
   (Lehrplan-Stichwörter) und ins Glossar.
4. Korpus, budgetiert (max. 12 Artikel, max. 400 Chunks):
   - Hauptartikel aus jedem aktiven Archiv (Wikipedia, Klexikon, Wikibooks, Wikiversity).
   - Verlinkte Unterartikel per Linkranking (bestehende Blacklist für Sprachen, Jahre, Metaseiten).
   - **Neu:** Volltextsuche je Baustein: `<Thema> <search_queries des Slots>` → Top-Artikel; daraus
     nur Abschnitte, die das Thema oder einen Alias enthalten. Damit werden Bausteine gefüllt, die
     im Hauptartikel selten vorkommen (Beruf, Regularien, Bildung: „Augenoptiker", „Laserklasse",
     „Physikunterricht").
5. Quellenrollen nach Projekt: Wikipedia = Leitquelle; Klexikon = einfache Sprache (Facette
   `Bildungsstufe: Primarstufe/Sek I`, bevorzugt für Baustein 1 und 4); Wikibooks/Wikiversity =
   Lehrbuch/Hochschule (bevorzugt für 3, 8, 10).

### 4.3 Segmentierung

- HTML → Abschnittsbaum (h2/h3/h4) mit vollständigem Überschriftenpfad; Boilerplate-Filter
  (Klexikon-Spendenhinweise, Wikibooks-Regalstatus) aus Konfiguration; ausgeschlossene
  Überschriften (Einzelnachweise, Weblinks, Literatur) wandern in Baustein 12 als Quellenhinweise
  statt verworfen zu werden.
- Tabellen werden eigene Chunks (`kind=table`) für Fachinhalte, Formeln, Klassifikationen.
- Satzsplitter mit Abkürzungs- und Ordnungszahl-Regel (behebt „aus dem 11. Einige …").
- Grobe Kategorie je Chunk über das Überschriften-Lexikon (4.4), nicht über Themen-Keywords.

### 4.4 Slot-Matching v2

Dreistufig und vollständig template-gesteuert. Kein themenspezifisches Vokabular im Code.

**Stufe 1 — Überschriften-Lexikon (deterministisch, hohe Präzision).** Wikipedia-Überschriften
bilden ein kleines Vokabular. Einmalig per Skript aus dem ZIM erhoben (Stichprobe 20.000 Artikel,
Top-1.000 H2/H3-Überschriften), die häufigsten ~300 werden manuell Bausteinen zugeordnet und in
`config/heading_lexicon.yaml` versioniert. Beispiele: Geschichte/Entwicklung → 5;
Anwendungen/Verwendung/Technik → 10; Einteilung/Teilgebiete/Klassifikation → 2;
Etymologie/Begriff/Definition → 3 (Aussagen über das Begriffssystem) bzw. Glossar-Kandidat;
Kritik/Kontroversen/Gesellschaft/Rezeption → 4; Berufe/Ausbildung/Studium → 7/8;
Rechtliches/Normen/Sicherheit/Vorschriften → 9; Siehe auch → 11 (Relationen); Literatur/Weblinks
→ 12. Templates ergänzen eigene `heading_patterns` (Regex) je Slot. Trifft der Überschriftenpfad
eines Chunks ein Muster, erhält er den Slot mit Score 0,9 ohne ML.

**Stufe 2 — Ranking für den Rest.** BM25 + Char-TF-IDF + Model2Vec gegen die
Slot-Repräsentation (Titel, Kurztext, Inklusionen, Unterpunkte, Suchbegriffe). Fusion über global
normierte Scores (Mittelwert plus kleiner Konsensbonus), nicht über Ränge: reine Rangfusion (RRF)
ließ in Phase 0 einen Absatz mit einem schwachen Treffer auf „Thema" mit einem Absatz mit vier
Treffern auf „Unterricht, Schule, Didaktik, Bildung" gleichziehen. Optionaler Cross-Encoder-Rerank,
wenn das Extra `ml` installiert ist.

**Stufe 3 — Policy-Layer (ein Modul, `matching/policy.py`).** Lead-Absatz → Baustein 1 (nur
Hauptartikel, Klexikon-Lead fester Rang 2); Einleitung eines Teilgebiets-Artikels (Titel trägt den
Themenstamm) → Baustein 2; Exklusions-Strafe aus `exclusions`; H2-Abschnittsleads → Boost für
Baustein 2; Quellenrollen-Boosts; Global-Best-Fit (jeder Chunk genau einem Slot). **Vertrauens-
schwelle** `POLICY_CONFIDENT_SCORE` (0,65, bis 2026-09-18 0,45; vorher glättet `POLICY_SECTION_SMOOTHING` jeden
Score mit dem Mittel seines Abschnitts, D28): erst ab dieser fusionierten Trefferstärke zählt ein
Ranker-Treffer als Beleg. Darunter erhalten themennahe Chunks (Hauptartikel, Zwilling, Teilgebiets-
Artikel, die weder Person noch Organisation noch Einzelwerk sind, `knowledge/entities.py`) den
**Standardbaustein** des Templates (`default_slot`, in sc26 Fachinhalte), alle anderen bleiben
unzugeordnet statt zu raten. Chunks unter Überschriften generierter Bausteine („Bekannte
Vertreter“) speisen die Generatoren und werden nicht klassifiziert. Slot-Budget (`min_chunks`,
`max_chunks`, `target_chars`, Gesamtlänge über `target_length` verteilt); `empty_slot_policy`.
Die Klassifikation vor dem Budget steht als `AssignmentResult.classified` für die Evaluation
bereit. Zweifelsfälle (kleiner Abstand zwischen den zwei besten Slots) gehen in Phase 5 optional an
den LLM-Router, budgetiert. **Umsetzung (2026-09-18):** Zweifelsfall ist ein Chunk, dessen bester Slot die
Vertrauensschwelle erreicht, unter einem Lexikontreffer liegt und weniger als 0,1 (`DOUBT_MARGIN`) vor dem
zweiten liegt; Leads nie. `AssignmentResult.doubtful` nennt je Chunk bis zu drei Kandidaten. Der Router
(`matching/router.py`) fragt in den Hybridmodi einmal je Kompendium für die knappsten Fälle (höchstens
`LLM_ROUTER_MAX_CHUNKS`) und erwartet ein JSON-Objekt; Antworten außerhalb der angebotenen Kandidaten werden
verworfen. `assign(..., overrides=…)` übernimmt die Entscheidungen als sichere Treffer in einem zweiten Lauf.
Gemessen (Optik): 3 Zweifelsfälle, 3 Entscheidungen, davon 2 abweichend von der Policy (`moved`), ein Aufruf mit
rund 1.200 Tokens in 3 s. Nur verschobene Chunks zählen als LLM-Beitrag zum Modus. **Abgelöst (D33,
2026-09-19):** Der Router ist entfernt; mit `extraction=llm` wählt das LLM die Sätze jedes Bausteins unter den
Kandidaten der Policy (4.7), die dafür je Baustein ihren Score jedes Absatzes meldet (`AssignmentResult.slot_scores`).

**Explizit entfernt:** alle Optik-Signalwörter, Slot-Guardrails in den Matchern,
`SLOT_ENHANCED_QUERIES` im Planner.

### 4.5 Evaluation als Gate vor der Matcher-Entscheidung

- **Was der Goldstandard ist:** eine kleine, von Hand geprüfte Referenz, in der für einige Themen
  jeder Textabschnitt (Chunk) dem Baustein zugeordnet ist, in den er gehört, oder „keinem". Erst
  damit lässt sich messen, wie oft ein Matcher richtig liegt, statt nur zu zählen, ob Slots
  gefüllt sind.
- **Umfang (Entscheidung D17):** zehn Themen, gestreut über Schulfächer: Physik (Optik), Biologie
  (Photosynthese), Chemie (Säuren und Basen), Mathematik (Bruchrechnung), Deutsch (Barock als
  Literaturepoche), Geschichte (Französische Revolution), Geographie (Klimawandel), Politik
  (Demokratie), Informatik (Programmiersprache), Musik (Sinfonie). Je Thema ~40 Chunks. Die
  Erstzuordnung erstellt das Entwicklungsteam (LLM-Vorschlag erlaubt, jede Zeile manuell
  geprüft); die Redaktion kann später korrigieren. Werkzeug: `compendium eval export` schreibt die
  Chunks als CSV, die geprüfte Spalte wird als `eval/gold/<thema>.jsonl` eingecheckt.
- **Metriken:** Precision/Recall/F1 je Baustein (macro), Anteil fehlbelegter Slots, Anteil ehrlich
  leerer Slots, Laufzeit, Speicher. Zielwert für die Freigabe: macro-F1 ≥ 0,70 und keine
  „Halluzinations-Slots" (ein Slot ohne passende Evidenz bleibt leer).
- **Umsetzung (2026-09-17):** Goldstandard in `eval/gold/*.jsonl` (10 Themen, 603 bewertete
  Chunks; Labels per Texthash an die Chunks gebunden, Erstzuordnung durch das Entwicklungsteam mit
  gelesener Zeile, Regeln in `eval/README.md`); Werkzeuge `compendium eval export|import|run`,
  Endpunkt `POST /api/v2/matching/compare`; Metriken je Baustein, macro- und micro-F1,
  Fehlbelegungen, Halluzinations-Slots, Verwechslungsmatrix; gemessen wird die **Klassifikation
  vor dem Budget**, die Auswahl nach Budget wird getrennt ausgewiesen.
- **Ergebnis:** Baseline (Phase 0/1) macro-F1 0,27 / micro-F1 0,32. Mit Standardbaustein,
  Teilgebiets-Regel, Fragmentfilter und Lexikon v3: 0,39 / 0,63. Mit Model2Vec
  (`JanSchachtschabel/m2v-gte-256-edu`, lokal, 256-dim statisch): **0,43 / 0,63**. Große
  Bausteine: Themendefinition 0,67, Systematik 0,60, Fachinhalte 0,69, Entwicklung 0,71,
  Gesellschaft 0,41; kleine Bausteine mit 2–18 Gold-Chunks (Beruf 0,22, Bildung 0,59, Regularien
  0,18, Praxis 0,22, Querschnitt 0,00) drücken den Mittelwert. Schwellenraster 0,35/0,45/0,55 →
  0,41/0,43/0,43 (auf demselben Gold gemessen, keine Hold-out-Menge).
- **Entscheidung (D20, D21):** `MATCHER_DEFAULT=hybrid_light` mit Model2Vec; das Modell wird zur
  Bauzeit ins `base`-Image gelegt (`/models/m2v`, `HF_HUB_OFFLINE=1`), das Extra `ml` (torch,
  Cross-Encoder, Electra-QA) kommt nicht ins Produktionsimage. Der Zielwert 0,70 ist **nicht
  erreicht**; die Freigabe des Regelmodus erfolgt trotzdem, weil micro-F1 0,63 (nach D28: 0,66) und die großen
  Bausteine tragen, kleine Bausteine ehrlich leer bleiben dürfen (`empty_slot_policy`) und der
  LLM-Router in Phase 5 genau die Zweifelsfälle adressiert (seit D33 die optionale LLM-Extraktion). Offen: Redaktionsprüfung der Labels,
  mehr Gold für die kleinen Bausteine, Hold-out-Themen für die Schwellen.
- Der Comparator-Endpunkt bleibt (`POST /api/v2/matching/compare`) und liefert die Metriken.

### 4.6 Facetten, Einmaligkeitsregeln, Governance

**Deklaration** `config/facets.yaml` — elf Facetten, je Facette Werteliste (Vorschlag, änderbar),
zulässige Bausteine, Kardinalität, Standardwert. Zulässigkeit folgt der Spezifikation
(⁺ = Pflicht):

| Baustein | Facetten |
|---|---|
| 1 Themendefinition | Bildungsstufe, Querschnittsthema |
| 2 Gliederung & Systematik | Bildungsstufe |
| 3 Fachinhalte | Bildungsstufe |
| 4 Gesellschaftlicher Kontext | Querschnittsthema, Evidenzgrad, Bildungsstufe |
| 5 Entwicklung & Ausblick | Zeitbezug⁺, Evidenzgrad, Haltbarkeit, Querschnittsthema |
| 6 Akteure | Akteursfunktion⁺ (1..n), Haltbarkeit |
| 7 Beruf & Wirtschaft | Haltbarkeit, Evidenzgrad, Bildungsstufe |
| 8 Bildung | Bildungsstufe⁺ (1..n), Haltbarkeit, Querschnittsthema |
| 9 Regularien & Rahmensetzung | Geltungsebene⁺ (1..n), Regelungsgegenstand, Haltbarkeit |
| 10 Praxis | Domäne, Evidenzgrad, Haltbarkeit, Bildungsstufe |
| 11 Querschnitt & Bezüge | Querschnittsthema |
| 12 Quellen | Zugang⁺, Vertrauensgrad⁺, Domäne |
| 13 Glossar | keine (generiert) |

Wertelisten (Vorschlag): Zeitbezug `historisch | gegenwärtig | prospektiv`; Evidenzgrad
`belegt | Schlussfolgerung | Annahme | Prognose`; Haltbarkeit `stabil | volatil`; Bildungsstufe
`Elementar | Primar | Sek I | Sek II | Hochschule | Berufliche Bildung | Erwachsenenbildung`;
Akteursfunktion `Rahmensetzung | Wissenschaft & Entwicklung | Bildung | Vernetzung &
Fachgebietsentwicklung`; Geltungsebene `EU | Bund | Land | Organisation | international`; Zugang
`frei | registrierungspflichtig | kostenpflichtig`; Vertrauensgrad `hoch | mittel | gering`;
Querschnittsthema, Domäne, Regelungsgegenstand als offene, gepflegte Listen.

**Annotatoren** (regelbasiert, je Facette ein kleines Modul mit Tests): Zeitbezug aus
Jahreszahlen, Epochenwörtern, Tempus- und Prognosemarkern; Evidenzgrad `belegt` für extraktive
Sätze, `Schlussfolgerung` für LLM-Synthese ohne direkte Belegstelle; Haltbarkeit `volatil` bei
Marktzahlen, Fristen, Stellenangeboten; Bildungsstufe aus Quellenrolle (Klexikon → Primar/Sek I)
oder Wikiversity (Hochschule); Vertrauensgrad und Zugang aus der Quelle; Akteursfunktion,
Geltungsebene, Regelungsgegenstand aus Lexika (EU/Bund/Land-Muster, DIN/ISO/Gesetz).

**Zweck und Umfang (Entscheidung D13).** Facetten dienen dazu, später gezielt Absätze aus dem
Text herauszuparsen, etwa alle Lehrplanbezüge eines Bundeslandes. Dieser Zweck wird in **Teil 2
verbindlich** erfüllt: jeder Absatz trägt maschinenlesbare Marker mit Bundesland, Bildungsstufe,
Klassenstufe, Schulart und Lehrplan-URI (siehe 5.4). In **Teil 1 sind Facetten Best Effort**:
`FACETS_LEVEL=minimal` (Standard) annotiert nur die zuverlässig ableitbaren Facetten Zeitbezug,
Bildungsstufe (aus der Quellenrolle) und Evidenzgrad; `full` schaltet alle elf zu. Unsichere
Annotationen in Teil 1 sind nicht kritisch und werden im Lint nur gemeldet.

**Notation.** Maschinenlesbar immer als HTML-Kommentar, unabhängig von der Anzeige:
`<!-- kompendium:section id=sc26_5 status=maschinell-extraktiv facets="Zeitbezug=historisch" hash=… -->`
je Abschnitt und `<!-- f: Bundesland=Sachsen; Bildungsstufe=Sek I -->` je Absatz. So hängen
Filterung, Parsing und Teil-Regeneration nicht am Fließtext. Die sichtbare Kurzform
`[Facette: Wert]` aus der Spezifikation (hinter der Überschrift für den Abschnitt, am Satzende für
den Satz) ist per `FACETS_VISIBLE` zuschaltbar, Standard aus, damit die Themenseite sauber rendert.

**Einmaligkeitsregeln als Lint** (Warnungen im `audit.lint`, keine harten Fehler): Definitionen
nur in 13, Aussagen über das Begriffssystem in 3; Personenname als Überschrift nur in 6, sonst
Anker-Link; Relevanzaussagen nur in 4; Facette nur in zulässigem Baustein; Pflichtfacette fehlt;
Teilgebiete werden nur in 2 aufgezählt; „Sonstiges" existiert nicht mehr.

**Governance je Abschnitt und im Frontmatter:** Quellenbeleg-IDs; Prüfstatus
`maschinell-extraktiv | ki-generiert | redaktionell-geprüft` (steuert den Standardfilter der
Themenseite); Aktualitätsdatum und Review-Intervall (Standard 12 Monate, 3 Monate bei
`volatil`); KI-Kennzeichnung nach Art. 50 EU AI Act (seit 08/2026 anzuwenden); Prompt-ID,
Modellversion, Parameter bei LLM-Beteiligung; Lizenz und TULLU je Quelle (Titel, Urheber, Lizenz,
Link, Ursprungsort). Die Quellenlizenz CC BY-SA 4.0 (Wikipedia, Klexikon) macht den Teil 1 zu
einem BY-SA-Werk — der Hinweis steht im Frontmatter und in Baustein 12.

**Teil-Regeneration:** `POST /api/v2/compendium` akzeptiert `existing_markdown` und
`regenerate_sections=[…]`. Abschnitte mit Marker `status=redaktionell-geprüft` bleiben byteweise
erhalten, alle anderen werden neu erzeugt. Das ist der Mechanismus für „Kategorien später
nachbearbeiten".

### 4.7 Synthese

**Regelmodus (Standard).** Extraktiv: zwei bis vier Sätze je Chunk, Dedup über
Satz-Fingerabdruck, Zitationsmarker `[n]`, Absatz-Facetten. Quellenüberschriften erscheinen nie
als Fettdruck im Fließtext (Befund aus `user_msg_optik.txt`), sondern nur in der Belegtabelle.

Generierte Bausteine:

- **6 Akteure:** Akteursverzeichnis aus den verlinkten Artikeln des Korpus. Typ per Kaskade und
  Heuristik: Person (Lebensdaten-Muster „(* 1571", Überschrift „Leben"), Organisation
  (Rechtsform, „gegründet", „Sitz"), Vorhaben (Laufzeit, „Projekt", „Programm"), Netzwerk
  („Verbund", „Community"). Nur Name, Kurzbeschreibung aus dem Lead, Anker-Link, Facette
  Akteursfunktion aus Lexikon. Optional LLM-Klassifikation (geplant, nicht umgesetzt).
- **12 Quellen:** alle Quellen mit Publikationsform (Nachschlagewerk, Grundlagenwerk,
  Primärquelle …), TULLU, Zugang, Vertrauensgrad, Revisionsstand; dazu die aus den Artikeln
  extrahierten Literatur- und Weblink-Abschnitte als „weiterführende Quellen".
- **13 Glossar:** Begriffe = Thema, Aliase, Teilgebiete aus Baustein 2 und häufig verlinkte
  Fachbegriffe; Definition = erster Satz des Lead-Absatzes des verlinkten Artikels (Belegstelle);
  SKOS-Relationen `broader`/`narrower` aus der Gliederung in 2, `altLabel` aus Aliasen.

**Zwei LLM-Schalter (Entscheidung D33, löst die drei Modi aus D10 ab).**

| Schalter | Wert | Was das LLM tut | Aufrufe je Kompendium |
|---|---|---|---|
| `extraction` | `rule-based` (Standard) | nichts: die Policy ordnet ganze Absätze zu, der Baustein nimmt ihre ersten Sätze | 0 |
| | `llm` | wählt je Inhaltsbaustein die passenden Sätze unter den Kandidaten; antwortet nur mit Satznummern, der Wortlaut bleibt der der Quelle | einer je Baustein mit Kandidaten (Optik: 10) |
| `generation` | `rule-based` (Standard) | nichts: der Baustein besteht aus den gewählten Sätzen mit Belegnummer je Absatz | 0 |
| | `llm-fast` | formuliert die Bausteine aus `LLM_FAST_SECTIONS` (Vorschlag 1 Themendefinition und 11 Querschnitt) aus ihrem Evidenzblock | 2–3 |
| | `llm` | formuliert alle Inhaltsbausteine aus ihren Evidenzblöcken | 8–10 |

Die Schalter sind frei kombinierbar; beide auf `llm` heißt: das LLM wählt die Sätze, und dieselben Sätze sind der
Evidenzblock, aus dem es schreibt. Quellen, Belegtabelle, Glossar, Akteure und Marker bleiben deterministisch.
Für `generation` gilt: Prompt mit Evidenzblock, strikte Zitationspflicht, Nachprüfung, dass jede Zitationsnummer
existiert; Sätze ohne Beleg werden verworfen oder als `Evidenzgrad: Schlussfolgerung` markiert (konfigurierbar).
Fällt die b-api aus oder ist das Budget erschöpft, bleibt der Baustein regelbasiert, und der tatsächlich
verwendete Schalter steht im Frontmatter.

**Umsetzung (2026-09-18, `synthesis/llm.py`, `synthesis/citations.py`, `synthesis/writer.py`).** Evidenzblock je Baustein mit lokalen
Nummern `[1] (Quelle › Überschrift) Text`, höchstens 1.500 Zeichen je Absatz; Ausgabegrenze aus dem Bausteinbudget
(200 bis 1.500 Tokens). Nachprüfung in zwei Stufen: (1) ein Satz braucht mindestens eine gültige Belegnummer; eine
Nummerngruppe hinter dem Satzpunkt („Satz. Satz. [2]“) gilt als Absatzbeleg für die unmarkierten Sätze davor, weil
das Modell so zitiert (gemessen: ohne diese Regel gingen in einem Baustein 8 von 11 Sätzen verloren); (2)
Deckungsprüfung: mindestens 20 % der Inhaltswort-Stämme des Satzes müssen in den zitierten Absätzen vorkommen
(`MIN_SUPPORT`, Sätze mit weniger als drei Inhaltswörtern ausgenommen). Vor der Prüfung werden Mehrfachmarker
(`[1, 2]`, `[1; 2]`, `[1-3]`) in Einzelmarker zerlegt, weil sie sonst die Umnummerierung überleben und auf fremde
Quellen zeigen; Listenzeilen und Sätze nach einem schließenden Anführungszeichen zählen einzeln, ein Marker
hinter einer Abkürzung mitten im Satz („usw. [1] und …“) bleibt, wo er steht. Ein klein geschrieben
beginnender Satz wird als eigener Satz erkannt, wenn davor eine Belegnummer oder ein echtes Wort (keine Abkürzung,
mindestens fünf Buchstaben) steht, damit ein unbelegter Nachbar nicht mitläuft; die Abkürzungsliste des
Satztrenners kennt dafür jetzt auch „bspw.“, „einschl.“, „insbes.“ und weitere. HTML-Kommentare in der Antwort
werden entfernt, weil das Dokument über Kommentar-Marker geparst wird, und zwar auch nach dem Entfernen
ungültiger Nummern, weil aus `-[9]->` sonst `-->` würde. Der Satztrenner schützt Initialen in Namen („Max M.
Mustermann“); vorher wurde der Satzanfang als unbelegt verworfen und der Rest verstümmelt (live gemessen). Gemessen an 175 Sätzen mit Prompt v1:
Median 0,73, Schlussfolgerungen mit bloßer Nummer 0,00 bis 0,17, schwächste treue Paraphrasen ab 0,20. Verworfene
Sätze stehen als `dropped_sentences` und `unsupported_sentences` im Audit; mit `LLM_UNSUPPORTED_SENTENCES=mark`
bleiben sie ohne Nummer stehen, eingefasst in `<!-- f: Evidenzgrad=Schlussfolgerung -->` und `<!-- /f -->`
(`marked_sentences`, Facette Evidenzgrad ergänzt); ein Baustein ganz ohne belegten Satz entsteht trotzdem
extraktiv. Entwürfe entstehen parallel (`LLM_MAX_CONCURRENCY`) mit lokalen Nummern und werden beim
Zusammenbau in die eine globale Belegfolge verschoben. Jeder Baustein, den das LLM nicht liefert (Fehler, Budget,
leere Antwort, nichts Belegtes), entsteht extraktiv; der Grund steht in `audit.llm.fallbacks`. Eine leere Antwort
mit `finish_reason=stop` heißt: die Belege passen nach Urteil des Modells nicht zum Baustein. Frontmatter `generation`
nennt den tatsächlich verwendeten Schalter: ohne LLM-Baustein ist das `rule-based`, der Wunsch steht dann in
`generation_requested`. `target_length` wirkt über die skalierten Bausteinbudgets
auch auf Ziellänge und Ausgabegrenze der LLM-Bausteine. Unerwartete Fehler in der LLM-Schicht (nicht nur
b-api-Fehler) führen ebenfalls zum extraktiven Baustein und stehen mit Fehlertyp im Audit.

**LLM-Extraktion (D33, 2026-09-19, `synthesis/selection.py`, `synthesis/extraction.py`).** Kandidaten eines
Bausteins sind die Absätze, die ihm die Policy gibt (alle), danach die nächstbesten nach dem Score der Policy für
diesen Baustein (`AssignmentResult.slot_scores`), zusammen `LLM_EXTRACTION_CANDIDATES` (Standard 8). Jeder
Kandidat erscheint mit nummerierten Sätzen („2.3“ ist der dritte Satz des zweiten Absatzes): nur die brauchbaren
Sätze der Regeln (Mindestlänge, keine durch eine entfernte Formel abgeschnittenen Sätze), höchstens 1.000
Zeichen je Absatz; Listen und Tabellen sind eine Einheit. Das Modell antwortet mit `{"saetze": [...]}` (Prompt
`passage_selection` v1). Nicht angebotene Nummern werden verworfen und gezählt (`invalid_numbers`); die gewählten
Sätze eines Absatzes stehen in Quellreihenfolge, die Absätze in der Reihenfolge, in der das Modell sie nennt;
über das 1,5-Fache der Ziellänge hinaus endet die Auswahl an einer Absatzgrenze (`cut_sentences`). Der Schreiber
übernimmt alle gewählten Sätze (Regelmodus: die ersten drei, im Lead fünf); die Dublettenprüfung über
Satzanfänge gilt weiter. Eine leere Auswahl heißt: kein angebotener Absatz passt, der Baustein bleibt leer
(`emptied`, Status `leer`). Scheitert die Auswahl (b-api, Budget, Frist, unlesbare Antwort, unerwarteter Fehler),
behält der Baustein die Absätze der Policy (`fallbacks`). Die Aufrufe laufen parallel (`LLM_MAX_CONCURRENCY`) aus
demselben Anfragebudget wie das Schreiben. Status `ki-ausgewählt`; die KI-Kennzeichnung im Frontmatter nennt
wörtliche Quellenauszüge mit KI-gestützter Auswahl, `review.status` ist `ki-ausgewählt`. Der Router für
Zweifelsfälle (4.4) ist entfallen, weil die Extraktion alle Absätze eines Bausteins entscheidet, nicht nur die
knappen. Gemessen mit `gpt-5.6-luna` (Optik, 2026-09-19): `extraction=llm` 10 Aufrufe, 16.467 Tokens (12.760
Eingabe, 3.707 Ausgabe mit Denken), 10,9 s, 81 Sätze in 10 Bausteinen, keine ungültige Nummer; beide Schalter auf
`llm` 20 Aufrufe, 27.205 Tokens, 18 s, alle 10 Bausteine geschrieben, kein Satz verworfen. Dabei fiel auf:
Reasoning-Modelle zählen ihr Denken in `max_completion_tokens`; die Synthese hatte die Grenze nur nach der
Textlänge bemessen (Baustein 2: 555 Tokens) und bekam reproduzierbar eine leere Antwort mit
`finish_reason=length`. Seither kommen für Reasoning-Modelle 1.000 Tokens hinzu (`REASONING_ALLOWANCE`, auch in
der Reservierung), und `LLM_MAX_TOKENS_PER_REQUEST` steht auf 40.000, weil 20.000 bei beiden Schaltern sieben von
zehn Bausteinen abwiesen. Beobachtet: das Modell wählte in „Fachinhalte“ einen Satz, der auf eine entfernte Formel
verweist („Dabei ist der Laplace-Operator …“); der Prompt schließt solche Sätze nur allgemein aus. Gegen den
Goldstandard (10 Themen, `compendium eval run --llm-extraction`, Einzelheiten in `eval/README.md`): das LLM druckt
131 Absätze, 77 richtig und 54 falsch, die Regeln in derselben Konfiguration (ohne Model2Vec) 107, 63 und 44;
macro-F1 der gedruckten Absätze 0,273 zu 0,214, die Regeln mit Model2Vec (Produktion) 0,277. Gewinn in den großen
Bausteinen, Verlust in den kleinen (Querschnitt, Bildung, Beruf), halb so viele Absätze ohne Baustein; 189.975
Tokens für zehn Themen. Offen: Lauf mit Model2Vec, Prompt für die kleinen Bausteine, Richter-Vergleich der Texte.

---

## 5. Teil 2 — Lehrplanbezüge (MEM, gepuffert)

### 5.1 Quellen und Abdeckung

Einzige Quelle ist der MEM-Triplestore (FWU): 2.514 Lehrpläne aus BY, SN, RP, BB (BE im
BB-Graphen). Für die übrigen Länder gibt es derzeit keine strukturierte Quelle; der Text nennt
die Abdeckung deshalb ausdrücklich („Lehrplanbezüge liegen strukturiert für Bayern, Sachsen,
Rheinland-Pfalz, Brandenburg/Berlin vor, Stand <Harvest-Datum>") und wächst automatisch mit,
sobald MEM weitere Länder veröffentlicht (der Harvest fragt alle 16 Landesklassen ab). Die
Landes-Terminologie (Bildungsplan, Kerncurriculum, Kernlehrplan, Rahmenlehrplan, LehrplanPLUS …)
wird beim Rendering verwendet.

Fachlicher Ausgangspunkt ist der in `mem-schule-optik` getestete, gezielte Abruf von
Lehrplanelementen zu einem Thema (Stichwortfilter über Themenbereiche, Kompetenzen und Inhalte,
Verknüpfung mit Bildungsstufen aus Knoten oder Lehrplan, Wortgrenzen-Regel gegen Rauschen,
Stufenleiter aus Daten oder Lehrplantitel). v2 kehrt die Reihenfolge um: erst vollständiger
Abzug in einen lokalen Cache, dann derselbe Stichwortfilter lokal zur Inferenzzeit.

### 5.2 Harvest-Job (offline-first)

Lehrpläne werden **nie zur Inferenzzeit abgerufen**, sondern aus dem lokalen Cache gelesen
(Entscheidung D16). Der Cache wird **wöchentlich geprüft** (`compendium lehrplan check`: eine
Zählabfrage je Bundesland und Fach, Vergleich mit dem letzten Harvest) und nur bei Abweichung oder
spätestens monatlich vollständig neu gezogen (`compendium lehrplan harvest`; MEM veröffentlicht
keine Änderungsdaten, daher Vollabzug mit lokalem Diff):

1. Alle Lehrpläne mit Bundesland, Schulart, Schulfach, Stufen (Query `lehrplaene` ohne
   Fach-Filter, gegen alle 16 Landesklassen als begrenzte UNION).
2. Je Lehrplan alle Knoten (ein Hop `obo:BFO_0000051`, der wegen der Über-Assertion alle Nachfahren
   liefert) mit Label, Klassen, Rolle (Funktionsspezifikation und Klassenzuordnung), Stufen am
   Knoten; echte Eltern per `FILTER NOT EXISTS`.
3. Rate-Limit 1–2 Anfragen/s, Retry mit Backoff, Abbruch bei HTTP 500 mit Fehlerbericht;
   geschätzt ~7.500 Anfragen, Laufzeit rund eine Stunde.
4. Schreiben in `lehrplan.db` (SQLite): Tabellen `lehrplan`, `node` (mit `parent_uri`,
   `parent_label`, `rollen`, `stufen_json`, `stufen_quelle`), FTS5 über `label` und
   `parent_label`; Harvest-Metadaten (Datum, Endpoint, Zählung je Land) für das Frontmatter.
   Geschätzte Größe: ~200.000 Knoten, 100–200 MB.
5. Atomarer Austausch der Datenbankdatei (`.tmp` → `rename`).

Der SPARQL-Client wird aus `mem-schule-optik` übernommen (validierte IRIs in `vocab.py`,
Query-Templates ohne `*`/`+`, Regressionstest dagegen, 49 Offline-Tests) und um die Vollabzug-
Queries erweitert. Die Rollenbestimmung nutzt zusätzlich die Erkenntnis aus dem MEM-Import-Plan
in `lehrplan-ontologien`: die häufigsten Landesklassen (`Kompetenzerwartung (BY)`, `Lernziel und
Lerninhalt (SN)`, `Kompetenz (RP)`) hängen nicht unter einem CE-Elterntyp und brauchen eine
explizite Zuordnungstabelle Landesklasse → Rolle. Die Ontologie-Version (`lp` 1.0.0rc3) wird im
Harvest protokolliert.

**Umsetzung (2026-09-17, `sources/lehrplan/`):** Der Harvest fragt alle 16 Bundesland-Individuen
(`vocab.BUNDESLAENDER`, IRIs aus `lp.ttl`) und arbeitet in vier Abfrageformen, alle ohne transitive
Pfade: (1) `lehrplan_list` je Land über `?lp a lp:LP_0000438` (die Inferenzgraphen liegen im
Default-Graph, 0,2 s), (2) `lehrplan_heads` in VALUES-Blöcken zu 40 Lehrplänen mit dem Property-Pfad
`(lp:LP_0000537|obo:BFO_0000051/lp:LP_0000537)`, weil Bayern Schulfach, Schulart und Jahrgang am
Fachlehrplan-Kind führt (0,5 s je Block; dieselben Felder über ein ganzes Land aggregiert liefen in ein
Timeout), (3) `closure` je Lehrplan in einem Subselect über Virtuosos transitive Option mit `t_distinct`
(`t_max` = `MAX_TREE_DEPTH` 30): die schlichte Form `BFO_0000051+` brach beim ersten Lauf an einem RP-Lehrplan
mit 121 Knoten mit „Exceeded transitive temp memory“ ab, weil die Länder die Closure materialisieren und jeder
Pfad gezählt wurde; gebundene Pfadlängen 1–6 waren dort vollständig, weil alle Nachfahren direkte Teile sind,
brauchten bis Länge 9 aber 151 s statt 0,5 s und würden reine Baumkanten unterhalb des Bounds abschneiden;
`t_distinct` liefert 1.007 Knoten in 4 s; tiefster gemessener Baum 8 Ebenen, der Harvest warnt an der Grenze), (4) `class_roles` für neue
Knotenklassen (Funktions-Individuen und CE-Oberklassen, bounded UNION). Rollen: direkte CE-Klasse
(BY, BE) → Klassenindex (SN, RP) → Override-Tabelle (`Themenfeld`, `Element (BE)`, `Fachlehrplan (BY)`);
Inhaltsrollen schlagen Strukturrollen. Echte Eltern aus der materialisierten Closure: der Vorfahr mit den
meisten eigenen Vorfahren (`tree.build_nodes`). Cache: `lehrplan.db` mit Tabellen `lehrplan`, `node`,
`meta` und FTS5-Trigram-Index über `label`/`parent_label` (Teilstring, groß/klein unabhängig, auch
Umlaute), geschrieben als `.tmp` und per `os.replace` getauscht; Leser öffnen je Aufruf. Statusdatei
`lehrplan_status.json`, Trigger-Datei `lehrplan.request`, Sidecar `compendium lehrplan harvest --loop`
(Zählprüfung `LEHRPLAN_CHECK_INTERVAL`, Vollabzug bei Änderung oder `LEHRPLAN_HARVEST_MAX_AGE`).
**Gemessen:** 2.514 Lehrpläne (BY 1.707, SN 532, RP 229, BE 46), 295.184 Knoten, Dauer
25 Minuten, Datei 278 MB; Klassen ohne Rolle: 4 Knoten mit Leitperspektiven-Klassen (LP_0030325/LP_0030329), 2.605 Anfragen, keine übersprungenen IRIs.

### 5.3 Themen-Matching zur Inferenzzeit

- Stichwortsatz: Thema, Aliase (aus 4.2), Teilgebiete (Überschriften und Links aus Baustein 2),
  fachliche Synonyme aus dem Template (`curricula.keywords`, editierbar).
- Fach-Filter: `subject` aus der Anfrage oder aus `ccm:taxonid` der Sammlung, übersetzt über
  `config/subjects.yaml` (WLO-Fachvokabular → MEM-Schulfach-Labels). Ohne Fach wird über alle
  Fächer gesucht; die Wortgrenzen-Regel des Prototyps (`is_noise`: „Licht" in „Pflichtbereich"
  ist Rauschen) bleibt.
- Ranking: Rolle (Themenbereich > Kompetenz > Inhalt), Treffer im Label vor Treffer im Elternteil,
  Stufenangabe vorhanden vor abgeleitet.
- Läuft vollständig lokal in Millisekunden. **Gemessen (2026-09-17, Cache mit 295.184 Knoten):** zwölf Themen,
  Matching 6–154 ms, Rendering 0–13 ms, Median 48 ms, Maximum 163 ms je Thema („Licht“ ohne Fach: 1.109 Treffer,
  2.066 Wortfragment-Treffer ausgeschlossen). Ohne Kappung wird Teil 2 bei breiten Themen ohne Fach sehr lang
  (Demokratie/Politik 161.000 Zeichen, „Wasser“ ohne Fach 720.000); mit Fach bleiben Optik 34.000 und
  Photosynthese 57.000 Zeichen. Ohne Cache oder bei einem nicht lesbaren Cache enthält Teil 2 einen
  Hinweistext; SPARQL gibt es zur Inferenzzeit nicht (D22).

**Umsetzung (2026-09-17):** Stichwortsatz aus Titel, Aliasen und Teilgebieten (Titel verlinkter
Artikel mit Themenstamm), Bindestrich-Teile ohne Gattungswörter, höchstens zwölf (`matcher.build_keywords`);
Fach über `config/subjects.yaml` (36 WLO-Fächer → MEM-Schulfach-Teilstrings, Quelle: 299 Labels aus MEM)
aus `subject` der Anfrage oder dem Präfix der Themenangabe; Treffer aus dem FTS5-Index, Wortgrenzen-Regel
des Prototyps (`stufen.is_noise`), Rangfolge Themenbereich > Kompetenz > Inhalt, Label vor Elternteil,
Stufe aus Daten vor abgeleitet. Nur Knoten mit Inhaltsrolle werden getroffen; Fragmente und Hinweise
bleiben Kontext. `LEHRPLAN_LIVE_FALLBACK` ist gestrichen (D22): ohne Cache enthält Teil 2 einen
Hinweistext. Äquivalenzprüfung mit den 17 Optik-Stichwörtern des Prototyps über Physik-Lehrpläne
(Teilstring, ohne Wortgrenzen-Regel): Sachsen 218 (Prototyp 272), Rheinland-Pfalz
200 (200), Berlin 0 (0), dazu Bayern 278, das der Prototyp wegen
des Fachlehrplan-Kinds nicht sah.

### 5.4 Rendering

Struktur (Bildungsstufe → Bundesland → Lehrplan mit Schulart und Klassenstufe → Lernbereich →
Kompetenzen und Inhalte), übernommen aus `optik_uebersicht.render`, gekürzt für den
Kompendialtext:

1. Abdeckungshinweis und Kennzahlen (Lehrpläne, Länder, Treffer, Stand).
2. Übersichtstabelle Bundesland × Bildungsstufe (Anzahl Treffer).
3. Je Bildungsstufe und Land die wichtigsten Lernbereiche mit Kompetenzformulierungen als Zitat,
   Link auf die `lp`-Ressource; Klassenstufe mit Herkunftsvermerk (Daten oder aus dem Titel
   abgeleitet).
4. Längenbudget: maximal n Einträge je Land, danach „weitere k Einträge".
5. Marker je Absatz (verbindlich, siehe 4.6), damit sich Absätze später gezielt herausparsen
   lassen: `<!-- f: Bundesland=Sachsen; Bildungsstufe=Sek I; Klassenstufe=7; Schulart=Oberschule;
   Lehrplan=https://lp-sachsen.org/resource/522 -->`. Sichtbare Facetten `[Bildungsstufe: …]`,
   `[Geltungsebene: Land]` nur bei `FACETS_VISIBLE`.

Die Datenlage-Tabelle des Prototyps (Herkunft der Stufenzuordnung) wandert in den `audit`-Block
der JSON-Antwort, nicht in den Text.


**Umsetzung (2026-09-17, `render.py`):** Abdeckungssatz mit Ländern, Stand und Lehrplanzahl aus den
Cache-Metadaten; Kennzahlenzeile; Tabelle Bundesland × Bildungsstufe; je Stufe und Land die Lernbereiche
mit Kompetenzen und Inhalten als Zitat und Link auf die `lp`-Ressource, Landes-Terminologie
(`*LehrplanPLUS: …*`, `*Rahmenlehrplan: …*`); Marker je Gruppe
`<!-- f: Bundesland=Sachsen; Bildungsstufe=Sek I; Klassenstufe=7; Schulart=Gymnasium; Lehrplan=https://… -->`;
abgeleitete Stufen mit Herkunftsvermerk; jede Gruppe endet mit `<!-- /f -->`, damit sich Absätze samt Facetten
herausparsen lassen (D23). Standardmäßig werden alle Treffer ausgegeben; `LEHRPLAN_MAX_GROUPS_PER_LAND` kappt
optional mit „weitere k Einträge“.
Die Datenlage-Zählung liegt in `curricula.summary.datenlage` der JSON-Antwort. Realdaten: Optik
135 Lehrplanelemente in 14 Lehrplänen aus 3 Ländern (Fach Physik, 110 ms), Photosynthese 195 Lehrplanelemente in 22 Lehrplänen aus 3 Ländern (Fach Biologie, 23 ms).
---

## 6. Teil 3 — Sammlungsüberblick und Wissens-Sammlung

### 6.1 Sammlung lesen

Eingabe `collection_id` (nodeId einer Sammlung; bei Themenseiten die `collectionId`, erkennbar am
Property `ccm:page_config_ref`). Dieselben Metadaten liefern auch das Thema für Teil 1 (siehe
4.2): Titel, Beschreibung, Schlagwörter, Fach (`ccm:taxonid`), Bildungsstufe
(`ccm:educationalcontext`). Aufrufe gegen `EDU_SHARING_BASE_URL`:
`GET /collection/v1/collections/-home-/{id}` (Titel, Beschreibung, `childReferencesCount`,
`childCollectionsCount`), `…/children/references` paginiert (Titel, `cclom:general_description`,
`cclom:general_keyword`, `ccm:oeh_lrt`, `ccm:educationalcontext`, `ccm:taxonid`,
`ccm:commonlicense_key`, URL), `…/children/collections` (Untersammlungen, eine Ebene). Anonym,
wenn keine Zugangsdaten konfiguriert sind. Cache je Sammlung 1 h, Schlüssel `modifiedAt`.

**Umsetzung (2026-09-17, `sources/wlo/`):** `client.py` (httpx, anonym oder Basic, Node-IDs als UUID
validiert, Referenzen seitenweise mit `maxItems`/`skipCount` bis `pagination.total`, 404 → `CollectionNotFoundError`,
sonst `EduSharingError`, ein Wiederholungsversuch bei Verbindungsabbruch), `models.py` (Felder wie vom Repository
geliefert: `*_DISPLAYNAME`-Zwillinge für Vokabularwerte, `ccm:wwwurl` oder Render-URL, `originalId` am
Reference-Knoten), `cache.py` (SQLite-TTL-Cache). Gemessen gegen `redaktion.openeduhub.net`: Sammlung 0,2 s,
Referenzseite 0,4 s, Untersammlungen 0,2 s, `textContent` 0,1–2,3 s je Knoten; `childReferencesCount` ist an den
realen Sammlungen `null`, die Größe kommt aus `pagination.total`. Ohne `topic` liefert die Sammlung Thema
(`cm:title`, normalisiert nach 4.2), Fach (`ccm:taxonid`, über `config/subjects.yaml`) und Kontext
(`ccm:educationalcontext`); ein nicht erreichbares Repository bricht nur ab, wenn das Thema von der Sammlung abhängt.

### 6.2 Rendering (Kurzform)

Zweck und Beschreibung der Sammlung; Kennzahlen (Inhalte, Untersammlungen, Verteilung nach
Materialtyp, Bildungsstufe, Fach); je Untersammlung eine kompakte Liste „Titel — Ein-Satz-
Beschreibung — Schlagwörter — Link"; Kappung (Standard 40 Einträge, dann „weitere n Inhalte").
Keine Bewertung, keine Erfindung: fehlende Beschreibungen bleiben leer.

**Umsetzung (2026-09-17, `overview.py`):** Kopfblock (Titel, Link, Fach, Bildungsstufe, Sammlungstyp, Stand),
Beschreibung oder sichtbarer Hinweis auf die fehlende Beschreibung, Kennzahlen (Inhalte, Untersammlungen,
Materialtypen, Bildungsstufen, Fächer, Lizenzen), alle Inhalte als Zeile „Titel · erster Satz · Schlagwörter ·
Materialtyp · Bildungsstufe · Lizenz · Link“, Untersammlungen eine Ebene tief mit ihren eigenen Inhalten. Jeder
Block steht zwischen `<!-- f: Sammlung=<id>; Fach=…; Bildungsstufe=… -->` (Untersammlungen: `Übergeordnet=<id>`)
und `<!-- /f -->`. Keine Kappung (D23; `COLLECTION_MAX_ITEMS` optional). Gemessen, ungecacht: Optik 31.000 Zeichen
in 5,5 s (6 Blöcke), Geometrische Optik 63.000 in 6,8 s (8), Wellenoptik 34.000 in 5,5 s (6), Photosynthese 6.800
in 3,5 s (2), Vorgänge in der Zelle 13.700 in 4,1 s (5); gecacht 3 ms.

### 6.3 Wissens-Sammlung (optional, `knowledge_collection_id`)

Metadaten und Volltexte (`GET /node/v1/nodes/-home-/{id}/textContent`) der referenzierten
Materialien werden als zusätzliche `Source`s (`project=wlo_material`, Lizenz aus
`ccm:commonlicense_key`) segmentiert und nehmen am Slot-Matching teil, bevorzugt für 8 (Bildung),
10 (Praxis, Materialbezug als Relation `behandelt`) und 12 (Quellen).

- **Lizenz-Policy:** wörtliche Übernahme (extraktiv) nur bei CC0, PDM, CC BY, CC BY-SA; andere
  Lizenzen nur als Evidenz für LLM-Synthese oder als Verweis. Konfigurierbar.
- **Grenzen:** maximal 30 Materialien, 20.000 Zeichen je Text, vier bis sechs parallele Aufrufe
  (Latenz Median 4,6 s), Volltext-Cache je Knoten 7 Tage. Bei Zeitüberschreitung wird Teil 1
  ohne die fehlenden Materialien erzeugt und der Umstand im `audit` vermerkt.

**Umsetzung (2026-09-17, `knowledge.py`, D24):** Lizenz-Allowlist `CC_0`, `PDM`, `CC_BY`, `CC_BY_SA`
(`COPYRIGHT_FREE` heißt zugänglich, nicht nachnutzbar, und bleibt draußen); Texte über `textContent` parallel
(vier), Budget 30 Materialien und 20.000 Zeichen je Text, Cache 7 Tage; Zeilen unter 40 Zeichen und
Consent-Banner werden verworfen; Beschreibung als Lead-Absatz, Text als Abschnitt „Inhalt“; Quellen mit
`project=wlo_material`, Rolle `material`, Lizenzlabel. Fehler je Material stehen in `audit.knowledge`, nie
bricht Teil 1 ab. Policy: Absätze dieser Quellen sind Beleg für Bausteine mit `wlo_material` in
`source_preference` (sc26: Bildung, Praxis) mit Score 0,5 plus halber Rankerstärke, weil sie sonst gegen
Wikipedia-Absätze untergehen. Gemessen (Sammlung Optik, 16 Materialien): 8 lizenzkonform, 6 mit Text, 5
Chunks, ein zusätzlicher Beleg in Baustein 8 (Bildung); Abruf 3,7 s, danach 7 ms aus dem Cache.

### 6.4 Rückschreiben (optional, spätere Phase)

Geprüft am alten Code (Frage F2): die alte API kennt edu-sharing nicht, sie liefert nur Markdown
zurück; der aufrufende KI-Workflow speichert den Text in `ccm:oeh_collection_compendium_text`. v2
behält diese Arbeitsteilung bei (Entscheidung D11). `write_back: true` bleibt als optionale
Erweiterung vorgesehen: `POST /node/v1/nodes/-home-/{id}/property?property=…` mit dem Text als
JSON-Array, vorher `node.access` auf `Write` prüfen, danach Read-Back, weil edu-sharing bei
fehlendem Recht oder fehlendem MDS-Eintrag still `200 OK` liefert. Standard aus.

---

## 7. LLM-Schicht (optional, b-api)

Client nach den gemessenen Eigenheiten der b-api: Header `X-API-KEY`, Pfad
`/api/v1/llm/{academiccloud|openai}/chat/completions`, Semaphore (Standard 4), Retry mit
exponentiellem Backoff bei 429/502/503/504 (kein `retry-after`), Timeout ≥ 120 s,
`max_completion_tokens` statt `max_tokens` für `gpt-5*`/`o*`, `chat_template_kwargs:
{enable_thinking:false}` für Qwen3 (nicht für Mistral), Antwort aus `content` oder `reasoning`.
Beim Start wird das konfigurierte Modell gegen `/models` geprüft und bei Abweichung gewarnt,
bei `status != ready` oder hohem `demand` fällt der Dienst auf den Regelmodus zurück.

Einsatzorte (alle einzeln abschaltbar): Satzauswahl (`extraction=llm`, D33), Abschnittssynthese (`generation`),
Akteurs-Klassifikation, Glossar-Politur, Template-Kurztexte (Admin), QA-Endpunkt.
Jeder Prompt hat eine ID und Version in `llm/prompt_registry.py`; beide landen im Frontmatter.

Kostenmodell (Schätzung der Planung je Kompendium, Modellklasse gpt-4.1-mini; Messwerte unten und in 4.7): `rule-based` 0;
`hybrid-fast` 2–3 Aufrufe × (1.500 Eingabe- + 400 Ausgabe-Tokens) ≈ 4.500/1.200;
`hybrid-quality` 13–15 Aufrufe ≈ 20.000/5.500. Zum Vergleich alt: ~1.500 Eingabe- + bis 4.000
Ausgabe-Tokens für den Text, plus 1–2 Linker-Aufrufe. Kostenschutz über
`LLM_MAX_TOKENS_PER_REQUEST` und ein Tagesbudget; Tokenverbrauch steht in `pipeline_statistics`.
**Vorkonfiguration (Entscheidung D19):** Provider `openai`, Modell `gpt-5.6-luna`. Provider,
Modell und Basis-URL sind Konfiguration (`B_API_PROVIDER`, `B_API_MODEL`, `B_API_BASE_URL`), der
Pfad `/api/v1/llm/{provider}/chat/completions` wird daraus gebildet, ein Wechsel auf
`academiccloud` (z. B. `deepseek-v4-flash-0731`, `openai-gpt-oss-120b`, Qwen3 mit
`enable_thinking:false`) braucht keinen Code. Der Client kennt beide Anfrageformen: GPT-5-Serie
mit `max_completion_tokens`, `reasoning_effort` und `verbosity` ohne `temperature`; klassische
Modelle mit `max_tokens` und `temperature`. Die konkrete Modell-ID wird beim Start gegen `/models`
geprüft, weil sie sich ohne Ankündigung ändert.

**Umsetzung (2026-09-18, `llm/`).** `client.py` spricht die b-api direkt über httpx (kein OpenAI-SDK): Header
`X-API-KEY`, Pfad aus Provider, beide Anfrageformen, `chat_template_kwargs` für Qwen3, Text aus `content` oder
`reasoning`, Semaphore, Backoff 1,5 s · 2ⁿ bei 429/502/503/504 und Verbindungsfehlern, andere Fehler ohne
Wiederholung; der Schlüssel erscheint in keiner Meldung. `check_model()` vergleicht mit `/models`: fehlt das Modell,
ist `status != ready` oder `demand ≥ 3`, gilt das LLM als nicht verfügbar; der Dienst prüft beim Start und, solange
nicht verfügbar, höchstens alle zehn Minuten erneut (`gateway.py`). Die Prüfung ist ein einzelner Versuch mit 10 s Timeout, `/health` liest nur den letzten
Stand und ruft die b-api nie selbst. Zeitüberschreitungen werden nicht wiederholt; nach einem Verbindungsfehler
oder Timeout setzt ein Schutzschalter die b-api 60 s aus, LLM-Anfragen laufen in dieser Zeit sofort im
Regelmodus. Der Schlüssel wird von Leerraum befreit, bei unzulässigen Zeichen abgelehnt (ohne ihn zu nennen) und
aus jeder Fehlermeldung geschwärzt, weil httpx unzulässige Header-Werte im Fehlertext zitiert; Fehlerkörper der
b-api stehen nur im Log, nie in `/health`, Audit oder Frontmatter. Antworten in unerwartetem Format werden zu
`LlmError`; fehlt `usage`, wird der Verbrauch aus den Textlängen geschätzt, damit das Budget weiterzählt.
`prompts.py`: `section_synthesis` v2 und
`passage_selection` v1 (D33; der frühere `slot_router` v1 ist mit dem Router entfallen); v2 entstand nach der ersten Messung, weil v1 die Ausschlussliste des Bausteins im Text
wiedergab und Schlussfolgerungen mit Belegnummer versah. `budget.py` und `budget_store.py`: Grenze je Kompendium und Tagesgrenze mit UTC-Wechsel; die verbrauchten Tokens
des Tages liegen in `STATE_DIR/llm_budget.db` (SQLite, UPSERT), gelten für alle Worker gemeinsam und überstehen
Neustarts, weil das Image mit zwei uvicorn-Workern läuft; Reservierungen laufender Aufrufe bleiben im Prozess,
ein Speicherfehler wird geloggt und der Prozesszähler trägt weiter. `deadline.py`: `REQUEST_TIMEOUT_S` begrenzt
die LLM-Arbeit einer Anfrage, jeder Aufruf bekommt das Minimum aus `LLM_TIMEOUT_S` und Restzeit, unter 5 s Rest
wird nicht mehr aufgerufen; ein so verkürzter Timeout löst den Schutzschalter nicht aus (erst ab 30 s Wartezeit).
Auch das Warten auf einen freien Aufruf-Platz (Semaphore) zählt gegen diese Frist. Tokens, die während eines
Speicherausfalls verbraucht wurden, trägt der Prozess mit der nächsten erfolgreichen Buchung nach.
Weiter in `budget.py`: jeder Aufruf reserviert vorab seine Obergrenze (Zeichen / 3 plus Ausgabegrenze) und
wird nach `usage` abgerechnet, atomar auch bei parallelen Entwürfen (Summe aller Reservierungen je Kompendium
gemessen: 12.000 bis 17.000 Tokens, unter der Standardgrenze); die Ablehnung nennt, ob die Anfrage- oder die
Tagesgrenze greift.
Gemessen am 2026-09-18 gegen `b-api.staging.openeduhub.net`: `/models` openai 138 Modelle ohne `status`/`demand`,
academiccloud 14 Modelle mit `status` und `demand` 0 bis 2; `gpt-5.6-luna` antwortet mit
`max_completion_tokens`, `reasoning_effort` und `verbosity` in 2,4 s; identische Anfragen beantwortet die b-api aus
einem Cache (0,2 s, gleiche `usage`). Kosten je Kompendium (Optik, Klimawandel, Photosynthese, Französische Revolution; die Modi heißen seit D33 `generation=llm-fast` und `generation=llm`): `hybrid-fast` 2 bis 3 Aufrufe
und 2.300 bis 4.000 Tokens (9 bis 15 s gesamt), `hybrid-quality` 8 bis 10 Aufrufe und 10.500 bis 14.500 Tokens
(16 bis 20 s gesamt bei vier parallelen Aufrufen), also unter der Schätzung oben, weil nur Bausteine mit Belegen geschrieben werden. Nicht umgesetzt:
Akteurs-Klassifikation und Glossar-Politur per LLM, Template-Kurztexte, QA-Endpunkt (Phase 6).

---

## 8. API-Design und Kompatibilität

### 8.1 Legacy-Endpunkte (v1) — Verhalten im Neubau

| Endpunkt | Alt | Neu | Hinweis |
|---|---|---|---|
| `GET /health` | status, service, version, timestamp | unverändert + `components` (zim, lehrplan_cache, llm, edu_sharing) | zusätzlich `GET /ready` |
| `POST /api/v1/pipeline-compendium-only` | Linker → LLM-Text | Themenauflösung → 3-Teile-Kompendium | Request unverändert; `compendium_output.markdown` = vollständiger Text, `bibliography` = Baustein 12, `statistics` erweitert; `linker_output.entities` aus den aufgelösten Artikeln (Label, url_de, Extract = Lead) als Kompatibilitäts-Shim; neue optionale Felder `config.compendium.{template_id, collection_id, knowledge_collection_id, subject, extraction, generation, parts}`; ein `text`, der eine nodeId (UUID) ist, wird als `collection_id` interpretiert |
| `POST /api/v1/compendium` | text oder linker_output → LLM | `text` → Themenauflösung; `linker_output` → Entity-Labels als Zusatzthemen | gleiche Response |
| `POST /api/v1/pipeline` | Linker → Text → QA | wie oben, QA nur mit `LLM_ENABLED` | ohne LLM: 503 mit klarem `detail` |
| `POST /api/v1/linker` | LLM-Entities + Wikipedia-API | ZIM-basiert und offline: Titel, Suggestion, Redirects, Lead als Extract, verlinkte Artikel als „generierte" Entities; `MODE=generate` zusätzlich mit LLM, wenn aktiviert | bleibt erhalten und wird verbessert (D14) |
| `POST /api/v1/qa` | LLM | mit LLM wie bisher; ohne LLM regelbasierter Rückfall: Frage-Antwort-Paare aus Glossardefinitionen und belegten Kernsätzen über Frage-Templates („Was versteht man unter …?", „Wann …?"), Bildungsstufen-Verteilung nur mit LLM | bleibt erhalten (D14) |
| `POST /api/v1/utils/split` | lokal | unverändert | — |
| `POST /api/v1/utils/synonyms` | LLM | ZIM-Suggestions/Redirects; LLM optional | — |
| `POST /api/v1/utils/translate` | LLM | mit LLM; ohne LLM 503 mit klarem Hinweis (eine Offline-Übersetzung wäre ein eigenes Modell und ist nicht eingeplant) | bleibt erhalten |

Grundsatz: keine Fehler als Markdown mit HTTP 200. Stattdessen 422 (Validierung), 404 (Thema
nicht auflösbar, mit Alternativen), 503 (ZIM fehlt, LLM erforderlich aber deaktiviert), 504
(Zeitbudget). Teilergebnisse werden als solche gekennzeichnet (`parts_status`). **Stand 2026-09-18:** 422, 404,
429 (`RATE_LIMIT`), 502 und 503 sind umgesetzt; 504 und `parts_status` sind geplant (Phase 6), Teilausfälle
stehen bis dahin als `available: false` im jeweiligen Teil.

### 8.2 Neue Endpunkte (v2)

`POST /api/v2/compendium` — `topic` oder `collection_id`, mindestens eines; bei beiden gewinnt
`topic`, die Sammlung liefert Fach und Kontext.

```json
{
  "topic": "Optik",
  "language": "de",
  "template_id": "sc26",
  "parts": ["world", "curricula", "collection"],
  "collection_id": "a1b2c3…",
  "knowledge_collection_id": null,
  "subject": "Physik",
  "extraction": "rule-based",
  "generation": "rule-based",
  "matcher": null,
  "target_length": 12000,
  "empty_slot_policy": "omit",
  "existing_markdown": null,
  "regenerate_sections": null,
  "write_back": false
}
```

Antwort: `markdown`, `frontmatter`, `resolution` {title, path, alternatives}, `parts`
{world: {sections: [{slot_id, title, text, citations, facets, governance}]}, curricula: {…},
collection: {…}}, `sources`, `audit` {matching, lint, timings, tokens, cache_hit}.

**Stand Phase 3 (2026-09-17):** `parts` kennt `world` und `curricula` (Standard beide; `collection`
folgt in Phase 4), `subject` nimmt WLO-Fach-ID, Vokabular-URI, Label oder Alias. Die Antwort trägt
`curricula` {available, keywords, subject_terms, summary, entries, markdown}; ohne Cache `available: false`
mit Hinweistext. Neu: `GET /api/v2/lehrplan/status`, `GET /api/v2/lehrplan/search?q=&subject=&limit=`,
`POST /api/v2/lehrplan/harvest` (Admin, Trigger-Datei für den Sidecar).

**Stand Phase 4 (2026-09-17):** `collection_id` und `knowledge_collection_id` (UUID) sind umgesetzt; `topic`
ist optional, wenn `collection_id` gesetzt ist. Die Antwort trägt `collection` {available, collection_id, title,
summary, markdown, error} und `audit.knowledge`. Neu: `GET /api/v2/collections/{id}/overview` (422 ungültige ID,
404 unbekannt, 502 Repository nicht erreichbar). `write_back` bleibt außen vor (D11).

**Stand D33 (2026-09-19, vorher Phase 5 mit `mode`):** `extraction` nimmt `rule-based` oder `llm`,
`generation` nimmt `rule-based`, `llm-fast` oder `llm`; fehlt ein Feld, gilt `LLM_EXTRACTION_DEFAULT` bzw.
`LLM_GENERATION_DEFAULT`; das frühere Feld `mode` ergibt 422 mit Hinweis. Die Antwort trägt `extraction` und
`generation` (tatsächlich verwendet), je Baustein `status` (`ki-ausgewählt` für Sätze, die das LLM gewählt hat,
`ki-generiert` für LLM-Text) und bei LLM-Text `llm` {prompt, model, tokens, dropped_sentences,
unsupported_sentences, marked_sentences}, dazu `audit.llm` {note, extraction {requested, used, sections, emptied,
fallbacks, sentences, invalid_numbers, cut_sentences}, generation {requested, used, sections, fallbacks,
dropped_sentences, unsupported_sentences, marked_sentences}} und `audit.llm_tokens` {prompt, completion, total,
calls}. Frontmatter: `extraction` und `generation`, bei Abweichung `extraction_requested` bzw.
`generation_requested`, und `llm` {provider, model, prompts, extraction {sections, emptied, fallbacks},
generation {sections, fallbacks}, note}. Ein LLM-Wunsch ohne konfiguriertes oder verfügbares LLM ist kein Fehler,
sondern ein Kompendium im Regelmodus mit Hinweis. `GET /health` zeigt `components.llm` {enabled, provider, model,
available, check, budget}.

Weitere: `GET /api/v2/templates`, `GET /api/v2/templates/{id}` (geplant: `PUT|DELETE /api/v2/templates/{id}`,
`POST /api/v2/templates/{id}/descriptions` mit LLM, Admin); `GET /api/v2/zim/status`,
`GET /api/v2/zim/catalog`, `POST /api/v2/zim/sync`, `GET /api/v2/zim/progress`,
`DELETE /api/v2/zim/{file}` (Admin); `GET /api/v2/lehrplan/status`,
`POST /api/v2/lehrplan/harvest` (Admin), `GET /api/v2/lehrplan/search?q=&subject=`;
`GET /api/v2/matching/strategies`, `POST /api/v2/matching/compare` (Admin, seit dem Audit vom 2026-09-18);
`GET /api/v2/collections/{id}/overview` (Teil 3 einzeln).

### 8.3 Laufzeitverhalten

Synchron mit Gesamtbudget `REQUEST_TIMEOUT_S` (Standard 120 s). Regelmodus liegt weit darunter;
Die LLM-Schalter parallelisieren ihre Aufrufe (Semaphore). Ein Job-Modell (`202 Accepted` +
`GET /api/v2/jobs/{id}`) ist vorgesehen, aber erst nötig, wenn Konsumenten es brauchen.

Ergebnis-Cache (geplant, nicht umgesetzt): Schlüssel aus aufgelöstem Titel, Template-ID und -Version, Teilen, LLM-Schaltern,
ZIM-UUIDs, Harvest-Datum, `collection_id` + `modifiedAt`; TTL 7 Tage; `force: true` umgeht ihn.

---

## 9. Templates und Redaktion

Template-Schema (JSON Schema, validiert beim Speichern): `id`, `version`, `name`,
`description`, `parts` (Konfiguration für curricula und collection, z. B. Stichwörter, Kappung),
`slots[]` mit den Feldern aus 3.4, `empty_slot_policy`, Verweis auf `facets.yaml`.

**Standard-Template `sc26`** wird aus der Spezifikation in dieses Repo übernommen; das
gleichnamige Template des Prototyps ist nur Vorlage und weicht ab (keine Facetten, Alltag/Hobby
fehlt in 4, Definitionen nicht auf 13 beschränkt, Quellen ohne Zugang/Vertrauensgrad). Zuordnung
Mindmap (16) → SC26 (13): 5 + 6 + 7 → 5 (Zeitbezug als Facette), 14 → 4 (Alltag, Hobby),
Definitionen 3 + 16 → 13, „angrenzende Themen" 2 → 11 (Relation Nachbargebiet),
„gesellschaftliche Erwartungshaltungen" 11 → 4, „Synergien" entfällt, „Material" wird Relation
in 10.

Speicherort: eingebaute Templates im Paket, redaktionelle Kopien und Custom-Templates unter
`STATE_DIR/templates/` (Volume). Jede Änderung erhöht `version`; die Version steht im
Frontmatter jedes erzeugten Textes. Eingebaute Templates sind schreibgeschützt, werden aber
kopierbar („Duplizieren und anpassen").

Redaktioneller Kreislauf: Redaktion passt Template (Kurztexte, Ein-/Ausschlüsse,
Überschriften-Muster, Budgets) an → erzeugt Kompendium → prüft und ändert Text in edu-sharing →
setzt Abschnittsstatus `redaktionell-geprüft` (Marker bleibt im Markdown) → spätere
Regeneration mit `existing_markdown` erneuert nur ungeprüfte Abschnitte.

---

## 10. Container, Deployment, Betrieb

**Image-Profile.** `base`: Python 3.13, libzim, numpy, scikit-learn, model2vec mit eingebautem
Modell (`JanSchachtschabel/m2v-gte-256-edu`, ~300 MB), geschätzt 700–900 MB. `ml`: zusätzlich
torch (CPU, 507 MB), transformers, sentence-transformers, Cross-Encoder und Electra-QA
(rund 1 GB Modelle), geschätzt 2,5–3 GB. Modelle werden im Build ins Image geladen; zur
Laufzeit findet kein Download statt (`HF_HUB_OFFLINE=1`).

**Compose/Kubernetes.** Dienst `api` (1 Replica, 2–4 Uvicorn-Worker), Sidecar `zim-updater`
(gleiches Image, `compendium jobs run --loop`), Volumes `zim` (40 GB, Entscheidung D18) und
`state` (2 GB). Ressourcen: 2 CPU, 2 GB RAM (`base`) bzw. 4 GB (`ml`); libzim nutzt mmap, der
Betriebssystem-Cache profitiert von zusätzlichem RAM.

**Erststart.** `GET /ready` bleibt rot, bis die Pflicht-Archive vorliegen. Mit
`ZIM_BOOTSTRAP_DOWNLOAD=true` lädt der Updater sie (14 GB bei 50 MB/s ≈ 5 min, bei 10 MB/s ≈
25 min). Alternativ werden die Dateien einmalig auf das Volume kopiert.

**CI (GitLab).** Vorhandene Pipeline übernehmen: Ruff, mypy strict, pytest offline (Sample-ZIM
aus eingecheckten HTML-Fixtures, SPARQL-Fixtures, edu-sharing per `respx` gemockt), Image-Build
und Push für `main`, `develop`, Tags; zusätzlicher Job für das `ml`-Tag. Der Kostenbericht-Job
wird auf die neuen Modi umgestellt (Regelmodus 0, Hybridszenarien).

**Beobachtbarkeit.** Strukturierte JSON-Logs mit Request-ID, Phasenzeiten je Anfrage in
`pipeline_statistics`, optional `/metrics` (Prometheus): Latenz, Cache-Trefferquote, LLM-Tokens,
ZIM-Stand, Harvest-Alter. **Stand 2026-09-18:** `/metrics` umgesetzt (D31) mit Latenz, LLM-Tokens,
ZIM-Stand und Harvest-Alter, dazu Alarmregeln; die Cache-Trefferquote fehlt, weil es den Ergebnis-Cache
noch nicht gibt. Request-IDs und JSON-Logs sind offen.

**Sicherheit.** Admin-Endpunkte hinter `ADMIN_TOKEN`; Download-URLs nur von Kiwix-Hosts;
Dateinamen ohne Pfadanteile; edu-sharing-Zugangsdaten als Secret; keine Nutzereingaben in
SPARQL ohne die Validatoren aus `queries.py`.

**Umstellung.** v2-Image parallel deployen, Contract-Tests und einen Vergleichslauf über 20
Themen fahren (alt vs. neu, Länge, Belegquote, Laufzeit), dann Image-Tag umschalten; altes Image
für Rollback behalten. Ablauf in `docs/MIGRATION.md`. `alterCode/` wird nach Abnahme entfernt
(Git-Historie reicht).

---

## 11. Teststrategie

| Ebene | Inhalt | Netz |
|---|---|---|
| Unit | Segmentierung, Satzsplitter, Überschriften-Lexikon, Policy-Layer, Facetten-Annotatoren, Lint, Lehrplan-Matcher (`is_noise`, Stufenleiter), Renderer, Lizenz-Policy | nein |
| Integration | Sample-ZIM (10 Artikel aus eingecheckten HTML-Fixtures, mit `libzim.Creator` in der Test-Session gebaut, Volltextindex an) → komplette Teil-1-Pipeline; Harvest gegen aufgezeichnete SPARQL-Antworten; Teil 3 gegen `respx`-Mocks | nein |
| Contract | alte Request- und Response-Modelle aus `alterCode` als Fixtures; jeder v1-Endpunkt antwortet schemakonform | nein |
| Golden | Markdown-Ausgabe für drei Themen aus dem Sample-ZIM, Änderungen müssen bewusst bestätigt werden | nein |
| Evaluation | Goldstandard (4.5), nächtlich oder manuell, nicht blockierend | ZIM lokal |
| Live-Smoke (manuell, markiert) | echter ZIM-Dump, MEM-Endpoint, edu-sharing Staging, b-api Staging | ja |

---

## 12. Arbeitspakete, Reihenfolge, Aufwand

Aufwände sind Schätzungen in Personentagen (PT), Unsicherheit ±30 %.

| Phase | Inhalt | Abnahmekriterium | PT |
|---|---|---|---|
| 0 Fundament ✅ (2026-09-17) | Repo-Struktur, uv/pyproject, Settings, Logging, Kern aus dem Prototyp portiert, Optik-Keywords entfernt (Wächter-Test), Sample-ZIM-Fixture aus 20 eingecheckten Artikeln, CI-Konfiguration, CLI, minimale API (`/health`, `/ready`, `POST /api/v2/compendium`, Templates, Strategien, ZIM-Status) | erfüllt: Teil 1 im Regelmodus aus Sample-ZIM und aus den echten Dumps; 52 Tests offline grün, Ruff und mypy strict ohne Befund | 2 |
| 1 ZIM-Betrieb ✅ (2026-09-17) | Manifest, Kiwix-OPDS-Katalog, Downloader (Range-Resume, SHA-256 aus dem Metalink, Host-Allowlist), `active.json` mit Watcher und Reload ohne Neustart, Sync-Job (adopt, bootstrap, update, retire, prune) als CLI und `--loop`-Sidecar mit Trigger-Datei, Admin-Endpunkte (Katalog, Fortschritt, Sync-Anstoß, Löschen), Dockerfile `base`, `compose.yml`, CI-Image-Jobs | erfüllt: Realdaten-Sync lädt fehlende Pflichtarchive selbst (Klexikon maxi und nopic; Abbruch bei 25 MB und Resume geprüft); `/ready` wechselt im Test ohne Neustart von 503 auf 200; 103 Tests offline grün, Ruff und mypy strict ohne Befund | 4 |
| 2 Matching und Template ⚠ teilweise (2026-09-17) | Überschriften-Lexikon aus 20.000 Dump-Artikeln erhoben und in Fassung 3 nachgeschärft, Policy kalibriert (Standardbaustein, Vertrauensschwelle, Teilgebiets-Einleitungen, Personen- und Werkartikel ausgenommen, Fragmentfilter), Goldstandard 10 Themen / 603 Chunks, Eval-Harness (CLI und `POST /api/v2/matching/compare`), Matcher-Entscheidung `hybrid_light` + Model2Vec im Image. Facetten-Annotatoren unverändert (Best Effort, D13) | macro-F1 0,43 (Ziel 0,70 nicht erreicht), micro-F1 0,63, nach D28 0,45 / 0,66, Baseline 0,27/0,32; Halluzinations-Slots bei kleinen Bausteinen vorhanden; Redaktionsprüfung steht aus | 7 |
| 3 Teil 2 Lehrpläne ✅ (2026-09-17) | Vokabular und Query-Builder (Closure über Virtuosos transitive Option mit `t_distinct`), SPARQL-Client mit Pacing und Retry, Vollabzug aller 16 Länder in `lehrplan.db` (SQLite, FTS5 trigram, atomarer Tausch), Rollen aus Ontologie plus Override-Tabelle, Fach-Mapping `config/subjects.yaml`, Themen-Matching mit Wortgrenzen-Regel, Rendering mit Markern, `compendium lehrplan status|check|harvest|search`, Endpunkte `/api/v2/lehrplan/*`, Sidecar in `compose.yml` | Harvest 25 min für 2.514 Lehrpläne / 295.184 Knoten (Ziel < 2 h); Äquivalenz zum Prototyp: SN 218/272, RP 200/200, BE 0/0, BY 278 neu; Teil 2 Optik 135 Lehrplanelemente in 14 Lehrplänen aus 3 Ländern (Fach Physik, 110 ms); 204 Tests offline grün, Ruff und mypy strict ohne Befund | 4 |
| 4 Teil 3 Sammlung ✅ (2026-09-17) | edu-sharing-Client (anonym oder Basic, Paginierung, UUID-Validierung, 404/502-Abbildung), TTL-Cache, Überblick mit Untersammlungen in parsebaren Blöcken, Wissens-Sammlung mit Lizenz-Policy und Policy-Regel für Materialbelege, `collection_id` als Eingabe (Thema, Fach, Kontext), `GET /api/v2/collections/{id}/overview`, CLI `compendium collection overview` | Überblick für 5 reale Sammlungen (3,5–6,8 s ungecacht, 6.800–63.000 Zeichen, alle Blöcke parsebar); Wissens-Sammlung Optik: 6 Materialquellen, ein zusätzlicher Beleg (Bildung); 234 Tests offline grün, Ruff und mypy strict ohne Befund | 4 |
| 5 LLM-Schicht ✅ (2026-09-18) | b-api-Client (beide Anfrageformen, Retry, Semaphore, Modellprüfung gegen `/models`), Prompt-Registry mit Versionen, Token-Budget je Kompendium und Tag, Gateway mit Rückfall, `hybrid-fast` und `hybrid-quality` mit Belegprüfung je Satz (Nummer und Deckung), LLM-Router für Zweifelsfälle, `mode` in Anfrage und CLI, LLM-Status in `/health`, Audit und Frontmatter mit tatsächlich verwendetem Modus; seit D33 (2026-09-19) zwei Schalter `extraction` (LLM wählt Sätze) und `generation` statt `mode`, Router entfernt | Live mit `gpt-5.6-luna`: jeder Satz der LLM-Bausteine trägt eine gültige Belegnummer (Endmessung: 4 Läufe, 167 Sätze, 0 ohne gültige Nummer, Belegfolge lückenlos); nicht erreichbare b-api ergibt ein Kompendium im Regelmodus mit `mode_requested` (4,3 s); unabhängiges Review eingearbeitet, offene Punkte geschlossen (D27); Image gebaut und im Container mit zwei Workern geprüft (Hybridlauf, gemeinsamer Tageszähler, Schlüssel nicht im Log); 337 Tests offline grün, Ruff und mypy strict ohne Befund | 3 |
| 6 API-Vertrag | v1-Adapter, Contract-Tests, `collection_id`-Eingabe mit Themen-Normalisierung, Alt-Funktionen erhalten und verbessern (Linker offline, QA-Rückfall, Synonyme über ZIM), v2-Endpunkte, Teil-Regeneration, Fehlerverhalten, OpenAPI-Texte, `MIGRATION.md` | alle Contract-Tests grün; Teil-Regeneration erhält geprüfte Abschnitte; Linker und Synonyme laufen ohne LLM | 4 |
| 7 Betrieb und Umstellung | CI-Jobs, Image `ml` optional, Runbook (Volume, Erststart, Update, Harvest), Vergleichslauf 20 Themen, Cutover | Image im Registry, Runbook geprüft, Umstellung durch Container-Tausch | 3 |
| | **Summe** | | **31** |

Reihenfolge: 0 → 1 → 2 (Gate) → 3 und 4 parallelisierbar → 5 → 6 → 7. Teil 2 und Teil 3 sind
unabhängig von der Matcher-Entscheidung und können vorgezogen werden, wenn das Labeling wartet.

---

## 13. Risiken und offene Fragen

### 13.1 Risiken

| Risiko | Wirkung | Gegenmaßnahme |
|---|---|---|
| Matching-Qualität bleibt unter Erwartung | dünne oder falsch belegte Bausteine | Überschriften-Lexikon als präzise erste Stufe, Goldstandard-Gate vor Festlegung, optionale LLM-Satzauswahl je Baustein (D33), ehrlich leere Slots |
| MEM deckt nur 4–5 Länder ab | Teil 2 lückenhaft | Abdeckung im Text nennen; Harvest fragt alle 16 Landesklassen ab und wächst mit, sobald MEM weitere Länder veröffentlicht |
| SPARQL-Endpoint instabil oder Schema ändert sich | Harvest schlägt fehl | Vollabzug mit Diff, alte Datenbank bleibt aktiv, Regressionstests gegen aufgezeichnete Antworten, Ontologie-Version protokolliert |
| MEM-Datenlizenz unbestätigt (manifest: `unconfirmed`); Wikipedia CC BY-SA färbt auf den Text (von Jan freigegeben, F6) | rechtliche Unsicherheit bei den Lehrplandaten | BY-SA-Attribution im Frontmatter und Baustein 12; MEM-Lizenz vor Produktivbetrieb bei FWU klären, bis dahin nur Labels und Links zitieren |
| Plattenplatz und I/O für 14 GB | langsame Kaltstarts | Profil `compact` als Rückfall, RAM für Page-Cache, Ergebnis-Cache |
| Image mit torch zu groß | Deploy-Zeit, Angriffsfläche | `ml` nur bei nachgewiesenem Mehrwert, sonst `base` |
| Konsumenten hängen an Details des alten Response (Entities) | Bruch beim Tausch | Shim für `linker_output`, Contract-Tests, Vergleichslauf, Rollback-Image |
| libzim-Thread-Sicherheit bei mehreren Workern | seltene Abstürze | Archive je Prozess, Searcher je Anfrage, Lasttest in Phase 1 |
| b-api-Limits und Modell-IDs ändern sich | LLM-Schalter fallen auf den Regelmodus zurück | Modellprüfung beim Start, Backoff, Rückfall auf Regelmodus |
| Zu häufige Abrufe externer Quellen (MEM, Kiwix) belasten Dritte oder führen zu Sperren | Harvest oder Sync scheitern, Teil 2 veraltet | Lehrpläne ausschließlich aus dem lokalen Cache; wöchentliche Zählprüfung, Vollabzug nur bei Änderung oder monatlich, Rate-Limit 1–2 Anfragen/s; ZIM-Katalog monatlich; keinerlei Abrufe zur Inferenzzeit (D16) |

### 13.2 Fragen: Antworten von Jan (2026-09-17) und Reststand

| Frage | Antwort | Konsequenz im Plan |
|---|---|---|
| F1 Konsumenten und Eingabe | Nicht genau bekannt, an der alten API orientieren. In der Regel wird die Sammlung hineingegeben. Eingabe per nodeId gewünscht, dann Metadaten der Sammlung nutzen. | v1-Vertrag bleibt unverändert (`text`); zusätzlich `collection_id` in v1 (`config.compendium`) und v2; eine UUID in `text` wird als Sammlung interpretiert; Thema aus dem Titel, Fach aus `ccm:taxonid`, Kontext aus Beschreibung, Schlagwörtern und `ccm:educationalcontext` (4.2, 6.1, D12). Beim Cutover Zugriffslogs der alten API auswerten, um die Konsumenten sicher zu identifizieren. |
| F2 Rückschreiben | Prüfen, wie es die alte API löst. | Geprüft: die alte API kennt edu-sharing nicht und liefert nur Markdown; der Aufrufer speichert. v2 behält das bei, `write_back` optional (6.4, D11). |
| F3 ZIM-Umfang | Zum Start nur deutsche Wikipedia (ca. 13–14 GB) und Klexikon (ca. 130 MB); weitere Archive abonnierbar. | Profil `standard` als Produktionsstandard, `extended` und beliebige Manifest-Einträge zuschaltbar; Volume 32 GB (4.1, 10, D9). |
| F4 Modus | Standard ohne LLM; schneller Hybridmodus mit wenig LLM; gute Qualität mit LLM. | Drei Modi `rule-based` (Standard), `hybrid-fast`, `hybrid-quality` (4.7, 7, D10), seit D33 zwei Schalter `extraction` und `generation`. Provider und Modell bleiben Konfiguration, Vorschlag in Abschnitt 7. |
| F5 Facetten | Idee war, später gezielt Absätze zu parsen (z. B. zum Bundesland eines Lehrplans); in Teil 1 nicht kritisch. | Marker je Absatz in Teil 2 verbindlich; Facetten in Teil 1 Best Effort mit `FACETS_LEVEL=minimal`; sichtbare Notation abschaltbar (4.6, 5.4, D13). |
| F6 Lizenz | CC BY-SA ist ok. | Attribution im Frontmatter und Baustein 12; MEM-Datenlizenz bleibt Prüfpunkt im Runbook (13.1). |
| F7 Goldstandard | Begriff unklar; selbst entscheiden; Themen über Schulfächer streuen. | Erklärung in 4.5; zehn Themen quer über Physik, Biologie, Chemie, Mathematik, Deutsch, Geschichte, Geographie, Politik, Informatik, Musik; Erstellung durch das Entwicklungsteam (D17). |
| F8 Alt-Funktionen | Erhalten und verbessern, da Bedarf unbekannt. | Keine Deprecation; Linker offline über ZIM, QA mit regelbasiertem Rückfall, Synonyme über ZIM, Übersetzung per LLM (8.1, D14). Phase 6 um einen Tag verlängert. |
| F9 Sprache | Nur deutsche Kompendien. | Englisch gestrichen; der Sprachparameter bleibt im Schema für später (D15). |
| F10 Themen wie „Optik in Klasse 7" | Auf „Optik" normalisieren; Kompendien sind bildungsbereichsübergreifend und bilden Weltwissen ab. | Normalisierungsschritt vor der Titelauflösung; Stufen- und Fachzusätze werden Kontext, nie Filter (4.2, D12). |

**Nachträge von Jan (2026-09-17):** Plattenplatz 40 GB (D18); b-api mit Provider `openai` und
`gpt-5.6-luna` vorkonfigurieren, Provider und Modell konfigurierbar halten (D19).

**Noch offen:** Zielumgebung (Compose oder Kubernetes); Bestätigung der Modell-ID zum
Deploymentzeitpunkt; Identifikation der tatsächlichen Konsumenten über die Zugriffslogs der alten
API.

---

## 14. Entscheidungen (ADR-Kurzform)

- **D1 Neubau statt Überarbeitung**, Kern aus `kompendium-test`, Vertrag aus `alterCode`.
- **D2 Kiwix-ZIM statt Wikipedia-Live-API**; Wikipedia, Klexikon, Wikibooks, Wikiversity über ein
  Abo-Manifest, Updates im Sidecar, atomarer Wechsel.
- **D3 Regelmodus als Standard, LLM optional** über b-api mit Budget und Rückfall.
- **D4 Template-gesteuerte Bausteine**, `sc26` nach Spezifikation als Standard, Facetten
  deklarativ, Einmaligkeitsregeln als Lint, Teil-Regeneration mit Statusmarkern.
- **D5 Lehrplanbezüge offline-first** aus einem MEM-Harvest; Live-SPARQL nur ausdrücklich.
- **D6 ZIM auf Volume, Modelle im Image**, kein Download zur Laufzeit.
- **D7 Python 3.13 mit uv**, Ruff und mypy strict wie bisher; Extras `ml` und `dev`.
- **D8 Matcher-Entscheidung erst nach Evaluation** (Phase 2 ist Gate).
- **D9 Start-Archive: deutsche Wikipedia (`wikipedia_de_all_nopic`) und Klexikon**; weitere
  Kiwix-Archive nur über das Abo-Manifest.
- **D10 Drei Modi:** `rule-based` (Standard, 0 LLM), `hybrid-fast` (2–3 Aufrufe),
  `hybrid-quality` (alle Inhaltsbausteine per LLM; Quellen und Marker deterministisch). Abgelöst durch D33.
- **D11 Kein Rückschreiben durch den Dienst**; der Aufrufer speichert wie bisher, `write_back`
  optional.
- **D12 Eingabe per Thema oder Sammlungs-nodeId** mit Themen-Normalisierung („Optik in Klasse 7"
  → „Optik"); Stufen- und Fachzusätze nur als Kontext, Kompendien bleiben
  bildungsbereichsübergreifend.
- **D13 Facetten:** Marker je Absatz in Teil 2 verbindlich; Teil 1 Best Effort mit
  `FACETS_LEVEL=minimal`, sichtbare Notation abschaltbar.
- **D14 Alt-Funktionen erhalten und verbessern** (Linker, QA, Synonyme, Übersetzung), keine
  Deprecation.
- **D15 Nur Deutsch** in dieser Ausbaustufe.
- **D16 Aktualisierungsrhythmus:** Lehrpläne wöchentlich prüfen, Vollabzug bei Änderung oder
  monatlich; ZIM-Katalog monatlich; nichts davon zur Inferenzzeit.
- **D17 Goldstandard** durch das Entwicklungsteam, zehn Themen über zehn Schulfächer.
- **D18 Volume 40 GB** für das ZIM-Verzeichnis.
- **D19 b-api vorkonfiguriert mit Provider `openai` und Modell `gpt-5.6-luna`**; Provider, Modell
  und Basis-URL bleiben Konfiguration, Wechsel auf `academiccloud` ohne Codeänderung.

---

- **D20 (2026-09-17)** Model2Vec `JanSchachtschabel/m2v-gte-256-edu` ist Teil des Matchers und wird zur
  Bauzeit ins `base`-Image gelegt (kein Hub-Zugriff zur Laufzeit). Begründung: macro-F1 0,43 statt 0,39, Bildung
  0,59 statt 0,38, Kosten 4 s je zehn Themen bei gecachtem Modell.
- **D21 (2026-09-17)** Das Phase-2-Gate (macro-F1 ≥ 0,70) ist nicht erreicht; der Regelmodus geht trotzdem in
  Produktion, weil die großen Bausteine tragen und kleine Bausteine ehrlich leer bleiben. Zweifelsfälle bekommt
  der budgetierte LLM-Router in Phase 5 (seit D33 die optionale LLM-Extraktion); das Extra `ml` (torch, Cross-Encoder) bleibt draußen.
- **D22 (2026-09-17)** Kein SPARQL zur Inferenzzeit, auch nicht als Rückfall: `LEHRPLAN_LIVE_FALLBACK` entfällt,
  ohne Cache trägt Teil 2 einen Hinweistext. Begründung: ein Themenabruf ohne Fachfilter bräuchte Hunderte
  Anfragen je Kompendium, und die Abdeckungsfrage ist mit dem Harvest beantwortet. Ebenso: Closure-Abfragen über Virtuosos transitive Option mit `t_distinct` und `t_max`
  (`MAX_TREE_DEPTH`), nie über `+`/`*` (Speicherabbruch an materialisierten Closures) und nicht über gebundene
  Pfadlängen (vollständig nur bei materialisierter Closure, ab Länge 9 Minuten statt Sekunden); der Harvest warnt,
  wenn ein Baum die Grenze erreicht.
- **D23 (2026-09-17, Jan)** Kompendialtexte dürfen lang sein: Teil 2 enthält alle relevanten Lehrplanelemente
  zum Thema, ohne Längenbudget (Kappung nur optional per `LEHRPLAN_MAX_GROUPS_PER_LAND`). Jeder Block trägt
  Bundesland und Lehrplan-IRI im öffnenden Marker und endet mit `<!-- /f -->`, damit er sich später herausparsen
  lässt. Gemessen: Optik rund 28.000 Zeichen, Photosynthese rund 30.000.
- **D24 (2026-09-17)** Wissens-Sammlung: Nur CC0, PDM, CC BY und CC BY-SA werden wörtlich übernommen
  (`COPYRIGHT_FREE` ist nicht nachnutzbar). Materialabsätze gelten als Beleg für die Bausteine, die
  `wlo_material` in `source_preference` führen (Bildung, Praxis): Score 0,5 plus halbe Rankerstärke. Ohne diese
  Regel lieferte die Sammlung Optik trotz sechs Materialquellen keinen einzigen Beleg, weil Wikipedia-Absätze
  höher rangieren. Das Repository wird zur Inferenzzeit gelesen (Cache 1 h / 7 Tage), ein Ausfall bricht nur
  ab, wenn das Thema von der Sammlung abhängt; sonst trägt Teil 3 einen Hinweis.
- **D25 (2026-09-17, Jan)** Standardmodell ist `gpt-5.6-luna` mit `verbosity=low` und `reasoning_effort=low`;
  beides ist Konfiguration (`LLM_VERBOSITY`, `LLM_REASONING_EFFORT`).
- **D26 (2026-09-18)** „Belegt“ heißt im Hybridmodus: gültige Belegnummer und lexikalische Deckung von mindestens
  20 % der Inhaltswort-Stämme im zitierten Absatz; alles andere wird verworfen und gezählt. Begründung: In der
  ersten Messung trugen Schlussfolgerungen des Modells eine Belegnummer, ohne im Beleg zu stehen (Deckung 0,00
  bis 0,17). Das Frontmatter nennt den tatsächlich verwendeten Modus; ein Hybridwunsch ohne LLM-Beitrag ist
  `rule-based` mit `mode_requested`. Leere Antworten des Modells führen zum extraktiven Baustein, nicht zu einem
  leeren. Das Tagesbudget zählte zunächst je API-Prozess; seit D27 liegt der Zähler in `STATE_DIR`.
- **D27 (2026-09-18)** Offene Punkte der Phase 5 geschlossen: gemeinsamer, neustartfester Tageszähler in
  `STATE_DIR/llm_budget.db` (das Image läuft mit zwei Workern); `REQUEST_TIMEOUT_S` als Frist für die LLM-Arbeit
  statt eines harten Abbruchs der ganzen Anfrage, weil der Regelpfad schnell ist und ein extraktiver Baustein
  besser ist als ein Fehler; `LLM_UNSUPPORTED_SENTENCES=mark` als Wahlmöglichkeit, Standard bleibt `drop` (D26);
  HTML-Kommentare aus Modellantworten entfernen, damit keine Antwort Abschnitts- oder Facettenmarker fälscht.
- **D28 (2026-09-18)** Zuordnung nachgeschärft: Vertrauensschwelle 0,65 statt 0,45 und Abschnitts-Glättung 0,5
  (Absätze unter derselben Überschrift stützen sich gegenseitig). Gemessen: auf dem Gold gleich viele richtige
  gedruckte Absätze (66 zu 67) bei einem Drittel weniger falschen (63 zu 43); ein blinder LLM-Richter bestätigt
  das auf vier fremden Themen (klar passend 46 zu 46, falsch 23 zu 14), drei von zwanzig Bausteinen verlieren
  dabei ihren Volltreffer. Begründung: Ein falscher Absatz in einem Baustein schadet mehr als ein ehrlich leerer
  Baustein (D21). Das Band 0,45 bis 0,65 bleibt in den Hybridmodi Sache des LLM-Routers (`DOUBT_FLOOR`; seit D33
  entfallen, die LLM-Extraktion bietet solche Absätze als Kandidaten an);
  die Materialregel (D24) startet an der konfigurierten Schwelle. Verworfen nach Messung: gelernte Zuordnung,
  Schwellen je Baustein, zentrierte Embeddings, Überschriften-Embedding, Füllregel für leere Bausteine. Der
  Vergleich mit der Testapp steht in `eval/README.md`.
- **D29 (2026-09-18)** Der Code liegt auf GitHub (`janschachtschabel/compendius-textgenerator-sc26`, Branch
  `main`) und steht unter Apache-2.0 (LICENSE von Jan, im Paket als `License-Expression` erklärt). Die
  Laufzeitabhängigkeit libzim steht unter GPL-3.0-or-later; ob die Weitergabe des Images daran etwas ändert,
  klärt edu-sharing vor einer Veröffentlichung. Die Historie des alten Dienstes bleibt im GitLab-Repo.
- **D30 (2026-09-18)** Nach dem Audit (`docs/audits/2026-09-18-audit.md`): Das Rate-Limit des alten Dienstes
  (`RATE_LIMIT`, 60 je Minute und Client) gilt wieder, aber nur für die erzeugenden Endpunkte, damit Proben
  nie gedrosselt werden. Der Matching-Vergleich ist ein Admin-Werkzeug. Eine Anmeldung für die öffentlichen
  Endpunkte gibt es nicht; ob der Dienst nur hinter dem WLO-Gateway steht oder eigene Schlüssel braucht, ist
  offen und Jans Entscheidung. Materialien der Wissens-Sammlung nennen Urheber und Lizenzversion so, wie das
  Repository sie führt; fehlt eine Angabe, wird nichts ergänzt.
- **D31 (2026-09-18)** Überwachung über Prometheus. `GET /metrics` liefert Zustandswerte, die bei jedem Abruf
  aus Registry, Cache und Statusdateien gelesen werden (in jedem Worker gleich bis auf `kompendium_llm_available`,
  den Stand des antwortenden Workers; unbekannte Werte fehlen statt 0), und Laufzeitmetriken, die über
  `PROMETHEUS_MULTIPROC_DIR` über alle Worker summiert werden. Labels nur aus festen Mengen. Die Kompendium-Metriken stammen aus dem Audit, der Service kennt Prometheus nicht. Alarmregeln
  mit promtool-Tests in `monitoring/`, Prometheus als Compose-Profil `monitoring`. Optionaler Schutz über
  `METRICS_TOKEN`, weil Budget- und Archivstand intern sind. Nicht Teil des Repos: Alertmanager und Dashboards.
  Neue Abhängigkeit prometheus-client (offizieller Client des Prometheus-Projekts, Apache-2.0/BSD-2).
- **D32 (2026-09-19)** Nach dem Review der Audit-Behebung (Nachtrag 2 in `docs/audits/2026-09-18-audit.md`):
  Proben, Archivprüfung und `/metrics` laufen in vier eigenen Threads je Worker (`app/api/system_threads.py`),
  damit Kompendium-Anfragen, die alle 40 Standard-Threads halten, weder einen Healthcheck noch einen Scrape
  aufhalten. Öffentliche Statusendpunkte fassen den Stand der Sidecars ohne Fehlertexte zusammen; die Texte
  bleiben in den Statusdateien, in `GET /api/v2/zim/progress` (Admin) und im Log. Ein ZIM-Sync hält die
  Sperrdatei `sync.lock` mit Lebenszeichen und Identität, endet bei einer Ausnahme mit `state: error` und wird
  nach einer Stunde wiederholt, ebenso wenn ein Download unterwegs stehen blieb (Netz, volles Volume); Hash- und
  Größenfehler und Archive, die libzim nicht öffnen kann, warten das normale Intervall ab, damit eine kaputte
  Datei nicht stündlich geladen wird. SIGTERM beendet Sync und Harvest sauber. `KompendiumZimSyncHangs` meldet
  einen laufenden Sync, der sechs Stunden nichts schreibt; ein gescheiterter Status-Abschnitt meldet sich über
  `KompendiumStatusIncomplete`, statt seine Alarme verstummen zu lassen.
  `KompendiumLlmUnavailable` stützt sich auf die über alle Worker summierten Kompendium-Zähler. `mode` (seit D33
  `extraction` und `generation`) und `matcher` betreffen nur Teil 1: ohne ihn ist ein Kompendium regelbasiert; Teil 3 allein braucht keinen
  Artikel in den Archiven; ein Auftrag ohne erzeugbaren Teil ist 422 (nur `collection` ohne `collection_id`)
  oder 503 (Teil nicht eingerichtet). Das Image baut auf dem per Digest gepinnten `python:3.13-slim-bookworm`
  (Dependabot schlägt neue Digests vor), uv gibt es nur im Builder, und der Start `python -m app.serve` löscht
  im Metrik-Verzeichnis nur die Dateien von prometheus_client.
- **D33 (2026-09-19)** LLM-Unterstützung als zwei unabhängige Schalter statt drei Modi (Jan): `extraction`
  (`rule-based` Standard, `llm`) entscheidet, wer die Textstellen eines Bausteins auswählt, `generation`
  (`rule-based` Standard, `llm-fast`, `llm`) entscheidet, wer den Baustein schreibt. `llm-fast` und `llm`
  entsprechen dem Schreiben der früheren Modi `hybrid-fast` und `hybrid-quality`. Die LLM-Extraktion wählt
  Sätze per Nummer (Jan: „Sätze wählen“ statt nur zuordnen oder frei zitieren), damit der Wortlaut der Quelle
  bleibt und nichts erfunden werden kann. Der Router für Zweifelsfälle geht darin auf und ist entfernt; `mode`
  entfällt ohne Übergang, weil v2 noch keine Nutzer hat, und eine Anfrage mit `mode` bekommt 422 mit Hinweis,
  statt stillschweigend regelbasiert zu laufen. Die Metrik `kompendium_compendium_requests_total` zählt nur
  noch, ob ein LLM-Schalter verlangt war und ob das LLM beigetragen hat (`llm_requested`, `llm_used`), damit die
  Alarmregeln für beide Schalter eine Bedingung behalten; `KompendiumHybridFallbacks` heißt jetzt
  `KompendiumLlmFallbacks`. Budget je Anfrage 40.000 statt 20.000 (4.7).

## Anhang A — Beispiel-Skelett der Ausgabe

```markdown
---
kompendium_version: 2
topic: Optik
topic_input: {collection_id: "a1b2c3…", raw_text: "Optik in Klasse 7", normalized: "Optik", subject: Physik, context: ["Klassenstufe 7"]}
topic_resolution: {title: Optik, project: wikipedia, path: Optik, alternatives: ["Optik (Begriffsklärung)"]}
template: {id: sc26, version: 3}
parts: [world, curricula, collection]
generated_at: 2026-09-17T10:12:00+02:00
mode: rule-based
ai_disclosure: "Maschinell erstellter Text (regelbasiert-extraktiv) nach Art. 50 EU AI Act"
review: {status: maschinell-extraktiv, interval_months: 12}
sources_snapshot:
  - {id: wikipedia_de_all_nopic, date: 2026-01-15, uuid: "…"}
  - {id: klexikon_de_all_maxi, date: 2026-08-07, uuid: "…"}
curricula_snapshot: {endpoint: sparql.mem.edufeed.org, harvested_at: 2026-09-14, laender: [BY, SN, RP, BB]}
license: "Teil 1 enthält Inhalte aus Wikipedia und Klexikon (CC BY-SA 4.0); TULLU je Quelle in Baustein 12"
---

# Kompendium: Optik

## Teil 1 · Weltwissen

### 1 · Themendefinition [Bildungsstufe: Sek I]
<!-- kompendium:section id=sc26_1 status=maschinell-extraktiv hash=… -->
Die Optik … [1] …

### 2 · Gliederung & Systematik
…

### 13 · Glossar
| Begriff | Definition | Relation | Beleg |
…

## Teil 2 · Lehrplanbezüge
Strukturierte Lehrplandaten liegen für Bayern, Sachsen, Rheinland-Pfalz und Brandenburg/Berlin vor (Stand 2026-09-14). …

### Sekundarstufe I
#### Sachsen — Physik Oberschule, Klassenstufe 7 [Geltungsebene: Land]
- Lernbereich 2: Optik → „Lichtbrechung an Linsen und Prismen" (Kompetenz, Inhalt) [lp:7053]
…

## Teil 3 · Die Sammlung im Überblick
Die Sammlung „…" bündelt 48 Inhalte in 4 Untersammlungen …
```

## Anhang B — Ausschnitt `sc26.json` (ein Slot vollständig)

```json
{
  "id": "sc26", "version": 1, "name": "SC26 (13 Bausteine)",
  "empty_slot_policy": "omit",
  "parts": {
    "curricula": {"max_entries_per_land": 12, "keywords_from": ["topic", "aliases", "subfields"]},
    "collection": {"max_items": 40}
  },
  "slots": [
    {
      "id": "sc26_5", "slot": "entwicklung_ausblick", "title": "5 · Entwicklung & Ausblick",
      "description": "Alle drei Zeitscheiben in einem Baustein: Epochen, Ereignisse und Meilensteine, aktuelle Themen und Herausforderungen, Trends und Prognosen sowie die Wirkung von Arbeiten auf das Fachgebiet.",
      "inclusions": "Epochen, Meilensteine, Entdeckungen, gegenwärtige Herausforderungen, Trends, Prognosen, Wirkung von Arbeiten",
      "exclusions": "Biografien (nur Anker-Link auf 6), Begriffsdefinitionen (13), Berufsbeschreibungen (7)",
      "sub_items": ["Epochen", "Ereignisse und Meilensteine", "Aktuelle Themen und Herausforderungen", "Trends, Prognosen, erwartete Entwicklungen", "Wirkung von Arbeiten auf das Fachgebiet"],
      "search_queries": ["Geschichte", "Entwicklung", "Meilenstein", "aktuell", "Zukunft", "Trend", "Forschung"],
      "heading_patterns": ["^Geschichte", "^Entwicklung", "^Historisch", "^Forschung", "^Zukunft", "^Ausblick"],
      "facets": {"required": ["Zeitbezug"], "allowed": ["Zeitbezug", "Evidenzgrad", "Haltbarkeit", "Querschnittsthema"], "defaults": {"Evidenzgrad": "belegt"}},
      "budget": {"min_chunks": 1, "max_chunks": 6, "target_chars": 1800, "weight": 1.2},
      "generated": false,
      "source_preference": ["wikipedia", "wikiversity"]
    }
  ]
}
```

---

## Änderungsprotokoll

- **2026-09-17, Fassung v1:** Erstfassung nach Analyse von `alterCode`, `kompendium-test`,
  `mem-schule-optik`, `mem-schule-abruf`, `lehrplan-ontologien` (nur MEM-Import) sowie der
  b-api- und edu-sharing-Skills.
- **2026-09-17, Fassung v2:** Antworten von Jan eingearbeitet: Start-Archive Wikipedia DE +
  Klexikon mit Abo-Manifest für weitere; drei Modi statt zwei; Eingabe per Sammlungs-nodeId mit
  Themen-Normalisierung; kein Rückschreiben durch den Dienst (am alten Code geprüft); Facetten in
  Teil 1 Best Effort, Marker in Teil 2 verbindlich; Alt-Funktionen erhalten und verbessern; nur
  Deutsch; Prüfrhythmus Lehrpläne wöchentlich und ZIM monatlich; Goldstandard erklärt und über
  Schulfächer gestreut. Neue Entscheidungen D9–D17, neue Risikozeile zu externen Abrufen, Phase 6
  auf 4 PT (Summe 31 PT).
- **2026-09-17, Fassung v3:** Volume 40 GB (D18); b-api-Vorkonfiguration `openai` /
  `gpt-5.6-luna` mit umschaltbarem Provider (D19); Phase 0 gestartet.
- **2026-09-17, Fassung v4 (Phase 0 abgeschlossen):** Umsetzung im Repo (`app/`, `tests/`,
  `config/`). Zwei Abweichungen vom Plan, beide zugunsten der Einfachheit: (1) keine
  SQLite-FTS5-Wissensbasis für Teil 1, BM25 rechnet über höchstens 400 Chunks im Speicher (der
  Store kommt erst mit dem Lehrplan-Cache in Phase 3); (2) Fusion der Ranker über global normierte
  Scores statt RRF (Begründung in 4.4). Erkenntnisse aus dem echten Dump: mwoffliner-HTML trägt
  Klassen wie `vector-toc-not-available` am `<html>`-Element, Klassenfilter müssen tokengenau
  arbeiten; Fußnoten und eingebettete `<style>`-Blöcke stehen im Absatztext und werden entfernt;
  Links tragen den dekodierten Titel im `title`-Attribut; MathML-Formeln werden verworfen, Satzreste
  („Fouriertransformierte von .") gefiltert. Policy-Regeln aus dem Lauf: Baustein 1 speist sich
  ausschließlich aus dem Lead des Hauptartikels, dessen ausdrücklichen Definitionsabschnitten und dem
  Lead des Zwillings aus dem zweiten Archiv (Klexikon, einfache Sprache, fester Rang 2); Einleitungen
  und „Allgemeines"-Abschnitte von Nebenartikeln gehören nie dorthin, Leads von Teilgebieten (Titel
  mit Themenstamm) neigen zu Baustein 2;
  nachgeladene Artikel ohne Themenstamm im Titel liefern nur Absätze, die das Thema nennen;
  Ranker-Gewichte BM25 1,0 und Char-TF-IDF 0,7. Ergebnis für „Optik" aus dem 14-GB-Dump: 12 Quellen,
  13 von 13 Bausteinen gefüllt, 34 Belege, 0,7 s Kern-Laufzeit plus Prozessstart.
- **2026-09-17, Fassung v5 (Phase 1 abgeschlossen):** ZIM-Betrieb umgesetzt (`sources/zim/subscriptions.py`,
  `catalog.py`, `downloader.py`, `active.py`, `refresh.py`, `jobs/runner.py`, `jobs/zim_sync.py`,
  `api/v2/zim.py`, `api/admin.py`, `cli_zim.py`, Dockerfile, `compose.yml`, CI-Image-Jobs). Befunde gegen
  den echten Katalog: `library.kiwix.org` leitet auf `opds.library.kiwix.org` um; der OPDS-`name` ist der
  Katalogname ohne Flavour (`klexikon_de_all`), die Abo-ID daher `name_flavour`; der `flavour`-Filter wird
  serverseitig ignoriert; `length` im Katalog ist gerundet, Größe und SHA-256 kommen aus dem Metalink;
  Download-URLs leiten 301/302 auf Spiegel (ftp.fau.de u. a.), die Range-Anfragen mit 206 beantworten.
  Abweichungen vom Plan: die API lädt nie selbst, `POST /api/v2/zim/sync` legt eine Trigger-Datei für den
  Updater ab (ein Schreiber für das Archivverzeichnis); die Allowlist gilt für die Start-URL, die Integrität
  sichert die Prüfsumme; `active.json` wird per `stat`-Signatur (mtime, Größe) überwacht; `ZIM_REQUIRED` ist
  standardmäßig leer und kommt aus dem Manifest. Realdaten-Lauf: Abbruch bei 25 MB, Fortsetzung, Prüfsumme,
  Aktivierung in 17 s inklusive Prozessstart; zweiter Lauf erkennt „aktuell“ in 0,2 s. Noch offen aus 13.1:
  der Lasttest zu libzim mit mehreren Uvicorn-Workern (Phase 7). Testsuite 103 Tests, Ruff und mypy strict grün.
- **2026-09-17, Fassung v6 (Phase 2 teilweise abgeschlossen):** Goldstandard (`eval/gold`, 10 Themen über
  Schulfächer, 603 bewertete Chunks, Regeln in `eval/README.md`), Eval-Harness (`matching/gold.py`, `eval.py`,
  `eval_runner.py`, CLI `compendium eval …`, `POST /api/v2/matching/compare` mit Übereinstimmungsmaß),
  Überschriften-Erhebung aus 20.000 Dump-Artikeln (`scripts/harvest_headings.py`, `eval/headings_top.csv`;
  Top 1000 decken 74 % der Vorkommen, davon 54 % bewusst ausgeschlossen, 14 % klassifiziert), Lexikon
  Fassung 3 mit Präfix-Mustern aus den Verwechslungen. Policy: Standardbaustein (`default_slot` im Template),
  Vertrauensschwelle als Einstellung, Teilgebiets-Einleitungen → Baustein 2, Personen-, Organisations- und
  Werkartikel (`knowledge/entities.py`, aus `synthesis/actors.py` herausgelöst) nie in den Standardbaustein,
  Überschriften generierter Bausteine nicht klassifiziert, Verweiszeilen und Formel-/Bildunterschriften-Fragmente
  verworfen, Listenartikel aus Suchtreffern ausgeschlossen. Der Orchestrator ist in `prepare`, `match` und
  `generate` geteilt, damit Evaluation und Dienst dieselbe Pipeline nutzen. Messwerte: Baseline 0,27/0,32 →
  0,39/0,63 → mit Model2Vec 0,43/0,63 (macro/micro-F1); Ziel 0,70 nicht erreicht (D21). Lehren: die Bewertung muss
  die Klassifikation vor dem Budget messen, Labels per Texthash binden und ein Label nie zweimal vergeben (ein
  Positionsversatz nach einem Filter hatte eine Messung verunreinigt); Schwellen wurden auf demselben Gold
  gewählt. Model2Vec wird zur Bauzeit ins Image gelegt (D20); Image `base` mit Modell 879 MB (ohne 542 MB), Modell lädt im Container offline. Testsuite 143 Tests, Ruff und mypy strict grün.
- **2026-09-17, Fassung v7 (Phase 3 abgeschlossen):** Teil 2 Lehrplanbezüge umgesetzt (`sources/lehrplan/`: `vocab`,
  `sparql`, `queries`, `tree`, `store`, `harvest`, `stufen`, `matcher`, `render`, `subjects`, `part`; `api/v2/lehrplan.py`;
  `cli_lehrplan.py`; `config/subjects.yaml`; Sidecar `lehrplan-updater` in `compose.yml`). Gemessen am Endpunkt: 2.514
  Lehrpläne in vier Ländern, 295.184 Knoten, Harvest 25 Minuten, tiefster Baum 8 Ebenen.
  Lehren: der transitive Pfad `BFO_0000051+` sprengt Virtuosos Speicher an materialisierten Closures (erster Lauf nach
  13 Minuten abgebrochen), gebundene Pfadlängen sind nur bei materialisierter Closure vollständig und ab Länge 9 langsam (151 s),
  Virtuosos transitive Option mit `t_distinct` antwortet in 0,4–4 s; Kopffelder eines ganzen Landes in einer Abfrage
  laufen in ein Timeout, VALUES-Blöcke zu 40 nicht; Bayern hängt Schulfach, Schulart und Jahrgang am Fachlehrplan-Kind,
  weshalb der Prototyp Bayern nicht sah. Äquivalenz zum Prototyp (17 Stichwörter, Physik): SN 218/272,
  RP 200/200, BE 0/0, BY 278 neu. `LEHRPLAN_LIVE_FALLBACK` gestrichen (D22).
  Anfrage: `parts` und `subject`; Antwort: `curricula`. Testsuite 204 Tests, Ruff und mypy strict grün.
  Nachtrag (D23): Teil 2 ohne Kappung, Blöcke mit `<!-- /f -->` abgeschlossen; Antwortzeit von Teil 2 gemessen
  (siehe 5.3).
- **2026-09-17, Fassung v8 (Phase 4 abgeschlossen):** Teil 3 Sammlungsüberblick und Wissens-Sammlung umgesetzt
  (`sources/wlo/`: `models`, `client`, `cache`, `overview`, `knowledge`, `part`; `api/v2/collections.py`;
  `cli_collection.py`; `collection_id`/`knowledge_collection_id`/`parts` in der Anfrage, `collection` und
  `audit.knowledge` in der Antwort; Offline-Fixtures aus dem echten Repository in `tests/fixtures/wlo`). Gemessen:
  Überblick für fünf reale Sammlungen in 3,5–6,8 s ungecacht; Wissens-Sammlung Optik 6 Quellen, ein zusätzlicher
  Beleg. Lehren: die Sammlungs-`childReferencesCount` sind `null`, die Größe steht in `pagination.total`;
  Materialtexte sind oft Arbeitsblatt-Fragmente oder Cookie-Banner, deshalb Zeilenfilter und Lizenz-Allowlist;
  ohne Policy-Regel (D24) bleiben Materialien unbelegt. Testsuite 234 Tests, Ruff und mypy strict grün.
- **2026-09-18, Fassung v9 (Phase 5 abgeschlossen):** LLM-Schicht über die b-api umgesetzt (`llm/`: `client`,
  `prompts`, `budget`, `gateway`, `report`; `synthesis/llm.py`, `synthesis/citations.py`, `synthesis/writer.py` aus `service.py`
  herausgelöst; `matching/router.py`, `Doubt` und `overrides` in der Policy; `mode` in Anfrage und CLI;
  `components.llm` in `/health`). Gemessen mit `gpt-5.6-luna`: `hybrid-fast` 2.300 Tokens und 15 s,
  `hybrid-quality` 10.500 bis 12.400 Tokens und rund 20 s je Kompendium. Lehren: das Modell zitiert auch
  absatzweise („Satz. Satz. [2]“); eine Belegnummer allein beweist nichts, deshalb die Deckungsprüfung (D26);
  Prompt v1 gab die Ausschlussliste des Bausteins wieder, v2 verbietet das; leere Antworten sind ein Urteil über
  unpassende Belege; die b-api beantwortet identische Anfragen aus einem Cache. Ein unabhängiges Review fand
  ein Schlüssel-Leck (httpx zitiert einen Schlüssel mit Zeilenumbruch im Fehlertext, der bis `/health` und ins
  Frontmatter lief), überlebende Mehrfachmarker, ein Budget mit Prüfen-dann-Handeln, ein wirkungsloses
  `target_length` und eine `/health`-Probe, die auf Chat-Timeouts warten konnte; alles behoben und mit Tests
  belegt. Testsuite 317 Tests, Ruff und mypy strict grün.
- **2026-09-18, Fassung v10 (offene Punkte der Phase 5 geschlossen, D27):** gemeinsamer, neustartfester
  Tageszähler in `STATE_DIR/llm_budget.db` (`llm/budget_store.py`), weil das Image mit zwei Workern läuft;
  `REQUEST_TIMEOUT_S` als Frist für die LLM-Arbeit (`llm/deadline.py`, Aufruf-Timeout = Minimum aus `LLM_TIMEOUT_S`
  und Restzeit, Semaphore-Wartezeit eingerechnet); `LLM_UNSUPPORTED_SENTENCES=mark`; HTML-Kommentare aus
  Modellantworten entfernt; Satzgrenzen: klein beginnende Sätze, Auslassungspunkte, weitere Abkürzungen,
  Initialen in Namen. Live gemessen: Frist 5 s ergibt 9 Rückfälle „Zeitbudget“ ohne Aufruf; Markier-Modus an
  „Klimawandel“ 2 Blöcke ohne Nummern; Initialen-Korrektur senkt „ohne Beleg“ von 2 auf 1 bei identischen
  Modellantworten. Container: `/health` nach 5 s, Hybridlauf 3.498 Tokens, Zähler über beide Worker gleich. Das
  zweite unabhängige Review brach am Nutzungslimit ab; seine Prüfaufträge wurden mit gezielten Angriffsskripten
  selbst abgearbeitet (Fund: Nummern-Entfernen setzte `-->` neu zusammen). Testsuite 337 Tests, Ruff und mypy
  strict grün.
- **2026-09-18, Fassung v11 (Matching nachgeschärft, D28):** Vergleich mit den Original-Matchern der Testapp auf
  drei Maßstäben (Gold, Testapp-Metrik, blinder LLM-Richter) und Nachschärfung der Policy: Schwelle 0,65,
  Abschnitts-Glättung 0,5 (`matching/fusion.py: smooth_sections`), `DOUBT_FLOOR` 0,45 für den Router,
  schwellenrelative Materialregel. Gold macro-F1 0,430 → 0,447, micro-F1 0,632 → 0,656, fehlbelegt 212 → 189;
  Richter auf vier fremden Themen: falsche gedruckte Absätze 23 → 14 bei gleich vielen klar passenden.
  Testsuite 340 Tests, Ruff und mypy strict grün.
- **2026-09-18, Fassung v12 (Audit und Behebung, D29, D30):** Audit über den ganzen Code (Bericht in
  `docs/audits/2026-09-18-audit.md`, 71 von 100, bedingt produktionsreif), danach Behebung in einzelnen
  Commits auf GitHub: `parts` ohne `world` wird eingehalten, unbekannte Matcher sind 422 und interne Fehler
  500, ein nicht lesbarer Lehrplan-Cache ergibt den Hinweis statt 500, Downloads sind auf die angekündigte
  Größe begrenzt und nur per https von der Allowlist, der Matching-Vergleich braucht das Admin-Token, keine
  Serverpfade und Repository-Antworten in Fehlermeldungen, Materialien mit Urheber und Lizenzversion, Cache
  räumt Abgelaufenes weg und übersteht Fehler, Templates robust gegen defekte Dateien, LRU für geparste
  Artikel, Korpus-Kappung nach Herkunft, Frist für Materialtexte, Router ohne zweiten Ranker-Lauf,
  `.part`-Bereinigung, `RATE_LIMIT`, Lifespan schließt die HTTP-Clients, Tests ohne Shell-Variablen, Model2Vec
  getestet, Abdeckungsschwelle 90 %, GitHub-Actions-CI mit pip-audit, Image mit fester uv-Version und
  Modell-Revision, `WEB_CONCURRENCY`, Betriebshandbuch `docs/betrieb.md`. Offen: Zugriffsschutz (D30),
  v1-Vertrag und Fehlermodell (Phase 6), Observability (Phase 7), Sperre gegen parallele Sync-Läufe,
  Aufteilung von Policy und Korpusbau. Testsuite 376 Tests, Ruff und mypy strict grün.
- **2026-09-18, Fassung v13 (Überwachung, D31):** Prometheus-Endpunkt `/metrics` mit Zustandswerten (Archive,
  Sync-Läufe, Lehrplan-Cache und Harvest, edu-sharing, LLM und Tagesbudget) und Laufzeitmetriken (Anfragen je
  Routen-Template, Modi, Phasen, Teile, Wissens-Sammlung, LLM-Verbrauch und Belegprüfung), summiert über die
  Worker; zwölf Alarmregeln mit promtool-Tests, Compose-Profil `monitoring`, `METRICS_ENABLED` und `METRICS_TOKEN`.
- **2026-09-19, Fassung v14 (Review der Behebung, D32):** Review von `3e6dd10..c0fe5fd` (0 kritisch, 4 schwer,
  21 klein, 7 geringfügig, dazu 9 ältere Punkte), behoben in 44 Commits (Code-Korrekturen mit zuerst rotem
  Test, Build-Änderungen am gebauten Image geprüft): Unterthemen von Teil 2 vor der Chunk-Kappung, eigene Threads für Proben und `/metrics`, ZIM-Sync mit Endstatus, Sperre,
  Wiederholung und `KompendiumZimSyncHangs`, Templates robust gegen JSON ohne Objekt und verschwindende
  Dateien, öffentliche Status ohne Fehlertexte, Metalink-Host nach Weiterleitungen geprüft und auf 1 MiB
  begrenzt, Start ohne `rm -rf`, Sidecars ohne API-Metriken, Methode als Label begrenzt, Fehlerquote ohne
  Proben, LLM-Alarm aus Zählern, 13 Alarmregeln mit je einem auslösenden und einem ruhigen promtool-Fall und
  Abgleich aller Metriknamen gegen einen echten Abruf (die Angabe „zwölf Alarmregeln mit promtool-Tests“ in
  v13 war zu hoch gegriffen: fünf Regeln hatten keinen Testfall), Lehrplan-Cache mit Zustand, edu-sharing-Cache
  mit Index, Formatversion und Start ohne lesbare Datei, Auflistung in der Frist und ohne Endlosseiten,
  Teile-Semantik (D32), Basis-Image per Digest mit Dependabot, Tests ohne lokale `.env`. Testsuite 449 Tests,
  93,2 % Zweigabdeckung, Ruff und mypy strict grün.
- **2026-09-19, Fassung v15 (Nachprüfung, D32):** drei weitere Prüfer auf `c0fe5fd..0e806ca` (1 schwer, 14 klein,
  10 geringfügig), behoben in 16 Commits: kein Abbruch und keine Download-Schleife bei einem Archiv, das libzim
  nicht öffnen kann, frühe Wiederholung nur für fortsetzbare Fehler, letzter abgeschlossener Lauf bleibt sichtbar,
  SIGTERM in den Schleifen, Sperre mit Identität, `KompendiumStatusIncomplete`, Metalink-Host vor dem Lesen geprüft
  und Grenze 8 MiB, Teile-Prüfung vollständig, Hinweistext für einen unlesbaren Lehrplan-Cache, Dependabot nur für
  Digests und Image-Build in der GitHub-CI (Nachtrag 3 im Audit-Bericht). Testsuite 478 Tests, 93,5 %
  Zweigabdeckung, Ruff und mypy strict grün.
- **2026-09-19, Fassung v16 (LLM-Schalter, D33):** `extraction` und `generation` ersetzen `mode` (4.7, 8.2):
  LLM-Satzauswahl je Baustein (`synthesis/selection.py`, Prompt `passage_selection` v1), Steuerung über alle
  Bausteine (`synthesis/extraction.py`), Kandidaten aus den Scores der Policy (`slot_scores`), Status
  `ki-ausgewählt`, Frontmatter und Audit mit Blöcken je Schalter, CLI `--extraction` und `--generation`,
  Metriken `llm_requested`/`llm_used` und `kompendium_llm_selections_total`, Router entfernt. Gemeinsamer
  budgetierter Aufruf für Auswahl und Synthese (`llm/call.py`). Behoben: leere Antworten von Reasoning-Modellen
  (`finish_reason=length`) durch `REASONING_ALLOWANCE`; Budget je Anfrage 40.000. Live gemessen (Optik): Auswahl
  16.467 Tokens in 11 s, beide Schalter 27.205 Tokens in 18 s. Eval `--llm-extraction` mit getrennten Sichten
  Klassifikation und gedruckt; Goldstandard: LLM 77 richtige und 54 falsche gedruckte Absätze gegen 63 und 44 der
  Regeln (ohne Model2Vec). Testsuite 506 Tests, Ruff und mypy strict grün.
