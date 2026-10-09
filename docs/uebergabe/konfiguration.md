# Konfiguration

[Übergabe](README.md) · Stand 09.10.2026 · Release 2.19.0

Der Dienst liest seine Einstellungen aus Umgebungsvariablen. Docker Compose nimmt sie aus der Datei `.env` neben der
`docker-compose.yml`: die Variablen des Dienstes für alle fünf Container, dazu vier, die Compose selbst auswertet
(`IMAGE`, `API_BIND`, `API_MEMORY`, `API_STOP_GRACE_PERIOD`). Eine fehlende Variable nimmt ihre Vorgabe; die Vorlage
[`.env.example`](../../.env.example) listet alle 79 des Dienstes mit ihrer Vorgabe. Die ausführliche Beschreibung jeder
Variable steht im [README](../../README.md), Abschnitt „Konfiguration“.

## Für den Betrieb

Die `.env` entsteht aus der Vorlage; für den Betrieb ändern sich diese Zeilen. Sie folgen dem, was der Testserver heute
nutzt: LLM gpt-6-luna über die b-api, edu-sharing der Staging, Archivprofil `standard`.

```bash
cp .env.example .env && chmod 600 .env
openssl rand -hex 32   # je Schlüssel und Token einmal
```

```dotenv
# Image mit fester Version aus der Registry des GitLab (ein Git-Tag v2.19.0 baut :2.19.0 und :2.19, wie auf GitHub).
# Mindestens 2.6.0 nehmen: 2.5.0 liest LLM_DAILY_TOKEN_BUDGET=0 aus .env.example als leeres Tagesbudget.
IMAGE=<registry>/<pfad>/compendious-text-fastapi:<version>

# LLM
LLM_ENABLED=true
B_API_KEY=<Schlüssel der b-api>

# Zugang: je aufrufendem System ein eigener Schlüssel, kommagetrennt
API_KEYS=<Schlüssel System A>,<Schlüssel System B>
ADMIN_TOKEN=<Token>
METRICS_TOKEN=<Token>
UI_ENABLED=true

# nur hinter einem Reverse-Proxy auf demselben Host
API_BIND=127.0.0.1:8000
FORWARDED_ALLOW_IPS=<Gateway des Compose-Netzes>
```

Geheim sind `B_API_KEY`, `API_KEYS`, `ADMIN_TOKEN`, `METRICS_TOKEN` und, wenn gesetzt, `EDU_SHARING_PASSWORD`: nur in
der `.env` auf dem Server, nie im Repository. Die Sidecars bekommen keines davon (`docker-compose.yml`, `x-no-secrets`).
Wechselt der Dienst von der Staging auf die Produktion von edu-sharing, genügt
`EDU_SHARING_BASE_URL=https://redaktion.openeduhub.net/edu-sharing/rest`; die b-api folgt von selbst
(`b-api.prod.openeduhub.net`), solange `B_API_BASE_URL` leer ist.

Ein Update liest die `.env` neu; eine geänderte Variable wirkt nach `docker compose up -d`. Was sich je Release an den
Vorgaben ändert, steht in [betrieb.md](../betrieb.md) unter „Updates“.

## Alle Variablen

83 Variablen: 79 des Dienstes und 4 von Compose. „Vorgabe“ ist der Wert der Vorlage `.env.example` beziehungsweise von
`docker-compose.yml`; „Betrieb“ nennt die Empfehlung, wo sie davon abweicht.

### Zugang und Sicherheit

| Variable | Vorgabe | Betrieb | Wofür |
|---|---|---|---|
| `API_KEYS` | leer | **je aufrufendem System ein Schlüssel** | Schlüssel der Aufrufer, kommagetrennt, je mindestens 16 Zeichen, im Header `X-API-Key`; leer beantwortet der Dienst jeden |
| `ADMIN_TOKEN` | leer | **gesetzt** | schützt die Admin-Endpunkte (ZIM-Sync, Harvest, Templates schreiben), mindestens 16 Zeichen; leer schaltet sie ab |
| `METRICS_TOKEN` | leer | **gesetzt** | verlangt `Authorization: Bearer <Token>` für `/metrics`; leer ist `/metrics` offen |
| `METRICS_ENABLED` | `true` | wie Vorgabe | `/metrics` für Prometheus ausliefern |
| `API_DOCS_ENABLED` | `true` | wie Vorgabe | `/docs`, `/redoc` und `/openapi.json`; die Seiten laden Swagger UI und ReDoc von cdn.jsdelivr.net |
| `UI_ENABLED` | `false` | **`true`, nur mit `API_KEYS`** | Prüfansicht `/ui/` für die Redaktion; sie fragt mit dem Schlüssel, den der Leser einträgt |
| `API_BIND` | `0.0.0.0:8000` | **hinter Reverse-Proxy `127.0.0.1:8000`** | Compose: woran der Port der API gebunden wird; Docker leitet an der Firewall des Hosts vorbei |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | **hinter Reverse-Proxy auf dem Host das Gateway des Compose-Netzes** | Absender, deren `X-Forwarded-For` uvicorn glaubt; sonst teilen sich alle Clients ein Rate-Limit |
| `RATE_LIMIT` | `60` | wie Vorgabe | Anfragen je Minute und Aufrufer, je Worker gezählt; `0` schaltet es ab |
| `REQUEST_BODY_MAX_BYTES` | `1000000` | wie Vorgabe | größter Anfragekörper, sonst 413; `/compendium` nimmt bis 13.000.000 Byte (`existing_markdown`) |

### Server und Ressourcen

| Variable | Vorgabe | Betrieb | Wofür |
|---|---|---|---|
| `IMAGE` | `ghcr.io/janschachtschabel/compendius-textgenerator-sc26:latest` | **feste Version ab 2.6.0, etwa `…/compendious-text-fastapi:2.19.0`** | Compose: Image aller fünf Container |
| `API_MEMORY` | `6g` | wie Vorgabe | Compose: Speichergrenze des api-Containers, bis 29.09.2026 `4g`; gemessen 3,4 GiB Prozesse mit 2 Workern, dazu Seiten-Cache |
| `WEB_CONCURRENCY` | `2` | wie Vorgabe | Worker der API; je Worker rund 1,7 GiB, mit 3 Workern `API_MEMORY=8g` |
| `API_STOP_GRACE_PERIOD` | `630s` | wie Vorgabe | Compose: Zeit für laufende Anfragen bei einem Update; deckt academiccloud (600 s) und OpenAI (300 s), über `REQUEST_TIMEOUT_S` plus 15 s halten |
| `REQUEST_TIMEOUT_S` | leer: `openai` 300, `academiccloud` 600, `router` 300 | wie Vorgabe | Frist je Anfrage für LLM und Repository; danach entsteht der Rest ohne LLM. Ein gesetzter Wert gilt für jeden Anbieter |
| `UVICORN_HTTP` | `h11` | wie Vorgabe | HTTP-Parser von uvicorn |
| `LOG_LEVEL` | `INFO` | wie Vorgabe | Protokollstufe der Zeilen des Dienstes und der Updater: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (`WARN` gilt als `WARNING`); ein unbekannter Wert hält den Start an |
| `LOG_FORMAT` | `text` | `json`, wenn ein Log-Sammler die Zeilen liest | eine Zeile Text oder ein JSON-Objekt je Ereignis nach stderr, mit Prozess- und Anfrage-ID, auch für die Zeilen von uvicorn und die Updater-Schleifen (docs/betrieb.md, Abschnitt „Logs“) |
| `PROMETHEUS_MULTIPROC_DIR` | leer | wie Vorgabe | wo die Worker ihre Messwerte ablegen; leer lassen, das Image setzt `/tmp/prometheus` |

### LLM über die b-api

| Variable | Vorgabe | Betrieb | Wofür |
|---|---|---|---|
| `LLM_ENABLED` | `false` | **`true`** | Hauptschalter; ohne LLM laufen Anfragen ohne Profil mit `llm-free`, und eine, die selbst ein anderes Profil nennt, ist ein 503 (D68) |
| `B_API_KEY` | leer | **Schlüssel der b-api** | geheim, nur in der `.env` |
| `B_API_BASE_URL` | leer | wie Vorgabe | leer: die b-api zum Repository (Staging oder Produktion); ein eigener Wert wird befolgt |
| `B_API_PROVIDER` | `openai` | wie Vorgabe | Anbieterprofil der b-api; `router` nutzt das Routing der b-api über eine vorab angelegte Route (D97) |
| `B_API_MODEL` | `gpt-6-luna` | wie Vorgabe | Modell; `/health` meldet, ob die b-api es führt. Mit `router` die Modellfamilie der Route |
| `B_API_ROUTE` | leer | leer, oder die Route der b-api | nur mit `B_API_PROVIDER=router`: Name der Route, leer eine Route, die wie `B_API_MODEL` heißt; anlegen müssen sie Administratoren der b-api |
| `B_API_RESPONSE_CACHE` | `false` | wie Vorgabe | aus: jeder LLM-Aufruf wird neu beantwortet, statt dass die b-api eine wortgleiche Anfrage aus ihrem Speicher wiederholt (D70); das Prompt-Caching des Anbieters bleibt |
| `LLM_REASONING_EFFORT` | `low` | wie Vorgabe | Denkaufwand von Reasoning-Modellen für jede Frage, die `LLM_REASONING_EFFORTS` nicht nennt |
| `LLM_REASONING_EFFORTS` | `topic_articles=none,article_choice=none,curriculum_check=none,topic_wording=none,qa_pairs=none` | wie Vorgabe | Fragen mit eigenem Denkaufwand; die fünf ausgelieferten antworteten ohne Denken gleich gut in der halben Zeit (D81) |
| `LLM_VERBOSITY` | `low` | wie Vorgabe | Ausführlichkeit von Reasoning-Modellen |
| `LLM_TEMPERATURE` | `0.2` | wie Vorgabe | nur klassische Modelle |
| `LLM_TIMEOUT_S` | `120` | wie Vorgabe | Frist je LLM-Aufruf |
| `LLM_MAX_CONCURRENCY` | leer: `openai` 20, `academiccloud` 2, `router` 20 | wie Vorgabe | gleichzeitige LLM-Aufrufe je Worker-Prozess; ein gesetzter Wert gilt für jeden Anbieter |
| `LLM_ATTEMPTS` | `3` | wie Vorgabe | Versuche je Aufruf |
| `LLM_MAX_TOKENS_PER_REQUEST` | `60000` | wie Vorgabe | Tokens je Anfrage in `llm-free` und `balanced` |
| `LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY` | `200000` | wie Vorgabe | Tokens je Anfrage in den drei Profilen ab `best-quality` |
| `LLM_MAX_TOKENS_CURRICULUM_CHECK` | `400000` | wie Vorgabe | Tokens der KI-Prüfung von Teil 2 je Anfrage, neben denen der Anfrage (D94); was darüber hinausgeht, bleibt ungeprüft stehen |
| `LLM_DAILY_TOKEN_BUDGET` | `0` | wie Vorgabe | Tokens je Tag für alle Worker; `0` setzt keine Grenze (D67), gezählt wird trotzdem. Eine Zahl kappt den Tag: 2.000.000 reichen für 25 bis 40 Kompendien mit `best-quality` oder rund 3.500 mit `balanced`. Ohne Grenze gehören `API_KEYS` gesetzt. Bis Release 2.5.0 hieß `0` ein leeres Budget: kein LLM-Aufruf, jeder Schritt fällt auf die Regeln zurück |
| `LLM_UNSUPPORTED_SENTENCES` | `drop` | wie Vorgabe | Sätze ohne deckenden Beleg: `drop` verwirft, `mark` kennzeichnet sie |
| `LLM_EXTRACTION_CANDIDATES` | `8` | wie Vorgabe | Absätze je Baustein, die `extraction=llm` angeboten bekommt: die der Policy und bis zu dieser Zahl die nächstbesten |
| `LLM_FAST_SECTIONS` | `sc26_1,sc26_11` | wie Vorgabe | Bausteine, die `generation=llm-fast` schreibt |

### Profile und Text

| Variable | Vorgabe | Betrieb | Wofür |
|---|---|---|---|
| `PRESET_DEFAULT` | `best-quality-generated` | wie Vorgabe | Profil einer Anfrage ohne `preset`, solange ein LLM eingerichtet ist; ohne LLM läuft sie mit `llm-free` (D68). Werte: `llm-free`, `balanced`, `best-quality`, `best-quality-generated`, `best-coverage-generated` (D69). Ein Profil im Aufruf geht vor |
| `TEMPLATE_DEFAULT` | `sc26` | wie Vorgabe | Gliederung von Teil 1: `sc26` (13 Bausteine) oder `standard` (6); nennt es kein vorhandenes Template, gilt `sc26` (D68). `template_id` im Aufruf geht vor |
| `FACETS_LEVEL` | `minimal` | wie Vorgabe | Facetten im Frontmatter: `minimal` oder `full` |
| `FACETS_VISIBLE` | `false` | wie Vorgabe | Facetten zusätzlich sichtbar im Text |
| `MODEL2VEC_PATH` | `/models/m2v` | wie Vorgabe | Einbettungsmodell der lokalen Zuordnung, im Image; leer ordnet schlechter zu |
| `SPACY_MODEL` | `de_core_news_md` | wie Vorgabe | Sprachmodell für Entitäten und QA-Regeln, im Image |
| `POLICY_CONFIDENT_SCORE` | `0.65` | wie Vorgabe | ab dieser Trefferstärke gilt ein Absatz als Beleg für einen Baustein |
| `POLICY_SECTION_SMOOTHING` | `0.5` | wie Vorgabe | Anteil des Abschnittsmittels an jedem Score; `0` schaltet es ab |
| `CORPUS_MAX_ARTICLES` | `12` | wie Vorgabe | Artikel je Kompendium; Thema und Klexikon-Zwilling sind immer dabei |
| `CORPUS_MAX_CHUNKS` | `400` | wie Vorgabe | Absätze je Kompendium |
| `BLOCK_BUDGET_FACTOR` | `10` | wie Vorgabe | vervielfacht beim Zuschnitt das Budget jedes Bausteins, Absätze und Zeichen (D102, M86); `1` hält die Budgets der Vorlage |

### edu-sharing: Teil 3, Materialien, Knoten

| Variable | Vorgabe | Betrieb | Wofür |
|---|---|---|---|
| `EDU_SHARING_BASE_URL` | `https://repository.staging.openeduhub.net/edu-sharing/rest` | wie Vorgabe | Repository; heute die Staging, für Produktion `https://redaktion.openeduhub.net/edu-sharing/rest`; leer schaltet Sammlungen ab |
| `EDU_SHARING_REPOSITORIES` | `repository.staging.openeduhub.net,redaktion.openeduhub.net` | wie Vorgabe | Hosts, die eine Anfrage als `repository` ihrer `node_id` nennen darf |
| `EDU_SHARING_USER` | leer | wie Vorgabe | Basic-Auth; leer liest anonym nur Öffentliches. Nur zusammen mit `API_KEYS` setzen |
| `EDU_SHARING_PASSWORD` | leer | wie Vorgabe | Passwort dazu, geheim |
| `EDU_SHARING_TIMEOUT_S` | `30` | wie Vorgabe | Frist je Anfrage an das Repository |
| `COLLECTION_CACHE_TTL_S` | `3600` | wie Vorgabe | wie lange eine gelesene Sammlung gilt, in Sekunden |
| `COLLECTION_MAX_ITEMS` | `0` | wie Vorgabe | Kappung der Inhalte je Sammlung; `0` listet alle |
| `MATERIAL_TEXT_CACHE_TTL_S` | `604800` | wie Vorgabe | wie lange ein geholter Materialtext gilt (sieben Tage) |
| `KNOWLEDGE_MAX_MATERIALS` | `30` | wie Vorgabe | Materialien, die `knowledge_collection_id` höchstens liest; mit `knowledge_depth` über alle Sammlungen zusammen, die reihum je eines abgeben |
| `KNOWLEDGE_MAX_CHARS` | `20000` | wie Vorgabe | Zeichen je Materialtext (mit `knowledge_fulltext`) |
| `KNOWLEDGE_CONCURRENCY` | `4` | wie Vorgabe | Materialtexte, die gleichzeitig geholt werden (mit `knowledge_fulltext`) |

### Archive: zim-updater

| Variable | Vorgabe | Betrieb | Wofür |
|---|---|---|---|
| `ZIM_DIR` | `/data/zim` | wie Vorgabe | Verzeichnis der Archive; Compose setzt `/data/zim` |
| `ZIM_PROFILE` | `standard` | wie Vorgabe | Archivbündel: `compact` (1,4 GB), `standard` (18,7 GB mit der Wikipedia 2026-10, vorher 14,7 GB), `extended` (22,8 GB; nicht empfohlen, D99) |
| `ZIM_REQUIRED` | leer | wie Vorgabe | Pflichtarchive für `/ready`; leer leitet sie aus dem Profil ab |
| `ZIM_PATHS` | leer | wie Vorgabe | feste Archivpfade statt `ZIM_DIR`, nur für die Entwicklung |
| `ZIM_BOOTSTRAP_DOWNLOAD` | `true` | wie Vorgabe | lädt beim Erststart die fehlenden Pflichtarchive; `false`, wenn sie von Hand kommen |
| `ZIM_SYNC_INTERVAL` | `30d` | wie Vorgabe | wie oft der zim-updater den Katalog prüft |
| `ZIM_RETENTION_HOURS` | `24` | wie Vorgabe | wie lange ein ersetztes Archiv liegen bleibt |
| `ZIM_CATALOG_URL` | leer | wie Vorgabe | eigener OPDS-Katalog; leer nimmt den von Kiwix |
| `ZIM_DOWNLOAD_HOSTS` | `download.kiwix.org,lb.download.kiwix.org,mirror.download.kiwix.org` | wie Vorgabe | Hosts, bei denen ein Download beginnen darf; Kiwix leitet von dort auf Spiegel um |

### Lehrpläne: lehrplan-updater

| Variable | Vorgabe | Betrieb | Wofür |
|---|---|---|---|
| `LEHRPLAN_ENDPOINT` | `https://sparql.mem.edufeed.org/sparql/` | wie Vorgabe | SPARQL-Endpunkt der MEM |
| `LEHRPLAN_CHECK_INTERVAL` | `7d` | wie Vorgabe | wie oft die Zählung geprüft wird |
| `LEHRPLAN_HARVEST_MAX_AGE` | `30d` | wie Vorgabe | spätestens nach dieser Zeit neu abziehen |
| `LEHRPLAN_REQUEST_PAUSE_S` | `0.5` | wie Vorgabe | Pause zwischen zwei Anfragen an die MEM |
| `LEHRPLAN_MAX_GROUPS_PER_LAND` | `0` | wie Vorgabe | Kappung der Lernbereiche je Land und Stufe; `0` nimmt alle |
| `LEHRPLAN_GENERIC_WORD_HITS` | `1000` | wie Vorgabe | Nebenwörter eines Themas mit mehr Treffern im Cache sucht Teil 2 nicht (D80); `0` sucht jedes |

### Kennungen: wikidata-updater und gnd-updater

| Variable | Vorgabe | Betrieb | Wofür |
|---|---|---|---|
| `WIKIDATA_DUMPS_URL` | `https://dumps.wikimedia.org` | wie Vorgabe | Quelle der Wikipedia-Dumps für den Wikidata-Index |
| `WIKIDATA_CHECK_INTERVAL` | `1d` | wie Vorgabe | wie oft der wikidata-updater prüft |
| `GND_DUMPS_URL` | `https://data.dnb.de/opendata` | wie Vorgabe | Quelle der GND-Abzüge der DNB |
| `GND_CHECK_INTERVAL` | `1d` | wie Vorgabe | wie oft der gnd-updater prüft |

### Verzeichnisse

| Variable | Vorgabe | Betrieb | Wofür |
|---|---|---|---|
| `STATE_DIR` | `/data/state` | wie Vorgabe | Zustandsvolume; Compose setzt `/data/state` |
| `CONFIG_DIR` | `config` | wie Vorgabe | Facetten, Überschriften-Lexikon, Fächer und Archiv-Abos, im Image |
| `EVAL_GOLD_DIR` | `eval/gold` | wie Vorgabe | Goldstandard für `compendium eval`; im Image nicht enthalten |
