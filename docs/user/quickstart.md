# Airframe quickstart

A hands-on walkthrough: create a service, get its pipeline running, give it a
**ground** environment to iterate in and a **flight** environment to actually
run in, then add a Redis cache.

We build `boarding-api`, a small Go service that looks up a passenger's gate/seat
assignment and caches the answer in Redis so a busy gate screen polling every few
seconds doesn't hammer the reservations system.

> An illustrated version of this guide is published at
> [Airframe Quickstart](https://claude.ai/artifact/WDPmWSD9BMBGurFzqATDWG).

**What has and hasn't been verified.** Sections 02–06 describe mechanisms that are
live and in use on real apps (`checkout-api`, `order-api`, `boarding-api`). Section
07 (Redis) is **not verified end to end** — no Redis has ever been provisioned
through this catalog, and it can only work on a cluster that has `provider-helm`
and the `Redis` XRD installed. As of 2026-09-23 that is the dev cluster only. The
section says exactly what is and isn't there.

## 01 — Ground & flight

Every Airframe app can have two kinds of environment, built by different
mechanisms with different review bars.

| | **Ground** | **Flight** |
|---|---|---|
| What it is | A disposable environment on the dev cluster | A governed environment on a real upper cluster |
| Declared in | `platform/envs/<name>.yaml` in **your source repo** | An `ApplicationEnvironment` XR, rendering `gitops-<app>/<cluster>/<env>/values.yaml` |
| Gets its image from | Your pipeline's `deploy` stage, **committed straight to `main`** — no PR | Your pipeline's `release` stage, as a **reviewed pull request** |
| Configured with | Editing `platform/envs/<name>.yaml` by hand | Tower's **App Configuration** tab (each save is a PR) |
| Cluster | Dev cluster only | Any cluster the registry marks `type: upper` |

Both render through the same Helm chart, `airframe-application`. "Ground" and
"flight" name the *tier*, not a field value — you'll still type real names like
`dev` and `staging` below.

## 02 — Create the app

**Tower → Create → GoApplication.** Every Bootstrap-tier stack (NodeJS, Spring
Boot, Go, Python, InfraService) is a Backstage Scaffolder template generated from
its XRD. Fill in:

| Field | Value |
|---|---|
| Name | `boarding-api` |
| `devCluster` | `kind-dev` |
| `description` | Gate/seat lookup with a Redis-backed cache |
| `goVersion` | `1.23` |
| `port` | `8080` |
| `visibility` | `private` |

Submitting opens a pull request into `gitops-cluster-dev-tenants` at
`tenants/boarding-api/xr-requests/boarding-api.yaml`. **Merge it** — the
`xr-requests` ApplicationSet applies that file to the dev cluster as a
`GoApplication` XR:

```
$ kubectl get goapplication boarding-api -n app-boarding-api-cicd
NAME           SYNCED   READY   COMPOSITION                     AGE
boarding-api   True     True    goapplications.catalog.idp.io   3m
```

`kubectl describe` shows the two custom conditions this catalog adds:
`DevClusterReady` (the dev cluster passed the registry check) and `CicdOnboarded`
(Glidepath has picked the app up).

Crossplane then creates the real `boarding-api` source repo (with a starter
`cicd.yaml`, see below) and an empty `gitops-boarding-api` repo, and registers the
app with Glidepath. You now have a repo — but no running pipeline yet, and nothing
deployed.

The scaffolded `cicd.yaml` is deliberately minimal: `build` only, `agent: go-1.23`,
unit tests off. You'll extend it in sections 05 and 06.

## 03 — Merge the pipeline onboarding PR

Pipelines run through Pipelines-as-Code, which reads pipeline definitions from a
`.tekton/` folder in the source repo. You don't write those files; Glidepath does.
But they have to get into your repo, and that takes **one pull request that you
merge**:

1. Once the app is registered, Glidepath's onboarding hook notices your repo has no
   `.tekton/onboarding-resync.yaml` and opens a PR against **`boarding-api`** (and
   against `gitops-boarding-api`) adding the generated `.tekton/*.yaml` files.
2. **Merge it.** Find it in GitHub, or in Tower's **Pull Requests** tab.
3. Until this is merged, pushing to `main` does nothing — PaC finds no pipeline to
   run.

These files are never hand-edited. From then on, **every push that changes
`cicd.yaml` opens a fresh PR** regenerating `.tekton/` if anything changed —
merge those too. (You will meet this again in sections 05 and 06.) If nothing
happens after you push, check first that the platform's GitHub App has access to
the repo.

Once merged, a push to `main` runs the scaffolded `build` stage and publishes an
image to `ghcr.io/<owner>/boarding-api`.

## 04 — The app starts with no deployment

At this point `boarding-api` has an image and no environment: **nothing is running
anywhere.** Onboarding creates the app, its repos, and its pipeline; it does not
create a Deployment. Environments are separate objects, added next. There are two
places to configure them, matching the two tiers:

- **Ground** — you edit `platform/envs/dev.yaml` yourself (section 05).
- **Flight** — you use Tower's **App Configuration** tab (section 06). That tab
  edits `gitops-<app>/<cluster>/<env>/values.yaml` through pull requests, and it
  only lists **flight** environments — the ones your `cicd.yaml` declares under
  `deploy.upperEnvironments`. It can't see a ground env, and it can't see a flight
  env until `cicd.yaml` declares it.

## 05 — Ground: a running environment on the dev cluster

A ground environment is two things: a file that creates the namespace, and a
pipeline stage that puts an image in it.

**Step 1 — declare the environment.** Create `platform/envs/dev.yaml` in the
`boarding-api` repo:

```yaml
# envName, not env — env is a reserved key in the chart's container env-var list.
# rollout: null must be explicit — omitting it makes the chart render its own
# default rollout with an empty image (two InvalidImageName pods).
envName: dev
rollout: null
```

A dev-cluster-only `ApplicationSet` (`boarding-api-lower-envs`) watches
`platform/envs/*.yaml` in your repo. Within a sync interval you get an empty
namespace, `app-boarding-api-dev`, with the baseline ServiceAccount and
NetworkPolicy and no workload.

**Step 2 — let the pipeline deploy to it.** Replace the scaffolded `cicd.yaml` with
a flow that builds, tests, and deploys to `dev`:

```yaml
apiVersion: platform/v1
kind: PipelineConfig

build:
  agent: go-1.23
  unitTest:
    enabled: false        # flip on once you add a test script

deploy:
  lowerEnvironments: [dev]

pipelines:
  ci:
    trigger: { source: git, event: push, branch: main }
    steps:
      - stage: build
      - stage: test       # no tests configured yet: runs, reports success, tests nothing
        env: dev
      - stage: deploy
        env: dev
```

**Step 3 — commit both files and merge the `.tekton/` PR.** Changing `cicd.yaml`
triggers section 03's resync: a new PR regenerates `.tekton/`. Merge it.
Separately, ArgoCD reads the new `cicd.yaml` and provisions the deploy RBAC for
`app-boarding-api-dev`.

**Step 4 — run it.** Push to `main`. The `deploy` stage **commits
`rollout.image.repository` and `rollout.image.tag` directly into
`platform/envs/dev.yaml` on `main`** — no branch, no PR. `git pull` before your
next push, or you'll be rebasing over the bot's commit.

```yaml
# platform/envs/dev.yaml after the first deploy
envName: dev
rollout:
  image:
    repository: ghcr.io/jfillman/boarding-api
    tag: 0.1.0-a1b2c3d
```

The chart's defaults apply for everything else: two replicas, container port
`8080` named `http`, no probes. `boarding-api` listens on 8080, so this works
as-is.

```
$ kubectl get pods -n app-boarding-api-dev
NAME                            READY   STATUS    RESTARTS
boarding-api-6c8f9d4b7-x2k9p    1/1     Running   0
```

To change ground settings (replicas, ports, probes, resources), edit
`platform/envs/dev.yaml` directly — the App Configuration tab does not cover it.

## 06 — Flight: a governed environment on an upper cluster

### Step 1 — declare the environment in `cicd.yaml`

Add the flight env and a `release` stage. The `release` stage is what supplies
the image to a flight env, and Tower's App Configuration tab builds its
environment list from this `upperEnvironments` block:

```yaml
deploy:
  lowerEnvironments: [dev]
  upperEnvironments:
    - { name: staging, cluster: kind-prod }

governance:
  allowedCommitSigners:
    - you@example.com       # release gates are enforced; with no signers every
                            # release fails the commit-signature gate

pipelines:
  ci:
    trigger: { source: git, event: push, branch: main }
    steps:
      - stage: build
      - stage: test
        env: dev
      - stage: deploy
        env: dev
      - stage: release
        env: staging
```

Merge the `.tekton/` PR this push opens (section 03). See Glidepath's
`docs/user/examples/04-multi-env-promotion.yaml` and
`10-production-grade.yaml` for the governance options.

### Step 2 — create the ApplicationEnvironment

**Tower → Create → ApplicationEnvironment.** The form has these fields:

| Field | Value | Notes |
|---|---|---|
| Name | `boarding-api-kind-prod-staging` | The XR's own name. Convention is `<app>-<cluster>-<env>`, as with every existing env. |
| Namespace | `app-boarding-api-cicd` | The app's tenant namespace, `app-<app>-cicd`. The `xr-requests` AppProject only permits this namespace. |
| Owner | `group:default/jfillman` | Same as every existing env. |
| `appName` | `boarding-api` | Required. Labels the env and drives a deletion-protection `Usage` on the app. Not live-checked: a typo silently creates an env for an app that doesn't exist. |
| `cluster` | `kind-prod` | Required. Live-checked against the cluster registry: must be `type: upper` and `crossplaneReady`. A dev cluster is rejected, and the XR reports `ClusterReady: False` and creates nothing. |
| `env` | `staging` | Required. A DNS label, max 20 characters (`^[a-z0-9]([-a-z0-9]*[a-z0-9])?$`) — it becomes part of the namespace `app-boarding-api-staging` and a git path. |
| `configMapGenerator` | off | Opt-in to a Kustomize `configMapGenerator` source for this env's config files. Leave off unless you need it. |

The Crossplane Settings page can stay at its defaults.

Submitting opens a PR into `gitops-cluster-dev-tenants`
(`tenants/boarding-api/xr-requests/boarding-api-kind-prod-staging.yaml`). Merge
it. Crossplane then commits a bootstrap `values.yaml` to
`gitops-boarding-api/kind-prod/staging/` and an onboarding entry to
`kind-prod`'s own tenants repo, so **kind-prod's own ArgoCD** picks the env up — no
cross-cluster credential is involved.

```
$ kubectl get applicationenvironment -n app-boarding-api-cicd
NAME                             SYNCED   READY   COMPOSITION                              AGE
boarding-api-kind-prod-staging   True     True    applicationenvironments.catalog.idp.io   2m
```

`kubectl describe` shows `ClusterReady: True` and `WorkloadDeployed: False`. The
bootstrap file is `rollout: null`: a namespace, no workload. `WorkloadDeployed`
stays `False` until one exists.

### Step 3 — configure it in Tower's App Configuration tab

**Tower → boarding-api → App Configuration → environment `staging`.** The active
environment is shown prominently at the top; check it before saving. Turn on the
**Deployment** switch (an env with `rollout: null` deploys no Rollout, Service,
HPA or PDB) and fill in:

| Section | For boarding-api |
|---|---|
| Deployment | On |
| Scaling | Replicas `2` |
| Resources | Requests `100m` / `128Mi`, limits `500m` / `256Mi` |
| Service | port name `http`, containerPort `8080` |
| Health checks | Liveness and readiness: HTTP GET `/healthz` on `8080` |
| Canary steps | Leave the default, or build a weight/pause/analysis sequence |

**Save** opens a pull request into `gitops-boarding-api` — never a direct commit,
in any environment. The tab validates the change against the chart's own
`values.schema.json` before it lets you submit. Merge the PR.

There is no image field. The image is set by the release pipeline in the next
step, so until it runs the Rollout has no image to start.

### Step 4 — release an image

Push to `main`. After `build`, `test` and `deploy` to dev, the `release` stage
opens a PR against `gitops-boarding-api` setting `rollout.image` for `staging`.
Merge it — as a **signed** commit; GitHub's merge button produces an unsigned one,
see Glidepath's `docs/admin/commit-signing.md` ("Merge strategy matters"). kind-prod's
ArgoCD syncs it and `WorkloadDeployed` flips to `True` once a real Rollout exists.

## 07 — Adding a Redis cache

**Not verified end to end. Read this section as "what the code says," not "what
was tried."**

### What kind of thing is Redis?

Redis is an **Attached-tier component**. It is not a Bootstrap object (you don't
create it in Tower's Create menu — there is no form for it) and not an Embedded
setting. You add one by putting an entry in the `components:` list of an
environment's `values.yaml`; the `airframe-application` chart renders that entry
into a `Redis` XR, whose Composition renders a `provider-helm` `Release` of
Bitnami's `redis` chart (standalone, one instance per entry, in the same
namespace as your app).

```yaml
components:
  - type: redis
    name: cache
    spec: { size: small, persistence: false }   # environmentRef is stamped for you
```

### Where it can work today

A component only works where Crossplane can actually reconcile it. Checked
against the live clusters on 2026-09-23:

| Cluster | `provider-helm` | `Redis` XRD |
|---|---|---|
| dev (`kiac-dev`) | installed, healthy | installed |
| `kind-prod` | **not installed** | **not installed** |

So the **ground** tier is the only place a Redis component can be tried, by
adding the block above to `platform/envs/dev.yaml`. A **flight** env on
`kind-prod` can't run one until `provider-helm` and the `Redis` XRD are installed
there. No `Redis` object, and no Helm release, currently exists on any cluster.

### Consuming it

The Composition publishes host, port, and password to a Secret named
`<xr-name>-connection` in your namespace. **Wiring that Secret into your app is
not built** — the Composition's own header says so. `secrets:` entries in
`values.yaml` read from Infisical by name; they don't read arbitrary Kubernetes
Secrets. The manual route is to copy the password into the app's Infisical
project, list it under `secrets:`, and put the host and port in `configMaps:`
(find the Service name with `kubectl get svc -n app-boarding-api-dev`).

### Shared Redis: not supported yet

One Redis serving several apps is not a feature of this catalog. `Redis` has no
attach mode, and the obvious construction — a standalone `InfraService` hosting
the instance — can't get a flight environment on a cluster that has no Redis
support, and `ApplicationEnvironment` rejects the dev cluster. The earlier version
of this guide described a shared-Redis flow; it was untested and has been removed.

## The cache, in Go

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

- **Merge the `.tekton/` PR** — after creating the app, and again after every
  `cicd.yaml` change. No merge, no pipeline.
- **Nothing is deployed after onboarding.** Ground needs `platform/envs/dev.yaml`
  plus a `deploy` stage; flight needs an `ApplicationEnvironment`, App
  Configuration, and a `release` stage.
- **App Configuration is flight-only**, and only lists envs declared in
  `deploy.upperEnvironments`.
- **`envName`, never `env`** in `platform/envs/*.yaml`.
- **`rollout: null` must be explicit.**
- **The ground deploy commits to `main` itself** — pull before you push.
- **`ApplicationEnvironment` rejects dev clusters** — `cluster` is live-gated to
  `type: upper`.
- **Redis is a component, dev cluster only, unverified.**
