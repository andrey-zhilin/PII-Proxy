{{/*
Expand the name of the chart.
*/}}
{{- define "pii-proxy.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this
(by the DNS naming spec). If release name contains the chart name it will be
used as a full name.
*/}}
{{- define "pii-proxy.fullname" -}}
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

{{/*
Create chart label for the helm.sh/chart label.
*/}}
{{- define "pii-proxy.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to all resources.
*/}}
{{- define "pii-proxy.labels" -}}
helm.sh/chart: {{ include "pii-proxy.chart" . }}
{{ include "pii-proxy.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels — used by Service and Deployment selector.matchLabels.
Must remain stable across upgrades.
*/}}
{{- define "pii-proxy.selectorLabels" -}}
app.kubernetes.io/name: {{ include "pii-proxy.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Validate mode-specific required values.
Call with: {{ include "pii-proxy.validateValues" . }}
*/}}
{{- define "pii-proxy.validateValues" -}}
{{- if eq .Values.mode "outgoing-proxy" }}
  {{- $_ := required "langfuse.host is required in outgoing-proxy mode." .Values.langfuse.host }}
{{- else if eq .Values.mode "reverse-proxy" }}
  {{- $_ := required "upstream.host is required in reverse-proxy mode. Set it to your upstream service hostname." .Values.upstream.host }}
{{- end }}
{{- if .Values.tls.enabled }}
  {{- $_ := required "tls.secretName is required when tls.enabled is true." .Values.tls.secretName }}
{{- end }}
{{- end }}
