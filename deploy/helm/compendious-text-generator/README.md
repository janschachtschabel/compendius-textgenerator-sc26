# Helm-Chart „Kompendiale Texte“

Die API und die vier Updater (ZIM-Archive, Lehrpläne, Wikidata- und GND-Index) aus einem Image. Zu jedem Git-Tag
`vX.Y.Z` baut die CI das Image `ghcr.io/janschachtschabel/compendius-textgenerator-sc26:X.Y.Z` und schiebt danach das
Chart mit derselben Version nach `oci://ghcr.io/janschachtschabel/charts/compendious-text-generator`. `appVersion` ist
die Vorgabe für den Image-Tag: Chart und Image einer Version gehören zusammen.

Alle Werte mit Beschreibung stehen in [values.yaml](values.yaml); die Umgebungsvariablen erklärt
`docs/uebergabe/konfiguration.md`, den Betrieb `docs/betrieb.md`.

## Installieren und aktualisieren

```bash
# Geheimnisse außerhalb des Charts; jeder Schlüssel ist optional, ein Token braucht mindestens 16 Zeichen
kubectl -n kompendium create secret generic kompendium-secrets \
  --from-literal=METRICS_TOKEN="$(openssl rand -hex 32)"

# Der Release-Name ist der Präfix aller Ressourcen (hier: compendious-text-generator-zim-updater usw.)
helm upgrade --install compendious-text-generator oci://ghcr.io/janschachtschabel/charts/compendious-text-generator \
  --version 2.26.1 --namespace kompendium --create-namespace --values meine-values.yaml
```

Ein Update ist derselbe Befehl mit der neuen Version. Was ein Release am Betrieb ändert, steht in `docs/betrieb.md`
unter „Updates“.

Der erste Start: `/ready` meldet 503, bis der ZIM-Updater die Pflichtarchive geladen hat (Profil `standard` rund
19 GB). `helm --wait` liefe dabei ab; die erste Installation ohne `--wait` oder mit langer `--timeout`.

## Was gesetzt werden muss

| Wert | Wofür |
|---|---|
| `api.secrets.existingSecret` | Name des Secrets mit `B_API_KEY`, `API_KEYS`, `ADMIN_TOKEN`, `METRICS_TOKEN`, `EDU_SHARING_USER`, `EDU_SHARING_PASSWORD` (jeder Schlüssel optional; hinter der b-api `API_KEYS` und `ADMIN_TOKEN` leer lassen) |
| `persistence.zim.storageClass`, `persistence.state.storageClass` | eine Klasse mit ReadWriteMany (NFSv4.1, CephFS); die Volumes werden von API-Pods und Updatern auf verschiedenen Nodes zugleich eingehängt |
| `networkPolicy.publicFrom`, `networkPolicy.internalFrom` | wer Port 8000 (b-api oder Ingress-Controller) und Port 9000 (Prometheus) erreichen darf; die Vorgaben sind Namespaces `b-api` und `monitoring` |
| `ingress.enabled`, `ingress.hosts`, `ingress.className`, `ingress.tls` | nur, wenn die b-api den Dienst über einen Ingress ruft; ruft sie den Service direkt, bleibt er aus |
| `serviceMonitor.enabled`, `prometheusRule.enabled` und ihre `labels` | mit dem Prometheus Operator; die Labels, nach denen Prometheus wählt |
| `api.env.B_API_BASE_URL`, `api.env.EDU_SHARING_BASE_URL` | Produktion oder Staging, beide zusammen (D106) |

Volume-Rechte: Die Container laufen als uid/gid 10001 mit `fsGroup: 10001`. Übergeht der CSI-Treiber `fsGroup`
(viele NFS- und CephFS-Treiber), legt der Provisioner die Volumes mit 10001:10001 an, oder ein einmaliger Job als
root macht `chown -R 10001:10001` auf beiden Volumes.

## Ports

Port `http` (8000) ist die API; nur er steht im Ingress, jeder Pfad dort geht fest an ihn. Port `internal` (9000)
trägt `/health`, `/ready`, `/metrics` und den Stand der Daten: die Proben und der ServiceMonitor fragen ihn, kein
Ingress führt dorthin, und die NetworkPolicy lässt ihn nur aus `networkPolicy.internalFrom` zu.

## Die Updater: zwei Betriebsarten

Jeder Updater läuft genau einmal, nie als Container im API-Pod. `updaters.mode` wählt:

- **`cronjob`** (Vorgabe): ein CronJob je Updater, der den Befehl einmal ausführt (ohne `--loop`) und endet;
  `concurrencyPolicy: Forbid`, Zeitzone `updaters.timeZone` (`Europe/Berlin`). Bei `helm install` startet je Updater
  sofort ein einmaliger Job (`updaters.initialRun`), damit die Daten nicht bis zum ersten Termin fehlen.
- **`deployment`**: wie bisher und wie in Compose, je Updater ein Deployment mit einem Replikat, Strategie `Recreate`,
  der Befehl mit `--loop` (Intervalle `ZIM_SYNC_INTERVAL` 30 Tage, `LEHRPLAN_CHECK_INTERVAL` 7 Tage,
  `WIKIDATA_CHECK_INTERVAL` und `GND_CHECK_INTERVAL` 1 Tag).

Jeder Updater lässt sich mit `updaters.<name>.enabled` abschalten.

### Der Nachtplan (mode `cronjob`)

| Zeit | Updater | Warum so |
|---|---|---|
| täglich 01:15 | `gnd-updater` | wie die Schleife täglich; prüft, ob die DNB eine neue Ausgabe hat, Neubau in Minuten (rund 65 MB) |
| täglich 02:15 | `wikidata-updater` | wie die Schleife täglich; baut nur, wenn ein neueres Wikipedia-Archiv einen neueren Dump braucht (rund 750 MB, 8 bis 20 Minuten) |
| sonntags 03:15 | `lehrplan-updater` | wie die Schleife wöchentlich; Vollabzug nur bei geänderter Zählung oder nach 30 Tagen, rund 25 Minuten |
| sonntags 04:15 | `zim-updater` | wöchentlich statt alle 30 Tage: eine Prüfung fragt nur den Katalog, geladen wird nur ein neuerer Dump; ein abgebrochener Download wartet eine Woche statt eines Monats, ein abgelöstes Archiv geht nach rund einer Woche |

Eine Stunde Abstand, die kurzen Läufe zuerst: Keine zwei Läufe überlagern sich, auch nicht mit dem größten
Wikidata-Neubau. Ein neues Wikipedia-Archiv vom Sonntag bekommt seinen Wikidata-Index in der Nacht zum Montag.
`activeDeadlineSeconds` beendet einen hängenden Lauf (ZIM 8 h, Lehrpläne und Wikidata 2 h, GND 1 h); `backoffLimit: 2`
wiederholt einen gescheiterten Lauf gleich (Exit-Code 1: Quelle nicht erreichbar, Download abgebrochen, Sperre
belegt), ein Download setzt seine `.part`-Datei fort.

### Was sich mit CronJobs gegenüber der Schleife ändert

- **Wiederholung nach einem Fehler.** Die Schleife versucht es nach einer Stunde wieder; ein CronJob wiederholt bis
  zu zweimal sofort (`backoffLimit`), danach erst zum nächsten Termin.
- **Abgelöste Archive.** Die Schleife löscht ein abgelöstes ZIM-Archiv nach `ZIM_RETENTION_HOURS` (24 h); der CronJob
  erst beim nächsten Lauf, also nach rund einer Woche. Das Volume `zim` (60 Gi) fasst beide Archive (bis rund 38 GB).
- **Anstoßen von Hand.** `POST /api/v2/zim/sync` und `POST /api/v2/lehrplan/harvest` legen eine Trigger-Datei an, die
  nur die Schleife liest; im Cluster gibt es diese Pfade ohnehin nicht (leeres `ADMIN_TOKEN`, Volumes für die API nur
  lesend). Einen Lauf außer der Reihe startet:

  ```bash
  kubectl -n kompendium create job --from=cronjob/compendious-text-generator-zim-updater zim-$(date +%s)
  ```

  Mit einer Option, etwa `--force` für den Lehrplan-Harvest:

  ```bash
  kubectl -n kompendium create job lehrplan-force --dry-run=client -o json \
      --from=cronjob/compendious-text-generator-lehrplan-updater \
    | jq '.spec.template.spec.containers[0].command += ["--force"]' | kubectl apply -f -
  ```

  Den Stand zeigt die API, die die Volumes lesend eingehängt hat:
  `kubectl -n kompendium exec deploy/compendious-text-generator -- compendium zim status` (ebenso
  `lehrplan status`, `wikidata status`, `gnd status`) oder `GET /api/v2/zim/status` am Port 9000.
- **Lebenszeichen.** Die Schleife schreibt stündlich ein Lebenszeichen, ein CronJob nicht. Die Alarme
  `Kompendium*Silent` fehlen darum in der PrometheusRule (`prometheusRule.cronJobDroppedAlerts`); dafür meldet
  `KompendiumUpdaterRunFailed` einen Termin ohne erfolgreichen Lauf (aus kube-state-metrics). Die übrigen Alarme
  (`*Stale`, `*Failed`, `*Missing`, `KompendiumZimSyncErrors`) bleiben.
- **Sperrdateien** bleiben; `Forbid` verhindert zwei Läufe desselben Updaters zusätzlich. Ein abgebrochener Lauf
  lässt seine Sperre liegen, sie verfällt nach 1 h (ZIM), 3 h (Indexe) oder 4 h (Harvest), lange vor dem nächsten
  Termin.

Wechsel zwischen den Betriebsarten: `helm upgrade --set updaters.mode=…`. Die Deployments enden mit SIGTERM (die
Schleife schreibt ihren Status), die CronJobs übernehmen beim nächsten Termin; die Daten bleiben in den Volumes. Der
einmalige Job der Installation läuft beim Wechsel nicht.

Argo CD rendert mit `helm template`, also bei jedem Abgleich wie eine Installation: dort `updaters.initialRun.enabled`
auf `false` setzen und die ersten Läufe mit `kubectl create job --from=cronjob/…` starten.

## Tracing (B3, D115)

Der Dienst liest B3 und W3C, legt ohne Spur eine an und nennt `trace_id`, `span_id` und `service` in jeder
JSON-Logzeile; an b-api und edu-sharing gehen `X-B3-TraceId`, `X-B3-SpanId` und `X-B3-Sampled`. Spans an Jaeger oder
einen anderen Sammler über OTLP/HTTP:

```yaml
tracing:
  serviceName: compendious-text-generator
  otlpEndpoint: http://jaeger-collector.observability:4318
  collectorTo:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: observability
```

`otlpEndpoint` setzt `OTEL_EXPORTER_OTLP_ENDPOINT` und öffnet in der NetworkPolicy der API den Port des Sammlers
(`collectorPort`, 4318); ohne ihn verlassen keine Spans den Dienst.

## Compose bleibt die Alternative

Für einen einzelnen Host bleibt `docker-compose.yml` unverändert unterstützt: dieselben fünf Container mit `--loop`
(entspricht `updaters.mode: deployment`), Volumes `zim` und `state`, Konfiguration über `.env`
(`docs/installation.md`). Chart und Compose nutzen dasselbe Image.

## Prüfen

```bash
helm lint deploy/helm/compendious-text-generator
helm template kt deploy/helm/compendious-text-generator --values deploy/helm/compendious-text-generator/ci/all-on-values.yaml
```

Die CI rendert beide Varianten, prüft sie mit kubeconform und läuft `tests/test_helm_chart.py`, das auch die Version
gegen `pyproject.toml` und `files/alerts.yml` gegen `monitoring/alerts.yml` vergleicht.
