# Installation auf einem frischen Debian 13 („Trixie“) mit Docker

Von der leeren Maschine bis zum ersten Kompendium. Die Anleitung setzt nur ein installiertes Debian 13 und
einen Benutzer mit `sudo` voraus. Betrieb, Störungen und Wiederherstellung stehen in
[betrieb.md](betrieb.md), alle Einstellungen mit ihrer Bedeutung im Abschnitt *Konfiguration* der
[README](../README.md#konfiguration); [.env.example](../.env.example) ist die kommentarfreie Vorlage dazu.

## Was die Maschine braucht

| | Minimum | Empfohlen | warum |
|---|---|---|---|
| CPU | 2 Kerne | 4 Kerne | eine Anfrage belegt einen Worker vollständig (`WEB_CONCURRENCY`, im Image 2) |
| RAM | 4 GB | 8 GB | gemessen am 2026-09-21 mit dem Profil `standard`: rund **1,4 GB je Worker** im Ruhezustand und rund 1,5 GB nach einer Anfrage; am 2026-09-28 die API mit ihren zwei Workern 2,64 GiB. Die vier Sidecars brauchen im Leerlauf je rund 108 MiB, zusammen rund 0,43 GiB (gemessen am 2026-09-28), beim Bau ihrer Indexe mehr (nicht gemessen). Zusammen rund 3,1 GiB und das Betriebssystem: 4 GB tragen den Dienst knapp, 5 GB bequem. Dazu kommt der Seiten-Cache für die Archive, den das System bei Speicherdruck wieder freigibt. Seit D57 fehlt torch: am 2026-09-26 auf dem Entwicklungsrechner im Ruhezustand 1.407 statt 1.559 MiB je Worker. Was auf 2 GB passiert, steht unter Abschnitt 7a |
| Platte | 35 GB | 60 GB | im Betrieb rund 16 GB: das Image für alle fünf Container rund 1,1 GB (gemessen am 2026-09-26; davon 0,3 GB Model2Vec; bis D57 mit torch und den QA-Modellen 2,7 GB), die Archive je nach Profil (siehe unten, `standard` 14,1 GB), der Zustand rund 0,45 GB (`lehrplan.db` 264 MB, `wikidata.db` 133 MB, `gnd.db` 53 MB, gemessen am 2026-09-28), die Protokolle höchstens 0,25 GB. Beim Update des Wikipedia-Archivs liegt das neue (13,6 GB) neben dem alten, bis der ZIM-Updater umschaltet: Spitze rund 30 GB. Danach baut der Wikidata-Updater seinen Index neu und braucht dafür rund 1,5 GB frei. Jedes Update des Images lässt das alte liegen, bis `docker image prune` es entfernt ([betrieb.md](betrieb.md)). Dazu das Betriebssystem |
| Netz | – | – | der Erststart lädt die Archive und drei Dumps der deutschen Wikipedia (rund 750 MB, für die Wikidata-Nummern und die DBpedia-URIs) und zwei Abzüge der DNB (rund 65 MB, für GND-Nummern); danach nur Updates, der Lehrplan-Abzug und optional edu-sharing und die b-api |

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

Die Vorlage läuft ohne Änderung und ohne LLM. Vor dem ersten Start lohnt ein Blick auf diese Zeilen:

| Zeile | Bedeutung |
|---|---|
| `ZIM_PROFILE` | welche Archive geladen werden (Tabelle oben) |
| `ZIM_BOOTSTRAP_DOWNLOAD` | in der Vorlage `true`: der Updater lädt beim ersten Start die fehlenden Pflichtarchive |
| `ADMIN_TOKEN` | leer heißt: die Admin-Endpunkte sind abgeschaltet. Nur setzen, wenn sie gebraucht werden, dann mit mindestens 16 Zeichen, am besten erzeugt (`openssl rand -hex 32`) |
| `API_KEYS`, `METRICS_TOKEN` | auf einem öffentlichen Server setzen, je mindestens 16 Zeichen: ohne sie antworten die Endpunkte mit einem Profil und `/metrics` jedem (Abschnitt 8) |
| `EDU_SHARING_BASE_URL` | welches edu-sharing-Repository Teil 3 liest; Standard Staging, für Produktion `https://redaktion.openeduhub.net/edu-sharing/rest` eintragen. Die b-api folgt dieser Zeile, solange `B_API_BASE_URL` leer bleibt |
| `B_API_KEY` mit `LLM_ENABLED=true` | schaltet die optionale LLM-Schicht frei; ohne beides bleibt alles regelbasiert |

`.env` enthält Zugangsdaten und gehört niemals ins Repository — `.gitignore` hält sie schon draußen.

## 5. Image bauen

```bash
cd /srv/kompendium && sudo -u kompendium docker compose build
```

Der Bau holt die Abhängigkeiten und backt das Embedding-Modell für den Matcher mit ein, damit die Laufzeit
nie den Hugging-Face-Hub braucht. Ohne Modell — kleineres Image, schwächeres Matching —
geht auch `docker compose build --build-arg MODEL2VEC_ID=`.

**Oder gar nicht bauen.** Der Job `publish` in `.github/workflows/ci.yml` veröffentlicht das fertige Image
nach jedem Push auf `main`, dessen Prüfungen grün sind, in die GitHub Container Registry; dann genügt
Schritt 6 ohne Schritt 5. Das Paket ist öffentlich (die Sichtbarkeit stellt man am Paket ein, nicht am
Repository); bei einem privaten Fork meldet sich der Host einmalig an:

```bash
sudo -u kompendium docker login ghcr.io -u <GitHub-Konto> --password-stdin   # Token mit read:packages
```

Der Bau auf der Zielmaschine dauert länger und braucht Platz für die Zwischenschichten; das Ziehen kostet
einmalig rund 1,1 GB. Wer eine eigene Registry nutzt, setzt `IMAGE` auf deren Adresse.

## 6. Erster Start

```bash
sudo -u kompendium docker compose up -d
```

Fünf Container laufen an: die API, der ZIM-Updater, der Lehrplan-Updater, der Wikidata-Updater und der GND-Updater.
Der ZIM-Updater lädt jetzt die Archive des Profils; bei `standard` dauert das je nach Anbindung eine halbe Stunde bis mehrere Stunden.

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
Der Wikidata-Updater lädt drei Dumps der deutschen Wikipedia und baut daraus den Wikidata-Index (`wikidata.db`,
rund zehn Minuten, gemessen 619 s auf dem Entwicklungsrechner, davon gut drei Minuten Download, und rund acht
Minuten auf dem Server am 28.09.2026; die Dumps löscht er danach); bis dahin nennt `/api/v2/entities` keine
Wikidata-Nummern, und `/health` meldet unter `entities.wikidata` noch `"available": false`. Der GND-Updater lädt
die Abzüge der DNB (Sachbegriffe und Geografika) und baut den GND-Index (`gnd.db`, gemessen 78 s, auf dem Server
34 s); bis dahin tragen Artikel ohne Normdaten-Block keine GND.

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

| Aufstellung | Start | Kompendium (Teil 1) |
|---|---|---|
| `WEB_CONCURRENCY=2` (Standard im Image) | der Kernel holt **einen der beiden Worker** noch im Start (`oom_kill 1`), der Dienst läuft einspurig weiter | HTTP 200 nach 8 s |
| `WEB_CONCURRENCY=1` | läuft sauber an, 1,40 GiB von 2 GiB | HTTP 200 nach 4 s, danach 1,47 GiB |

Daraus folgt: 2 GB tragen den Dienst nur mit `WEB_CONCURRENCY=1` —
eine Demo-Aufstellung, keine Betriebsaufstellung, denn eine einzige lange Anfrage blockiert dann alles.
Ein kleineres Archivprofil (`compact`) senkt den Grundbedarf, wurde hier aber nicht gemessen.

**QA-Paare auf so einer Maschine:** Die Regeln (`rule-based`, seit D57 in `llm-free` und `balanced`) brauchen
kein Modell außer dem spaCy-Modell, das ohnehin geladen ist. Die QA-Stufe `models`, die bei diesen Messungen
2 GB nicht überstand, gibt es seit D57 nicht mehr.

Der Spitzenwert lässt sich im laufenden Container nachlesen:

```bash
docker exec <container> sh -c 'cat /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.events'
```

Das gilt für cgroup v2, die Debian 13 verwendet: `memory.peak` ist der Spitzenwert, `oom_kill` in `memory.events`
zählt die Abbrüche. Unter cgroup v1, etwa in Docker Desktop, heißen die Dateien
`/sys/fs/cgroup/memory/memory.max_usage_in_bytes` und `/sys/fs/cgroup/memory/memory.oom_control`.

## 7b. Welche Modelle wie viel Speicher kosten

Im Image stecken zwei Modelle; torch und die beiden QA-Modelle sind mit D57 entfallen. Gemessen am 2026-09-21, jedes
allein in einem frischen Prozess im laufenden Container (`VmRSS` vorher/nachher), damit die Reihenfolge nichts
verfaelscht:

| Modell | auf der Platte | im Speicher | wann geladen |
|---|---|---|---|
| die Anwendung selbst | — | +138 MiB | immer |
| spaCy `de_core_news_md` | 60 MB | **+580 MiB** | immer: Entitaeten und die QA-Regeln |
| Model2Vec `m2v-gte-256-edu` | 322 MB | **+1012 MiB** | beim Start je Worker: `hybrid_light` (Standard) laedt es, sobald `MODEL2VEC_PATH` gesetzt ist — im Image `/models/m2v` |

Model2Vec kostet seine 1,0 GB schon beim Start. Eine eigene Matching-Strategie dafuer gibt es nicht: Die vier sind
`hybrid_light`, `bm25`, `char_tfidf` und `lexicon_only`, und nur `hybrid_light`, der Standard, nutzt das Modell.
Eine andere Strategie in der Anfrage spart deshalb nichts, das Modell ist dann schon geladen. Sparen laesst es sich
nur mit leerem `MODEL2VEC_PATH`; `hybrid_light` rechnet dann ohne Einbettungen und ordnet schlechter zu
(Goldstandard macro-F1 0,39 statt 0,45, `eval/reports/d33_rules_printed.json` gegen `d33_rules_printed_m2v.json`).
Alle vier Profile nutzen `hybrid_light`, `best-quality` und `best-quality-generated` als Rueckfall der LLM-Zuordnung
(D53); das Modell wird also in jedem Profil gebraucht.

## 8. Von außen erreichbar machen

Compose bindet den Port an alle Schnittstellen (`API_BIND`, Vorgabe `0.0.0.0:8000`). Das ist nötig, damit
eine Hosting-Umgebung ihn erreicht: deren Proxy läuft in der Regel nicht im selben Netz-Namensraum und
käme an eine Loopback-Bindung nicht heran. **Die Firewall des Hosts schützt diesen Port nicht.** Docker
veröffentlicht Ports über eigene NAT-Regeln, an denen ufw und die INPUT-Kette nicht vorbeikommen: Ein Port, den
ufw sperrt, ist trotzdem offen. Firewall-Regeln für veröffentlichte Ports gehören in die Kette `DOCKER-USER`.

Der Dienst kennt keine Anmeldung, aber auf einem öffentlichen Server gehören zwei Variablen in die `.env` (oder
in die Variablen des Hosting-Panels):

- `API_KEYS`: ein oder mehrere Schlüssel, kommagetrennt, je mindestens 16 Zeichen (`openssl rand -hex 32`). Dann
  verlangen alle Endpunkte mit einem Profil — `/compendium`, `/knowledge`, `/qa`, `/entities`,
  `/lehrplan/search`, `/nodes` und der Sammlungsüberblick — einen davon im Header `X-API-Key`, sonst 401. Ohne
  Schlüssel kann jeder das gemeinsame LLM-Tagesbudget in Minuten aufbrauchen. `/health`, `/ready`, `/docs`, die
  Templates und die Statusendpunkte bleiben offen. Ein eigener Schlüssel je aufrufender Anwendung lässt sich
  einzeln zurückziehen.
- `METRICS_TOKEN`, ebenfalls mindestens 16 Zeichen: sonst liest jeder `/metrics`.

`ADMIN_TOKEN`, `METRICS_TOKEN` und `API_KEYS` mit weniger als 16 Zeichen lehnt der Dienst beim Start ab; die
Meldung nennt die Variable, nicht ihren Wert. 16 ist das Minimum: 16 zufällige Hex-Zeichen sind 64 Bit und unter
dem Rate-Limit nicht zu erraten. Die Prüfung misst nur die Länge; ein ausgedachter Wert ist auch mit 16 Zeichen
schwächer als ein erzeugter. Länger ist besser, `openssl rand -hex 32` erzeugt 64 Zeichen.

Auf einer Maschine, die nur selbst zugreifen soll, gehört die alte Bindung zurück:
`API_BIND=127.0.0.1:8000`.

Für Zugriff von außen gehört ein Reverse-Proxy davor, der TLS beendet. Steht nginx auf dem Host, bindet
`API_BIND=127.0.0.1:8000` den Port nur an Loopback; ohne diese Zeile bleibt Port 8000 neben dem Proxy offen. Dann
gehört zwingend auch `FORWARDED_ALLOW_IPS` auf die Adresse gesetzt, von der der Proxy im Container ankommt —
sonst sehen alle Aufrufer dieselbe Adresse und teilen sich ein Rate-Limit-Fenster. Das ist nicht `127.0.0.1`:
Auch ein Proxy auf dem Host kommt über den veröffentlichten Port vom Gateway des Compose-Netzes (am 27.09.
gemessen: `172.23.0.1`). `docker network inspect kompendium_default --format '{{(index .IPAM.Config 0).Gateway}}'`
nennt es; ein Proxy in einem eigenen Container hat eine Adresse aus dem Docker-Netz (meist `172.16.0.0/12`).

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;   # eine Anfrage darf REQUEST_TIMEOUT_S lang dauern
}
```

Drei Zeilen in `.env` gehören dann dazu:

- `API_BIND=127.0.0.1:8000`, damit Port 8000 nur über den Proxy erreichbar ist.
- `FORWARDED_ALLOW_IPS` auf die Gateway-Adresse von oben setzen. Sonst sieht der Dienst nur diese Adresse, und
  alle Aufrufer teilen sich **ein** Rate-Limit-Fenster.
- `RATE_LIMIT` prüfen (Standard 60 Anfragen je Minute und Aufrufer, je Worker).

## 9. Updates und Sicherung

```bash
cd /srv/kompendium && sudo -u kompendium git pull && sudo -u kompendium docker compose build && sudo -u kompendium docker compose up -d
```

Wer das fertige Image zieht, statt zu bauen: `git pull`, dann `docker compose pull && docker compose up -d`. Die
Archive bleiben dabei im Volume; der Updater tauscht sie eigenständig gegen neue Ausgaben. Was ein Update für den
Betrieb ändert — neue Dienste, geänderte Vorgaben —, steht in [betrieb.md](betrieb.md) unter „Updates“. Ein
Hosting-Panel übernimmt eine neue `docker-compose.yml` nicht von selbst, wenn es nur das Image neu zieht.

Sichern muss man nur das Volume `state` — und dort genau genommen nur eigene Templates: `lehrplan.db` baut
ein Harvest neu auf, `wikidata.db` der Wikidata-Updater, `gnd.db` der GND-Updater, `wlo_cache.db` und `llm_budget.db` sind verzichtbar.

Das Archiv gehört neben den Checkout, nicht hinein: dort landete es in `git status` und im Build-Kontext.

```bash
sudo install -d -o kompendium -g kompendium /srv/kompendium-backup
sudo -u kompendium docker run --rm -v kompendium_state:/state -v /srv/kompendium-backup:/backup alpine tar czf /backup/state.tar.gz -C /state .
```

Zurückspielen bei angehaltenen Diensten; `tar` stellt die Eigentümer wieder her, der Dienst läuft als UID 10001:

```bash
cd /srv/kompendium && sudo -u kompendium docker compose stop
sudo -u kompendium docker run --rm -v kompendium_state:/state -v /srv/kompendium-backup:/backup alpine tar xzf /backup/state.tar.gz -C /state
sudo -u kompendium docker compose start
```

Compose benennt die Volumes nach dem Verzeichnis: aus `/srv/kompendium` wird `kompendium_state`. `docker volume ls` zeigt die tatsächlichen Namen.

## 10. Überwachung

Prometheus liegt als Compose-Profil bei und schreibt in ein eigenes Volume:

```bash
sudo -u kompendium docker compose --profile monitoring up -d prometheus
```

Die Alarmregeln stehen in `monitoring/`, die Metriken unter `/metrics` (mit `METRICS_TOKEN` nur gegen
Bearer-Token). Was die einzelnen Alarme bedeuten, steht in [betrieb.md](betrieb.md).
