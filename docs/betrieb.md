# Betrieb der Kompendium-API

Kurzes Handbuch für Betrieb, Störungen und Wiederherstellung. Architektur und Entscheidungen stehen in
[PLAN.md](../PLAN.md), alle Einstellungen in [.env.example](../.env.example).

## Prozesse und Volumes

| Prozess | Befehl | Aufgabe |
|---|---|---|
| `api` | `uvicorn app.main:create_app --factory` (Worker: `WEB_CONCURRENCY`, im Image 2) | beantwortet Anfragen, lädt nie Archive herunter |
| `zim-updater` | `compendium zim sync --loop` | Kiwix-Katalog prüfen, Dumps laden, `active.json` umschalten, alte Dateien löschen |
| `lehrplan-updater` | `compendium lehrplan harvest --loop` | MEM-Lehrpläne in `lehrplan.db` ziehen und atomar tauschen |

| Volume | Inhalt | Wiederherstellung |
|---|---|---|
| `zim` (`ZIM_DIR`) | ZIM-Archive, `active.json`, `sync_status.json` | neu laden lassen (`ZIM_BOOTSTRAP_DOWNLOAD=true`) oder Dateien hineinkopieren; der nächste Sync übernimmt sie |
| `state` (`STATE_DIR`) | `lehrplan.db`, `wlo_cache.db`, `llm_budget.db`, `templates/` | `lehrplan.db` per Harvest neu erzeugen (rund 25 Minuten); `wlo_cache.db` und `llm_budget.db` sind verzichtbar; `templates/` sichern, falls eigene Templates angelegt wurden |

## Zustand prüfen

- `GET /health`: Prozess lebt; `components` zeigt `zim`, `lehrplan_cache`, `edu_sharing` und `llm`
  (Modellprüfung, Tagesverbrauch). Ruft keinen fremden Dienst auf.
- `GET /ready`: 200 erst, wenn alle Pflichtarchive des Profils vorliegen, sonst 503.
- `GET /api/v2/zim/status`, `GET /api/v2/lehrplan/status`: Archive, letzter Sync, Cache-Stand.
- Die Sidecars haben keinen HTTP-Server und keinen Healthcheck; ihren Stand zeigen `sync_status.json` und
  `GET /api/v2/zim/progress` (Admin) sowie die Logs.

## Störungen

| Symptom | Ursache und Verhalten | Maßnahme |
|---|---|---|
| Hybrid-Anfragen kommen als `mode: rule-based` mit `mode_requested` zurück | b-api nicht erreichbar, Modell fehlt in `/models`, Tagesbudget erschöpft oder Schutzschalter aktiv (60 s nach einem Verbindungsfehler) | `components.llm` in `/health` und `audit.llm.note` lesen; die Modellprüfung wiederholt sich höchstens alle zehn Minuten von selbst |
| Teil 3 meldet, dass der Sammlungsüberblick nicht erstellt werden konnte | edu-sharing antwortet nicht oder mit Fehler; Details stehen im Log, nicht in der Antwort | Repository prüfen; `GET /api/v2/collections/{id}/overview` antwortet 502, wenn schon die Sammlung nicht lesbar ist, sonst 200 mit `available: false` |
| Teil 2 enthält nur den Hinweistext | `lehrplan.db` fehlt (`reason: cache_missing`) oder ist nicht lesbar (`cache_unreadable`) | `POST /api/v2/lehrplan/harvest` (Admin) oder `compendium lehrplan harvest --force` im Sidecar |
| 429 mit `Retry-After` | `RATE_LIMIT` je Client und Minute überschritten | hinter einem Proxy `FORWARDED_ALLOW_IPS` setzen, sonst teilen sich alle Clients ein Fenster |
| `/ready` bleibt 503 | Pflichtarchive fehlen oder `active.json` ist beschädigt (steht im Log) | `compendium zim status`; Sync anstoßen (`POST /api/v2/zim/sync`, Admin) |
| ZIM-Volume läuft voll | abgelöste Dumps bleiben `ZIM_RETENTION_HOURS` liegen; `.part`-Dateien älterer Dumps räumt der Sync weg | `DELETE /api/v2/zim/{datei}` (Admin) für nicht aktive Dateien; Volume für zwei Generationen des Profils auslegen (Profil `standard`: rund 2 × 14 GB) |
| Download bricht ab | `.part` bleibt für den nächsten Lauf; ein Spiegel, der mehr als die angekündigte Größe schickt, wird abgebrochen und die `.part` gelöscht | Log des Updaters; der nächste Lauf setzt fort |

## Regeln

- Keinen zweiten Sync von Hand starten, solange der Sidecar lädt: Es gibt keine Sperre gegen zwei
  gleichzeitige Läufe, beide würden in dieselbe `.part` schreiben. Einen Lauf stößt man über
  `POST /api/v2/zim/sync` (Admin) oder die Trigger-Datei an.
- Der Dienst hat keine Anmeldung für die öffentlichen Endpunkte; er gehört hinter ein Gateway. Admin-Endpunkte
  sind nur mit `ADMIN_TOKEN` aktiv.
- `B_API_KEY` und `EDU_SHARING_PASSWORD` kommen nur aus der Umgebung und erscheinen in keiner Meldung.
- Ein neues Embedding-Modell oder eine neue Revision (`MODEL2VEC_REVISION` im Dockerfile) erst nach einer
  Messung mit `compendium eval run` übernehmen; die Zahlen stehen in [eval/README.md](../eval/README.md).
