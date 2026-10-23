{{/*
airframe-application.namespace - every resource lives in this release's own namespace. A named template
so every file calls the same thing.
*/}}
{{- define "airframe-application.namespace" -}}
{{- .Release.Namespace -}}
{{- end -}}

{{/*
airframe-application.labels - the Kubernetes recommended labels plus hangar.io/app, env and cluster, on
every resource this chart renders. These labels are reserved: userMeta refuses to let values override them.
part-of is the app (Kubernetes' "higher-level application"), not the platform: tools that group by it (Radar)
put every app under one "hangar" group.
*/}}
{{- define "airframe-application.labels" -}}
app.kubernetes.io/name: {{ .Values.appName }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if eq (include "airframe-application.hasRollout" .) "true" }}
app.kubernetes.io/version: {{ (include "airframe-application.image" . | fromYaml).tag | quote }}
{{- else }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: {{ .Values.appName }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
hangar.io/component: application
hangar.io/app: {{ .Values.appName }}
hangar.io/env: {{ .Values.envName }}
hangar.io/cluster: {{ .Values.cluster }}
{{- end -}}

{{/*
airframe-application.selectorLabels - the stable subset used for Rollout matchLabels /
pod template labels / Service selector. Deliberately excludes version/chart-version
(both of which change on every deploy) - a selector must never depend on a label
that changes without changing what's being selected.
*/}}
{{- define "airframe-application.selectorLabels" -}}
app.kubernetes.io/name: {{ .Values.appName }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
airframe-application.workloadEnabled / hasRollout - "true" or "".
workloadEnabled: this environment runs a service (rollout.enabled; rollout: null counts as false).
hasRollout: it does, and an image has been released (release.image, or the deprecated rollout.image), so
a new environment renders no Rollout rather than one whose image is ":". The two are different facts and
Tower shows them differently; only the first is configuration.
*/}}
{{- define "airframe-application.workloadEnabled" -}}
{{- if and .Values.rollout (ne (toString .Values.rollout.enabled) "false") -}}true{{- end -}}
{{- end -}}
{{- define "airframe-application.hasRollout" -}}
{{- if and (include "airframe-application.workloadEnabled" .) (include "airframe-application.image" .) -}}true{{- end -}}
{{- end -}}

{{/*
airframe-application.otelInjectRuntime - the OpenTelemetry Operator runtime to inject (nodejs, java or python), or
"" when the cluster names no Instrumentation or the runtime has no injectable agent here (go: privileged eBPF).
*/}}
{{- define "airframe-application.otelInjectRuntime" -}}
{{- $o := .Values.observability | default dict -}}
{{- if and $o.instrumentation (has $o.runtime (list "nodejs" "java" "python")) -}}{{ $o.runtime }}{{- end -}}
{{- end -}}

{{/*
airframe-application.image - the image this release runs, as YAML {repository, tag}, or empty when none is set.
The release-owned key `release.image` wins; `rollout.image` is the deprecated location and is used only when
`release.image` is not fully set. Both need repository AND tag.
Usage: {{ $img := include "airframe-application.image" . | fromYaml }}
*/}}
{{- define "airframe-application.image" -}}
{{- $rel := .Values.release | default dict -}}
{{- $ri := $rel.image | default dict -}}
{{- if and $ri.repository $ri.tag -}}
{{- dict "repository" $ri.repository "tag" $ri.tag | toYaml -}}
{{- else if .Values.rollout -}}
{{- $ro := .Values.rollout.image | default dict -}}
{{- if and $ro.repository $ro.tag -}}{{- dict "repository" $ro.repository "tag" $ro.tag | toYaml -}}{{- end -}}
{{- end -}}
{{- end -}}

{{/*
airframe-application.environmentRef - <app>-<cluster>-<env>, stamped into every attached XR's
spec.environmentRef.name.
*/}}
{{- define "airframe-application.environmentRef" -}}
{{- .Values.appName }}-{{ .Values.cluster }}-{{ .Values.envName -}}
{{- end -}}

{{/*
airframe-application.componentKind - the XR kind for a components: entry's `type`, from
componentKinds; fails the render on an unknown type. `slo` maps to SLO directly, so slos.yaml shares
this helper without a componentKinds row.

Usage: {{ include "airframe-application.componentKind" (dict "ctx" $ "type" $entry.type) }}
*/}}
{{- define "airframe-application.componentKind" -}}
{{- $ctx := .ctx -}}
{{- $type := .type -}}
{{- if eq $type "slo" -}}
SLO
{{- else if hasKey $ctx.Values.componentKinds $type -}}
{{- get $ctx.Values.componentKinds $type -}}
{{- else -}}
{{- fail (printf "components: entry has unknown type '%s' - must be one of: %s (see values.yaml's componentKinds map)" $type (join ", " (keys $ctx.Values.componentKinds))) -}}
{{- end -}}
{{- end -}}

{{/*
airframe-application.serviceAccountName - serviceAccountName for every pod (Rollout, Job, CronJob):
serviceAccount.name, else appName. The same name whether the chart creates the ServiceAccount
(serviceAccount.create) or expects one to exist.
*/}}
{{- define "airframe-application.serviceAccountName" -}}
{{- .Values.serviceAccount.name | default .Values.appName -}}
{{- end -}}

{{/*
airframe-application.intOr - like Sprig's `default`, for an int where 0 is a real value: `default`
treats 0 as unset, so `.backoffLimit | default 3` would turn backoffLimit: 0 into 3. Checks hasKey instead.
Scalar output positions only: `include` returns a string, and "false" is truthy in an `if`. For a boolean
(job.yaml's `hook`), test the raw value: `{{- if or (not (hasKey . "hook")) .hook }}`.

Usage: {{ include "airframe-application.intOr" (dict "map" . "key" "backoffLimit" "default" 3) }}
*/}}
{{- define "airframe-application.intOr" -}}
{{- if hasKey .map .key -}}{{- get .map .key -}}{{- else -}}{{- .default -}}{{- end -}}
{{- end -}}

{{/*
airframe-application.resolveAs - a configMaps:/secrets: entry's `as` (env | volume | both), or the
given default. Fails on anything else, which would otherwise match no branch below and drop the entry.

Usage: {{ $as := include "airframe-application.resolveAs" (dict "entry" . "default" "volume") }}
*/}}
{{- define "airframe-application.resolveAs" -}}
{{- $as := .entry.as | default .default -}}
{{- if not (has $as (list "env" "volume" "both")) -}}
{{- fail (printf "'%s' has invalid as: '%s' - must be one of: env, volume, both" .entry.name $as) -}}
{{- end -}}
{{- $as -}}
{{- end -}}

{{/*
airframe-application.configMapObjectName - the ConfigMap a configMaps: entry refers to: `.name` when
the chart renders it (data:), or `.existingConfigMap` for one created elsewhere under a fixed name (a
Kustomize configMapGenerator needs disableNameSuffixHash: true). Exactly one of the two, or the render fails.
*/}}
{{- define "airframe-application.configMapObjectName" -}}
{{- if and (hasKey . "data") (hasKey . "existingConfigMap") -}}
{{- fail (printf "configMaps: entry '%s' sets both data: and existingConfigMap: - set exactly one (data: for a ConfigMap this chart renders, existingConfigMap: to reference one created elsewhere)" .name) -}}
{{- else if hasKey . "existingConfigMap" -}}
{{- .existingConfigMap -}}
{{- else if hasKey . "data" -}}
{{- .name -}}
{{- else -}}
{{- fail (printf "configMaps: entry '%s' needs either data: (this chart renders the ConfigMap) or existingConfigMap: (referencing one created elsewhere)" .name) -}}
{{- end -}}
{{- end -}}

{{/*
airframe-application.resolveFromComponent - resolves one `env[].fromComponent: {name, output}` to a
`value` or `valueFrom`, from the matching components: entry and files/component-outputs.yaml (generated from
xrds/*.meta.yaml by tools/gen_component_outputs.py). Fails on a reference nothing declares;
tools/airframe-validate (AF-COMP-002) catches the same thing before merge.

Usage: {{ $resolved := include "airframe-application.resolveFromComponent" (dict "root" $ "ref" .fromComponent) | fromYaml }}
*/}}
{{- define "airframe-application.resolveFromComponent" -}}
{{- $root := .root -}}
{{- $ref := .ref -}}
{{- $comp := "" -}}
{{- range $root.Values.components -}}
{{- if eq .name $ref.name -}}{{- $comp = . -}}{{- end -}}
{{- end -}}
{{- if not $comp -}}
{{- fail (printf "fromComponent: no components[] entry named '%s'" $ref.name) -}}
{{- end -}}
{{- $allOutputs := $root.Files.Get "files/component-outputs.yaml" | fromYaml -}}
{{- $typeOutputs := index $allOutputs $comp.type -}}
{{- if not $typeOutputs -}}
{{- fail (printf "fromComponent: component type '%s' declares no outputs" $comp.type) -}}
{{- end -}}
{{- $out := index $typeOutputs $ref.output -}}
{{- if not $out -}}
{{- fail (printf "fromComponent: component '%s' (%s) has no output '%s' - see xrds/%s.meta.yaml" $ref.name $comp.type $ref.output $comp.type) -}}
{{- end -}}
{{- $ns := include "airframe-application.namespace" $root -}}
{{- $subst := (dict "n" $ref.name "ns" $ns) -}}
{{- if eq $out.kind "literal" -}}
value: {{ ($out.value | toString | replace "{name}" $subst.n | replace "{namespace}" $subst.ns) | quote }}
{{- else if eq $out.kind "secretKeyRef" -}}
valueFrom:
  secretKeyRef:
    name: {{ ($out.secret | replace "{name}" $subst.n | replace "{namespace}" $subst.ns) | quote }}
    key: {{ $out.key | quote }}
{{- else if eq $out.kind "configMapKeyRef" -}}
valueFrom:
  configMapKeyRef:
    name: {{ ($out.configMap | replace "{name}" $subst.n | replace "{namespace}" $subst.ns) | quote }}
    key: {{ $out.key | quote }}
{{- else -}}
{{- fail (printf "fromComponent: unknown output kind '%s' for %s.%s" $out.kind $comp.type $ref.output) -}}
{{- end -}}
{{- end -}}

{{/*
airframe-application.workloadEnv - the container env shared by the Rollout and every Job and CronJob:
each env: entry (`value`, `valueFrom`, or `fromComponent`), then a secretKeyRef into app-secrets for each
secrets: entry consumed as env (`key` is the env var name; default: the upper-cased name).

Usage: {{ $env := fromYamlArray (include "airframe-application.workloadEnv" $) }}
*/}}
{{- define "airframe-application.workloadEnv" -}}
{{- $root := . -}}
{{- $env := list -}}
{{- range .Values.env -}}
{{- if .fromComponent -}}
{{- $resolved := include "airframe-application.resolveFromComponent" (dict "root" $root "ref" .fromComponent) | fromYaml -}}
{{- $env = append $env (merge (dict "name" .name) $resolved) -}}
{{- else if .valueFrom -}}
{{- $env = append $env (dict "name" .name "valueFrom" .valueFrom) -}}
{{- else -}}
{{- $env = append $env (dict "name" .name "value" (.value | toString)) -}}
{{- end -}}
{{- end -}}
{{- range .Values.secrets -}}
{{- $as := include "airframe-application.resolveAs" (dict "entry" . "default" "env") -}}
{{- if or (eq $as "env") (eq $as "both") -}}
{{- $envName := .key | default (upper (regexReplaceAll "-" .name "_")) -}}
{{- $env = append $env (dict "name" $envName "valueFrom" (dict "secretKeyRef" (dict "name" "app-secrets" "key" .name))) -}}
{{- end -}}
{{- end -}}
{{- $env | toYaml -}}
{{- end -}}

{{/*
airframe-application.workloadEnvFrom - one envFrom configMapRef per configMaps: entry consumed as env:
every key becomes an env var under its own name.

Usage: {{ $envFrom := fromYamlArray (include "airframe-application.workloadEnvFrom" $) }}
*/}}
{{- define "airframe-application.workloadEnvFrom" -}}
{{- $envFrom := list -}}
{{- range .Values.configMaps -}}
{{- $as := include "airframe-application.resolveAs" (dict "entry" . "default" "volume") -}}
{{- if or (eq $as "env") (eq $as "both") -}}
{{- $envFrom = append $envFrom (dict "configMapRef" (dict "name" (include "airframe-application.configMapObjectName" .))) -}}
{{- end -}}
{{- end -}}
{{- $envFrom | toYaml -}}
{{- end -}}

{{/*
airframe-application.workloadVolumeMounts / workloadVolumes - the matching mounts (container) and volumes
(pod) for configMaps: entries consumed as a volume, volumes: (PVCs), secrets: entries consumed as a volume,
and serviceAccount.projectedTokens. Shared by every workload.

All secret volume entries share one app-secrets volume, each mounted with `subPath: <name>`, so a secrets:
mountPath is the exact file. A configMaps:/volumes: mountPath is a directory.

Usage: {{ $volumeMounts := fromYamlArray (include "airframe-application.workloadVolumeMounts" $) }}
      {{ $volumes := fromYamlArray (include "airframe-application.workloadVolumes" $) }}
*/}}
{{- define "airframe-application.workloadVolumeMounts" -}}
{{- $volumeMounts := list -}}
{{- range .Values.configMaps -}}
{{- $as := include "airframe-application.resolveAs" (dict "entry" . "default" "volume") -}}
{{- if or (eq $as "volume") (eq $as "both") -}}
{{- $mountPath := .mountPath | default (printf "/config/%s" .name) -}}
{{- $volumeMounts = append $volumeMounts (dict "name" .name "mountPath" $mountPath) -}}
{{- end -}}
{{- end -}}
{{- range .Values.volumes -}}
{{- $volumeMounts = append $volumeMounts (dict "name" .name "mountPath" .mountPath) -}}
{{- end -}}
{{- range .Values.secrets -}}
{{- $as := include "airframe-application.resolveAs" (dict "entry" . "default" "env") -}}
{{- if or (eq $as "volume") (eq $as "both") -}}
{{- $mountPath := .mountPath | default (printf "/secrets/%s" .name) -}}
{{- $volumeMounts = append $volumeMounts (dict "name" "app-secrets" "mountPath" $mountPath "subPath" .name "readOnly" true) -}}
{{- end -}}
{{- end -}}
{{- range .Values.serviceAccount.projectedTokens -}}
{{- $volumeMounts = append $volumeMounts (dict "name" .name "mountPath" .mountPath "readOnly" true) -}}
{{- end -}}
{{- $volumeMounts | toYaml -}}
{{- end -}}

{{- define "airframe-application.workloadVolumes" -}}
{{- $volumes := list -}}
{{- range .Values.configMaps -}}
{{- $as := include "airframe-application.resolveAs" (dict "entry" . "default" "volume") -}}
{{- if or (eq $as "volume") (eq $as "both") -}}
{{- $volumes = append $volumes (dict "name" .name "configMap" (dict "name" (include "airframe-application.configMapObjectName" .))) -}}
{{- end -}}
{{- end -}}
{{- range .Values.volumes -}}
{{- $volumes = append $volumes (dict "name" .name "persistentVolumeClaim" (dict "claimName" .name)) -}}
{{- end -}}
{{- $needsSecretVolume := false -}}
{{- range .Values.secrets -}}
{{- $as := include "airframe-application.resolveAs" (dict "entry" . "default" "env") -}}
{{- if or (eq $as "volume") (eq $as "both") -}}{{- $needsSecretVolume = true -}}{{- end -}}
{{- end -}}
{{- if $needsSecretVolume -}}
{{- $volumes = append $volumes (dict "name" "app-secrets" "secret" (dict "secretName" "app-secrets")) -}}
{{- end -}}
{{- /* serviceAccount.projectedTokens: a kubelet-rotated token of the pod's own ServiceAccount for another audience
(e.g. a cluster that trusts this one's issuer). Nothing stored; the file is <mountPath>/token. */ -}}
{{- range .Values.serviceAccount.projectedTokens -}}
{{- $tok := dict "audience" .audience "expirationSeconds" (int (include "airframe-application.intOr" (dict "map" . "key" "expirationSeconds" "default" 600))) "path" "token" -}}
{{- $volumes = append $volumes (dict "name" .name "projected" (dict "sources" (list (dict "serviceAccountToken" $tok)))) -}}
{{- end -}}
{{- $volumes | toYaml -}}
{{- end -}}

{{/*
airframe-application.batchContainer - the container for a jobs:/cronJobs: entry: its own `image:`, else
the release image. Fails when there is neither.

Usage: {{ $container := fromYaml (include "airframe-application.batchContainer" (dict "ctx" $ "entry" .)) }}
*/}}
{{- define "airframe-application.batchContainer" -}}
{{- $ctx := .ctx -}}
{{- $entry := .entry -}}
{{- $image := $entry.image -}}
{{- if not $image -}}
{{- $image = include "airframe-application.image" $ctx | fromYaml -}}
{{- end -}}
{{- if or (not $image) (not $image.repository) -}}
{{- fail (printf "'%s' needs an image - neither release.image nor rollout.image is set, so there's no default to fall back to. Set this entry's own image: {repository, tag}." $entry.name) -}}
{{- end -}}
{{- $container := dict "name" $entry.name "image" (printf "%s:%s" $image.repository $image.tag) -}}
{{- if $entry.command -}}{{- $_ := set $container "command" $entry.command -}}{{- end -}}
{{- if $entry.args -}}{{- $_ := set $container "args" $entry.args -}}{{- end -}}
{{- if $entry.resources -}}{{- $_ := set $container "resources" $entry.resources -}}{{- end -}}
{{- if $entry.containerSecurityContext -}}{{- $_ := set $container "securityContext" $entry.containerSecurityContext -}}{{- end -}}
{{- $env := fromYamlArray (include "airframe-application.workloadEnv" $ctx) -}}
{{- if $env -}}{{- $_ := set $container "env" $env -}}{{- end -}}
{{- $envFrom := fromYamlArray (include "airframe-application.workloadEnvFrom" $ctx) -}}
{{- if $envFrom -}}{{- $_ := set $container "envFrom" $envFrom -}}{{- end -}}
{{- $volumeMounts := fromYamlArray (include "airframe-application.workloadVolumeMounts" $ctx) -}}
{{- if $volumeMounts -}}{{- $_ := set $container "volumeMounts" $volumeMounts -}}{{- end -}}
{{- $container | toYaml -}}
{{- end -}}

{{/*
airframe-application.networkPolicyPeer - one NetworkPolicyPeer from an allowIngressFrom:/allowEgressTo:
entry: `namespace` (matched on its kubernetes.io/metadata.name label, optionally ANDed with `podLabels`) or
`cidr`. Exactly one of the two, or the render fails.

Usage: {{ include "airframe-application.networkPolicyPeer" . }}
*/}}
{{- define "airframe-application.networkPolicyPeer" -}}
{{- if and .cidr .namespace -}}
{{- fail "networkPolicy allowIngressFrom/allowEgressTo entry sets both namespace: and cidr: - set exactly one (namespace: for an in-cluster peer, cidr: for an external one)" -}}
{{- end -}}
{{- $peer := dict -}}
{{- if .cidr -}}
{{- $_ := set $peer "ipBlock" (dict "cidr" .cidr) -}}
{{- else if .namespace -}}
{{- $_ := set $peer "namespaceSelector" (dict "matchLabels" (dict "kubernetes.io/metadata.name" .namespace)) -}}
{{- if .podLabels -}}{{- $_ := set $peer "podSelector" (dict "matchLabels" .podLabels) -}}{{- end -}}
{{- else -}}
{{- fail "networkPolicy allowIngressFrom/allowEgressTo entry needs either namespace: or cidr:" -}}
{{- end -}}
{{- $peer | toYaml -}}
{{- end -}}

{{/*
airframe-application.networkPolicyPorts - an entry's bare `ports: [8080, 9090]` as TCP NetworkPolicyPorts.
UDP and SCTP need extraIngressRules/extraEgressRules.

Usage: {{ include "airframe-application.networkPolicyPorts" . }}
*/}}
{{- define "airframe-application.networkPolicyPorts" -}}
{{- $ports := list -}}
{{- range .ports -}}
{{- $ports = append $ports (dict "protocol" "TCP" "port" .) -}}
{{- end -}}
{{- $ports | toYaml -}}
{{- end -}}

{{/*
airframe-application.userMeta - rollout.labels/annotations, rollout.podLabels/podAnnotations and
rollout.serviceLabels/serviceAnnotations: extra metadata a developer sets on the objects this chart renders.
Returns the map as YAML ("" when unset) and fails the render, naming the key, when it would override something the
chart owns: any label the chart itself stamps (app.kubernetes.io/*, hangar.io/*, helm.sh/chart - the selector labels
above all, which must never change), and the checksum/* pod annotations that force a new revision on a config change.
Failing beats ignoring the key or rendering a duplicate one.
Usage: {{ include "airframe-application.userMeta" (dict "root" $ "kind" "labels" "field" "rollout.podLabels" "map" .Values.rollout.podLabels) }}
*/}}
{{- define "airframe-application.userMeta" -}}
{{- $root := .root -}}
{{- if .map -}}
{{- $reserved := include "airframe-application.labels" $root | fromYaml -}}
{{- range $key, $_ := .map -}}
{{- if eq $.kind "labels" -}}
{{- if or (hasKey $reserved $key) (hasPrefix "hangar.io/" $key) (hasPrefix "app.kubernetes.io/" $key) (eq $key "helm.sh/chart") -}}
{{- fail (printf "%s must not set '%s': the chart owns that label (app.kubernetes.io/*, hangar.io/* and helm.sh/chart are reserved)" $.field $key) -}}
{{- end -}}
{{- else if hasPrefix "checksum/" $key -}}
{{- fail (printf "%s must not set '%s': checksum/* annotations are chart-owned (they roll the pods when a ConfigMap or Secret entry changes)" $.field $key) -}}
{{- end -}}
{{- end -}}
{{- toYaml .map -}}
{{- end -}}
{{- end -}}
