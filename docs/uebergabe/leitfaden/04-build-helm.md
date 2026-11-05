# 4. Build und Helm

[Leitfaden](../leitfaden-dienste.md) · zurück: [3. Betrieb](03-betrieb.md) · weiter: [5. Dienste kombinieren](05-kestra.md)

## Repository und CI

- [ ] Code in einem Repository, auf das T6 Zugriff hat.
- [ ] Die CI prüft (Lint, Typen, Tests, Abhängigkeiten auf bekannte Lücken) und baut die Images automatisch.
- [ ] **Tags:** Produktion nur mit getaggten Versionen (SemVer, `vX.Y.Z`); `latest` nur für Test und Staging.
- [ ] Abhängigkeiten aktuell halten (Dependabot oder Renovate), Basis-Image mit Digest pinnen.

## Kleine Images

- [ ] Schlankes Basis-Image (`python:3.x-slim`), **Multi-Stage-Build** (Compiler bleiben draußen).
- [ ] `.dockerignore` für Tests, Notebooks, lokale Daten; nur Laufzeit-Abhängigkeiten installieren.
- [ ] **Nicht als root**, Dateisystem nur lesend, beschreibbar nur `/tmp` (emptyDir).
- [ ] Daten und Modelle auf Volumes (Kapitel 3); wer Modelle im Image lässt, begründet es und nennt die Größe.
- [ ] Prüfen: `docker image ls` (entpackt) und die Summe der Schichten in der Registry (Download).

## Helm-Chart je Tag

- [ ] Chart im Repository (`deploy/helm/<dienst-id>`), `version` = `appVersion` = Version des Dienstes.
- [ ] Die CI prüft es (`helm lint --strict`, `helm template`, kubeconform) und veröffentlicht zu jedem Tag das Image
      und das Chart in derselben Version (OCI-Registry). So passt bei Updates die Konfiguration zum Image.
- [ ] **`values.yaml` kommentiert** jeden Wert (`## @param …`): Image (Tag, `imagePullSecrets`), Ressourcen, Proben,
      Ingress mit Beispiel-Host, Secrets (nur Namen, nie Werte), Env, Volumes, NetworkPolicy, ServiceMonitor,
      PrometheusRule, CronJobs, Autoscaling.
- [ ] **Pod Security „restricted“:** `runAsNonRoot`, `readOnlyRootFilesystem`, `drop: [ALL]`,
      `seccompProfile: RuntimeDefault`.
- [ ] **Optionale Teile abschaltbar** (Datenbank, Redis, Worker, Updater, Tracing).
- [ ] **NetworkPolicy** liefert der Dienst mit: wer ihn erreichen darf, was er selbst erreichen muss.
- [ ] **Docker Compose** als Referenz für einen Host, mit demselben Image, weiter gepflegt.
- [ ] Ein Test hält die Version des Charts gleich der des Dienstes.

## Registry und Pull-Secrets

- [ ] Nach dem ersten Push prüfen, ob Image und Chart ohne Login abrufbar sind (neue Pakete sind oft privat); sonst
      `imagePullSecrets` im Chart vorsehen.
- [ ] Für die Produktion spiegelt die Plattform die Images in ihre Registry (Harbor) – Pfad im Chart einstellbar.

## Praxis aus „Kompendiale Texte“

- Ein Tag `vX.Y.Z` baut `:X.Y.Z`, `:X.Y` und das Chart `X.Y.Z`; die CI prüft danach, dass beide ohne Login abrufbar
  sind.
- Wichtige Values: `image.tag`, `api.resources`, `api.env` (b-api), `api.secrets.existingSecret`,
  `persistence.*.storageClass`, `networkPolicy.publicFrom`/`internalFrom`, `ingress.hosts`, `updaters.mode`,
  `tracing.otlpEndpoint`.
- Image 577 MB komprimiert, davon 304 MB Modelle; ohne Modelle rund 275 MB.

Muster: [deploy/helm/compendious-text-generator](../../../deploy/helm/compendious-text-generator/), Job `chart` in
`.github/workflows/ci.yml`.
