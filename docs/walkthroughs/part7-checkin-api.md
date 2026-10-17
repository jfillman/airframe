# Airframe quickstart part 7: checkin-api (Tower path)

Converted from [`../user/quickstart-checkin-api.md`](../user/quickstart-checkin-api.md).

Placeholders: `<dev-context>`, `<prod-cluster>`, `<prod-context>` are the names chosen when the clusters were built (render with `--dev-cluster` etc. to fill them in).

## checkin-api passes the PythonApplication verify contract

```bash
tools/airframe-verify pythonapplication app-checkin-api-cicd/checkin-api --context "<dev-context>"
```

**Expected:** xr-synced, dev-cluster-ready, cicd-onboarded, source-repo and gitops-repo all pass

## The app's request was made through Tower (it carries the scaffolder's source-info annotation)

```bash
kubectl --context "<dev-context>" get pythonapplication checkin-api -n app-checkin-api-cicd \
  -o jsonpath='{.metadata.annotations.terasky\.backstage\.io/source-info}'
```

**Expected:** a JSON source-info annotation naming the tenants repo (Tower's provisioning view finds the request PR through it)

## The repo has the alpine Containerfile without pip, and a cicd.yaml on deploy.environments

```bash
gh api repos/jfillman/checkin-api/contents/Containerfile --jq .content | base64 -d
gh api repos/jfillman/checkin-api/contents/cicd.yaml --jq .content | base64 -d
```

**Expected:** FROM python:3.12-alpine with pip uninstall -y setuptools pip; deploy.environments with dev (ground) and staging (flight)

## Running healthy in dev: the Rollout is Healthy with every replica available, and no pod is restarting

```bash
kubectl --context "<dev-context>" get rollout checkin-api -n app-checkin-api-dev
kubectl --context "<dev-context>" get pods -n app-checkin-api-dev -l app.kubernetes.io/name=checkin-api
```

**Expected:** phase Healthy, availableReplicas == replicas; no container in CrashLoopBackOff (the crash loop Tower reported as Progressing)

## The staging ApplicationEnvironment passes its verify contract

```bash
tools/airframe-verify applicationenvironment app-checkin-api-cicd/checkin-api-<prod-cluster>-staging --context "<dev-context>"
```

**Expected:** cluster-ready, app-resolved and env-identity-file pass

## App Configuration was saved: staging values set replicas, /healthz probes and canary steps

```bash
gh api repos/jfillman/gitops-checkin-api/contents/<prod-cluster>/staging/values.yaml --jq .content | base64 -d
```

**Expected:** rollout.replicas set, liveness and readiness on /healthz, rollout.steps with setWeight entries

## Live on staging: the Rollout runs the released image with every replica available, and answers

```bash
kubectl --context "<prod-context>" get rollout checkin-api -n app-checkin-api-staging
curl -s http://localhost:18087/api/checkin/AC123
```

**Expected:** availableReplicas == replicas; the image tag equals release.yaml's; /api/checkin/AC123 returns counters 12-18

