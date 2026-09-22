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

| Volume | Inhalt | Wiederherstellung |
|---|---|---|
| `zim` (`ZIM_DIR`) | ZIM-Archive, `active.json`, `sync_status.json` | neu laden lassen (`ZIM_BOOTSTRAP_DOWNLOAD=true`) oder Dateien hineinkopieren; der nächste Sync übernimmt sie |

**`ZIM_PATHS` umgeht dieses Volume.** Sind dort Pfade eingetragen, liest der Dienst genau diese Dateien:
`active.json` wird nicht gelesen, der Sync-Job verwaltet die Archive nicht, und ein Wechsel braucht einen
Neustart. Der Start warnt ausdrücklich davor. Für den Betrieb `ZIM_PATHS` leer lassen und `ZIM_DIR`
verwenden; `ZIM_PATHS` ist für Entwicklung und Tests gedacht.
| `state` (`STATE_DIR`) | `lehrplan.db`, `wlo_cache.db`, `llm_budget.db`, `templates/` | `lehrplan.db` per Harvest neu erzeugen (rund 25 Minuten); `wlo_cache.db` und `llm_budget.db` sind verzichtbar; `templates/` sichern, falls eigene Templates angelegt wurden (`PUT`/`DELETE /api/v2/templates/{id}` oder `compendium templates save|delete` schreiben dorthin) |

## Zustand prüfen

- `GET /health`: Prozess lebt; `components` zeigt `zim`, `lehrplan_cache`, `edu_sharing` und `llm`
  (Modellprüfung, Tagesverbrauch). Je Modell steht dort, ob es wirklich geladen ist: `matching.embeddings`
  für das Model2Vec-Modell, `entities.ner` für das spaCy-Modell, `qa_models.present` für die beiden Modelle der
  QA-Stufe `models` — ein fehlendes Modell macht die Antworten schwächer, ohne dass eine Anfrage scheitert.
  `qa_models` meldet nur, ob die Dateien da sind: eine Sonde darf keine 1,3 GB in den Speicher ziehen.
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
`KompendiumLlmUnavailable`, `KompendiumLlmBudgetNearlySpent` und `KompendiumLlmFallbacks`. Nach einer Änderung
an den Regeln `promtool test rules monitoring/alerts_test.yml` laufen lassen. Die Sidecars haben keinen eigenen
Endpunkt; ihren Stand melden die Zustandswerte der API aus den Statusdateien. Wer `/metrics` nicht offen lassen
will, setzt `METRICS_TOKEN` und trägt es im Scrape-Job ein (`authorization.credentials_file`).

## Störungen

| Symptom | Ursache und Verhalten | Maßnahme |
|---|---|---|
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
- Zurück auf eine frühere Fassung: Das Image entsteht aus dem Quelltext, also `git checkout <Commit>` und
  `docker compose build && docker compose up -d`. Die Volumes bleiben, wie sie sind. Findet die ältere Fassung
  einen neueren Zustand vor — etwa `lehrplan.db` mit einer anderen Schemaversion —, meldet sie das als
  `cache_unreadable` und ein Harvest baut den Cache neu auf (siehe Störungen); die Archive sind davon nicht
  betroffen.
- Ein neues Embedding-Modell oder eine neue Revision (`MODEL2VEC_REVISION` im Dockerfile) erst nach einer
  Messung mit `compendium eval run` übernehmen; die Zahlen stehen in [eval/README.md](../eval/README.md).
