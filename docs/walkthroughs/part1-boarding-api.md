# Airframe quickstart part 1: boarding-api

Converted from [`../user/quickstart.md`](../user/quickstart.md).

Placeholders: `<dev-context>`, `<github-owner>`, `<prod-cluster>`, `<prod-context>` are the names chosen when the clusters were built (render with `--dev-cluster` etc. to fill them in).

## The app exists as a synced, ready NodeJSApplication XR

```bash
kubectl --context "<dev-context>" get nodejsapplication boarding-api -n app-boarding-api-cicd
```

**Expected:** SYNCED=True READY=True, and the DevClusterReady/CicdOnboarded custom conditions are both True

## The pipeline onboarding PR was merged (.tekton/ exists in the source repo)

```bash
gh api repos/<github-owner>/boarding-api/contents/.tekton --jq '.[].name'
```

**Expected:** flow-ci.yaml, flow-pr-build.yaml and onboarding-resync.yaml are all present

## The real app code replaced the hello-world scaffold

```bash
gh api repos/<github-owner>/boarding-api/contents --jq '.[].name'
```

**Expected:** app.js, store.js, reservations.js and public/ are present (the scaffold's index.js alone would mean this step never happened)

## Ground: boarding-api is Running on the dev cluster and answers

```bash
kubectl --context "<dev-context>" get pods -n app-boarding-api-dev
kubectl --context "<dev-context>" port-forward -n app-boarding-api-dev svc/boarding-api 18080:8080 &
curl -s http://localhost:18080/healthz
```

**Expected:** at least one boarding-api pod Running; /healthz returns 200

## Flight: boarding-api's staging environment is Synced/Ready with a real deployed Rollout

```bash
kubectl --context "<dev-context>" get applicationenvironment boarding-api-<prod-cluster>-staging -n app-boarding-api-cicd
kubectl --context "<prod-context>" get rollout boarding-api -n app-boarding-api-staging
```

**Expected:** the ApplicationEnvironment XR is Synced/Ready; the Rollout has availableReplicas == replicas (all pods up)

## The Redis component is attached and boarding-api reads through it

```bash
kubectl --context "<dev-context>" get secret cache -n app-boarding-api-dev
curl -s http://localhost:18080/api/whoami
```

**Expected:** the `cache` Secret exists with a redis-password key; /api/whoami reports "cache":"redis"

## The canary mechanism (Argo Rollouts, canary strategy) is in place

```bash
kubectl --context "<prod-context>" get rollout boarding-api -n app-boarding-api-staging -o jsonpath='{.spec.strategy}'
```

**Expected:** the Rollout's strategy is `canary` with real steps (setWeight/pause/setWeight). This only checks the mechanism exists - the doc itself says no canary has actually been walked yet with this app, and this step does not claim otherwise.

