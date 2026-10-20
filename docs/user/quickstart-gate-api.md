# Airframe quickstart, part 6: gate-api, from the terminal

The smallest Skyport service, taken from one XR to a canary on the prod cluster without Tower: every step
is a file in git or a `kubectl`/`gh` command. This is the path recorded as **"gate-api, in the terminal"**
on [hangarplatform.dev/run](https://hangarplatform.dev/run/) (chapters: Ask, Compose, Environments, Build,
Dev, Staging, A real bug, Signed release, More bugs, Canary, The canary in Tower).

> The checkable version - real commands, replayed against the live clusters - is
> [`../walkthroughs/part6-gate-api.yaml`](../walkthroughs/part6-gate-api.yaml) (run it with
> `tools/walkthrough-runner`).

Cluster names: `<dev-cluster>` and `<prod-cluster>` are the names chosen when the clusters were built
(for example `hangar-dev` and `hangar-prod`), as explained at the top of [part 1](quickstart.md).
`<github-owner>` is the GitHub owner of the app repos (set once, see the runbook's [Configure](skyport-runbook.md#configure) step).

**What has and hasn't been verified.**
- **Verified live, recorded 2026-09-27/28:** the whole path, in the previous lab. The recording found
  four platform bugs, all fixed since (Glidepath known gaps 12, 18, 19, 22: release gates that ignored
  `release.yaml`, `image-promotion` waiting forever, a relay address the prod cluster couldn't route
  to, a release hook ServiceAccount that never existed). Three of the four were in machinery that has
  since been removed (the hook Jobs and `relayHostAliasIP`, glidepath ADR-0021 phase 3).
- **This guide is reconstructed from the result, not from the raw log.** The recording's command log
  is not published (it carries the lab's names), so the steps below are derived from the files the run
  left in `gate-api`, `gitops-gate-api` and the tenants repo, and from the run page's chapters.
  Commands are the ones those files imply; no output here is quoted from the recording.
- **Not yet verified on freshly built clusters.**

## 01 — The app

`gate-api` answers "what's at this gate?" and says which version and pod answered, so a canary is
visible from outside. Source: [`examples/skyport/gate-api/`](../../examples/skyport/gate-api/) (no
dependencies; Node's built-in test runner).

| Endpoint | Purpose |
|---|---|
| `GET /` | A small HTML list of the gates, with the version and pod |
| `GET /api/gates/{gate}` | `A12`, `A14`, `B3`, `C7`; 404 for any other |
| `GET /api/whoami` | `{version, pod}` |
| `GET /healthz` | Liveness / readiness |

## 02 — Ask: write the XR request

Instead of the Tower form, write the request file yourself, in a branch of the dev cluster's tenants
repo (the repo named by the dev cluster's `tenantsRepo` in `clusters.yaml`):

```yaml
# tenants/gate-api/xr-requests/gate-api.yaml
apiVersion: catalog.hangar.io/v1alpha1
kind: NodeJSApplication
metadata:
  name: gate-api
  namespace: app-gate-api-cicd
spec:
  devCluster: <dev-cluster>
  description: 'Skyport gate display: which flight is at which gate, and which version answered'
  nodeVersion: '20'
  packageManager: npm
  port: 8080
  visibility: private
```

Check it against the XRD before you push:

```bash
tools/airframe-validate --xr tenants/gate-api/xr-requests/gate-api.yaml
```

Open a PR and merge it. The `xr-requests` ApplicationSet applies it within about three minutes. A
request made through Tower's form also carries Backstage annotations (owner, system, source-info);
Tower's provisioning view finds the request PR through `source-info` (Tower `docs/provisioning.md`), so
without it that one link is missing. See *Not yet verified* below.

## 03 — Compose: watch it come up

```bash
kubectl --context <dev-cluster> get nodejsapplication gate-api -n app-gate-api-cicd -w
tools/airframe-verify nodejsapplication app-gate-api-cicd/gate-api --context <dev-cluster>
```

`airframe-verify` checks `DevClusterReady`, `CicdOnboarded`, and that the `gate-api` and
`gitops-gate-api` repos exist. Then merge the two onboarding PRs Glidepath opens (one on each repo):

```bash
gh pr list -R <github-owner>/gate-api
gh pr list -R <github-owner>/gitops-gate-api
```

If a previous run left `gate-api` or `gitops-gate-api` behind, the composition adopts nothing cleanly:
decommission first ([runbook](skyport-runbook.md#before-you-start-leftovers-from-a-previous-run)).

## 04 — Environments: `cicd.yaml` and the code

Clone the repo (move any old `./gate-api` aside first), copy the code in, and replace the starter
`cicd.yaml`, which still uses the removed `lowerEnvironments` keys (see [part 1](quickstart.md#02--create-the-app)):

```bash
git clone https://github.com/<github-owner>/gate-api.git && cd gate-api
cp -R /tmp/airframe/examples/skyport/gate-api/. .
npm test
```

```yaml
# cicd.yaml
apiVersion: platform/v1
kind: PipelineConfig

build:
  agent: nodejs-20
  containerfile: ./Containerfile
  unitTest:
    enabled: true
    command: ./test.sh

deploy:
  strategy: rollout
  environments:
    - { name: dev,     tier: ground }
    - { name: staging, tier: flight, cluster: <prod-cluster> }

pipelines:
  ci:
    trigger: { source: git, event: push, branch: main }
    steps:
      - stage: build
      - stage: deploy
        env: dev
      - stage: release
        env: staging
```

The example's `Containerfile` (`node:20-alpine`, `apk upgrade`, removes npm after install) replaces the
scaffold's. Keep one container file. `glidepath/envs/dev.yaml` stays as onboarding wrote it
(`envName: dev`).

Commit **with gitsign** (Glidepath [commit-signing.md](https://github.com/jfillman/glidepath/blob/main/docs/admin/commit-signing.md):
`git config gpg.x509.program gitsign`, `gpg.format x509`, `commit.gpgsign true`), push, and merge the
`.tekton/` resync PR the `cicd.yaml` change opens.

Then request the flight environment, in the same tenants repo:

```yaml
# tenants/gate-api/xr-requests/gate-api-<prod-cluster>-staging.yaml
apiVersion: catalog.hangar.io/v1alpha1
kind: ApplicationEnvironment
metadata:
  name: gate-api-<prod-cluster>-staging
  namespace: app-gate-api-cicd
spec:
  appName: gate-api
  cluster: <prod-cluster>
  env: staging
  configMapGenerator: false
```

```bash
tools/airframe-validate --xr tenants/gate-api/xr-requests/gate-api-<prod-cluster>-staging.yaml
```

Merge it, then check:

```bash
tools/airframe-verify applicationenvironment app-gate-api-cicd/gate-api-<prod-cluster>-staging --context <dev-cluster>
```

## 05 — Build and dev

The push after the `.tekton/` merge builds the image (`ghcr.io/<github-owner>/gate-api:<package.json version>-<sha>`)
and deploys it to dev, committing `glidepath/envs/dev.release.yaml`:

```bash
kubectl --context <dev-cluster> get pipelineruns -n app-gate-api-cicd
kubectl --context <dev-cluster> get rollout gate-api -n app-gate-api-dev
kubectl --context <dev-cluster> -n app-gate-api-dev port-forward svc/gate-api 18086:8080 &
curl -s localhost:18086/api/whoami
```

## 06 — Staging values

Configure staging in `gitops-gate-api/<prod-cluster>/staging/values.yaml`, through a PR. These are the
values the recorded run ended with:

```yaml
# keep appName, appType, cluster, envName as Crossplane wrote them
rollout:
  replicas: 1
  ports:
    - { name: http, containerPort: 8080 }
  resources:
    requests: { cpu: 50m, memory: 64Mi }
    limits: { memory: 128Mi }
  steps:                       # the canary: 25%, wait 45 s, 50%, wait 45 s, 100%
    - setWeight: 25
    - pause: { duration: 45s }
    - setWeight: 50
    - pause: { duration: 45s }
    - setWeight: 100
  livenessProbe:
    httpGet: { path: /healthz, port: 8080 }
    initialDelaySeconds: 5
  readinessProbe:
    httpGet: { path: /healthz, port: 8080 }
    initialDelaySeconds: 5
```

```bash
tools/airframe-validate <prod-cluster>/staging/values.yaml   # from the gitops-gate-api checkout, with airframe's tools on PATH
```

With **one replica** the canary has nothing to split by pod count (the chart has no traffic router), so
25% and 50% both mean "the new pod is up beside the old one". Use four replicas, as in part 1, to see the
percentages.

## 07 — Signed release

The `release` step opens a PR on `gitops-gate-api` that writes `<prod-cluster>/staging/release.yaml`
and a release record under `releases/`. The gates run on it (`sast`, `image-scan`, `sbom`, `values`,
`provenance`, then `image-promotion` last, which waits for the others).

**Merge it by fast-forward, never with GitHub's button**: every button strategy makes a new, unsigned
commit and `provenance` fails, and `image-promotion` with it. Locally:

```bash
git -C gitops-gate-api fetch origin
git -C gitops-gate-api checkout main && git -C gitops-gate-api merge --ff-only origin/<release-branch>
git -C gitops-gate-api push origin main
```

The prod cluster's own Argo CD syncs it.

## 08 — Canary

Make v2: bump `"version"` in `package.json`, commit (signed), push. The pipeline builds, deploys to dev,
and opens a new release PR; fast-forward it. Then watch the steps:

```bash
kubectl --context <prod-cluster> argo rollouts get rollout gate-api -n app-gate-api-staging --watch
```

The run page's last chapter shows the same canary in Tower's Deployments tab.

## Not yet verified

- **How the recorded run made its requests.** The run's request files in the tenants repo carry
  Backstage annotations (owner, system, source-info), so they were not hand-written like section 02's;
  the chapters are named *Ask* and *Compose*, which suggests Autopilot's AppSpec planner
  (`contract/appspec.schema.json`), but the published sources don't say. The hand-written requests here
  validate against the XRDs (`airframe-validate --xr`); whether every Tower view works without the
  annotations is not verified.
- The local fast-forward commands in section 07 are the method Glidepath's commit-signing doc
  describes; the exact branch name of a release PR is whatever the release step created (`release-*`).

## Cheat sheet

- **Two XR requests make an app with a flight env:** the app XR and one `ApplicationEnvironment`.
  `airframe-validate --xr` checks them before you push.
- **`airframe-verify <kind> <ns>/<name>`** is the read-only check for each XR.
- **Replace the starter `cicd.yaml`** with `deploy.environments`.
- **Sign every commit (gitsign), fast-forward every release PR.**
- **Canary percentages need replicas**: one replica can't show 25%.
