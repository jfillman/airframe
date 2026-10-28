# airframe-application

The Helm chart every Hangar app environment runs. One release per `(app, cluster, env)`, into the
namespace `app-<app>-<env>`. From one set of values it renders:

- **The workload:** an Argo `Rollout`, its `Service` (and a `-preview` Service for blue-green), a
  `ServiceAccount`, `ServiceMonitor`, `HorizontalPodAutoscaler`, `PodDisruptionBudget`, app-specific
  `AnalysisTemplate`s, `Job`s and `CronJob`s.
- **Config and secrets:** `ConfigMap`s, one `ExternalSecret` (`app-secrets`) and, for AI-triage Slack
  notifications, a second one (`notify-secrets`).
- **Networking:** the `Namespace`, a `NetworkPolicy`, and an optional Gateway API `HTTPRoute` or classic
  `Ingress`.
- **Attached XRs:** one Crossplane XR per `components:` entry (Redis, PostgreSQL, RabbitMQ, MongoDB, Dex),
  one `SLO` per `slos:` entry, and a `RolloutWatch` for the Rollout.
- **`extraManifests:`**, raw objects rendered as-is, for anything the chart doesn't model.

Nobody installs it by hand. ArgoCD renders it: on the dev cluster, Glidepath's `ApplicationSet`s render it for
Ground environments and PR previews; on an upper cluster, the tenant-onboarding `ApplicationSet` renders it for
each Flight environment. Each cluster's default chart version is pinned in Apron's `cluster-defaults.yaml`; an
app can pin its own with `deploy.chart` in its `cicd.yaml`.

## Where the values come from

The `ApplicationSet` sets `appName`, `cluster`, `envName` and `namespace.labels` itself, then layers value files,
later ones winning:

| Environment | Human-owned files | Release file (Glidepath only) |
|---|---|---|
| Flight, in `gitops-<app>` | `<cluster>/base.yaml` (optional, shared by the cluster's environments), then `<cluster>/<env>/values.yaml` | `<cluster>/<env>/release.yaml` |
| Ground, in the app's source repo | `glidepath/envs/<env>.yaml` | `glidepath/envs/<env>.release.yaml` |

People and Tower edit the human-owned files; `ApplicationEnvironment` writes a Flight environment's identity there
when it creates it. The release file holds only `release.image` and `releaseTracking`.

`values.schema.json` marks every key `x-hangar-owner: human | release | platform`, and
`tools/airframe-validate` fails a file that puts a key in the wrong one (`AF-OWNER-001`).

## When a workload renders

Two facts decide it, kept in two places:

| Fact | Key | Owner |
|---|---|---|
| Does this environment run a service at all? | `rollout.enabled` (default `true`) | people |
| Has an image been released to it? | `release.image.repository` and `.tag` | Glidepath |

The Rollout, Service, ServiceMonitor, HPA, PDB, route and RolloutWatch render only when both say yes. A
new environment has no image yet, so it renders its Namespace, ServiceAccount, NetworkPolicy, config and
attached XRs, and nothing that runs. `rollout.enabled: false` is a components-and-jobs-only environment:
the rest of `rollout:` is kept, so turning it back on restores the settings. `rollout: null` is read as
`enabled: false`. `rollout.image` is a deprecated fallback for `release.image`, which wins when both are
set. `jobs:` and `cronJobs:` entries without their own `image:` run the release image.

When the release file also sets `release.image.digest` (`sha256:<hex>`, written by Glidepath, ADR-0029), every
container that runs the release image is rendered as `repository:tag@digest`: the runtime pulls the digest, so the
tag can no longer change what runs. `release.image.source` records the repository the image was built in (the
Ground registry) and is never rendered; it equals `repository` until a separate Flight registry is configured.

`releaseTracking` (written by Glidepath's `open-release-pr`) puts `hangar.io/release-id` and
`hangar.io/app-namespace` annotations and a `hangar.io/release-tracked` label on the Rollout's own
metadata, never the pod template. The Argo Rollouts notifications engine reports the Rollout's phase to
Glidepath's relay by that id (glidepath `docs/admin/release-state.md`). `releaseTracking` on an
environment with no Rollout fails the render (`templates/release-tracking-guard.yaml`).

## The Rollout

- `strategy: canary` (default) or `blueGreen`. `rollout.steps`, `canaryAnalysis` and `blueGreen` are raw
  Argo Rollouts passthroughs. With no `steps`, a canary renders one `setWeight: 100` step, which behaves
  like an ordinary rolling update: there is no platform default step sequence.
- `blueGreen` must not set `activeService`/`previewService`: the chart always names them `<app>` and
  `<app>-preview`.
- `maxSurge`/`maxUnavailable` (canary only; unset keeps Argo Rollouts' 25%/25%). `maxSurge: 0` with
  `maxUnavailable: 1` replaces a single replica without ever running two. Both 0 fails the render.
- `rollbackWindow` (default `{revisions: 3}`): going back to one of the last three revisions skips the
  steps and analysis, which is what a Glidepath rollback does. `null` turns it off; `{}` doesn't, because
  Helm merges it with the default.
- Probes: an empty `livenessProbe`/`readinessProbe` (the default) renders an HTTP GET of `/` on the first
  port. Set one to change it.
- Security: the pod runs as UID/GID 65532 with `runAsNonRoot`, seccomp `RuntimeDefault`, no privilege
  escalation and every capability dropped. 65532 is also Tower's break-glass debug container's UID, so it
  can read the app's files through `/proc/1/root`. Keys you set merge onto the defaults; `null` drops them.
- `podSpec` is deep-merged last onto the pod spec. It must not set `containers` (use the curated fields
  and `extraContainers`), because a merge replaces whole arrays.
- Extra labels and annotations: `rollout.labels/annotations` (the Rollout), `podLabels/podAnnotations`
  (every pod) and `serviceLabels/serviceAnnotations` (the Services). A label the chart owns
  (`app.kubernetes.io/*`, `hangar.io/*`, `helm.sh/chart`) or a `checksum/*` pod annotation fails the
  render, naming the key.

## Config and secrets

- `env:` entries carry `value`, `valueFrom`, `fromComponent: {name, output}` or `fromService`, at most one. `fromComponent` resolves
  against `files/component-outputs.yaml`, which `tools/gen_component_outputs.py` generates from each
  component's `xrds/<type>.meta.yaml`, so `{name: DB_URI, fromComponent: {name: db, output: uri}}` becomes a
  `secretKeyRef` to the Secret the PostgreSQL component created. An unknown component or output fails the
  render.
- `fromService: {app, port, scheme, type, env, service}` is another app's in-cluster Service URL,
  `<scheme>://<service>.<namespace>.svc.cluster.local:<port>`, so `{name: FLIGHT_API_URL, fromService: {app:
  flight-api, port: 8080}}` in boarding-api's dev values becomes
  `http://flight-api.app-flight-api-dev.svc.cluster.local:8080`. The chart does not know the namespace
  convention: the platform passes it as `serviceNamespacePattern` (platform-owned, like `envName`), a pattern
  over `{type}`, `{app}` and `{env}` taken from Glidepath's `glidepath-app.envNamespacePattern` for Ground and
  PR environments and set by the cluster's tenant-onboarding ApplicationSet for Flight. `port` is required
  (the chart cannot read another app's values); `scheme` defaults to `http`, `type` to `app` (`infra` for an
  InfraService), `service` to `app`, and `env` to this release's `envName`. Set `env` where the names differ:
  a PR environment (`pr-12`) has no `flight-api-pr-12`, so `glidepath/pr-env.yaml` sets `env: dev`. An empty
  `serviceNamespacePattern` (an environment whose platform config or chart pin predates it), or no env at
  all, fails the render; nothing falls back to a guessed namespace. `airframe-validate` warns on a
  hand-written `*.svc[.cluster.local]` URL (AF-SVC-001) and names the `fromService` that replaces it.
- `configMaps:` entries set `data:` (the chart renders the ConfigMap) or `existingConfigMap:` (one created
  elsewhere, under a fixed name), exactly one. `as: volume` (default), `env` (every key via `envFrom`) or
  `both`.
- `secrets:` entries are Infisical keys, never values. All of them land in one `app-secrets` Secret. `as:
  env` (default; the env var is `key`, or the upper-cased name), `volume` (one file per entry via
  `subPath`, at `mountPath`) or `both`.
- Which store a secret comes from depends on `clusterType`, the cluster's registry type, never its name:

  | `clusterType` | Default store | `shared: true` | Infisical key |
  |---|---|---|---|
  | `dev` | `<app>-<cluster>` | same store | `<envName>/<name>`, or `<name>` when shared |
  | `upper` | `<app>-<cluster>-<env>` | `<app>-<cluster>` | `<name>` |

  The dev cluster has one shared Infisical environment per app, so the `<envName>/` prefix is what keeps
  `pr-12` and `pr-13` apart. `secrets:` without `cluster` and `clusterType` fails the render.
- `checksum/configmaps` and `checksum/secrets` on the pod template roll the pods when `configMaps:` data
  or the `secrets:` list changes. A secret's value lives in Infisical, out of Helm's sight, so rotating
  it does not roll the pods.
- Every ServiceAccount gets `registry-credentials` as an image pull secret; the platform distributes that
  Secret to every managed namespace. `serviceAccount.projectedTokens` mounts a kubelet-rotated token of
  the ServiceAccount for another audience on the main container and every Job and CronJob.

## Networking

- `NetworkPolicy` (on by default) admits same-namespace pods, the Gateway's namespace when `httpRoute` or
  `ingress` is enabled (`networkPolicy.ingressControllerNamespaceSelector`, default `hangar-gateway`), and
  each `allowIngressFrom` entry. Egress stays open unless `allowEgressTo` or `extraEgressRules` adds a rule.
  `allowIngressFrom`/`allowEgressTo` entries take `namespace` (optionally with `podLabels`) or `cidr`, and
  bare TCP `ports`; `extraIngressRules`/`extraEgressRules` are raw passthroughs for anything else.
- `httpRoute` (Gateway API) needs `hostnames` and `parentRefs`; the platform Gateway is `hangar` in
  `hangar-gateway`, which Apron installs. Its `pathType` is `PathPrefix | Exact | RegularExpression`,
  unlike `ingress.pathType`.

## Observability

`observability` is platform-owned: the tenant-onboarding ApplicationSet sets it from Apron's cluster config and
the app's kind, and an env file may not. Every field empty (the default) renders exactly as before.

- `observability.namespace` (where Prometheus runs): when the app opts in to scraping (`serviceMonitor.enabled`,
  off by default), the NetworkPolicy admits it on the ServiceMonitor's port. Without it the baseline policy drops
  every scrape. The scrape is opt-in because Hangar apps send metrics over OTLP; a scrape of an app that serves no
  `/metrics` is a target that is always down, and a 404 traced every 30s.
- `observability.instrumentation` (`<namespace>/<name>` of the cluster's OpenTelemetry Operator
  `Instrumentation`) and `observability.runtime` (`nodejs`, `java`, `python` or `go`, from the app's kind): the
  pods carry `instrumentation.opentelemetry.io/inject-<runtime>` and `deployment.environment.name`, so the app
  sends traces and metrics to the collector with no code change. `go` is not injected (the operator's Go agent is a
  privileged eBPF sidecar). If the app restricts egress, the NetworkPolicy also allows OTLP (4317/4318) to that
  namespace.

## Attached XRs

`components:` entries become XRs of the kind `componentKinds` maps their `type` to, with `spec:` passed
through and `spec.environmentRef.name: <app>-<cluster>-<env>` added. The component's XRD validates the
spec; `tools/airframe-validate` checks it before merge. `slos:` entries become `SLO` XRs the same way. A
`RolloutWatch` named after the app watches the Rollout and, with `notifications.slack.enabled`, posts its
diagnosis to Slack using the `slack-webhook-url` key from the app's shared store. All attached XRs use
`attachedResourceApiVersion` (`catalog.hangar.io/v1alpha1`).

## Jobs and CronJobs

Both share the main workload's `env`, `secrets`, `configMaps`, `volumes` and projected tokens. A `jobs:`
entry is a Helm `pre-install,pre-upgrade` hook by default (ArgoCD runs it before each sync, for
migrations); `hook: false` makes it a plain Job. Integer fields where 0 is meaningful (`backoffLimit`, the
history limits) use the `airframe-application.intOr` helper, because Sprig's `default` treats 0 and `false`
as unset.

## Editing the chart

- `values.schema.json` is the source of truth. `values.yaml` is generated from it
  (`python3 tools/gen_airframe_schema.py --write-values`), and so are the contract and the AppSpec
  `$defs` (`tools/gen_contract.py`, `tools/gen_appspec_schema.py`). CI runs each with `--check`.
  Autopilot vendors `contract/appspec.schema.json`, so a schema description change needs an Autopilot
  sync too.
- `tests/run.sh` renders the fixtures in `tests/fixtures/` and checks what appears, and runs
  `tools/airframe-validate` against `tests/validate/`. No cluster needed. CI runs it with `helm lint`
  (`.github/workflows/airframe-chart-ci.yaml`).
- Validate a values file with `tools/airframe-validate FILE` (schema, component XRDs, and a `helm
  template`), or `--no-render` for the schema only.
- The chart fails the render, with a message naming the field, rather than rendering something wrong:
  unknown component types, both or neither of `data:`/`existingConfigMap:`, a bad `as:`, a NetworkPolicy
  peer with both `namespace` and `cidr`, missing `httpRoute` hostnames or parentRefs. New fields should do
  the same.
