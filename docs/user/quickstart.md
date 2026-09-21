# Airframe quickstart

A hands-on walkthrough: create a service, give it a **ground** environment to
iterate in and a **flight** environment to actually run in, then attach it to a
Redis cache — either its own, or one shared with other apps.

Every step below is real. We build `boarding-api`, a small Go service that looks up
a passenger's gate/seat assignment and caches the answer in Redis so a busy gate
screen polling every few seconds doesn't hammer the reservations system.

> An illustrated, diagram-led version of this same guide is published at
> [Airframe Quickstart](https://claude.ai/artifact/WDPmWSD9BMBGurFzqATDWG).

## 01 — Ground & flight

Every Airframe app has access to two kinds of environment. They're not "dev" and
"prod" with different names — they're built by entirely different mechanisms, with
different owners and different review bars.

| | **Ground** | **Flight** |
|---|---|---|
| What it is | A disposable environment on the dev cluster | A governed environment on a real upper cluster |
| Where it lives | `platform/envs/*.yaml`, in your own source repo | An `ApplicationEnvironment` XR, rendering into `gitops-<app>/<cluster>/<env>/values.yaml` |
| How it deploys | A direct commit — no PR, no review | A CI-opened, reviewed pull request |
| Cluster | Dev cluster only — structurally rejected everywhere else | Any cluster the registry marks `type: upper` |
| Also covers | Per-PR preview environments (auto-created, TTL-swept) | Every promoted release this app will ever have |

Both tiers render through the exact same Helm chart, `airframe-application` — a
ground environment isn't a toy version of the real thing, it's the same rendering
path with a shorter, unreviewed path to get there. "Ground" and "flight" describe
the *tier*, not a literal field value — you'll still type real names like `dev` or
`staging` into the actual YAML below.

## 02 — Create the app

Open **Tower → Create → GoApplication**. Every Bootstrap-tier stack — NodeJS,
Spring Boot, Go, Python, InfraService — is a real Backstage Scaffolder template,
generated straight from its XRD's schema. Tower's form *is* the primary path; you
never have to hand-write the XR.

| Field | Value |
|---|---|
| `appName` | `boarding-api` |
| `devCluster` | `kind-dev` |
| `description` | Gate/seat lookup with a Redis-backed cache |
| `goVersion` | `1.23` |
| `port` | `8080` |
| `visibility` | `private` |

Submitting opens a real pull request into
`tenants/boarding-api/xr-requests/goapplication.yaml`. Merge it, then watch the
conditions flip:

```
$ kubectl get goapplication boarding-api -n app-boarding-api-cicd
NAME            DEVCLUSTERREADY   CICDONBOARDED   READY
boarding-api    True              True            True
```

Behind the form: Crossplane reconciles the `GoApplication` XR,
`provider-upjet-github` creates the real `boarding-api` source repo and an empty
`gitops-boarding-api` repo, and a composed `TektonCICD` child wires up the real
pipeline. Scaffolding also commits a minimal, real `cicd.yaml` at the repo root —
build-only, `agent: go-1.23` (matching the `goVersion` you picked), no test stage
yet — so the pipeline is actually runnable immediately, not just onboarded. You
now have a repo and a working pipeline, with nowhere to deploy yet.

## 03 — Ground: somewhere to run today

Ground environments live in your own repo — no PR, no reviewer, no gitops repo
involved. Commit straight to your branch and a dev-cluster-only `ApplicationSet`
reads it live.

`boarding-api/platform/envs/dev.yaml`:

```yaml
# envName, not env — env is a reserved key in the chart's own container
# env-var list. Bootstrap stub: rollout must be explicit null, not omitted,
# or the chart's own non-null default renders two InvalidImageName pods.
envName: dev
rollout: null
```

That's the whole file. Within a sync interval you have a real namespace,
`app-boarding-api-dev`, with nothing running in it yet. A normal push through the
onboarded pipeline builds and pushes a real image, then opens a PR that sets
`rollout.image` in this same file. Merge it, and the ground namespace runs the
real thing.

## 04 — Flight: somewhere that matters

A flight environment is a real `ApplicationEnvironment` XR — created in Tower the
same way you created the app, but gated: the target cluster has to be
live-registered as `type: upper`, or the request is rejected outright.

**Tower → Create → ApplicationEnvironment**

| Field | Value |
|---|---|
| `appName` | `boarding-api` |
| `cluster` | `kind-prod` — must resolve `type: upper` |
| `env` | `staging` |

This opens PRs in two places: a values-bootstrap commit into
`gitops-boarding-api/kind-prod/staging/values.yaml`, and an onboarding entry into
`kind-prod`'s own tenants repo so its **own** ArgoCD picks the release up — no
cross-cluster credential is ever used to do this.

`gitops-boarding-api/kind-prod/staging/values.yaml`:

```yaml
appName: boarding-api
appType: app
cluster: kind-prod
envName: staging
rollout:
  image:
    repository: ghcr.io/jfillman/boarding-api
    tag: 0.1.0-a1b2c3d
  ports:
    - name: http
      containerPort: 8080
  strategy: canary
```

Merge the release PR. `ClusterReady` and then `WorkloadDeployed` flip `True` once
`kind-prod`'s ArgoCD actually syncs a running `Rollout` — not on a timer, on the
real object existing.

## 05 — A Redis of its own

Redis is an Attached-tier component — no Tower form, no new repo. Add four lines
to the env's own `values.yaml` and the chart's existing `components:` loop
renders a real `Redis` XR, which composes a `provider-helm` Release of Bitnami's
chart, standalone, in your app's own namespace.

```yaml
components:
  - type: redis
    name: cache
    spec: { size: small, persistence: false }
# environmentRef is stamped automatically — never type it by hand.
# persistence: false because this is a lookup cache, not a store: a
# restart losing the cache is fine, a restart losing real data isn't.
```

```
$ kubectl get secret cache-connection -n app-boarding-api-staging -o json | jq '.data | keys'
["host", "password", "port"]

$ kubectl get svc -n app-boarding-api-staging | grep cache
cache-master   ClusterIP   10.96.14.2   <none>   6379/TCP
```

Host, port, and password land in a K8s Secret named `cache-connection`, same
namespace, via Crossplane's own connection-secret mechanism. Reference it from
`secrets:` on the same release like any other app secret — it never leaves this
namespace, and nobody else can reach it.

## 06 — A shared Redis

Redis in this catalog only ever provisions **one dedicated instance per
`components:` entry** — there's no `mode: create | attach` field the way a future
shared-tenant Postgres might have one. "Shared Redis" isn't a distinct catalog
feature; it's a pattern built from the primitives that already exist.

> **Be honest about this one.** Consumer access to an Attached-tier component's
> connection secret is real, working, **manual** plumbing today — not an automatic
> catalog feature. The Redis Composition itself says so in its own header.
> Everything below is the recommended pattern given what's actually built, not a
> documented "shared mode."

### Bootstrap the shared instance as its own InfraService

**Tower → Create → InfraService** — no `nodeVersion`, no `port`, because there's
no application code here, only infrastructure:

| Field | Value |
|---|---|
| `appName` | `shared-redis` |
| `devCluster` | `kind-dev` |
| `description` | Shared lookup-cache Redis, kind-prod |

This gets you the same `gitops-infra-shared-redis` repo and CI/CD onboarding a
real app gets — it's a service with no source code, not a special object.

### Give it a flight environment, then attach Redis to itself

`gitops-infra-shared-redis/kind-prod/prod/values.yaml`:

```yaml
appName: shared-redis
appType: infra
cluster: kind-prod
envName: prod
rollout: null
components:
  - type: redis
    name: cache
    spec: { size: medium, persistence: true }
```

Same `components:` mechanism as §05 — the only difference is that this app's
whole purpose is being that instance. Persistence on this time: other apps depend
on this cache surviving a restart.

### Copy the credential into boarding-api's own Infisical project

The host and port aren't secret — just a same-cluster Service DNS name — so they
go straight into a plain `configMaps:` entry on the consuming app. Only the
password needs secure distribution, and each app already has its own Infisical
project wired for exactly this:

```bash
# one-time, by a human — the missing automatic step
infisical secrets set REDIS_SHARED_PASSWORD "$(kubectl get secret cache-connection \
    -n app-shared-redis-prod -o jsonpath='{.data.password}' | base64 -d)" \
    --projectId boarding-api-prod --path /
```

`gitops-boarding-api/kind-prod/staging/values.yaml`:

```yaml
configMaps:
  REDIS_SHARED_HOST: "cache-master.app-shared-redis-prod.svc.cluster.local"
  REDIS_SHARED_PORT: "6379"
secrets:
  - name: REDIS_SHARED_PASSWORD
    fromInfisical: REDIS_SHARED_PASSWORD
```

boarding-api now reads the shared instance through plain env vars — same as any
Embedded-tier config, nothing Redis-specific about the wiring on this side.

## 07 — The cache, in Go

```go
func getBoardingInfo(ctx context.Context, rdb *redis.Client, code string) (*Boarding, error) {
	key := "boarding:" + code

	if cached, err := rdb.Get(ctx, key).Result(); err == nil {
		var b Boarding
		if json.Unmarshal([]byte(cached), &b) == nil {
			return &b, nil // cache hit — no reservations-system call at all
		}
	}

	b, err := lookupFromReservations(ctx, code) // the slow path
	if err != nil {
		return nil, err
	}

	if payload, err := json.Marshal(b); err == nil {
		rdb.Set(ctx, key, payload, 3*time.Minute) // short TTL, no manual invalidation
	}
	return b, nil
}
```

## Cheat sheet

- **`envName`, never `env`** — `env:` is a reserved key in the chart's own
  container env-var list. Using it for the environment name renders a real Helm
  error, not a warning.
- **`rollout: null` must be explicit** — omitting the key entirely inherits the
  chart's own non-null default and renders two crash-looping pods instead of a
  clean, empty bootstrap namespace.
- **`environmentRef` is never hand-typed** — every Attached-tier `components:`
  entry gets its `environmentRef` auto-stamped by the chart's own renderer.
- **`ApplicationEnvironment` rejects dev clusters** — a flight environment's
  `cluster` field is live-gated to `type: upper`, by design.
