# Airframe quickstart part 4: baggage-api (MongoDB + broker consumer)

Converted from [`../user/quickstart-baggage-api.md`](../user/quickstart-baggage-api.md).

Placeholders: `<dev-context>`, `<prod-cluster>`, `<prod-context>` are the names chosen when the clusters were built (render with `--dev-cluster` etc. to fill them in).

## The MongoDB XRD is installed on both clusters

```bash
kubectl --context "<dev-context>" get xrd mongodbs.catalog.hangar.io
kubectl --context "<prod-context>" get xrd mongodbs.catalog.hangar.io
```

**Expected:** both XRDs exist and report Established=True

## The app exists as a synced, ready PythonApplication XR

```bash
kubectl --context "<dev-context>" get pythonapplication baggage-api -n app-baggage-api-cicd
```

**Expected:** DevClusterReady/CicdOnboarded/Synced/Ready all True

## The real code replaced the scaffold, with exactly one container file

```bash
gh api repos/jfillman/baggage-api/contents --jq '.[].name'
```

**Expected:** baggage.py, events.py and Containerfile are present, and there is no Dockerfile beside it

## The Containerfile is the alpine one that removes pip and setuptools (image-scan gate)

```bash
gh api repos/jfillman/baggage-api/contents/Containerfile --jq .content | base64 -d
```

**Expected:** FROM python:3.13-alpine and a `pip uninstall -y setuptools pip` line

## cicd.yaml uses deploy.environments, not the removed lowerEnvironments/upperEnvironments

```bash
gh api repos/jfillman/baggage-api/contents/cicd.yaml --jq .content | base64 -d
```

**Expected:** a deploy.environments list with dev (tier: ground); no lowerEnvironments/upperEnvironments/promotionOrder

## Ground: the bag-db MongoDB component passes its verify contract

```bash
kubectl --context "<dev-context>" get mongodbs.catalog.hangar.io bag-db -n app-baggage-api-dev
tools/airframe-verify mongodb app-baggage-api-dev/bag-db --context "<dev-context>"
```

**Expected:** COMPONENT MongoDBReady; airframe-verify passes xr-synced, xr-ready, secret-exists (username, password, connectionString.standard) and reachable (TCP 27017)

## Ground: the bag-mq RabbitMQ attach passes its verify contract

```bash
tools/airframe-verify rabbitmq app-baggage-api-dev/bag-mq --context "<dev-context>"
```

**Expected:** ComponentReady RabbitMQAttachReady; bag-mq-user-credentials and bag-mq-connection carry their keys

## Ground: one baggage-api pod is Running and /healthz answers

```bash
kubectl --context "<dev-context>" get pods -n app-baggage-api-dev -l app.kubernetes.io/name=baggage-api
kubectl --context "<dev-context>" port-forward -n app-baggage-api-dev svc/baggage-api 18083:8080 &
curl -s http://localhost:18083/healthz
```

**Expected:** exactly one Running pod (one consumer replica, on purpose); /healthz returns 200

## baggage-api is connected to the broker, has received events, and holds bag state

```bash
curl -s http://localhost:18083/api/events/status
curl -s http://localhost:18083/api/bags
```

**Expected:** {"mode": "connected", "received": N} with N > 0, and /api/bags lists at least one flight. Read-only: this does not move a gate itself; the flight-api simulator produces the events.

## Flight: the staging ApplicationEnvironment is Synced/Ready with ClusterReady and AppResolved

```bash
kubectl --context "<dev-context>" get applicationenvironment baggage-api-<prod-cluster>-staging -n app-baggage-api-cicd
```

**Expected:** Synced/Ready True; ClusterReady and AppResolved True

## Flight: bag-db on the prod cluster passes its verify contract

```bash
tools/airframe-verify mongodb app-baggage-api-staging/bag-db --context "<prod-context>"
```

**Expected:** MongoDBReady, Secret keys present, TCP 27017 answers

## Flight: the staging Rollout has all its replicas available

```bash
kubectl --context "<prod-context>" get rollout baggage-api -n app-baggage-api-staging
```

**Expected:** availableReplicas == replicas

