{{/*
Expand the name of the chart.
*/}}
{{- define "geolens.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
Truncated at 63 chars because some K8s name fields are limited to this.
*/}}
{{- define "geolens.fullname" -}}
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
Create chart name and version as used by the chart label.
*/}}
{{- define "geolens.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to every resource.
*/}}
{{- define "geolens.labels" -}}
helm.sh/chart: {{ include "geolens.chart" . }}
{{ include "geolens.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels (shared across all components).
*/}}
{{- define "geolens.selectorLabels" -}}
app.kubernetes.io/name: {{ include "geolens.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
API component selector labels.
*/}}
{{- define "geolens.api.selectorLabels" -}}
{{ include "geolens.selectorLabels" . }}
app.kubernetes.io/component: api
{{- end }}

{{/*
Worker component selector labels.
*/}}
{{- define "geolens.worker.selectorLabels" -}}
{{ include "geolens.selectorLabels" . }}
app.kubernetes.io/component: worker
{{- end }}

{{/*
Frontend component selector labels.
*/}}
{{- define "geolens.frontend.selectorLabels" -}}
{{ include "geolens.selectorLabels" . }}
app.kubernetes.io/component: frontend
{{- end }}

{{/*
Derive PUBLIC_APP_URL.
Returns publicAppUrl if set, otherwise https://{ingress.host} if ingress
is enabled, otherwise empty string.
*/}}
{{- define "geolens.publicAppUrl" -}}
{{- if .Values.publicAppUrl }}
{{- .Values.publicAppUrl }}
{{- else if .Values.ingress.enabled }}
{{- printf "https://%s" .Values.ingress.host }}
{{- end }}
{{- end }}

{{/*
Derive PUBLIC_API_URL.
Returns publicApiUrl if set, otherwise {publicAppUrl}/api when available.
*/}}
{{- define "geolens.publicApiUrl" -}}
{{- if .Values.publicApiUrl }}
{{- .Values.publicApiUrl }}
{{- else }}
{{- $publicAppUrl := include "geolens.publicAppUrl" . -}}
{{- if $publicAppUrl }}
{{- printf "%s/api" ($publicAppUrl | trimSuffix "/") }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Derive CORS_ALLOWED_ORIGINS.
Returns cors.allowedOrigins if set, otherwise falls back to publicAppUrl.
*/}}
{{- define "geolens.corsOrigins" -}}
{{- if .Values.cors.allowedOrigins }}
{{- .Values.cors.allowedOrigins }}
{{- else }}
{{- include "geolens.publicAppUrl" . }}
{{- end }}
{{- end }}
