# Betrieb der Kompendium-API

Kurzes Handbuch für Betrieb, Störungen und Wiederherstellung. Die Einrichtung einer neuen Maschine steht in
[installation.md](installation.md), Architektur und Entscheidungen in [PLAN.md](../PLAN.md), alle Einstellungen
mit ihrer Bedeutung im Abschnitt *Konfiguration* der [README](../README.md#konfiguration);
[.env.example](../.env.example) ist die kommentarfreie Vorlage dazu.

## Prozesse und Volumes

| Prozess | Befehl | Aufgabe |
|---|---|---|
| `api` | `uvicorn app.main:create_app --factory` (Worker: `WEB_CONCURRENCY`, im Image 2) | beantwortet Anfragen, lädt nie Archive herunter |
| `zim-updater` | `compendium zim sync --loop` | Kiwix-Katalog prüfen, Dumps laden, `active.json` umschalten, alte Dateien löschen |
| `lehrplan-updater` | `compendium lehrplan harvest --loop` | MEM-Lehrpläne in `lehrplan.db` ziehen und atomar tauschen |
| `wikidata-updater` | `compendium wikidata sync --loop` | Wikidata-Index `wikidata.db` bauen, wenn er fehlt, und neu nach einem jüngeren Wikipedia-Archiv (D64); lädt drei Dumps von dumps.wikimedia.org (rund 750 MB) und löscht sie nach dem Bau |
| `gnd-updater` | `compendium gnd sync --loop` | GND-Index `gnd.db` bauen, wenn er fehlt, und neu bei einer neueren Ausgabe der DNB (D65); lädt die Abzüge Sachbegriffe und Geografika von data.dnb.de (rund 65 MB) und löscht sie nach dem Bau |

| Volume | Inhalt | Wiederherstellung |
|---|---|---|
| `zim` (`ZIM_DIR`) | ZIM-Archive, `active.json`, `sync_status.json` | neu laden lassen (`ZIM_BOOTSTRAP_DOWNLOAD=true`) oder Dateien hineinkopieren; der nächste Sync übernimmt sie |
| `state` (`STATE_DIR`) | `lehrplan.db`, `wlo_cache.db`, `llm_budget.db`, `templates/`, `wikidata.db` mit `wikidata_status.json`, `gnd.db` mit `gnd_status.json` | `lehrplan.db` per Harvest neu erzeugen (rund 25 Minuten); `wikidata.db` baut der Sidecar `wikidata-updater` selbst neu (rund 750 MB Download, dabei rund 1,5 GB frei im Volume), von Hand `docker compose run --rm --no-deps wikidata-updater compendium wikidata sync --force` (README „Entitäten und Kennungen“); `gnd.db` baut der Sidecar `gnd-updater` selbst neu (rund 65 MB), von Hand `docker compose run --rm --no-deps gnd-updater compendium gnd sync --force`; `wlo_cache.db` und `llm_budget.db` sind verzichtbar; `templates/` sichern, falls eigene Templates angelegt wurden (`PUT`/`DELETE /api/v2/templates/{id}` oder `compendium templates save|delete` schreiben dorthin) |

**`ZIM_PATHS` umgeht dieses Volume.** Sind dort Pfade eingetragen, liest der Dienst genau diese Dateien:
`active.json` wird nicht gelesen, der Sync-Job verwaltet die Archive nicht, und ein Wechsel braucht einen
Neustart. Der Start warnt ausdrücklich davor. Für den Betrieb `ZIM_PATHS` leer lassen und `ZIM_DIR`
verwenden; `ZIM_PATHS` ist für Entwicklung und Tests gedacht.

## Zustand prüfen

- `GET /health`: Prozess lebt; `components` zeigt `zim`, `lehrplan_cache`, `edu_sharing` und `llm`
  (Modellprüfung, Tagesverbrauch). Je Modell steht dort, ob es wirklich geladen ist: `matching.embeddings`
  für das Model2Vec-Modell, `entities.ner` für das spaCy-Modell, `entities.wikidata` für den Wikidata-Index
  (D43) — ein fehlendes Modell macht die Antworten schwächer, ohne dass eine Anfrage scheitert. Die Komponente
  `qa_models` entfiel mit den beiden QA-Modellen (D57).
  Ruft keinen fremden Dienst auf.
- `GET /ready`: 200 erst, wenn alle Pflichtarchive des Profils vorliegen, sonst 503.
- `GET /api/v2/zim/status`, `GET /api/v2/lehrplan/status`: Archive, letzter Sync, Cache-Stand.
- Die Sidecars haben keinen HTTP-Server und keinen Healthcheck; ihren Stand zeigen `sync_status.json` und
  `GET /api/v2/zim/progress` (Admin) sowie die Logs.

## Überwachung

`GET /metrics` liefert Zustand und Laufzeitmetriken für Prometheus (Liste im README). Die Alarmregeln in
`monitoring/alerts.yml` decken die Störungen unten ab: `KompendiumDown`, `KompendiumNotReady`,
`KompendiumHighErrorRate`, `KompendiumStatusIncomplete`, `KompendiumSlowCompendia`, `KompendiumZimSyncErrors`,
`KompendiumZimSyncStale`,
`KompendiumZimSyncHangs`,
`KompendiumLehrplanCacheMissing`, `KompendiumLehrplanCacheStale`, `KompendiumLehrplanHarvestFailed`,
`KompendiumWikidataIndexMissing`, `KompendiumWikidataSyncFailed`, `KompendiumGndIndexMissing`, `KompendiumGndSyncFailed`,
`KompendiumLlmUnavailable`, `KompendiumLlmBudgetNearlySpent` und `KompendiumLlmFallbacks`. Nach einer Änderung
an den Regeln `promtool test rules monitoring/alerts_test.yml` laufen lassen. Die Sidecars haben keinen eigenen
Endpunkt; ihren Stand melden die Zustandswerte der API aus den Statusdateien. Wer `/metrics` nicht offen lassen
will, setzt `METRICS_TOKEN` und trägt es im Scrape-Job ein (`authorization.credentials_file`).

## Störungen

| Symptom | Ursache und Verhalten | Maßnahme |
|---|---|---|
| Ein Update meldet Erfolg, `GET /health` nennt aber noch die alte `version` | Der Pull scheiterte (im Protokoll `error from registry: unauthorized`: das GHCR-Paket ist nicht öffentlich oder dem Host fehlt die Anmeldung), und Compose startete die Container mit dem Image, das schon auf dem Host lag | Sichtbarkeit des Pakets prüfen (öffentlich, siehe README), das Update wiederholen, danach `version` in `GET /health` vergleichen |
| Der API-Container steht nach dem Start einige Minuten auf `health: starting` | Normal: Die API lädt nach dem Start Archive und Modelle, gemessen 144 s mit zwei Workern. Der Healthcheck zählt Fehlschläge erst nach 600 s Anlaufzeit, die erste gelungene Probe meldet ihn sofort `healthy` | Abwarten. Erst `unhealthy` nach Ablauf der Frist deutet auf einen Startfehler: `docker compose logs api` |
| Ein Aufrufer meldet einen Fehler | Die Antwort trug `request_id`; danach im Log suchen (jede Zeile der Anfrage nennt sie), der Grund steht dort, nicht in der Antwort | `docker compose logs api | Select-String <id>` |
| Eine Anfrage endet ohne Antwort, das Log der API meldet `Child process [n] died` | Der Elternprozess tötet einen Worker, der seinen Healthcheck nicht rechtzeitig beantwortet. Ein Worker, der an einem Kompendium arbeitet, schweigt dabei: die Arbeit steckt in C-Code (ZIM-Lesen, Matching), der die Interpreter-Sperre hält (gemessen 26 s am Stück). Der Startbefehl setzt das Fenster deshalb auf `REQUEST_TIMEOUT_S` plus 60 s. Sichtbar wird das nur unter Last: Je knapper die CPU, desto länger schweigt der Worker | Dauern Anfragen regelmäßig länger, `REQUEST_TIMEOUT_S` anheben — das Fenster wächst mit. Tritt es weiterhin auf, hängt der Worker wirklich: Log und Speicher prüfen |
| LLM-Anfragen kommen mit `extraction: rule-based` oder `generation: rule-based` und dem Feld `*_requested` zurück | b-api nicht erreichbar, Modell fehlt in `/models`, Tagesbudget erschöpft oder Schutzschalter aktiv (60 s nach einem Verbindungsfehler) | `components.llm` in `/health` und `audit.llm.note` lesen; die Modellprüfung wiederholt sich höchstens alle zehn Minuten von selbst |
| Teil 3 meldet, dass der Sammlungsüberblick nicht erstellt werden konnte | edu-sharing antwortet nicht oder mit Fehler; Details stehen im Log, nicht in der Antwort | Repository prüfen; `GET /api/v2/collections/{id}/overview` antwortet 502, wenn schon die Sammlung nicht lesbar ist, sonst 200 mit `available: false` |
| Teil 2 enthält nur den Hinweistext | `lehrplan.db` fehlt (`reason: cache_missing`) oder ist beschädigt oder von einer anderen Schemaversion (`cache_unreadable`) | `POST /api/v2/lehrplan/harvest` (Admin) oder `compendium lehrplan harvest --force` im Sidecar |
| 503 „Kein angefragter Teil ist erzeugbar“ | Die Anfrage verlangt nur Teile, die der Dienst nicht eingerichtet hat (etwa Teil 3 ohne `EDU_SHARING_BASE_URL`); das Log meldet `compendium request refused` mit dem Grund. Eine Wiederholung ändert nichts | Konfiguration ergänzen oder den Teil nicht anfragen |
| 429 mit `Retry-After` | `RATE_LIMIT` je Client und Minute überschritten | hinter einem Proxy `FORWARDED_ALLOW_IPS` setzen, sonst teilen sich alle Clients ein Fenster |
| `/ready` bleibt 503 | Pflichtarchive fehlen oder `active.json` ist beschädigt (steht im Log) | `compendium zim status`; Sync anstoßen (`POST /api/v2/zim/sync`, Admin) |
| ZIM-Volume läuft voll | abgelöste Dumps bleiben `ZIM_RETENTION_HOURS` liegen; `.part`-Dateien älterer Dumps räumt der Sync weg | `DELETE /api/v2/zim/{datei}` (Admin) für nicht aktive Dateien; Volume für zwei Generationen des Profils auslegen (Profil `standard`: rund 2 × 14 GB) |
| `KompendiumZimSyncHangs`: Sync läuft laut Statusdatei, schreibt aber seit sechs Stunden nicht mehr | Updater abgestürzt (OOM, `docker kill`) oder Volume voll, sodass nicht einmal die Statusdatei geschrieben werden kann; ein Lauf, der mit einer Ausnahme abbricht, endet dagegen mit `state: error`, löst `KompendiumZimSyncErrors` aus und wird nach einer Stunde wiederholt | Log des Updaters; Platz schaffen, Sidecar neu starten |
| Download bricht ab | `.part` bleibt für den nächsten Lauf; ein Spiegel, der mehr als die angekündigte Größe schickt, wird abgebrochen und die `.part` gelöscht | Log des Updaters; nach einer Stunde setzt der nächste Lauf fort (auch bei vollem Volume, sobald Platz ist). Nach einem Hash- oder Größenfehler oder einem Archiv, das libzim nicht öffnen kann, wartet der Updater das normale Intervall ab; eine schon vollständige, geprüfte Datei lädt er nicht noch einmal |
| Entitäten tragen keine Wikidata-Nummer, `/health` meldet `entities.wikidata.available: false` (`KompendiumWikidataIndexMissing`) | Der Index fehlt: Bei einer neuen Installation lädt und baut der Sidecar `wikidata-updater` noch (rund zehn Minuten), oder sein Lauf scheiterte (`wikidata_status.json`, `KompendiumWikidataSyncFailed`): dumps.wikimedia.org nicht erreichbar, Prüfsumme falsch, Volume voll (ein Lauf braucht rund 1,5 GB). Ein Fehler, den derselbe Lauf wiederholen würde, wartet bis zur nächsten täglichen Prüfung, ein Netzfehler eine Stunde | `docker compose logs wikidata-updater` lesen; nach der Behebung `docker compose run --rm --no-deps wikidata-updater compendium wikidata sync --force`. Die API übernimmt den neuen Index binnen einer Minute, ohne Neustart |
| Artikel ohne Normdaten-Block tragen keine GND, `/health` meldet `entities.gnd.available: false` (`KompendiumGndIndexMissing`) | Der GND-Index fehlt: Bei einer neuen Installation lädt und baut der Sidecar `gnd-updater` noch (wenige Minuten), oder sein Lauf scheiterte (`gnd_status.json`, `KompendiumGndSyncFailed`): data.dnb.de nicht erreichbar, Prüfsumme falsch, Volume voll | `docker compose logs gnd-updater` lesen; nach der Behebung `docker compose run --rm --no-deps gnd-updater compendium gnd sync --force`. Die API übernimmt den neuen Index binnen einer Minute, ohne Neustart |
| Der Port antwortet von außen nicht | Zwei Ursachen, die der Fehler selbst unterscheidet: **Zeitüberlauf** heißt, das SYN kommt gar nicht bis zum Host — dann wirft eine Firewall oder eine fehlende Portfreigabe es weg. **Connection refused** heißt, der Host antwortet, aber nichts lauscht auf dieser Schnittstelle — dann bindet der Port nur an Loopback. | Zeitüberlauf: Port beim Anbieter freigeben. Refused: `API_BIND` auf `0.0.0.0:8000` (Vorgabe) prüfen, `docker compose config` zeigt die wirksame Bindung. Und `/` gibt es nicht — der Dienst antwortet auf `/docs`, `/health`, `/ready` |

## Regeln

- Es läuft immer nur ein Sync: Die Sperrdatei `sync.lock` im ZIM-Verzeichnis weist einen zweiten Lauf ab
  („Ein ZIM-Sync läuft bereits“), weil beide in dieselbe `.part` schreiben würden. Jeder Statuseintrag des
  laufenden Syncs frischt sie auf; nach einer Stunde ohne Lebenszeichen gilt sie als verwaist und wird
  übernommen. Einen Lauf stößt man über `POST /api/v2/zim/sync` (Admin) oder die Trigger-Datei an. Ein
  `docker stop` (SIGTERM) beendet einen laufenden Sync oder Harvest sauber: Endstatus geschrieben, Sperre frei, der
  nächste Start setzt die `.part` fort.
- Der Dienst hat keine Anmeldung für die öffentlichen Endpunkte; er gehört hinter ein Gateway. Admin-Endpunkte
  sind nur mit `ADMIN_TOKEN` aktiv.
- `B_API_KEY` und `EDU_SHARING_PASSWORD` kommen nur aus der Umgebung und erscheinen in keiner Meldung.
- Zurück auf eine frühere Fassung: Jeder Commit auf `main`, dessen Prüfungen grün waren, liegt als Image mit
  seiner kurzen Commit-Sha in der Registry, jedes Versions-Tag `vX.Y.Z` als `X.Y.Z`. Also
  `IMAGE=ghcr.io/janschachtschabel/compendius-textgenerator-sc26:<sha>` setzen (in der `.env` oder den Variablen
  des Hosting-Panels) und `docker compose up -d`; zurück auf den neuesten Stand geht es, indem man `IMAGE` wieder
  entfernt. Wer selbst baut: `git checkout <Commit>` und `docker compose build && docker compose up -d`. Die
  Volumes bleiben, wie sie sind. Findet die ältere Fassung
  einen neueren Zustand vor — etwa `lehrplan.db` mit einer anderen Schemaversion —, meldet sie das als
  `cache_unreadable` und ein Harvest baut den Cache neu auf (siehe Störungen); die Archive sind davon nicht
  betroffen.
- Ein neues Embedding-Modell oder eine neue Revision (`MODEL2VEC_REVISION` im Dockerfile) erst nach einer
  Messung mit `compendium eval run` übernehmen; die Zahlen stehen in [eval/README.md](../eval/README.md).
