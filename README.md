# compendious-text-fastapi (v2)

Erzeugt kompendiale Texte zu einem Thema für WirLernenOnline: Weltwissen aus lokalen
Kiwix-ZIM-Archiven (Wikipedia, Klexikon, weitere abonnierbar), Lehrplanbezüge aus einem
MEM-Cache und einen Überblick über die zugehörige Sammlung. Ohne LLM lauffähig; die b-api
kann optional zugeschaltet werden.

Der vollständige Plan mit Architektur, Entscheidungen und Phasen steht in [PLAN.md](PLAN.md).
Der alte Dienst liegt bis zur Abnahme als Referenz unter `alterCode/` und ist nicht Teil des
Builds.

## Stand

- Phase 0 (Fundament): Kern aus dem Prototyp portiert, Teil 1 im Regelmodus, Tests offline.
- Phase 1 (ZIM-Betrieb): Abo-Manifest, Kiwix-Katalog, Downloader mit Resume und SHA-256,
  `active.json` mit Wechsel ohne Neustart, Sync-Job als Sidecar, Dockerfile und Compose.
- Phase 2 (Matching, teilweise): Goldstandard über zehn Schulfach-Themen, Eval-Harness,
  Überschriften-Lexikon aus dem Dump, kalibrierte Policy mit Standardbaustein, Model2Vec im
  Image, Vertrauensschwelle 0,65 mit Abschnitts-Glättung (D28). macro-F1 0,45 und micro-F1 0,66
  (Ziel 0,70 nicht erreicht, siehe `eval/README.md`).
- Phase 3 (Lehrplanbezüge): Vollabzug aller MEM-Lehrpläne in einen SQLite-Cache
  (`lehrplan.db`), wöchentliche Zählprüfung, Themen-Matching mit Wortgrenzen-Regel und
  Fach-Filter, Teil 2 mit Markern je Absatz, Endpunkte und CLI. Zur Inferenzzeit kein
  SPARQL.
- Phase 4 (Sammlung): edu-sharing-Client für Sammlungen, Teil 3 „Die Sammlung im Überblick“
  mit Untersammlungen, Eingabe per `collection_id` (Thema, Fach und Kontext aus der Sammlung),
  Wissens-Sammlung (`knowledge_collection_id`) mit Lizenz-Policy als zusätzliche Quellen für
  Teil 1, Caches, `GET /api/v2/collections/{id}/overview`, CLI `compendium collection overview`.
- Phase 5 (LLM-Schicht): b-api-Client, Prompt-Registry mit Versionen, zwei Schalter `extraction`
  (das LLM wählt die Sätze, D33) und `generation` (`llm-fast`, `llm`), Belegprüfung je Satz,
  Token-Budget, Modellprüfung gegen `/models`, Rückfall auf den Regelmodus.
- Audit vom 2026-09-18 ([Bericht](docs/audits/2026-09-18-audit.md)): Befunde zu API-Vertrag, Fehlerpfaden,
  Attribution, Downloads, Caches, Rate-Limit, Tests, CI und Image behoben; offen sind Zugriffsschutz,
  v1-Vertrag (Phase 6) und Request-IDs mit Fehlererfassung (Phase 7). Stand je Befund im Nachtrag des Berichts.
- Überwachung: Prometheus-Endpunkt `/metrics` mit Zustand und Laufzeitmetriken, getestete Alarmregeln in
  `monitoring/`, Prometheus als Compose-Profil (D31).

## Installation

Für eine Maschine, auf der nur Debian 13 liegt, führt [docs/installation.md](docs/installation.md) von
Docker bis zum ersten Kompendium. Kurzfassung, wenn Docker schon läuft:

```bash
git clone https://github.com/janschachtschabel/compendius-textgenerator-sc26.git && cd compendius-textgenerator-sc26
cp .env.example .env          # läuft unverändert und ohne LLM; ZIM_PROFILE wählt die Archivgröße
docker compose build
docker compose up -d          # der Updater lädt die Archive des Profils (standard: rund 14,1 GB)
curl -fsS http://127.0.0.1:8000/ready
```

`/ready` meldet bis dahin 503 und nennt die Archive, auf die der Dienst noch wartet.

## Entwicklung

```bash
uv sync --all-extras
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy app
```

Die CI (GitHub Actions `.github/workflows/ci.yml`, GitLab `.gitlab-ci.yml`) führt dieselben Prüfungen aus,
dazu die Tests mit Zweigabdeckung (`uv run pytest --cov`, Schwelle 90 %) und `pip-audit` über die gelockten
Laufzeitpakete. Tests sehen keine Variablen aus der Shell (`tests/conftest.py`), auch nicht `B_API_KEY`.

Ein Kompendium von der Kommandozeile (Teil 1 und, wenn der Lehrplan-Cache vorliegt, Teil 2;
Regelmodus):

```bash
uv run compendium generate --topic Optik --zim /pfad/wikipedia_de_all_nopic_2026-01.zim --zim /pfad/klexikon_de_all_maxi_2026-08.zim --out optik.md
```

API lokal:

```bash
uv run uvicorn app.main:create_app --factory --reload
```

Konfiguration über Umgebungsvariablen oder `.env` (Vorlage `.env.example`, Felder in
`app/settings.py`).

## Matching bewerten

Der Goldstandard in `eval/gold` sagt für Chunks echter Korpora, in welchen Baustein sie gehören.
`compendium eval export` schreibt Chunks eines Themas zum Labeln, `eval import` macht aus der
geprüften CSV eine Gold-Datei, `eval run` misst alle Strategien (Klassifikation vor dem Budget,
je Baustein Präzision, Recall, F1). Details, Labelregeln und Stand in [eval/README.md](eval/README.md).
Der Embedding-Ranker läuft, wenn `MODEL2VEC_PATH` gesetzt ist (im Image `/models/m2v`; lokal die
Hugging-Face-ID mit `HF_HUB_OFFLINE=1` und `uv run --extra embeddings`).

## ZIM-Archive betreiben

Welche Archive ein Profil braucht, steht in `config/zim_subscriptions.yaml` (`compact` für
Entwicklung und CI, `standard` für die Produktion, `extended` mit Wikibooks und Wikiversity).
Die Archiv-ID ist Katalogname plus Flavour, zum Beispiel `wikipedia_de_all_nopic`.

Der Sync-Job pflegt das Verzeichnis `ZIM_DIR`: Er übernimmt vorhandene Dateien, lädt
neue Dumps aus dem Kiwix-Katalog (Range-Resume in eine `.part`-Datei, SHA-256 aus dem
Metalink), schaltet `active.json` atomar um und löscht abgelöste Dateien nach
`ZIM_RETENTION_HOURS`. Die API-Prozesse prüfen `active.json` bei jeder Anfrage und öffnen
neue Archive ohne Neustart. Zur Inferenzzeit wird nichts heruntergeladen.

```bash
uv run compendium zim status                       # aktive Archive, fehlende Pflichtarchive, letzter Sync
uv run compendium zim catalog                      # neueste Dumps der abonnierten Archive im Kiwix-Katalog
uv run compendium zim sync --download-missing      # einmal abgleichen, fehlende Pflichtarchive laden
uv run compendium zim sync --loop                  # Updater-Sidecar: monatlich (ZIM_SYNC_INTERVAL) plus Trigger-Datei
uv run compendium zim sync --offline               # nur lokale Dateien übernehmen, kein Katalogzugriff
```

Erststart: Mit `ZIM_BOOTSTRAP_DOWNLOAD=true` lädt der Updater die Pflichtarchive des
Profils selbst (Profil `standard` rund 14,1 GB). Alternativ werden die Dateien einmalig in
`ZIM_DIR` kopiert; der nächste Sync übernimmt sie. `GET /ready` antwortet erst mit 200, wenn
alle Pflichtarchive vorliegen.

Container: `compose.yml` startet `api`, `zim-updater` und `lehrplan-updater` aus demselben
Image mit den Volumes `zim` (geplant 40 GB, in Kubernetes ein PVC mit 40Gi) und `state`.

```bash
docker compose up --build
```

## Lehrpläne betreiben (Teil 2)

Einzige Quelle ist der MEM-Triplestore der FWU (`LEHRPLAN_ENDPOINT`). Der Harvest-Job zieht
alle Lehrpläne aller Bundesländer, die MEM veröffentlicht (Stand 2026-09-17: Bayern, Sachsen,
Rheinland-Pfalz, Berlin), samt Knoten, Rollen und Stufenangaben in `STATE_DIR/lehrplan.db`
(SQLite mit FTS5-Trigram-Index) und tauscht die Datei atomar aus; ein Vollabzug dauert rund 25
Minuten (2.514 Lehrpläne, 295.000 Knoten, 278 MB). Die API liest nur den Cache; ohne Cache enthält
Teil 2 einen Hinweistext. Das Fach kommt aus der Anfrage (`subject`) oder
aus einem Präfix wie „Physik: Optik“ und wird über `config/subjects.yaml` auf MEM-Schulfächer
abgebildet; ohne Fach wird über alle Fächer gesucht. Teil 2 enthält alle Treffer (Kompendialtexte
dürfen lang sein); jede Gruppe steht zwischen `<!-- f: Bundesland=…; Bildungsstufe=…;
Klassenstufe=…; Schulart=…; Lehrplan=<IRI> -->` und `<!-- /f -->` und lässt sich so
herausparsen. `LEHRPLAN_MAX_GROUPS_PER_LAND` kappt optional.

```bash
uv run compendium lehrplan status          # Cache-Stand, Lehrpläne je Land, letzter Harvest-Lauf
uv run compendium lehrplan check           # MEM-Zählung je Land mit dem letzten Harvest vergleichen
uv run compendium lehrplan harvest         # Vollabzug, wenn fällig (Änderung oder älter als LEHRPLAN_HARVEST_MAX_AGE)
uv run compendium lehrplan harvest --loop  # Sidecar: wöchentlich prüfen (LEHRPLAN_CHECK_INTERVAL) plus Trigger-Datei
uv run compendium lehrplan search --q Optik --subject Physik
```

## Sammlungen (Teil 3 und Wissens-Sammlung)

`collection_id` (nodeId einer WLO-Sammlung) liefert Thema, Fach und Bildungsstufe für Teil 1
und 2 sowie Teil 3: Zweck, Kennzahlen (Materialtypen, Bildungsstufen, Fächer, Lizenzen), alle
Inhalte als kompakte Liste und die Untersammlungen eine Ebene tief, jeder Block zwischen
`<!-- f: Sammlung=<id>; Fach=…; Bildungsstufe=… -->` und `<!-- /f -->`. Fehlende Beschreibungen
bleiben sichtbar leer. `knowledge_collection_id` nimmt die Materialien einer Sammlung als Quellen
in Teil 1 auf, wörtlich nur unter CC0, PDM, CC BY oder CC BY-SA (Bausteine Bildung und Praxis
bevorzugen sie). Die Quellenliste nennt je Material Urheber und Lizenz mit der Version, die das
Repository führt (`ccm:commonlicense_cc_version`; ohne Angabe keine Version, ohne Urheber „nicht
angegeben“), der Lizenzhinweis die tatsächlich verwendeten Lizenzen.

Welches Repository gilt, entscheidet `EDU_SHARING_BASE_URL` (anonym oder Basic-Auth); der Standard ist
Staging (`repository.staging.openeduhub.net`), die Produktion (`redaktion.openeduhub.net`) steht
auskommentiert daneben. Die b-api folgt dem Repository: `B_API_BASE_URL` leer lassen heißt
`b-api.staging` zum Staging-Repository und `b-api.prod` zur Produktion. Ein eigener Wert wird befolgt,
und wenn er nicht zum Repository passt, sagt es das Log beim Start. `GET /health` nennt beide Hosts
(`components.edu_sharing.repository`, `components.llm.host`), damit sichtbar ist, womit der Dienst
gerade spricht. Das Repository wird zur Inferenzzeit gelesen, Sammlungen 1 h und
Materialtexte 7 Tage gecacht (`STATE_DIR/wlo_cache.db`, abgelaufene Einträge räumt jeder Schreibvorgang
weg). Materialtexte, die bis zum Ablauf von `REQUEST_TIMEOUT_S` nicht geholt sind, bleiben draußen und
stehen als `timed_out` im Audit.

```bash
uv run compendium collection overview 9e7ae956-e9df-430f-bace-f3db4b910013 --out optik_teil3.md
uv run compendium generate --collection-id 9e7ae956-e9df-430f-bace-f3db4b910013 --knowledge-collection-id 9e7ae956-e9df-430f-bace-f3db4b910013 --zim … --out optik.md
```

## LLM-Schicht (optional)

Standard ist der Regelmodus ohne LLM. Mit `LLM_ENABLED=true` und `B_API_KEY` lassen sich zwei Schritte von
Teil 1 unabhängig voneinander an das LLM geben (D33): je Anfrage über `extraction` und `generation`, global
über `LLM_EXTRACTION_DEFAULT` und `LLM_GENERATION_DEFAULT`. Ein dritter Schalter, `enrichment`, entscheidet,
ob das schreibende Modell über die Quellen hinausgehen darf.

| Schalter | Wert | Was das LLM tut |
|---|---|---|
| `extraction` | `rule-based` (Standard) | nichts: die Policy ordnet ganze Absätze zu, der Baustein nimmt ihre ersten Sätze |
| | `llm` | wählt je Baustein die passenden Sätze unter den Kandidaten (Absätze der Policy, dann die nächstbesten nach ihrem Score, `LLM_EXTRACTION_CANDIDATES`, Standard 8); es nennt nur Satznummern, der Wortlaut bleibt der der Quelle |
| `generation` | `rule-based` (Standard) | nichts: der Baustein besteht aus den gewählten Sätzen, je Absatz mit Belegnummer |
| | `llm-fast` | formuliert die Bausteine aus `LLM_FAST_SECTIONS` (Standard 1 und 11) aus ihren Belegen |
| | `llm` | formuliert jeden Inhaltsbaustein aus seinen Belegen |
| `enrichment` | `sources-only` (Standard) | nichts: jeder Satz muss aus den Belegen gedeckt sein, alles andere wird verworfen |
| | `model-knowledge` | ergänzt gesichertes eigenes Fachwissen; solche Sätze tragen keine Belegnummer und werden im Text gekennzeichnet (braucht `generation` `llm` oder `llm-fast`) |

Gemessen für „Optik“ mit `gpt-5.6-luna` am 2026-09-19: `extraction=llm` 10 Aufrufe, rund 16.500 Tokens und 11 s;
beide Schalter auf `llm` 20 Aufrufe, rund 27.200 Tokens und 18 s. Das Schreiben allein (Messung vom 2026-09-18,
vier Themen): `llm-fast` 2 bis 3 Aufrufe und 2.300 bis 4.000 Tokens, `llm` 8 bis 10 Aufrufe und 10.500 bis
14.500 Tokens.

Mit `extraction=llm` tragen die Bausteine den Status `ki-ausgewählt`, die KI-Kennzeichnung im Frontmatter nennt
wörtliche Quellenauszüge mit KI-gestützter Auswahl. Passt kein angebotener Absatz, bleibt der Baustein leer
(`audit.llm.extraction.emptied`); scheitert die Auswahl (b-api, Budget, Zeit, unlesbare Antwort), behält der
Baustein die Absätze der Policy (`audit.llm.extraction.fallbacks`).

Schreibt das LLM, sieht es nur den nummerierten Evidenzblock des Bausteins, mit `extraction=llm` nur die
ausgewählten Sätze. Nach dem Aufruf bleibt ein Satz nur
stehen, wenn er eine gültige Belegnummer trägt und seine Inhaltswörter im zitierten Absatz vorkommen;
alles andere wird verworfen und im Audit gezählt (`dropped_sentences`, `unsupported_sentences`). Mit
`LLM_UNSUPPORTED_SENTENCES=mark` bleiben solche Sätze ohne Nummer stehen, eingefasst in
`<!-- f: Evidenzgrad=Schlussfolgerung -->` und `<!-- /f -->` (`marked_sentences`). HTML-Kommentare in der
Modellantwort werden entfernt, damit sie keine Marker des Dokuments fälschen kann.

Mit `enrichment: model-knowledge` gilt dieselbe Prüfung, aber nicht gedeckte Sätze werden nicht verworfen,
sondern als `<!-- f: Evidenzgrad=Modellwissen -->` … `<!-- /f -->` gekennzeichnet. Es schreibt dann ein anderer
Prompt (`section_enrichment`, im Frontmatter unter `llm.prompts` nachlesbar), der eigenes Fachwissen erlaubt,
aber ohne Belegnummer verlangt und höchstens jeden dritten Satz. Ein Baustein braucht weiterhin mindestens
einen belegten Satz, sonst bleibt er regelbasiert. Die Antwort sagt es an drei Stellen: `enrichment` im
Kompendium und im Frontmatter, `frontmatter.llm.enrichment` mit Satzzahl und Hinweis, `audit.llm.generation`
mit `enrichment` und `marked_sentences`, je Baustein `sections[].llm.marked_sentences`. Die KI-Kennzeichnung
richtet sich nach dem Text, nicht nach der Erlaubnis: Nur wenn wirklich etwas ergänzt wurde, nennt sie
„ergänzt um Modellwissen ohne Quellenbeleg“ — bleibt das Modell in den Quellen, steht dort die gewohnte
Kennzeichnung und der erklärende Hinweis im Frontmatter entfällt. Ohne schreibendes LLM
(`generation: rule-based` oder b-api nicht verfügbar) meldet die Antwort `sources-only` — der Schalter kann
dann nichts bewirken.
Quellen, Belegtabelle, Glossar, Akteure und alle Marker bleiben deterministisch. LLM-Bausteine tragen
den Status `ki-generiert`, Prompt-ID und Version stehen im Frontmatter (`llm.prompts`).

Fällt die b-api aus, fehlt das Modell in `/models`, ist das Budget erschöpft oder liefert das Modell
nichts Brauchbares, bleibt der Baustein regelbasiert. Das Frontmatter nennt die tatsächlich verwendeten
Schalter (`extraction`, `generation`) und, wenn sie abweichen, die angeforderten (`extraction_requested`,
`generation_requested`); `audit.llm` nennt je Schalter Bausteine und Gründe, `audit.llm_tokens` den
Verbrauch. `GET /health` zeigt unter `components.llm`
Verfügbarkeit, Modellprüfung und Tagesverbrauch. Standard ist `gpt-5.6-luna` beim Provider `openai`
mit `reasoning_effort=low` und `verbosity=low`; ein Wechsel auf `academiccloud` braucht nur
`B_API_PROVIDER` und `B_API_MODEL`.

Betrieb: Die Modellprüfung ist ein einzelner Versuch mit 10 s Timeout (Start, danach höchstens alle zehn
Minuten, solange das Modell fehlt); `/health` ruft die b-api nie selbst. Nach einem Verbindungsfehler oder
Timeout setzt ein Schutzschalter die b-api 60 s aus, Anfragen laufen dann sofort im Regelmodus. Jeder Aufruf
reserviert sein Token-Budget vorab (`LLM_MAX_TOKENS_PER_REQUEST` je Kompendium, `LLM_DAILY_TOKEN_BUDGET` je Tag);
der Tageszähler liegt in `STATE_DIR/llm_budget.db`, gilt für alle Worker gemeinsam und übersteht Neustarts.
`REQUEST_TIMEOUT_S` begrenzt die LLM-Arbeit und das Lesen der Materialtexte einer Anfrage: jeder Aufruf
bekommt höchstens die Restzeit, bei weniger als 5 s Rest entsteht der Baustein extraktiv. Der Schlüssel erscheint in keiner Meldung, Fehlerkörper
der b-api nur im Log.

```bash
LLM_ENABLED=true uv run compendium generate --topic Optik --extraction llm --generation llm-fast --zim … --out optik.md
```

## Endpunkte

| Endpunkt | Zweck |
|---|---|
| `GET /metrics` | Prometheus-Metriken (siehe „Überwachung“); optional nur mit `METRICS_TOKEN` |
| Alle Antworten | tragen `X-Request-ID` (die des Aufrufers oder eine neue); jede Logzeile der Anfrage nennt sie, ein unerwarteter Fehler antwortet mit 500, `detail` und `request_id` |
| `GET /health`, `GET /ready` | Prozess lebt (mit LLM-Status unter `components.llm`); Pflichtarchive vorhanden (sonst 503) |
| `POST /api/v2/compendium` | Kompendium zu `topic` oder `collection_id`; `parts` wählt `world`, `curricula`, `collection` (ohne `world` entfallen Teil 1, seine Quellen, das Matching und die Wissens-Sammlung; `extraction`, `generation` und `matcher` betreffen nur Teil 1, ohne ihn ist das Kompendium regelbasiert und `audit.matcher` leer); `subject`, `knowledge_collection_id`; `extraction` wählt `rule-based` oder `llm`, `generation` `rule-based`, `llm-fast` oder `llm`, `enrichment` `sources-only` oder `model-knowledge`; das frühere Feld `mode`: 422; unbekannte Strategie in `matcher`: 422; nur `collection` ohne `collection_id`: 422 (mit ihr braucht Teil 3 keinen Artikel in den Archiven); kein angefragter Teil erzeugbar (etwa Teil 3 ohne `EDU_SHARING_BASE_URL`): 503; `template_id` wählt ein Template (Standard aus den Einstellungen), `max_articles` begrenzt den Korpus (Standard `CORPUS_MAX_ARTICLES`, Thema und Zwilling sind immer dabei), `empty_slot_policy` und `facets_visible` überschreiben Template bzw. `FACETS_VISIBLE`, `language` kennt heute nur `de` (sonst 422); zur teilweisen Neuerzeugung mit `existing_markdown` und `regenerate_sections` siehe unten |
| `POST /api/v2/knowledge` | Wissenstexte zu `topic`, ohne Template und Synthese: die Artikel des Korpus mit ihren Abschnitten. `archives` fragt gezielt einzelne Archive (unbekannte ID: 404), `max_articles` begrenzt die zusätzlichen Artikel (Thema und Zwilling sind immer dabei), `max_chars` deckelt den Text über alle Artikel und setzt `truncated`; Thema nicht gefunden: 404 mit `resolution` |
| `POST /api/v2/entities` | Entitäten in einem Text, in zwei Schichten: `methods` wählt `ner` (spaCy-Modell, braucht keine Archive) und `dictionary` (Begriffe, die einen Artikel haben); die Antwort nennt unter `methods`, welche Wege wirklich liefen, und je Entität `source`, `kind`, `linked` und den Artikel mit seinem Lead. `link: false` lässt das Nachschlagen weg, `archives` grenzt ein (unbekannte ID: 404); fällt beides aus — kein Modell und keine Archive —: 503. Steht hinter einem Begriff des Wörterbuchs nur eine Begriffsklärungsseite, entfällt er: die Methode verspricht Begriffe **mit** Artikel. Das gilt nicht für `ner` und nicht bei `link: false` — dort sagt `note`, dass ungeprüft geliefert wurde. `max_entities` greift vor dieser Prüfung, es können also weniger zurückkommen |
| `POST /api/v2/qa` | Frage-Antwort-Paare zu `text` oder `topic`. **`text`** ist der Text, aus dem die Paare gemacht werden — etwa das Markdown eines Kompendiums, das du schon hast. **`topic`** erzeugt erst Teil 1 des Kompendiums zu diesem Thema und fragt dessen Bausteine ab; beide Schritte also in einem Aufruf, zum Preis einer Erzeugung (404 mit `resolution`, wenn es das Thema nicht gibt, 503 wenn Teil 1 nicht erzeugbar ist). `method` wählt `rule-based` (Fragevorlagen über die Sätze, braucht nichts, Standard), `models` (zwei kleine deutsche Modelle im Image: ein Generator schreibt die Frage zu einer Nominalphrase, ein extraktives Modell markiert die antwortende Stelle — rund 2,2 s je Paar auf CPU, die Modelle laden bei der ersten Anfrage) oder `llm` (die b-api schreibt sie); fehlen die Modelle, die b-api oder eine verwertbare Antwort, fällt es auf `rule-based` zurück und `note` sagt warum. `count` und `max_answer_length` begrenzen. Die Fragevorlagen prüfen mit dem spaCy-Modell, ob der Betreff wirklich ein Begriff ist — Deutsch schreibt am Satzanfang groß, sonst entstünde „Was versteht man unter Daneben?“. Fehlt das Modell, entfällt die Prüfung und `note` sagt es |
| `GET /api/v2/collections/{id}/overview` | Teil 3 für eine Sammlung (404 unbekannt, 502 Repository nicht erreichbar); hält sich an `REQUEST_TIMEOUT_S`, danach `summary.incomplete` und ein Hinweis im Text |
| `GET /api/v2/templates`, `/templates/{id}` | Templates (Bausteine) |
| `PUT /api/v2/templates/{id}` (Admin) | eigenes Template anlegen oder ersetzen; die Version zählt bei jedem Schreiben hoch. Die id im Pfad und im Body müssen übereinstimmen (sonst 422), eingebaute Templates sind schreibgeschützt (409). Den Rumpf beschreibt `/docs` Feld für Feld: `slots` mit `title`, `inclusions`, `exclusions`, `sub_items`, `search_queries`, `facets`, `budget` und `generator`. `default_slot` nennt den Baustein, in den thematische Passagen ohne sichere Zuordnung wandern; `version` und `builtin` setzt der Dienst selbst |
| `DELETE /api/v2/templates/{id}` (Admin) | eigenes Template löschen (204); eingebaute: 409, unbekannte: 404 |
| `GET /api/v2/matching/strategies` | Matching-Strategien |
| `POST /api/v2/matching/compare` (Admin) | Strategien auf einem Thema vergleichen, mit Gold-Metriken, wenn `EVAL_GOLD_DIR` eine Gold-Datei hat; `matchers` wählt die Strategien aus `GET /api/v2/matching/strategies` (unbekannte: 422), `template_id` und `target_length` wirken wie beim Kompendium |
| `GET /api/v2/lehrplan/status` | Lehrplan-Cache: Stand, Abdeckung, Lehrpläne je Land, letzter Harvest (ob er scheiterte, ohne Fehlertext) |
| `GET /api/v2/lehrplan/search?q=&subject=&limit=` | Lehrplanelemente zu einem Stichwort aus dem Cache; `limit` begrenzt die Treffer |
| `POST /api/v2/lehrplan/harvest` (Admin) | Harvest-Prüfung anstoßen (Trigger-Datei für den Sidecar) |
| `GET /api/v2/zim/status` | Archive, Pflichtarchive, `active.json`, letzter Sync (Zahl der Fehler; die Texte nennt `/progress`) |
| `GET /api/v2/zim/catalog` (Admin) | Kiwix-Katalog mit Markierung abonniert/installiert |
| `GET /api/v2/zim/progress` (Admin) | Stand des Sync-Jobs samt laufendem Download |
| `POST /api/v2/zim/sync` (Admin) | Sync anstoßen (Trigger-Datei für den Updater) |
| `DELETE /api/v2/zim/{datei}` (Admin) | nicht aktive Archivdatei samt `.part` löschen |

**Teilweise neu erzeugen.** `existing_markdown` nimmt ein früheres Kompendium entgegen. Bausteine, die dort
als `redaktionell-geprüft` markiert sind, bleiben wortgleich stehen; mit `regenerate_sections` werden nur die
genannten Bausteine neu gemacht und alle übrigen behalten. Ein behaltener Baustein behält seine Belegnummern,
sein Text wird also gar nicht angefasst — die neuen Bausteine werden hinter der höchsten behaltenen Nummer
weitergezählt, und der Quellen-Baustein führt beide auf.

Admin-Endpunkte erwarten den Header `X-Admin-Token` mit dem Wert von `ADMIN_TOKEN`; ohne
gesetztes Token sind sie deaktiviert. Dieselben Schreibwege gibt es in der CLI:
`compendium templates save datei.json` und `compendium templates delete id`; `compendium templates`
ohne Verb listet wie bisher.

`POST /api/v2/compendium`, `GET /api/v2/collections/{id}/overview` und `GET /api/v2/lehrplan/search`
sind je Client auf `RATE_LIMIT` Anfragen pro Minute begrenzt (Standard 60 wie im alten Dienst, je Worker,
0 schaltet ab); darüber antworten sie 429 mit `Retry-After`. Hinter einem Reverse-Proxy sieht uvicorn die
Client-Adresse nur mit `FORWARDED_ALLOW_IPS`. Eine Anmeldung für die öffentlichen Endpunkte gibt es nicht;
der Dienst gehört hinter ein Gateway. `API_DOCS_ENABLED=false` schaltet `/docs`, `/redoc` und
`/openapi.json` ab. `GET /health` meldet `zim`, `lehrplan_cache`, `edu_sharing` und `llm`; Fehlermeldungen
nennen keine Serverpfade und keine Antworttexte des Repositorys (die stehen im Log).

Betrieb, Störungen und Wiederherstellung: [docs/betrieb.md](docs/betrieb.md).

## Überwachung (Prometheus)

`GET /metrics` liefert Metriken im Prometheus-Format (Textformat 0.0.4 oder OpenMetrics, je nach `Accept`).
Zustandswerte liest der Endpunkt bei jedem Abruf aus Registry, Cache und den Statusdateien der Sidecars; sie
sind in jedem Worker gleich, bis auf `kompendium_llm_available`: Das ist der Stand des Workers, der den Abruf
beantwortet (letzte Modellprüfung, Schutzschalter), und er sieht Antworten mit 401 oder 5xx nicht. Der Alarm
`KompendiumLlmUnavailable` stützt sich deshalb auf die über alle Worker summierten Kompendium-Zähler. Unbekannte
Werte (noch kein Sync, kein Cache) fehlen, statt als 0 zu erscheinen.
Laufzeitmetriken summiert der Endpunkt über alle Worker: Im Image legt jeder Worker seine Werte in
`PROMETHEUS_MULTIPROC_DIR` ab (`/tmp/prometheus`; der Start löscht dort nur die Metrik-Dateien eines früheren
Laufs; die Variable setzt nur der API-Befehl `python -m app.serve`, die Sidecars laden die Metriken nicht). Labels kommen nur aus festen Mengen
(Routen-Templates, Schalter, Phasen), nie aus Eingaben. Die Kompendium-Metriken stammen aus dem Audit jeder Antwort.

| Metrik | Bedeutung |
|---|---|
| `kompendium_zim_ready`, `kompendium_zim_archives`, `kompendium_zim_required_missing`, `kompendium_zim_archive_articles{archive}` | Archive, wie `/ready` sie sieht |
| `kompendium_zim_sync_running`, `kompendium_zim_sync_status_updated_timestamp_seconds`, `kompendium_zim_sync_last_run_timestamp_seconds`, `kompendium_zim_sync_last_run_errors` | Updater-Sidecar (`sync_status.json`); ein abgebrochener Lauf endet mit `state: error`; während eines Laufs gelten Ende und Fehler des letzten abgeschlossenen |
| `kompendium_lehrplan_cache_available`, `kompendium_lehrplan_cache_harvested_timestamp_seconds`, `kompendium_lehrplan_harvest_failed`, `kompendium_lehrplan_harvest_last_run_timestamp_seconds` | Lehrplan-Cache und Harvest-Sidecar |
| `kompendium_llm_enabled`, `kompendium_llm_available`, `kompendium_llm_tokens_used_today`, `kompendium_llm_daily_budget_tokens` | b-api und Tagesbudget; `_available` ist der Stand des antwortenden Workers |
| `kompendium_edu_sharing_enabled`, `kompendium_build_info{version}` | Konfiguration und Version |
| `kompendium_status_section_failed{section}` | 1, wenn ein Abschnitt dieser Zustandswerte nicht gelesen werden konnte (seine Werte fehlen dann) |
| `kompendium_http_requests_total{method,route,status}`, `kompendium_http_request_duration_seconds{method,route}` | Anfragen je Routen-Template (unbekannte Pfade als `unmatched`) |
| `kompendium_compendium_requests_total{llm_requested,llm_used}`, `kompendium_compendium_phase_seconds{phase}` | Kompendien, Rückfall auf den Regelmodus (ein LLM-Schalter verlangt, nichts vom LLM), Dauer der Phasen |
| `kompendium_parts_total{part,available}`, `kompendium_knowledge_materials_total{outcome}`, `kompendium_corpus_chunks_truncated_total` | Teile 2 und 3, Wissens-Sammlung, Kappung des Korpus |
| `kompendium_llm_tokens_total{type}`, `kompendium_llm_calls_total`, `kompendium_llm_selections_total{outcome}`, `kompendium_llm_sections_total{outcome}`, `kompendium_llm_sentences_total{outcome}` | LLM-Verbrauch, Satzauswahl (`chosen`, `emptied`, `fallback`) und Belegprüfung |

`METRICS_TOKEN` verlangt `Authorization: Bearer …`, `METRICS_ENABLED=false` schaltet den Endpunkt ab.
Alarmregeln liegen in [monitoring/alerts.yml](monitoring/alerts.yml), ihre Tests in `monitoring/alerts_test.yml`:

```bash
docker run --rm -v "$PWD/monitoring:/m" --entrypoint promtool prom/prometheus:v3.14.0 test rules /m/alerts_test.yml
docker compose --profile monitoring up -d api prometheus   # Prometheus lokal auf 127.0.0.1:9090
```

Benachrichtigungen braucht einen Alertmanager; er ist nicht Teil des Repos.

## Lizenz

Der Code steht unter der Apache License 2.0 ([LICENSE](LICENSE)). Das Image enthält libzim, das unter
GPL-3.0-or-later steht; wer das Image weitergibt, prüft dessen Bedingungen. Die erzeugten Texte übernehmen
Inhalte unter den Lizenzen der Quellen (Wikipedia und Klexikon CC BY-SA 4.0, Materialien wie angegeben).
