# Airframe quickstart, part 7: checkin-api, through Tower

The same path as [part 6](quickstart-gate-api.md), for a small Python service, done in **Tower**
(Backstage) instead of the terminal: the create form, a staging environment, the App Configuration tab,
and the release. This is the path recorded as **"checkin-api, in Tower"** on
[hangarplatform.dev/run](https://hangarplatform.dev/run/) (chapters: Create, Onboarded, Staging
environment, A crash loop, Configure staging, Release, Live on staging).

> The checkable version - real commands, replayed against the live clusters - is
> [`../walkthroughs/part7-checkin-api.yaml`](../walkthroughs/part7-checkin-api.yaml) (run it with
> `tools/walkthrough-runner`).

Cluster names: `<dev-cluster>` and `<prod-cluster>` are the names chosen when the clusters were built
(for example `hangar-dev` and `hangar-prod`), as explained at the top of [part 1](quickstart.md).

**Needs Tower.** Tower must be up (the `backstage` app's prod environment; see the
[runbook](skyport-runbook.md#prerequisites)) and you must be signed in.

**What has and hasn't been verified.**
- **Verified live, recorded 2026-09-27/28:** the whole path, in the previous lab, including the crash
  loop in section 05 (Glidepath known gap 21: Tower showed the crash-looping pods as "Progressing").
- **Reconstructed from the result:** the recording's driver keeps no log of clicks, so the steps below
  follow the run page's chapters, the files the run left (`checkin-api`, `gitops-checkin-api`, the
  tenants repo) and Tower's docs (`provisioning.md`, `environments.md`). Labels in Tower may differ
  slightly from the ones named here.
- **Not yet verified on freshly built clusters.**

## 01 — The app

`checkin-api` says which check-in counters are open for a flight, and which version answered. Standard
library only. Source: [`examples/skyport/checkin-api/`](../../examples/skyport/checkin-api/).

| Endpoint | Purpose |
|---|---|
| `GET /api/checkin/{flight}` | `AC123`, `WS456`, `PD789`: counters, opening time, bag drop; 404 otherwise |
| `GET /api/whoami` | `{version, pod}` |
| `GET /healthz`, `GET /` | `{"ok": true}` |

## 02 — Create

**Tower → Create → PythonApplication.**

| Field | Value |
|---|---|
| Name | `checkin-api` |
| `devCluster` | `<dev-cluster>` |
| `description` | Skyport check-in counters: which counters open for a flight, and which version answered |
| `pythonVersion` | `3.12` |
| `packageManager` | `pip` |
| `port` | `8080` |
| `visibility` | `private` |

Submit. Tower opens the request PR in the tenants repo; **merge it** (the provisioning strip says "Merge
the request PR to start provisioning" until you do).

## 03 — Onboarded

The Services tab's in-flight strip, and **Provisioning** for the service, show each step: request
applied, dev cluster chosen (`DevClusterReady`), CI/CD onboarded (`CicdOnboarded`), repositories and
starter files, catalog entry, the two **application onboarding PRs** (merge both; merging the source one
starts the first build), the Infisical secret store (`checkin-api-<dev-cluster>`), the first build, and
"Running healthy in dev".

Before the first build can pass, the source repo needs three changes. Make them in a clone (move any old
`./checkin-api` aside) and push them together:

1. **The code:** `cp -R /tmp/airframe/examples/skyport/checkin-api/. .`
2. **The `Containerfile`:** the example's replaces the scaffold's `python:3.12-slim`: it is
   `python:3.12-alpine` with `RUN apk upgrade --no-cache && pip uninstall -y setuptools pip`. The Debian
   base and pip's vendored packages both fail the image-scan gate (see [part 4](quickstart-baggage-api.md#04--pull-in-the-code)).
3. **`cicd.yaml`:** the starter's removed `lowerEnvironments` keys fail `preflight`. Replace it:

```yaml
apiVersion: platform/v1
kind: PipelineConfig
build:
  agent: python-3.12
  unitTest:
    enabled: true
    command: ./test.sh
deploy:
  strategy: rollout
  environments:
    - { name: dev, tier: ground }
governance:
  sast: true
  imageScan: true
  policyCheck: true
  sbom: true
  allowedCommitSigners:
    - you@example.com
pipelines:
  ci:
    trigger: { source: git, event: push, branch: main }
    steps:
      - stage: build
      - stage: deploy
        env: dev
```

(Tower's **Glidepath** tab edits `cicd.yaml` too, as a PR, and converts the old keys to
`deploy.environments` on the first change it stages.) Merge the `.tekton/` resync PR the change opens.
The image version comes from `VERSION`.

## 04 — Staging environment

**Tower → checkin-api → Environments → Add environment**, tier **Flight**, name `staging`, cluster
`<prod-cluster>`. Opening the pull request creates **two** PRs, in this order: the
`ApplicationEnvironment` request on the tenants repo (`checkin-api-<prod-cluster>-staging`, launched
through the same Backstage template as **Create → ApplicationEnvironment**), then the `cicd.yaml` change
adding `{ name: staging, tier: flight, cluster: <prod-cluster> }`. **Merge the request first**, so the
environment exists when `cicd.yaml` names it. Leave `configMapGenerator` off unless the app has config files to
mount (see the quickstart's `configMapGenerator` row).

Then add the release step to `cicd.yaml` (Glidepath tab → Pipelines, or by hand):

```yaml
      - stage: release
        env: staging
```

The expanded row shows provisioning progress for the new environment: the request PR, Crossplane
applying it, the files written, the secret store, the values file, the first deploy.

## 05 — A crash loop (what the recording hit)

The recording's dev pods crash-looped: the readiness probe was on a path that returned 404, and Tower
showed the rollout as "Progressing" with the pods "running" (Glidepath known gap 21, open). If a
rollout sits in Progressing, look at the pods directly:

```bash
kubectl --context <dev-cluster> get pods -n app-checkin-api-dev
kubectl --context <dev-cluster> describe pod -n app-checkin-api-dev -l app.kubernetes.io/name=checkin-api | grep -A3 -i "probe failed"
```

The fix is a probe on a path the app serves: `/healthz` (the example code also answers `/`).

## 06 — Configure staging

**Tower → checkin-api → App Configuration → environment `staging`** (check the environment named at the
top before saving). The values the recorded run ended with:

| Section | Value |
|---|---|
| Deployment | On |
| Scaling | Replicas `4` (readable 25% canary steps by pod count) |
| Service | port name `http`, containerPort `8080` |
| Health checks | Liveness and readiness: HTTP GET `/healthz` on `8080` |
| Canary steps | setWeight 25, pause 45s, setWeight 50, pause 45s, setWeight 100 |

**Save** opens a PR on `gitops-checkin-api` (validated against the chart's schema first). Read the diff,
merge it.

## 07 — Release

Push to `main` (or merge a change). After build and deploy to dev, the `release` step opens a PR on
`gitops-checkin-api` writing `<prod-cluster>/staging/release.yaml`. Tower's **Pull Requests** tab lists it
with its gates. Wait for the gates (`image-promotion` runs last).

**Do not press GitHub's Merge button** (or merge it from any UI that creates a merge commit): `provenance`
fails on the new, unsigned commit. Fast-forward the signed commit from a terminal, as in
[part 6, section 07](quickstart-gate-api.md#07--signed-release).

> **Not yet verified:** whether Tower's own merge action (if your Tower build offers one on the Pull
> Requests tab) fast-forwards or creates a merge commit. Until it is checked, merge release PRs from the
> terminal.

## 08 — Live on staging

**Tower → checkin-api → Environments**: `staging` shows Flight, the prod cluster, Healthy, and the live
image. From a terminal:

```bash
kubectl --context <prod-cluster> get rollout checkin-api -n app-checkin-api-staging
kubectl --context <prod-cluster> -n app-checkin-api-staging port-forward svc/checkin-api 18087:8080 &
curl -s localhost:18087/api/checkin/AC123
```

## Cheat sheet

- **Tower first**: it runs as the `backstage` app's prod environment; sign in before you start.
- **Merge the request PR**, then **both onboarding PRs**, then the `.tekton/` resync PR.
- **Replace the starter `cicd.yaml` and `Containerfile`** before the first build.
- **Add environment (Flight) opens two PRs: merge the ApplicationEnvironment request first.**
- **"Progressing" in Tower can be a crash loop**: check `kubectl get pods`.
- **Release PRs: fast-forward the signed commit.**
