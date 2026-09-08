{{/*
airframe-application.namespace - every resource this chart renders lives in exactly one
namespace: this release's own. Unlike platform-cicd-app (one chart, many possible
env namespaces via envNamespace), airframe-application IS one env - §3's own header:
"one values.yaml, one Application, one namespace" - so there's nothing to compute.
Exists as a named template anyway so every template calls the same thing rather
than sprinkling .Release.Namespace directly, matching the sibling-chart idiom.
*/}}
{{- define "airframe-application.namespace" -}}
{{- .Release.Namespace -}}
{{- end -}}

{{/*
airframe-application.labels - standard Kubernetes-recommended labels (interop, matching
every other chart in this platform - see platform-cicd's docs/naming-conventions.md)
plus this platform's own hangar.io/* namespace. hangar.io/app is applied to
EVERY resource this chart renders, not just the Attached-tier XRs §3 explicitly
calls out ("stamps ... hangar.io/app: <app> onto every XR/resource it renders
from a components:/slos: block") - naming-conventions.md's own reasoning for
platform-cicd-app ("applied to every app-chart resource, not just the
shared-namespace ones, for consistency") applies identically here, so this chart
follows the platform-wide norm rather than only the letter of §3's Attached-tier
sentence. hangar.io/env and hangar.io/cluster are new to this chart (not in
naming-conventions.md yet) - real, chart-scoped values unique to airframe-application's
1-release-per-(app,cluster,env) shape, same audit-selector value as hangar.io/app.
*/}}
{{- define "airframe-application.labels" -}}
app.kubernetes.io/name: {{ .Values.appName }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if eq (include "airframe-application.hasRollout" .) "true" }}
app.kubernetes.io/version: {{ .Values.rollout.image.tag | quote }}
{{- else }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: hangar
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
airframe-application.hasRollout - "true"/"" - whether this release has a workload at
all. §3's "Open design question", implemented here per the doc's own stated
leaning ("optional in the same chart... for mechanism reuse") - an appType: infra
release that's only a components: block (§ Item 7's standalone-Redis case) sets
rollout: null (or omits it) and gets no Rollout/Service/HPA/AnalysisTemplate.
*/}}
{{- define "airframe-application.hasRollout" -}}
{{- if .Values.rollout -}}true{{- end -}}
{{- end -}}

{{/*
airframe-application.environmentRef - the deterministic <app>-<cluster>-<env> name §3's
"Linking mechanism" section defines: what every Attached-tier XR's
spec.environmentRef.name is stamped with, naming the specific ApplicationEnvironment
XR that resource depends on. See values.yaml's own header comment on cluster/env for
why those two are plain top-level fields here (not in §3's schema block verbatim).
*/}}
{{- define "airframe-application.environmentRef" -}}
{{- .Values.appName }}-{{ .Values.cluster }}-{{ .Values.envName -}}
{{- end -}}

{{/*
airframe-application.componentKind - looks up the Crossplane kind for one components:/
slos: entry's `type`, failing fast (not silently skipping) on an unknown type -
matching platform-cicd's validateFlows instinct of a fast, readable rejection over
a late, opaque one. `slo` is hardcoded (not in values.yaml's componentKinds map)
since the SLO XRD isn't a "component" in §3's `components:` list at all - it's its
own top-level `slos:` field with its own XRD, kept as a separate lookup entry point
so components.yaml and slos.yaml can share this same helper without slos.yaml
needing a fake "type: slo" entry.

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
airframe-application.serviceAccountName - the name every pod this chart renders
(Rollout, Job, CronJob) sets as its own serviceAccountName, whether this chart
creates that ServiceAccount itself (serviceAccount.create: true, the default) or
one is expected to already exist (create: false - some cluster-admin process
provisioned it, e.g. with a cloud workload-identity annotation this chart doesn't
know about). Computed identically regardless of which case applies - same
"computed the same way in both places, not passed as a value" idiom already used
for the ClusterSecretStore name in external-secret.yaml's own header comment.
*/}}
{{- define "airframe-application.serviceAccountName" -}}
{{- .Values.serviceAccount.name | default .Values.appName -}}
{{- end -}}

{{/*
airframe-application.intOr - like Sprig's `default`, but correct for an int field where
0 is a legitimate explicit value, not "unset" - Sprig's own `default` can't tell
those apart (it treats the Go zero value as empty, full stop), which is a real bug
caught live during this build: `.backoffLimit | default 3` silently turned an
explicit `backoffLimit: 0` (a real, meaningful Kubernetes setting - "no retries")
into 3. Uses `hasKey` on the entry's own raw map instead, which does distinguish
"key present with value 0" from "key absent". SCALAR OUTPUT POSITIONS ONLY (e.g.
`backoffLimit: {{ include ... }}`) - do NOT use this inside an `{{- if }}` the way
you might for a bool: `include` always returns a string, and a non-empty string
like "false" is truthy to Go's `if`, which is the exact same class of bug relocated
one level up. A boolean "present but false vs. absent" check (see job.yaml's own
`hook:` field) needs a direct `{{- if or (not (hasKey . "hook")) .hook }}` instead,
using the real, un-stringified value.

Usage: {{ include "airframe-application.intOr" (dict "map" . "key" "backoffLimit" "default" 3) }}
*/}}
{{- define "airframe-application.intOr" -}}
{{- if hasKey .map .key -}}{{- get .map .key -}}{{- else -}}{{- .default -}}{{- end -}}
{{- end -}}

{{/*
airframe-application.resolveAs - validates and returns a configMaps:/secrets: entry's
`as` field (env | volume | both), applying the given default when unset. Fails
fast on a typo (e.g. `as: enviroment`) rather than silently treating it as
neither - without this, a mistyped `as` would match none of the `eq` checks in
every consumption helper below and silently produce no env var, no mount, AND no
error - a config source just quietly disappears.

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
airframe-application.configMapObjectName - resolves which ConfigMap object name a
configMaps: entry actually refers to: `.name` when this chart renders it itself
(data: set), or `.existingConfigMap` when it doesn't (referencing one created
elsewhere - e.g. a Kustomize configMapGenerator with disableNameSuffixHash: true,
so the name is fixed and known up front, not hash-suffixed - a hash-suffixed name
would need an external process keeping this field in sync on every regeneration,
not solved here). Fails fast if an entry sets both or neither - exactly one of
data:/existingConfigMap: must be present, same fail-fast instinct as
airframe-application.componentKind/batchContainer's own image-fallback check.
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
airframe-application.workloadEnv - the container env list shared by every workload
(main Rollout container, every jobs:/cronJobs: entry): .Values.env verbatim, plus
one secretKeyRef entry per .Values.secrets entry whose `as` (default: env)
includes env (see external-secret.yaml - same `app-secrets` target Secret, `key`
field means the container-facing env var name here). Factored out so Job/CronJob
don't re-derive this - a batch task in the same app almost always wants the same
config/secrets the main workload has, and this is the one place that mapping is
defined.

Usage: {{ $env := fromYamlArray (include "airframe-application.workloadEnv" $) }}
*/}}
{{- define "airframe-application.workloadEnv" -}}
{{- $env := list -}}
{{- range .Values.env -}}
{{- $env = append $env (dict "name" .name "value" (.value | toString)) -}}
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
airframe-application.workloadEnvFrom - one envFrom: configMapRef entry per configMaps:
entry whose `as` (default: volume) includes env - every key in that ConfigMap's
data becomes an env var verbatim, using the keys' own names (no per-key renaming -
use the plain top-level env: list for a single renamed value instead). Separate
template from workloadEnv since envFrom is its own container-spec field, not
merged into the individual-entry env: list.

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
airframe-application.workloadVolumeMounts / airframe-application.workloadVolumes - the
volumeMount/volume pair for every configMaps: entry whose `as` (default: volume)
includes volume, every volumes: (PVC) entry, and every secrets: entry whose `as`
(default: env) includes volume - shared by every workload the same way workloadEnv
is. Two separate templates (mount goes on the container, volume goes on the pod)
computed from the same three values lists, so a Job/CronJob container and pod spec
both call in and stay consistent by construction rather than by two templates
being kept in sync by hand.

secrets: volume entries deliberately do NOT get their own Secret/volume each -
every `as: volume`/`both` entry shares the single `app-secrets` Secret volume
(added once, only if at least one entry needs it), each mounted at its own exact
file path via `subPath: <name>` - the standard mechanism for projecting one key
from a Secret to an exact path without a volume per key. This is also why a
secrets: entry's mountPath means "the exact file", unlike configMaps'/volumes'
mountPath, which is a directory a ConfigMap's/PVC's whole content mounts under.

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
{{- $volumes | toYaml -}}
{{- end -}}

{{/*
airframe-application.batchContainer - builds the single container spec shared by every
jobs:/cronJobs: entry (job.yaml/cronjob.yaml). Falls back to rollout.image when the
entry doesn't set its own `image:` - fails fast (not a silent empty image string)
when neither is available, i.e. rollout: isn't set at all and the entry didn't
supply one either.

Usage: {{ $container := fromYaml (include "airframe-application.batchContainer" (dict "ctx" $ "entry" .)) }}
*/}}
{{- define "airframe-application.batchContainer" -}}
{{- $ctx := .ctx -}}
{{- $entry := .entry -}}
{{- $image := $entry.image -}}
{{- if not $image -}}
{{- if $ctx.Values.rollout -}}{{- $image = $ctx.Values.rollout.image -}}{{- end -}}
{{- end -}}
{{- if or (not $image) (not $image.repository) -}}
{{- fail (printf "'%s' needs an image - rollout: is not set (or has no image), so there's no default to fall back to. Set this entry's own image: {repository, tag}." $entry.name) -}}
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
airframe-application.networkPolicyPeer - builds one NetworkPolicyPeer from an
allowIngressFrom:/allowEgressTo: entry. Exactly one of namespace:/cidr: is
required - namespace: resolves via the auto-populated kubernetes.io/metadata.name
label (every namespace gets one since k8s 1.21+), the same mechanism already used
for networkPolicy.ingressControllerNamespaceSelector; podLabels: (only meaningful
alongside namespace:) is ANDed onto the same peer as a real K8s NetworkPolicyPeer
can combine namespaceSelector + podSelector on one object. Fails fast on both/
neither set, matching this chart's established instinct (componentKind,
configMapObjectName, resolveAs) rather than silently picking one or rendering
nothing.

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
airframe-application.networkPolicyPorts - converts an allowIngressFrom:/allowEgressTo:
entry's `ports: [8080, 9090]` (bare port numbers) into the real NetworkPolicyPort
list shape, TCP assumed - the overwhelming common case, and the whole point of
this being simpler than extraIngressRules/extraEgressRules. UDP/SCTP genuinely
need the raw escape hatch instead, not reinvented here.

Usage: {{ include "airframe-application.networkPolicyPorts" . }}
*/}}
{{- define "airframe-application.networkPolicyPorts" -}}
{{- $ports := list -}}
{{- range .ports -}}
{{- $ports = append $ports (dict "protocol" "TCP" "port" .) -}}
{{- end -}}
{{- $ports | toYaml -}}
{{- end -}}
