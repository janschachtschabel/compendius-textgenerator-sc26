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

Konfiguration über Umgebungsvariablen oder `.env` (Vorlage `.env.example`, jede Variable erklärt
unter [Konfiguration](#konfiguration)).

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

Container: `docker-compose.yml` startet `api`, `zim-updater` und `lehrplan-updater` aus demselben
Image mit den Volumes `zim` (geplant 40 GB, in Kubernetes ein PVC mit 40Gi) und `state`.

```bash
docker compose up --build
```

Ohne eigenen Bau zieht Compose das fertige Image aus der GitHub Container Registry; dorthin
veröffentlicht es `.github/workflows/publish.yml` bei jedem Push auf `main` (Tags `latest`, `main` und
die Commit-Sha):

```bash
docker compose up -d
```

**Das Paket ist so sichtbar wie das Repository, also privat.** Ein fremder Host braucht deshalb einmalig
Zugangsdaten — ein persönliches Zugriffstoken mit `read:packages` genügt:

```bash
docker login ghcr.io -u <GitHub-Konto> --password-stdin
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
Inhalte und die Untersammlungen eine Ebene tief, jeder Block zwischen
`<!-- f: Sammlung=<id>; Fach=…; Bildungsstufe=… -->` und `<!-- /f -->`. Fehlende Beschreibungen
bleiben sichtbar leer.

### Materialblöcke in Teil 3

Jedes Material steht in einem eigenen Block `::: wlo-material` … `:::`, damit ein nachgelagertes
Werkzeug es ohne Kenntnis dieses Dienstes herauslösen kann:

```markdown
::: wlo-material
![Elliptischer Hohlspiegel](https://repository.staging.openeduhub.net/edu-sharing/preview?nodeId=8f42c56f-cd9f-47e1-bc20-b75fbb81ce51)

[**Elliptischer Hohlspiegel**](https://www.geogebra.org/classic/WtDBvGD9) — Lizenz: [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/deed.de)

Ein Hohlspiegel mit elliptischem Querschnitt · Schlagwörter: Optik, Spiegel · Simulation · Sekundarstufe I
:::
```

Was dabei zugesichert ist:

| Zeile | Inhalt |
|---|---|
| `::: wlo-material` | öffnet den Block; davor und danach steht eine Leerzeile, `:::` allein schließt ihn |
| `![Titel](…/preview?nodeId=<id>)` | die Vorschau trägt die **nodeId** des Materials — das ist `originalId` der Sammlungs­referenz, also der Knoten des Materials selbst, nicht der der Referenz |
| `[**Titel**](URL) — Lizenz: …` | Titel verlinkt das Material; hat es keine eigene URL, verlinkt er seine Seite im Repository, sodass immer genau ein Ziel dasteht |
| Lizenz | verlinkt den Creative-Commons-Deed, wenn Schlüssel **und** Version vorliegen; sonst reiner Text (`frei zugänglich (keine OER-Lizenz)`, `urheberrechtlich geschützt`, …). Eine Version wird nie geraten |
| letzte Zeile | Beschreibungssatz, Schlagwörter, Materialtyp, Bildungsstufe — entfällt, wenn nichts davon hinterlegt ist |

Titel und URLs kommen aus dem Repository und werden entschärft, bevor sie in den Block gehen:
`[` und `]` im Titel werden maskiert, URLs mit Leerzeichen oder Klammern in `<…>` gesetzt. Ein Block
kann damit nicht durch einen Materialtitel aufgebrochen werden. `knowledge_collection_id` nimmt die Materialien einer Sammlung als Quellen
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

## Konfiguration

Alle Einstellungen kommen aus Umgebungsvariablen (`app/settings.py`). `.env.example` ist die Vorlage:
Kopie als `.env`, Werte anpassen. **Die Vorlage enthält bewusst keine Kommentare und keine Leerzeilen** —
nur `NAME=Wert`, eine Einstellung je Zeile. Manche Hosting-Umgebungen (etwa Hostinger) lesen eine solche
Datei Zeile für Zeile und stolpern über Kommentare oder halten `# FOO=bar` für eine Variable namens
`# FOO`. Die Erklärungen stehen deshalb hier und in `docs/`; ein Test hält beides zusammen.

Die angegebenen Werte sind die der Vorlage. Wer eine Zeile wegnimmt, bekommt die Vorgabe aus
`app/settings.py` — bei den meisten ist das derselbe Wert.

### Compose-Variablen

Diese zwei liest `docker-compose.yml` selbst, nicht der Dienst — sie stehen deshalb **nicht** in
`.env.example`, sondern werden beim Aufruf gesetzt oder in die `.env` geschrieben.

| Variable | Vorgabe | Bedeutung |
|---|---|---|
| `IMAGE` | `ghcr.io/janschachtschabel/compendius-textgenerator-sc26:latest` | Welches Image die drei Dienste nutzen. Eine eigene Registry, ein Sha-Tag oder ein lokal gebautes Image tragen sich hier ein |
| `API_BIND` | `0.0.0.0:8000` | Woran der Port der API gebunden wird. Die Vorgabe bindet an **alle** Schnittstellen, damit der Dienst in einer Hosting-Umgebung überhaupt erreichbar ist — deren Proxy läuft meist nicht im selben Netz-Namensraum und käme an eine Loopback-Bindung nicht heran. Der Schutz ist dann die Firewall des Hosts und ein Reverse-Proxy davor, denn der Dienst kennt keine Anmeldung. Auf einem Arbeitsrechner gehört `API_BIND=127.0.0.1:8000` gesetzt |

### Betrieb

| Variable | Vorlage | Bedeutung |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Protokollstufe der Anwendung (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `REQUEST_TIMEOUT_S` | `120` | Frist je Anfrage für die LLM-Arbeit und das Lesen der Materialtexte. Aufrufe bekommen höchstens die Restzeit; danach entsteht der Rest extraktiv, nicht geholte Materialtexte bleiben draußen (`audit.knowledge.timed_out`) |
| `RATE_LIMIT` | `60` | Anfragen je Minute und Client auf `compendium`, `collections/overview` und `lehrplan/search`, je Worker gezählt; `0` schaltet es ab |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | Hinter einem Reverse-Proxy sieht uvicorn nur dessen Adresse, und alle Clients teilen sich ein Rate-Limit-Fenster. Diese Variable sagt uvicorn, welchen Absendern es `X-Forwarded-For` glauben darf: einzelne Adressen, Netze in CIDR-Schreibweise, mehrere durch Komma getrennt. **Nur das eigene Proxy-Netz eintragen** — `*` lässt jeden Aufrufer seine Adresse frei wählen und hängt damit das Rate-Limit aus |
| `WEB_CONCURRENCY` | `2` | Worker-Prozesse der API; uvicorn liest die Variable selbst. Jede Anfrage belegt einen Worker für ihre ganze Laufzeit, und jeder Worker kostet eigenen Speicher (siehe `docs/installation.md`) |
| `API_DOCS_ENABLED` | `true` | `/docs`, `/redoc` und `/openapi.json` ausliefern |
| `ADMIN_TOKEN` | leer | Admin-Endpunkte (ZIM-Katalog, Sync-Anstoß, Löschen, Harvest-Anstoß, Matching-Vergleich) nur mit diesem Token; leer schaltet sie ab |

### ZIM-Archive

| Variable | Vorlage | Bedeutung |
|---|---|---|
| `ZIM_DIR` | `/data/zim` | Verzeichnis mit `active.json`, vom Sync-Job gepflegt |
| `ZIM_PATHS` | leer | Statt des Verzeichnisses explizite Pfade, durch Komma getrennt — für die Entwicklung. Gesetzt hat es Vorrang vor `ZIM_DIR` |
| `ZIM_PROFILE` | `standard` | Welches Archivbündel gilt: `compact`, `standard` oder `extended` (`config/zim_subscriptions.yaml`) |
| `ZIM_REQUIRED` | leer | Pflichtarchive für `/ready`; leer leitet sie aus `config/zim_subscriptions.yaml` für `ZIM_PROFILE` ab |
| `ZIM_BOOTSTRAP_DOWNLOAD` | `true` | Lädt beim ersten Start die fehlenden Pflichtarchive des Profils — `compact` rund 1,4 GB, `standard` rund 14,1 GB, `extended` rund 18,1 GB. Erst danach meldet `/ready` den Dienst bereit. `false` lässt das Volume, wie es ist; dann müssen die Archive von Hand hinein |
| `ZIM_SYNC_INTERVAL` | `30d` | Wie oft der Sync-Job (`compendium zim sync --loop` im Updater-Sidecar) den Katalog prüft |
| `ZIM_RETENTION_HOURS` | `24` | Wie lange ein ersetztes Archiv nach dem Umschalten liegen bleibt, bevor es gelöscht wird |
| `ZIM_CATALOG_URL` | leer | OPDS-Katalog für den Sync-Job; leer nimmt den eingebauten Kiwix-Katalog (`https://opds.library.kiwix.org/catalog/v2/entries`) |
| `ZIM_DOWNLOAD_HOSTS` | `download.kiwix.org,lb.download.kiwix.org,mirror.download.kiwix.org` | Von welchen Hosts der Sync-Job laden darf. Ein Katalogeintrag, der woanders hinzeigt, wird abgelehnt |

### Ablage

| Variable | Vorlage | Bedeutung |
|---|---|---|
| `STATE_DIR` | `/data/state` | Zustandsvolume: Lehrplan-Cache, Sammlungs-Cache, Tagesbudget, eigene Templates |
| `CONFIG_DIR` | `config` | Verzeichnis mit `facets.yaml`, `zim_subscriptions.yaml` und den Templates |
| `EVAL_GOLD_DIR` | `eval/gold` | Goldstandard für `compendium eval` und `POST /api/v2/matching/compare` (Admin); im Image nicht enthalten |

### Kompendium und Matching

| Variable | Vorlage | Bedeutung |
|---|---|---|
| `TEMPLATE_DEFAULT` | `sc26` | Template, wenn die Anfrage keines nennt |
| `MATCHER_DEFAULT` | `hybrid_light` | Zuordnungsstrategie, wenn die Anfrage keine nennt. Vier stehen zur Wahl, alle laufen lokal auf der CPU und kosten nichts: **`hybrid_light`** (Überschriften-Lexikon, BM25 und Zeichen-TF-IDF zusammen, dazu Model2Vec-Einbettungen, wenn `MODEL2VEC_PATH` gesetzt ist) — der Standard; **`bm25`** (Okapi BM25 allein); **`char_tfidf`** (Zeichen-TF-IDF, trägt deutsche Komposita); **`lexicon_only`** (nur das Überschriften-Lexikon, ohne Ranker). Eine unbekannte Strategie beantwortet der Endpunkt mit 422 |
| `POLICY_CONFIDENT_SCORE` | `0.65` | Ab dieser fusionierten Trefferstärke gilt ein Ranker-Treffer als Beleg; darunter greift der Standardbaustein des Templates. Mit Glättung 0,5 auf `eval/gold` gemessen: 0,45 → 0,65 hebt macro-F1 von 0,430 auf 0,447 und senkt falsch gedruckte Absätze um ein Drittel |
| `POLICY_SECTION_SMOOTHING` | `0.5` | Anteil des Abschnittsmittels an jedem Score — Absätze unter einer Überschrift stützen sich gegenseitig; `0` schaltet es ab |
| `FACETS_LEVEL` | `minimal` | Wie viele Facetten das Frontmatter trägt: `minimal` oder `full` |
| `FACETS_VISIBLE` | `false` | Facettenmarken zusätzlich sichtbar in den Text schreiben |
| `CORPUS_MAX_ARTICLES` | `12` | Artikel je Kompendium. Thema und Zwilling sind immer dabei |
| `CORPUS_MAX_CHUNKS` | `400` | Absätze je Kompendium. Gefüllt wird in der Reihenfolge Hauptartikel, Klexikon, angeforderte Materialien, verlinkte, gesuchte Artikel; der Rest steht als `chunks_truncated` im Audit |

### Modelle im Image

| Variable | Vorlage | Bedeutung |
|---|---|---|
| `MODEL2VEC_PATH` | `/models/m2v` | Statisches Einbettungsmodell für `hybrid_light`; im Image unter `/models/m2v`. Lokal eine Hugging-Face-ID mit `HF_HUB_OFFLINE=1`, wenn das Modell im Cache liegt. Leer heißt: `hybrid_light` ohne Einbettungen |
| `SPACY_MODEL` | `de_core_news_md` | Modell für die Entitätserkennung (`POST /api/v2/entities`) und für die QA-Stufen `rule-based` und `parse-based`: installierter Name oder Pfad. Leer heißt: `/api/v2/entities` antwortet nur mit den Begriffen, die einen Artikel haben, und `parse-based` fällt auf `rule-based` zurück |
| `QG_MODEL_PATH` | `/models/qg` | Fragengenerator der QA-Stufe `models`. Leer schaltet die Stufe ab; die Anfrage fällt dann auf `rule-based` zurück und sagt es in `note` |
| `QA_MODEL_PATH` | `/models/qa` | Extraktives Antwortmodell derselben Stufe. Zusammen kosten beide rund 1,7 GB je Worker, und zwar erst bei der ersten Anfrage, die sie braucht |

### Lehrpläne (Teil 2)

Vollabzug aus MEM in `STATE_DIR/lehrplan.db` durch den Harvest-Sidecar (`compendium lehrplan harvest --loop`);
die API liest nur den Cache. Wöchentlich wird die Zählung geprüft, ein Vollabzug bei Änderung oder spätestens
nach `LEHRPLAN_HARVEST_MAX_AGE` angestoßen — er dauert rund 25 Minuten und stellt 2.605 Anfragen.

| Variable | Vorlage | Bedeutung |
|---|---|---|
| `LEHRPLAN_ENDPOINT` | `https://sparql.mem.edufeed.org/sparql/` | SPARQL-Endpunkt der MEM |
| `LEHRPLAN_CHECK_INTERVAL` | `7d` | Wie oft die Zählung geprüft wird |
| `LEHRPLAN_HARVEST_MAX_AGE` | `30d` | Spätestens nach dieser Zeit wird neu abgezogen, auch ohne erkannte Änderung |
| `LEHRPLAN_REQUEST_PAUSE_S` | `0.5` | Pause zwischen zwei Anfragen an die MEM |
| `LEHRPLAN_MAX_GROUPS_PER_LAND` | `0` | Optionale Kappung der Lernbereiche je Bundesland und Bildungsstufe; `0` heißt: alle Treffer, denn kompendiale Texte dürfen lang sein |

### Sammlungen (Teil 3) und Wissens-Sammlung

edu-sharing-Repository, anonym oder mit Basic-Auth; leere Basis-URL schaltet Teil 3 ab (der Endpunkt
antwortet dann 503). Der Cache liegt in `STATE_DIR/wlo_cache.db`. Wörtlich übernommen wird nur, was unter
CC0, PDM, CC BY oder CC BY-SA steht.

| Variable | Vorlage | Bedeutung |
|---|---|---|
| `EDU_SHARING_BASE_URL` | `https://repository.staging.openeduhub.net/edu-sharing/rest` | Welches Repository gilt. Staging ist der Standard; für Produktion `https://redaktion.openeduhub.net/edu-sharing/rest` |
| `EDU_SHARING_USER` | leer | Benutzername für Basic-Auth; leer heißt anonym |
| `EDU_SHARING_PASSWORD` | leer | Passwort dazu. Gehört in die `.env`, nicht in die Vorlage |
| `EDU_SHARING_TIMEOUT_S` | `30` | Frist je Anfrage an das Repository |
| `COLLECTION_CACHE_TTL_S` | `3600` | Wie lange eine Sammlung im Cache gilt |
| `COLLECTION_MAX_ITEMS` | `0` | Optionale Kappung der Inhalte je Sammlung; `0` listet alle |
| `MATERIAL_TEXT_CACHE_TTL_S` | `604800` | Wie lange ein geholter Materialtext im Cache gilt (sieben Tage) |
| `KNOWLEDGE_MAX_MATERIALS` | `30` | Materialien, die die Wissens-Sammlung höchstens liest |
| `KNOWLEDGE_MAX_CHARS` | `20000` | Zeichen je Materialtext |
| `KNOWLEDGE_CONCURRENCY` | `4` | Wie viele Materialtexte gleichzeitig geholt werden |

### LLM-Schicht über die b-api

Optional und standardmäßig aus. Ohne `LLM_ENABLED=true` **und** einen `B_API_KEY` laufen beide Schalter
regelbasiert; das Frontmatter nennt dann `extraction_requested` beziehungsweise `generation_requested`.

| Variable | Vorlage | Bedeutung |
|---|---|---|
| `LLM_ENABLED` | `false` | Hauptschalter der LLM-Schicht |
| `LLM_EXTRACTION_DEFAULT` | `rule-based` | Vorgabe für `extraction`: `rule-based` oder `llm` (das LLM wählt die Sätze je Baustein, der Wortlaut bleibt der der Quelle) |
| `LLM_GENERATION_DEFAULT` | `rule-based` | Vorgabe für `generation`: `rule-based`, `llm-fast` (nur die Bausteine aus `LLM_FAST_SECTIONS`) oder `llm` (alle Inhaltsbausteine aus ihren Belegen) |
| `LLM_ENRICHMENT_DEFAULT` | `sources-only` | Vorgabe für `enrichment`: `sources-only` (nur die Quellen) oder `model-knowledge` (das Modell darf eigenes Wissen ergänzen). Solche Sätze tragen keine Belegnummer, stehen im Text als Evidenzgrad=Modellwissen und werden je Baustein gezählt. Wirkt nur mit `generation` auf `llm` oder `llm-fast` |
| `LLM_EXTRACTION_CANDIDATES` | `8` | Bei `extraction=llm` angebotene Absätze je Baustein: erst die der Policy, dann die nächstbesten nach Score |
| `LLM_FAST_SECTIONS` | `sc26_1,sc26_11` | Welche Bausteine `llm-fast` schreibt |
| `LLM_UNSUPPORTED_SENTENCES` | `drop` | Sätze ohne gültigen, deckenden Beleg: `drop` (verwerfen) oder `mark` (als Schlussfolgerung kennzeichnen) |
| `B_API_KEY` | leer | Schlüssel der b-api. Gehört in die `.env`, nicht in die Vorlage |
| `B_API_BASE_URL` | leer | Leer lassen: dann gilt die b-api, die zum Repository oben gehört (Staging → `https://b-api.staging.openeduhub.net`, Redaktion → `https://b-api.prod.openeduhub.net`). Ein eigener Wert wird befolgt; passt er nicht zum Repository, sagt es das Log beim Start |
| `B_API_PROVIDER` | `openai` | Anbieterprofil der b-api |
| `B_API_MODEL` | `gpt-5.6-luna` | Modell, das die b-api ansprechen soll |
| `LLM_REASONING_EFFORT` | `low` | Nur GPT-5- und o-Serie |
| `LLM_VERBOSITY` | `low` | Nur GPT-5- und o-Serie |
| `LLM_TEMPERATURE` | `0.2` | Nur klassische Modelle; die GPT-5-Serie nutzt stattdessen die beiden Zeilen darüber |
| `LLM_TIMEOUT_S` | `120` | Frist je einzelnem LLM-Aufruf |
| `LLM_MAX_CONCURRENCY` | `10` | Gleichzeitige LLM-Aufrufe |
| `LLM_ATTEMPTS` | `3` | Versuche je Aufruf, bevor aufgegeben wird |
| `LLM_MAX_TOKENS_PER_REQUEST` | `60000` | Kostenschutz je Kompendium. Für *Optik* wurden mit beiden Schaltern 27.205 Tokens gemessen; über die zehn Gold-Themen kostet allein die Auswahl 14.000 bis 22.400, das Schreiben 10.500 bis 14.500. Parallele Aufrufe reservieren vorab ihren Höchstbedarf, daher der Abstand |
| `LLM_DAILY_TOKEN_BUDGET` | `2000000` | Kostenschutz je Tag. Der Zähler liegt in `STATE_DIR/llm_budget.db`, gilt für alle Worker gemeinsam und übersteht Neustarts |

### Metriken

| Variable | Vorlage | Bedeutung |
|---|---|---|
| `METRICS_ENABLED` | `true` | `GET /metrics` ausliefern |
| `METRICS_TOKEN` | leer | Verlangt `Authorization: Bearer <Token>`; leer heißt ohne Token |
| `PROMETHEUS_MULTIPROC_DIR` | leer | Wo die Worker ihre Werte ablegen, damit `/metrics` sie summiert. Leer nimmt den Standard `/tmp/prometheus`, den der API-Befehl des Images selbst setzt — **in der Regel leer lassen**, denn diese Datei gilt auch für die Sidecars, die keine Metriken schreiben. Ein eigener Pfad muss je Container leer und beschreibbar sein und darf niemals das Zustandsvolume sein |

## Endpunkte

| Endpunkt | Zweck |
|---|---|
| `GET /metrics` | Prometheus-Metriken (siehe „Überwachung“); optional nur mit `METRICS_TOKEN` |
| Alle Antworten | tragen `X-Request-ID` (die des Aufrufers oder eine neue); jede Logzeile der Anfrage nennt sie, ein unerwarteter Fehler antwortet mit 500, `detail` und `request_id` |
| `GET /health`, `GET /ready` | Prozess lebt (mit LLM-Status unter `components.llm`); Pflichtarchive vorhanden (sonst 503) |
| `POST /api/v2/compendium` | Kompendium zu `topic` oder `collection_id`; `parts` wählt `world`, `curricula`, `collection` (ohne `world` entfallen Teil 1, seine Quellen, das Matching und die Wissens-Sammlung; `extraction`, `generation` und `matcher` betreffen nur Teil 1, ohne ihn ist das Kompendium regelbasiert und `audit.matcher` leer); `subject`, `knowledge_collection_id`; `extraction` wählt `rule-based` oder `llm`, `generation` `rule-based`, `llm-fast` oder `llm`, `enrichment` `sources-only` oder `model-knowledge`; das frühere Feld `mode`: 422; unbekannte Strategie in `matcher`: 422; nur `collection` ohne `collection_id`: 422 (mit ihr braucht Teil 3 keinen Artikel in den Archiven); kein angefragter Teil erzeugbar (etwa Teil 3 ohne `EDU_SHARING_BASE_URL`): 503; `template_id` wählt ein Template (Standard aus den Einstellungen), `max_articles` begrenzt den Korpus (Standard `CORPUS_MAX_ARTICLES`, Thema und Zwilling sind immer dabei), `empty_slot_policy` und `facets_visible` überschreiben Template bzw. `FACETS_VISIBLE`, `language` kennt heute nur `de` (sonst 422); zur teilweisen Neuerzeugung mit `existing_markdown` und `regenerate_sections` siehe unten; `frontmatter_in_markdown: false` lässt den YAML-Vorspann im Markdown weg und beginnt bei der Überschrift — dieselben Angaben stehen weiter im Feld `frontmatter` |
| `POST /api/v2/knowledge` | Wissenstexte zu `topic`, ohne Template und Synthese: die Artikel des Korpus mit ihren Abschnitten. `archives` fragt gezielt einzelne Archive (unbekannte ID: 404), `max_articles` begrenzt die zusätzlichen Artikel (Thema und Zwilling sind immer dabei), `max_chars` deckelt den Text über alle Artikel und setzt `truncated`; Thema nicht gefunden: 404 mit `resolution` |
| `POST /api/v2/entities` | Entitäten in einem Text, in zwei Schichten: `methods` wählt `ner` (spaCy-Modell, braucht keine Archive) und `dictionary` (Begriffe, die einen Artikel haben); die Antwort nennt unter `methods`, welche Wege wirklich liefen, und je Entität `source`, `kind`, `linked` und den Artikel mit seinem Lead. `link: false` lässt das Nachschlagen weg, `archives` grenzt ein (unbekannte ID: 404); fällt beides aus — kein Modell und keine Archive —: 503. Steht hinter einem Begriff des Wörterbuchs nur eine Begriffsklärungsseite, entfällt er: die Methode verspricht Begriffe **mit** Artikel. Das gilt nicht für `ner` und nicht bei `link: false` — dort sagt `note`, dass ungeprüft geliefert wurde. `max_entities` greift vor dieser Prüfung, es können also weniger zurückkommen |
| `POST /api/v2/qa` | Frage-Antwort-Paare zu `text` oder `topic`. **`text`** ist der Text, aus dem die Paare gemacht werden — etwa das Markdown eines Kompendiums, das du schon hast. **`topic`** erzeugt erst Teil 1 des Kompendiums zu diesem Thema und fragt dessen Bausteine ab; beide Schritte also in einem Aufruf, zum Preis einer Erzeugung (404 mit `resolution`, wenn es das Thema nicht gibt, 503 wenn Teil 1 nicht erzeugbar ist). `method` wählt `rule-based` (Fragevorlagen über die Sätze, braucht nichts, Standard), `parse-based` (der spaCy-Parse ersetzt das Satzsubjekt durch ein Fragewort, die Antwort ist dann das Subjekt statt des ganzen Satzes; braucht das spaCy-Modell), `models` (zwei kleine deutsche Modelle im Image: ein Generator schreibt die Frage zu einer Nominalphrase, ein extraktives Modell markiert die antwortende Stelle — rund 1,1 s je Paar auf CPU bei 20 Paaren, bei wenigen Paaren eher 2 s, weil der Generator eine ganze Runde auf einmal erzeugt; die Modelle laden bei der ersten Anfrage) oder `llm` (die b-api schreibt sie); fehlen die Modelle, die b-api oder eine verwertbare Antwort, fällt es auf `rule-based` zurück und `note` sagt warum. `count` und `max_answer_length` begrenzen. **Welche Stufe wofür:** gemessen am 2026-09-21 auf einem Kompendiumtext greift `rule-based` nur bei jedem achten Satz und die Hälfte der Fragen fragt nach einer Jahreszahl (8 von 20 angefragten Paaren, 4 Fragetypen); `parse-based` holt aus denselben Texten viermal so viel wie die Vorlagen — gemessen am 2026-09-22 über 172 Sätze aus vier Kompendien 33 Fragen statt 8, rund 4 ms je Satz (warm; der erste Text eines Prozesses zahlt einmalig das Aufwärmen von spaCy), 26 der 33 mangelfrei — ohne ein Modell zu laden; `models` lieferte aus demselben Text 20 von 20 mit 18 Fragetypen und keiner Jahresfrage, weil die Fragen aus den Nominalphrasen entstehen statt aus Vorlagen, und ist mit 94 % mangelfreien Paaren die genaueste und mit Abstand langsamste Stufe. `/docs` hat je ein Beispiel dafür. Die Fragevorlagen prüfen mit dem spaCy-Modell, ob der Betreff wirklich ein Begriff ist — Deutsch schreibt am Satzanfang groß, sonst entstünde „Was versteht man unter Daneben?“. Fehlt das Modell, entfällt die Prüfung und `note` sagt es |
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
