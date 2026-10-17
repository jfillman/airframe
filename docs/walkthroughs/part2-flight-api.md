# Airframe quickstart part 2: flight-api

Converted from [`../user/quickstart-flight-api.md`](../user/quickstart-flight-api.md).

Placeholders: `<dev-context>`, `<prod-context>` are the names chosen when the clusters were built (render with `--dev-cluster` etc. to fill them in).

## The app exists as a synced, ready SpringBootApplication XR

```bash
kubectl --context "<dev-context>" get springbootapplication flight-api -n app-flight-api-cicd
```

**Expected:** DevClusterReady/CicdOnboarded/Synced/Ready all True

## The PostgreSQL component is attached and flight-api reads through it

```bash
kubectl --context "<dev-context>" get secret flight-db-app -n app-flight-api-dev
curl -s http://localhost:18090/api/whoami
```

**Expected:** the flight-db-app Secret exists (basic-auth type); /api/whoami reports "database":"postgresql"

## Ground: flight-api is Running on the dev cluster and its liveness probe passes

```bash
kubectl --context "<dev-context>" get pods -n app-flight-api-dev
curl -s -o /dev/null -w '%{http_code}' http://localhost:18090/actuator/health/liveness
```

**Expected:** at least one flight-api pod Running; the liveness endpoint returns 200

## Flight: flight-api's staging environment has real Running pods on the prod cluster

```bash
kubectl --context "<prod-context>" get pods -n app-flight-api-staging
```

**Expected:** at least one flight-api pod Running on the prod cluster

