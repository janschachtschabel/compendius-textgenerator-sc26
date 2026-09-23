# Installation auf einem frischen Debian 13 („Trixie“) mit Docker

Von der leeren Maschine bis zum ersten Kompendium. Die Anleitung setzt nur ein installiertes Debian 13 und
einen Benutzer mit `sudo` voraus. Betrieb, Störungen und Wiederherstellung stehen in
[betrieb.md](betrieb.md), alle Einstellungen mit ihrer Bedeutung im Abschnitt *Konfiguration* der
[README](../README.md#konfiguration); [.env.example](../.env.example) ist die kommentarfreie Vorlage dazu.

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

**Oder gar nicht bauen.** `.github/workflows/publish.yml` veröffentlicht das fertige Image bei jedem Push
auf `main` in die GitHub Container Registry; dann genügt Schritt 6 ohne Schritt 5. Das Paket ist so
sichtbar wie das Repository — bei einem privaten Repository meldet sich der Host einmalig an:

```bash
sudo -u kompendium docker login ghcr.io -u <GitHub-Konto> --password-stdin   # Token mit read:packages
```

Der Bau auf der Zielmaschine dauert länger und braucht Platz für die Zwischenschichten; das Ziehen kostet
einmalig 2,74 GB. Wer eine eigene Registry nutzt, setzt `IMAGE` auf deren Adresse.

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

**Was auf so einer Maschine trotzdem geht:** `method: "parse-based"`. Die Stufe braucht nur das spaCy-Modell, das ohnehin geladen ist, kostet also keinen zusaetzlichen Speicher — und liefert gemessen ueber 172 Saetze vierer Kompendien 33 Fragen statt der 8 der Vorlagen, bei rund 4 ms je Satz. Auf 2 GB ist sie damit der einzige Weg zu mehr als einer Handvoll duenner Paare.

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
| Model2Vec `m2v-gte-256-edu` | 322 MB | **+1012 MiB** | beim Start je Worker: `hybrid_light` (Standard) laedt es, sobald `MODEL2VEC_PATH` gesetzt ist — im Image `/models/m2v` |
| `dehio/german-qg-t5-quad` + `deepset/gelectra-base-germanquad` | 637 MB | **+1728 MiB** | nur bei `method: "models"` am QA-Endpunkt, faul und je Worker |
| dieselben beim Erzeugen | — | **+190 MiB** Spitze | zusaetzlich waehrend der Anfrage: acht Saetze zu je vier Strahlen rechnen gleichzeitig (`BATCH_SIZE` in `app/synthesis/qa_models.py`) |

Wer `method: "models"` nie anfragt, zahlt dessen 1,7 GB nie. Model2Vec dagegen kostet seine 1,0 GB schon beim
Start. Eine eigene Matching-Strategie dafuer gibt es nicht: Die vier sind `hybrid_light`, `bm25`, `char_tfidf` und
`lexicon_only`, und nur `hybrid_light`, der Standard, nutzt das Modell. Eine andere Strategie in der Anfrage spart
deshalb nichts, das Modell ist dann schon geladen. Sparen laesst es sich nur mit leerem `MODEL2VEC_PATH`;
`hybrid_light` rechnet dann ohne Einbettungen und ordnet schlechter zu (Goldstandard macro-F1 0,39 statt 0,45,
`eval/reports/d33_rules_printed.json` gegen `d33_rules_printed_m2v.json`). Wer stattdessen `MATCHER_DEFAULT`
umstellt, verschiebt das Laden nur: Die erste Anfrage, die `hybrid_light` verlangt, laedt das Modell in ihrem
Worker nach.

**Halbe Genauigkeit spart Platte, nicht Speicher.** Die beiden QA-Modelle liegen als float16 im Image
(das hat es von 3,40 auf 2,74 GB gebracht), werden beim Laden aber bewusst auf float32 zurueckgerechnet:
halbe Genauigkeit rechnet auf einer CPU teils gar nicht und teils falsch. Aus 637 MB auf der Platte
werden so rund 1,3 GB Gewichte im Speicher. Wer nach dem Image-Umfang plant, plant den Speicher zu klein.

## 8. Von außen erreichbar machen

Compose bindet den Port an alle Schnittstellen (`API_BIND`, Vorgabe `0.0.0.0:8000`). Das ist nötig, damit
eine Hosting-Umgebung ihn erreicht: deren Proxy läuft in der Regel nicht im selben Netz-Namensraum und
käme an eine Loopback-Bindung nicht heran. **Der Schutz ist damit die Firewall des Hosts** — der Dienst
selbst kennt weder Anmeldung noch CORS.

Auf einer Maschine, die nur selbst zugreifen soll, gehört die alte Bindung zurück:
`API_BIND=127.0.0.1:8000`.

Für Zugriff von außen gehört ein Reverse-Proxy davor, der TLS beendet. Dann gehört zwingend auch
`FORWARDED_ALLOW_IPS` auf das Netz dieses Proxys gesetzt — sonst sehen alle Aufrufer dieselbe Adresse und
teilen sich ein Rate-Limit-Fenster. Steht der Proxy in einem eigenen Container, ist seine Adresse die des
Docker-Netzes (meist `172.16.0.0/12`), nicht `127.0.0.1`.

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
