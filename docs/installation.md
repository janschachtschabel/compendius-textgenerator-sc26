# Installation auf einem frischen Debian 13 („Trixie“) mit Docker

Von der leeren Maschine bis zum ersten Kompendium. Die Anleitung setzt nur ein installiertes Debian 13 und
einen Benutzer mit `sudo` voraus. Betrieb, Störungen und Wiederherstellung stehen in
[betrieb.md](betrieb.md), alle Einstellungen in [.env.example](../.env.example).

## Was die Maschine braucht

| | Minimum | Empfohlen | warum |
|---|---|---|---|
| CPU | 2 Kerne | 4 Kerne | eine Anfrage belegt einen Worker vollständig (`WEB_CONCURRENCY`, im Image 2) |
| RAM | 4 GB | 8 GB | gemessen am 2026-09-21 mit dem Profil `standard`: rund **1,4 GB je Worker** im Ruhezustand und rund 1,5 GB nach einer Anfrage. Dazu kommt der Seiten-Cache für die Archive, den das System bei Speicherdruck wieder freigibt. Die QA-Stufe `models` lädt bei ihrer ersten Anfrage rund 1,3 GB je Worker nach — wer sie nie anfragt, zahlt das nie. Was auf 2 GB passiert, steht unter Abschnitt 7a |
| Platte | 25 GB | 60 GB | Image rund 2,7 GB (gemessen; davon 0,9 GB Modelle und 0,8 GB torch), Archive je nach Profil (siehe unten), Zustand wenige hundert MB, dazu Reserve für den Wechsel auf ein neues Archiv |
| Netz | – | – | der Erststart lädt die Archive; danach nur Updates, der Lehrplan-Abzug und optional edu-sharing und die b-api |

Die Archivgröße bestimmt das Profil (`ZIM_PROFILE`, Manifest in `config/zim_subscriptions.yaml`):

| Profil | Inhalt | Größe |
|---|---|---|
| `compact` | Wikipedia-Top-Artikel und Klexikon | rund 1,4 GB |
| `standard` | vollständige deutsche Wikipedia ohne Bilder und Klexikon | rund 14,1 GB |
| `extended` | `standard` plus Wikibooks und Wikiversity | rund 18,1 GB |

Für einen ersten Test genügt `compact`; die Platte oben ist für `standard` gerechnet.

## 1. System vorbereiten

```bash
sudo apt update && sudo apt upgrade -y && sudo apt install -y ca-certificates curl git
```

## 2. Docker aus dem Archiv von Docker installieren

Debian 13 heißt `trixie`; Docker liefert dafür Pakete für amd64 und arm64. Das Archiv von Docker bringt
Buildx und Compose als Plugin mit — beides braucht der Bau.

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

```bash
sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

```bash
sudo systemctl enable --now docker && docker compose version
```

`systemctl enable` sorgt zusammen mit `restart: unless-stopped` in der Compose-Datei dafür, dass die
Container nach einem Neustart der Maschine von selbst wieder laufen. Eine eigene systemd-Unit braucht es nicht.

## 3. Konto und Verzeichnis für den Dienst

```bash
sudo adduser --disabled-password --gecos "Kompendium-API" kompendium
sudo usermod -aG docker kompendium
```

> **Wer in der Gruppe `docker` ist, ist faktisch root auf dieser Maschine** — die Gruppe erlaubt es, jedes
> Verzeichnis des Wirts in einen Container zu hängen. Auf einer Maschine, die noch andere Dienste trägt,
> deshalb entweder nur Administratoren in die Gruppe nehmen und die Container per `sudo` starten, oder
> [rootless Docker](https://docs.docker.com/engine/security/rootless/) einrichten.

## 4. Quelltext holen und Konfiguration anlegen

```bash
sudo install -d -o kompendium -g kompendium /srv/kompendium
sudo -u kompendium git clone https://github.com/janschachtschabel/compendius-textgenerator-sc26.git /srv/kompendium
```

```bash
cd /srv/kompendium && sudo -u kompendium cp .env.example .env && sudo -u kompendium chmod 600 .env
```

Die Vorlage läuft ohne Änderung und ohne LLM. Vor dem ersten Start lohnt ein Blick auf vier Zeilen:

| Zeile | Bedeutung |
|---|---|
| `ZIM_PROFILE` | welche Archive geladen werden (Tabelle oben) |
| `ZIM_BOOTSTRAP_DOWNLOAD` | in der Vorlage `true`: der Updater lädt beim ersten Start die fehlenden Pflichtarchive |
| `ADMIN_TOKEN` | leer heißt: die Admin-Endpunkte sind abgeschaltet. Nur setzen, wenn sie gebraucht werden |
| `EDU_SHARING_BASE_URL` | welches edu-sharing-Repository Teil 3 liest; Standard Staging, Produktion steht auskommentiert daneben. Die b-api folgt dieser Zeile, solange `B_API_BASE_URL` leer bleibt |
| `B_API_KEY` mit `LLM_ENABLED=true` | schaltet die optionale LLM-Schicht frei; ohne beides bleibt alles regelbasiert |

`.env` enthält Zugangsdaten und gehört niemals ins Repository — `.gitignore` hält sie schon draußen.

## 5. Image bauen

```bash
cd /srv/kompendium && sudo -u kompendium docker compose build
```

Der Bau holt die Abhängigkeiten und backt das Embedding-Modell für den Matcher mit ein, damit die Laufzeit
nie den Hugging-Face-Hub braucht. Ohne Modell — kleineres Image, schwächeres Matching —
geht auch `docker compose build --build-arg MODEL2VEC_ID=`.

## 6. Erster Start

```bash
sudo -u kompendium docker compose up -d
```

Drei Container laufen an: die API, der ZIM-Updater und der Lehrplan-Updater. Der Updater lädt jetzt die
Archive des Profils; bei `standard` dauert das je nach Anbindung eine halbe Stunde bis mehrere Stunden.

```bash
sudo -u kompendium docker compose logs -f zim-updater
```

Der Fortschritt lässt sich auch am Dienst ablesen: `/health` antwortet sofort, `/ready` nennt unter
`missing_required` die Archive, auf die er noch wartet, und meldet erst danach `"ready": true`.

```bash
curl -fsS http://127.0.0.1:8000/ready
```

Parallel zieht der Lehrplan-Updater die Lehrpläne aus dem MEM-Endpunkt in den Zustand (`lehrplan.db`,
rund 25 Minuten). Teil 2 eines Kompendiums bleibt bis dahin leer, Teil 1 funktioniert davon unabhängig.

## 7. Prüfen, dass wirklich etwas herauskommt

```bash
curl -fsS -X POST http://127.0.0.1:8000/api/v2/compendium -H 'Content-Type: application/json' -d '{"topic":"Optik","parts":["world"],"target_length":6000}' | head -c 600
```

Die Antwort enthält `markdown` mit dem Kompendium, `sections` mit den Bausteinen, `sources` mit den Belegen
und `parts_status` mit dem Ergebnis je Teil. Dauert eine Anfrage länger als erwartet: Jede Anfrage belegt einen Worker für ihre ganze Laufzeit,
mehr gleichzeitige Anfragen brauchen also mehr Worker (`WEB_CONCURRENCY`) und entsprechend mehr RAM.

## 7a. Kleine Maschinen: was auf 2 GB passiert

Gemessen am 2026-09-21 im Image `compendious-text-fastapi:local`, Archive des Profils `standard`
(13,6 GB Wikipedia plus Klexikon), harte Grenze `--memory 2g --memory-swap 2g --cpus 2`:

| Aufstellung | Start | Kompendium (Teil 1) | QA-Stufe `models` |
|---|---|---|---|
| `WEB_CONCURRENCY=2` (Standard im Image) | der Kernel holt **einen der beiden Worker** noch im Start (`oom_kill 1`), der Dienst läuft einspurig weiter | HTTP 200 nach 8 s | **keine Antwort**, zweiter Worker getötet |
| `WEB_CONCURRENCY=1` | läuft sauber an, 1,40 GiB von 2 GiB | HTTP 200 nach 4 s, danach 1,47 GiB | **Container beendet**, Exit 137 |

Daraus folgt: 2 GB tragen den Dienst nur mit `WEB_CONCURRENCY=1` und **ohne** die Stufe `models` —
eine Demo-Aufstellung, keine Betriebsaufstellung, denn eine einzige lange Anfrage blockiert dann alles.
Wer die Modellstufe anbieten will, braucht die 4 GB aus der Tabelle oben. Ein kleineres Archivprofil
(`compact`) senkt den Grundbedarf, wurde hier aber nicht gemessen.

Der Spitzenwert lässt sich im laufenden Container nachlesen:

```bash
docker exec <container> sh -c 'cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes /sys/fs/cgroup/memory/memory.oom_control'
```

## 7b. Welche Modelle wie viel Speicher kosten

Im Image stecken vier Modelle. Gemessen am 2026-09-21, jedes allein in einem frischen Prozess im
laufenden Container (`VmRSS` vorher/nachher), damit die Reihenfolge nichts verfaelscht:

| Modell | auf der Platte | im Speicher | wann geladen |
|---|---|---|---|
| torch (nur die Bibliothek) | 0,8 GB | +209 MiB | sobald irgendein Modell kommt |
| die Anwendung selbst | — | +138 MiB | immer |
| spaCy `de_core_news_md` | 60 MB | **+580 MiB** | immer: Entitaeten und die Antwortkandidaten der Stufe `models` |
| Model2Vec `m2v-gte-256-edu` | 322 MB | **+1012 MiB** | nur bei Matching-Strategie `model2vec` |
| `dehio/german-qg-t5-quad` + `deepset/gelectra-base-germanquad` | 637 MB | **+1728 MiB** | nur bei `method: "models"` am QA-Endpunkt, faul und je Worker |

Wer `method: "models"` nie anfragt, zahlt dessen 1,7 GB nie. Wer eine andere Matching-Strategie als
`model2vec` waehlt, zahlt dessen 1,0 GB nie.

**Halbe Genauigkeit spart Platte, nicht Speicher.** Die beiden QA-Modelle liegen als float16 im Image
(das hat es von 3,40 auf 2,74 GB gebracht), werden beim Laden aber bewusst auf float32 zurueckgerechnet:
halbe Genauigkeit rechnet auf einer CPU teils gar nicht und teils falsch. Aus 637 MB auf der Platte
werden so rund 1,3 GB Gewichte im Speicher. Wer nach dem Image-Umfang plant, plant den Speicher zu klein.

## 8. Von außen erreichbar machen

Compose veröffentlicht den Port absichtlich nur auf `127.0.0.1`. Für Zugriff von außen gehört ein
Reverse-Proxy davor, der TLS beendet — der Dienst selbst kennt weder Anmeldung noch CORS.

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;   # eine Anfrage darf REQUEST_TIMEOUT_S lang dauern
}
```

Zwei Zeilen in `.env` gehören dann dazu:

- `FORWARDED_ALLOW_IPS` auf die Adresse des Proxys setzen. Sonst sieht der Dienst nur dessen Adresse, und
  alle Aufrufer teilen sich **ein** Rate-Limit-Fenster.
- `RATE_LIMIT` prüfen (Standard 60 Anfragen je Minute und Aufrufer, je Worker).

## 9. Updates und Sicherung

```bash
cd /srv/kompendium && sudo -u kompendium git pull && sudo -u kompendium docker compose build && sudo -u kompendium docker compose up -d
```

Die Archive bleiben dabei im Volume; der Updater tauscht sie eigenständig gegen neue Ausgaben.

Sichern muss man nur das Volume `state` — und dort genau genommen nur eigene Templates: `lehrplan.db` baut
ein Harvest neu auf, `wlo_cache.db` und `llm_budget.db` sind verzichtbar.

```bash
sudo -u kompendium docker run --rm -v kompendium_state:/state -v "$PWD":/backup alpine tar czf /backup/state.tar.gz -C /state .
```

Compose benennt die Volumes nach dem Verzeichnis: aus `/srv/kompendium` wird `kompendium_state`. `docker volume ls` zeigt die tatsächlichen Namen.

## 10. Überwachung

Prometheus liegt als Compose-Profil bei und schreibt in ein eigenes Volume:

```bash
sudo -u kompendium docker compose --profile monitoring up -d prometheus
```

Die Alarmregeln stehen in `monitoring/`, die Metriken unter `/metrics` (mit `METRICS_TOKEN` nur gegen
Bearer-Token). Was die einzelnen Alarme bedeuten, steht in [betrieb.md](betrieb.md).
