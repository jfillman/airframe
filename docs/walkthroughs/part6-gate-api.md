# Airframe quickstart part 6: gate-api (terminal path)

Converted from [`../user/quickstart-gate-api.md`](../user/quickstart-gate-api.md).

Placeholders: `<dev-context>`, `<prod-cluster>`, `<prod-context>` are the names chosen when the clusters were built (render with `--dev-cluster` etc. to fill them in).

## gate-api passes the NodeJSApplication verify contract (dev cluster ready, CI/CD onboarded, both repos exist)

```bash
tools/airframe-verify nodejsapplication app-gate-api-cicd/gate-api --context "<dev-context>"
```

**Expected:** xr-synced, dev-cluster-ready, cicd-onboarded, source-repo and gitops-repo all pass

## The onboarding PR was merged (.tekton/ exists in the source repo)

```bash
gh api repos/jfillman/gate-api/contents/.tekton --jq '.[].name'
```

**Expected:** flow-ci.yaml and onboarding-resync.yaml are present

## cicd.yaml declares dev (ground) and staging (flight, on the prod cluster), with a signer

```bash
gh api repos/jfillman/gate-api/contents/cicd.yaml --jq .content | base64 -d
```

**Expected:** deploy.environments: dev/ground and staging/flight with cluster = the prod cluster's name; allowedCommitSigners not empty; no removed keys

## The staging ApplicationEnvironment passes its verify contract

```bash
tools/airframe-verify applicationenvironment app-gate-api-cicd/gate-api-<prod-cluster>-staging --context "<dev-context>"
```

**Expected:** cluster-ready, app-resolved and env-identity-file pass

## Dev: gate-api is Running and answers /api/whoami

```bash
kubectl --context "<dev-context>" get rollout gate-api -n app-gate-api-dev
curl -s http://localhost:18086/api/whoami
```

**Expected:** the Rollout has all replicas available; whoami returns a version and a pod name

## Staging was released: release.yaml in the gitops repo names a gate-api image

```bash
gh api repos/jfillman/gitops-gate-api/contents/<prod-cluster>/staging/release.yaml --jq .content | base64 -d
```

**Expected:** release.image.repository is ghcr.io/<owner>/gate-api with a tag

## Staging: the Rollout is a canary with steps, fully available, on the released image

```bash
kubectl --context "<prod-context>" get rollout gate-api -n app-gate-api-staging -o jsonpath='{.spec.strategy}'
```

**Expected:** strategy canary with setWeight steps; availableReplicas == replicas; the running image tag equals release.yaml's

