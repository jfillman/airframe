{{/*
airframe-identity.namespace - the Application's own destination namespace, same
as airframe-application.namespace's identical one-liner - both charts are always
installed with spec.destination.namespace set to the app's env namespace, never a
values field.
*/}}
{{- define "airframe-identity.namespace" -}}
{{- .Release.Namespace -}}
{{- end -}}

{{/*
airframe-identity.labels - mirrors airframe-application.labels' shape (same
app.kubernetes.io/* + hangar.io/* keys) so resources from both charts read as one
logical unit in tooling that groups by hangar.io/app+env, without actually sharing
a Helm release/chart identity (helm.sh/chart and app.kubernetes.io/instance are
this chart's own, not airframe-application's).
*/}}
{{- define "airframe-identity.labels" -}}
app.kubernetes.io/name: {{ .Values.appName }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: hangar
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
hangar.io/component: application
hangar.io/app: {{ .Values.appName }}
hangar.io/env: {{ .Values.envName }}
hangar.io/cluster: {{ .Values.cluster }}
{{- end -}}
