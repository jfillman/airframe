# Airframe quickstart

A hands-on walkthrough that ends with a **running application**: create a service,
get its pipeline running, pull in the code, give it a **ground** environment to
iterate in and a **flight** environment to run in, add a Redis cache, and finish
with a real **canary** rollout you can watch.

We build `boarding-api`, the gate board of [Skyport](skyport-demo.md) — a small
NodeJS service that looks up a flight's gate and caches the answer in Redis so a
busy gate screen doesn't hammer the reservations system. It also has a page built
to make canary and blue/green deployments *visible*.

> An illustrated version of this guide is published at
> [Airframe Quickstart](https://claude.ai/artifact/WDPmWSD9BMBGurFzqATDWG).

**What has and hasn't been verified.**
- **Verified:** the app itself. Its tests pass, and it was run against a real Redis
  container, including two instances sharing one counter.
- **Verified in production use:** the create → onboard → environment mechanics
  (sections 02–03 and 05–07) are live on real apps (`checkout-api`, `order-api`).
- **Not verified end to end:** this exact walkthrough with *this* code, and the
  Redis component (section 08) — no Redis has ever been provisioned through this
  catalog. The Redis platform pieces are installed on both clusters (airframe
  v0.3.83); section 08 says what is and isn't in place. Sections 06–09 are being
  walked for the first time — where a step here turns out wrong, this guide is
  corrected.

**Starting over?** If a previous `boarding-api` was decommissioned, finish
[decommissioning](decommission-app.md) first — in particular delete its Infisical
projects (`boarding-api-kind-dev`, `boarding-api-kind-prod`) and any
`boarding-api` key in kind-prod's `secretstore-provisioner` ConfigMap, or the new
app tries to adopt a dead project. Also move any old local `boarding-api` checkout
out of the way: section 04 clones into that directory name.

**Two architectures.** The dev cluster (`kiac-dev`) is arm64 and `kind-prod` is
amd64. Leave `build.platforms` unset in `cicd.yaml` so your image is built for both;
if you set it to one, the other cluster gets `exec format error`.

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

**Tower → Create → NodeJSApplication.** Every Bootstrap-tier stack (NodeJS, Spring
Boot, Go, Python, InfraService) is a Backstage Scaffolder template generated from
its XRD. Fill in:

| Field | Value |
|---|---|
| Name | `boarding-api` |
| `devCluster` | `kind-dev` |
| `description` | Skyport gate board: Redis-cached flight lookups and a canary visualizer |
| `nodeVersion` | `20` |
| `packageManager` | `npm` |
| `port` | `8080` |
| `visibility` | `private` |

**Use `kind-dev` exactly, even though the dev cluster is `kiac-dev`.** The dev ApplicationSets hard-code `cluster: kind-dev` when they render an environment's ExternalSecret, so it reads the store `<app>-kind-dev`. An app created with `devCluster: kiac-dev` gets a store named `<app>-kiac-dev`, its ExternalSecret never syncs, and its pods sit in `CreateContainerConfigError`. And don't remove `kind-dev` from the cluster-registry: every existing app is pinned to it, and removing it turns their stores `InvalidProviderConfig` fleet-wide.

Submitting opens a pull request into `gitops-cluster-dev-tenants` at
`tenants/boarding-api/xr-requests/boarding-api.yaml`. **Merge it** — the
`xr-requests` ApplicationSet applies that file to the dev cluster as a
`NodeJSApplication` XR:

```
$ kubectl get nodejsapplication boarding-api -n app-boarding-api-cicd
NAME           SYNCED   READY   COMPOSITION                          AGE
boarding-api   True     True    nodejsapplications.catalog.idp.io    3m
```

`kubectl describe` shows the two custom conditions this catalog adds:
`DevClusterReady` (the dev cluster passed the registry check) and `CicdOnboarded`
(Glidepath has picked the app up).

Crossplane then creates the real `boarding-api` source repo and an empty
`gitops-boarding-api` repo, and registers the app with Glidepath. The source repo
starts with a hello-world `index.js`, a `package.json`, a `Containerfile`, and a
minimal `cicd.yaml` (`build` only, `agent: nodejs-20`, unit tests off). You now have a
repo — but no running pipeline yet, and nothing deployed.

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
merge those too. (You will meet this again in sections 06 and 07.) If nothing
happens after you push, check first that the platform's GitHub App has access to
the repo.

Once merged, a push to `main` runs the scaffolded `build` stage and publishes a
multi-arch image to `ghcr.io/<owner>/boarding-api`.

## 04 — Pull in the code

The scaffold's `index.js` is hello-world. The real `boarding-api` lives in the
`airframe` repo, under `examples/skyport/boarding-api/`. Copy it over the scaffold:

```bash
git clone https://github.com/jfillman/airframe.git /tmp/airframe
git clone https://github.com/jfillman/boarding-api.git && cd boarding-api   # fails if ./boarding-api already exists

cp -R /tmp/airframe/examples/skyport/boarding-api/. .
git add -A && git commit -m "boarding-api: gate board with Redis-backed lookups"
```

This overwrites `index.js` and `package.json` and adds `app.js`, `store.js`,
`reservations.js`, `public/`, `test/` and `test.sh`. **Keep the scaffolded
`Containerfile`** — it already does what this app needs (`npm install`, `COPY . .`,
`CMD ["node", "index.js"]`). Keep `cicd.yaml` for now too; you'll change it in
section 06, and push then.

Try it locally before pushing:

```bash
npm install && npm test        # 6 passing
PORT=8080 node index.js        # open http://localhost:8080
```

You'll see the gate board. With no `REDIS_URL` set the header says `cache: memory` —
the app falls back to an in-process store so it runs anywhere. That fallback is a
teaching aid: with two replicas each pod keeps its own counts, which is the exact
problem Redis fixes in section 08.

What the app does:

| Endpoint | Purpose |
|---|---|
| `GET /` | The gate board — flight lookup, boarding-pass scans, and the version tally |
| `GET /api/boarding/:flight` | Boarding info for a flight like `AC123`; cached for 3 minutes; reports `cached` and `latencyMs` |
| `POST /api/boarding/:flight/scan` | Increments that flight's boarded counter |
| `GET /api/whoami` | Version, pod and cache mode — what the canary tally polls |
| `GET /healthz` | Liveness / readiness |

## 05 — The app starts with no deployment

At this point `boarding-api` has an image and no environment: **nothing is running
anywhere.** Onboarding creates the app, its repos, and its pipeline; it does not
create a Deployment. Environments are separate objects, added next. There are two
places to configure them, matching the two tiers:

- **Ground** — you edit `platform/envs/dev.yaml` yourself (section 06).
- **Flight** — you use Tower's **App Configuration** tab (section 07). That tab
  edits `gitops-<app>/<cluster>/<env>/values.yaml` through pull requests, and it
  only lists **flight** environments — the ones your `cicd.yaml` declares under
  `deploy.upperEnvironments`. It can't see a ground env, and it can't see a flight
  env until `cicd.yaml` declares it.

## 06 — Ground: a running environment on the dev cluster

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
  agent: nodejs-20
  unitTest:
    enabled: true         # runs ./test.sh, which the code you copied in provides

deploy:
  lowerEnvironments: [dev]

pipelines:
  ci:
    trigger: { source: git, event: push, branch: main }
    steps:
      - stage: build
      - stage: test
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
as-is. Two replicas matters later: it's what makes the in-memory counter visibly
wrong.

```
$ kubectl get pods -n app-boarding-api-dev
NAME                            READY   STATUS    RESTARTS
boarding-api-6c8f9d4b7-x2k9p    1/1     Running   0
```

**See it.** Reach it with a port-forward (find the Service name with
`kubectl get svc -n app-boarding-api-dev`):

```bash
kubectl port-forward -n app-boarding-api-dev svc/boarding-api 8080:8080
```

Open <http://localhost:8080>. Look up `AC123` twice — the second answer is a
**cache hit**, a few milliseconds instead of ~400. Then press **Scan a boarding pass**
several times: the counter jumps around, because the two pods each count on their
own (`counter: memory`). Keep that in mind for section 08.

To change ground settings (replicas, ports, probes, resources), edit
`platform/envs/dev.yaml` directly — the App Configuration tab does not cover it.

## 07 — Flight: a governed environment on an upper cluster

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
| Scaling | Replicas `4` (a canary splits by replica count, so 4 gives readable 25% steps) |
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

## 08 — Add a Redis cache

**Not verified end to end. Read this section as "what the code says," not "what
was tried."** The app side *is* verified against a real Redis; the platform side —
the component provisioning it — has never run.

### What kind of thing is Redis?

Redis is an **Attached-tier component**. It is not a Bootstrap object (you don't
create it from Tower's Create menu — there is no form for it) and not an Embedded
setting. You add one by putting an entry in the `components:` list of an
environment's values; the `airframe-application` chart renders that entry into a
`Redis` XR, whose Composition renders a `provider-helm` `Release` of Bitnami's
`redis` chart (standalone, one instance per entry, in the same namespace as your
app, password-protected).

### Where it can work

A component only works where Crossplane can reconcile it — `provider-helm` and the
`Redis` XRD must both be installed on that cluster. As of 2026-09-23:

| Cluster | `provider-helm` | `Redis` XRD |
|---|---|---|
| dev (`kiac-dev`, arm64) | installed, healthy | installed |
| `kind-prod` (amd64) | installed, healthy | installed (delivered by the `idp-service-catalog-redis` Application) |

Both tiers have what they need, and both clusters run airframe v0.3.83, which
includes the Redis naming fix. All the images involved are multi-arch, checked
against the registries.

### Ground: add it to `platform/envs/dev.yaml`

Name the component whatever you like; we use **`cache`**. The Composition sets the
Bitnami chart's `fullnameOverride` to the component name, so the Service is
`<name>-master` (here `cache-master`) and the password Secret is `<name>` (here
`cache`), exactly what the connection secret expects. (Before airframe v0.3.79 this
was broken and the name had to be `redis`; every cluster is past that now.)

```yaml
envName: dev
components:
  - type: redis
    name: cache
    spec: { size: small, persistence: false }   # environmentRef is stamped for you
env:
  - { name: REDIS_URL, value: "redis://cache-master:6379" }
secrets:
  - name: redis-password      # read from this app's Infisical project
    key: REDIS_PASSWORD       # the env var boarding-api reads
```

(Keep the `rollout:` block the deploy stage wrote; only add the keys above.)

### The one manual step

Wiring the Redis connection Secret into your app **is not built** — the
Composition's own header says so. `secrets:` entries read from Infisical by name, not
from arbitrary Kubernetes Secrets. So copy the password across once:

```bash
kubectl get secret cache -n app-boarding-api-dev -o jsonpath='{.data.redis-password}' | base64 -d
```

Add it to `boarding-api`'s Infisical project as `redis-password`. (The host and port
are already in `REDIS_URL` above.)

### See it

Once the pods restart, the gate board header says `cache: redis`. Scan a boarding
pass repeatedly: the counter now climbs by exactly one each time, no matter which
pod answers — and it survives a pod restart if you set `persistence: true`. That's
the difference between section 06's scattered counts and one shared truth.

### Shared Redis: not supported yet

One Redis serving several apps is not a feature of this catalog. `Redis` has no
attach mode, and the obvious construction — a standalone `InfraService` hosting the
instance — can't yet give a flight environment a cluster that has no Redis support.
Skyport's plan uses `InfraService` for RabbitMQ and the OAuth server instead, once
those components exist.

## 09 — Roll out a canary

`boarding-api` is built for this. The gate board polls `/api/whoami` twice a second
and draws a bar of **which version answered**; the header colour comes from that
version. Version 2 also adds a "boarding group" line to lookups, so a canary changes
behaviour as well as colour.

**Start with v1 in flight** (section 07 done, image released). Port-forward to the
staging Service and open the board — one solid bar, `v1.0.0: 100%`.

**Make v2.** In the repo, set `"version": "2.0.0"` in `package.json`, commit and push
to `main`. The pipeline builds, tests, deploys to dev, and opens a release PR for
`staging`; merge it as a signed commit.

**Watch the canary.** The Rollout does not replace v1. It steps: with the chart's
default canary steps (or the ones you set in App Configuration → Canary steps) and
four replicas, the bar goes from all-v1 to roughly a quarter v2, then half, then all.
The chart has no traffic router, so the split is by **pod count**, not by request
weight — percentages round to whole pods, which is why four replicas reads better
than two. A step that pauses without a duration waits for you to promote it.

```bash
kubectl argo rollouts get rollout boarding-api -n app-boarding-api-staging --watch
kubectl argo rollouts promote boarding-api -n app-boarding-api-staging   # if paused
```

Press **Reset tally** between steps to see the current mix rather than a running
average. **Look up `AC123`**: only the v2 pods show the boarding-group line, and the
`answered by` row says which version you got.

**Blue/green instead.** Set the env's `rollout.strategy: blueGreen`. The chart then
renders two Services, `boarding-api` (active) and `boarding-api-preview`. Port-forward
to the preview Service to see v2 at 100% *before* promotion, while the active Service
still shows v1 at 100%; after promotion the active bar flips in one step.

**Roll back** by promoting nothing and aborting the rollout, or by reverting the
release PR; the bar returns to all-v1.

This is the unverified end of the guide: the mechanism is Argo Rollouts driven by
the chart's own values, but no canary has been run with this app.

## Cheat sheet

- **Merge the `.tekton/` PR** — after creating the app, and again after every
  `cicd.yaml` change. No merge, no pipeline.
- **Copy the demo code over the scaffold**, keep the scaffolded `Containerfile`.
- **Nothing is deployed after onboarding.** Ground needs `platform/envs/dev.yaml`
  plus a `deploy` stage; flight needs an `ApplicationEnvironment`, App
  Configuration, and a `release` stage.
- **App Configuration is flight-only**, and only lists envs declared in
  `deploy.upperEnvironments`.
- **`envName`, never `env`**, as the environment's name key in
  `platform/envs/*.yaml`.
- **`rollout: null` must be explicit.**
- **The ground deploy commits to `main` itself** — pull before you push.
- **`ApplicationEnvironment` rejects dev clusters** — `cluster` is live-gated to
  `type: upper`.
- **Redis is a component**, not a Bootstrap object: add it to `components:`; its Service is `<name>-master`.
- **Two architectures** — don't narrow `build.platforms`.
- **Canary splits by pod count**, so use four replicas.
