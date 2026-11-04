{{/* Name des Charts */}}
{{- define "kompendium.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Voller Name: Release und Chart, höchstens 63 Zeichen */}}
{{- define "kompendium.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/* Chart und Version für das Label helm.sh/chart */}}
{{- define "kompendium.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Labels jeder Ressource */}}
{{- define "kompendium.labels" -}}
helm.sh/chart: {{ include "kompendium.chart" . }}
{{ include "kompendium.selectorLabels" . }}
app.kubernetes.io/version: {{ include "kompendium.imageTag" . | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/* Labels, nach denen Services, Deployments und NetworkPolicies wählen */}}
{{- define "kompendium.selectorLabels" -}}
app.kubernetes.io/name: {{ include "kompendium.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* Tag des Images: image.tag, sonst die appVersion des Charts */}}
{{- define "kompendium.imageTag" -}}
{{- .Values.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/* Image mit Tag oder Digest */}}
{{- define "kompendium.image" -}}
{{- if .Values.image.digest }}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest }}
{{- else }}
{{- printf "%s:%s" .Values.image.repository (include "kompendium.imageTag" .) }}
{{- end }}
{{- end }}

{{/* Ressourcenname der API */}}
{{- define "kompendium.apiName" -}}
{{- include "kompendium.fullname" . }}
{{- end }}

{{/* Name der gemeinsamen und der API-ConfigMap */}}
{{- define "kompendium.envConfigMap" -}}
{{- printf "%s-env" (include "kompendium.fullname" . | trunc 59 | trimSuffix "-") }}
{{- end }}
{{- define "kompendium.apiEnvConfigMap" -}}
{{- printf "%s-api-env" (include "kompendium.fullname" . | trunc 55 | trimSuffix "-") }}
{{- end }}

{{/* Kubernetes-Name eines Updaters aus seinem Schlüssel in den Values (zimUpdater -> zim-updater) */}}
{{- define "kompendium.updaterKind" -}}
{{- . | kebabcase }}
{{- end }}

{{/* Ressourcenname eines Updaters, höchstens 52 Zeichen (Grenze eines CronJobs). Aufruf: (dict "root" $ "key" "zimUpdater") */}}
{{- define "kompendium.updaterName" -}}
{{- $kind := include "kompendium.updaterKind" .key }}
{{- printf "%s-%s" (include "kompendium.fullname" .root | trunc (int (sub 51 (len $kind))) | trimSuffix "-") $kind }}
{{- end }}

{{/* Name des PVC eines Volumes. Aufruf: (dict "root" $ "volume" "zim") */}}
{{- define "kompendium.claimName" -}}
{{- $p := index .root.Values.persistence .volume }}
{{- if $p.existingClaim }}
{{- $p.existingClaim }}
{{- else }}
{{- printf "%s-%s" (include "kompendium.fullname" .root | trunc 57 | trimSuffix "-") .volume }}
{{- end }}
{{- end }}

{{/* Name der Templates-ConfigMap */}}
{{- define "kompendium.templatesConfigMap" -}}
{{- if .Values.templates.files }}
{{- printf "%s-templates" (include "kompendium.fullname" . | trunc 53 | trimSuffix "-") }}
{{- else }}
{{- .Values.templates.configMap }}
{{- end }}
{{- end }}

{{/* Felder jedes Pods: Pull-Secrets, Service-Links, Service-Account, Sicherheit, Platzierung */}}
{{- define "kompendium.podCommon" -}}
{{- with .Values.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
enableServiceLinks: {{ .Values.enableServiceLinks }}
automountServiceAccountToken: {{ .Values.automountServiceAccountToken }}
{{- with .Values.serviceAccountName }}
serviceAccountName: {{ . }}
{{- end }}
{{- with .Values.podSecurityContext }}
securityContext:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.affinity }}
affinity:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}

{{/* Annotationen und Labels jedes Pods */}}
{{- define "kompendium.podMeta" -}}
{{- with .root.Values.podAnnotations }}
annotations:
  {{- toYaml . | nindent 2 }}
{{- end }}
labels:
  {{- include "kompendium.selectorLabels" .root | nindent 2 }}
  app.kubernetes.io/component: {{ .component }}
  {{- with .root.Values.podLabels }}
  {{- toYaml . | nindent 2 }}
  {{- end }}
{{- end }}

{{/* Prüft Werte, die das Chart nicht zulässt */}}
{{- define "kompendium.validate" -}}
{{- if not (has .Values.updaters.mode (list "cronjob" "deployment")) }}
{{- fail (printf "updaters.mode muss cronjob oder deployment sein, nicht %q" .Values.updaters.mode) }}
{{- end }}
{{- if or (not .Values.api.internalPort) (eq (int .Values.api.internalPort) (int .Values.api.port)) }}
{{- fail "api.internalPort muss gesetzt sein und sich von api.port unterscheiden: Proben und /metrics gehören nicht an den Port des Ingress" }}
{{- end }}
{{- end }}

{{/*
Pod-Spec eines Updaters, für Deployment, CronJob und den Job der Installation.
Aufruf: (dict "root" $ "key" "zimUpdater" "updater" $u "loop" true|false)
*/}}
{{- define "kompendium.updaterPodSpec" -}}
{{- $root := .root }}
{{- $u := .updater }}
{{- include "kompendium.podCommon" $root | trim }}
containers:
  - name: {{ include "kompendium.updaterKind" .key }}
    image: {{ include "kompendium.image" $root }}
    imagePullPolicy: {{ $root.Values.image.pullPolicy }}
    {{- $command := $u.command }}
    {{- if .loop }}
    {{- $command = append $u.command "--loop" }}
    {{- end }}
    command:
      {{- toYaml $command | nindent 6 }}
    envFrom:
      - configMapRef:
          name: {{ include "kompendium.envConfigMap" $root }}
    {{- $env := merge (deepCopy ($u.env | default dict)) ($root.Values.updaters.env | default dict) }}
    {{- with $env }}
    env:
      {{- range $name, $value := . }}
      - name: {{ $name }}
        value: {{ $value | toString | quote }}
      {{- end }}
    {{- end }}
    {{- with $root.Values.containerSecurityContext }}
    securityContext:
      {{- toYaml . | nindent 6 }}
    {{- end }}
    resources:
      {{- toYaml ($u.resources | default $root.Values.updaters.resources) | nindent 6 }}
    volumeMounts:
      - name: tmp
        mountPath: {{ $root.Values.updaters.tmpEmptyDir.mountPath }}
      {{- range $u.volumes }}
      - name: {{ . }}
        mountPath: {{ (index $root.Values.persistence .).mountPath }}
        {{- if has . ($u.readOnlyVolumes | default list) }}
        readOnly: true
        {{- end }}
      {{- end }}
volumes:
  - name: tmp
    emptyDir:
      sizeLimit: {{ $root.Values.updaters.tmpEmptyDir.sizeLimit }}
  {{- range $u.volumes }}
  - name: {{ . }}
    persistentVolumeClaim:
      claimName: {{ include "kompendium.claimName" (dict "root" $root "volume" .) }}
      {{- if has . ($u.readOnlyVolumes | default list) }}
      readOnly: true
      {{- end }}
  {{- end }}
{{- end }}
