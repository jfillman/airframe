# Airframe quickstart, part 4: a consumer with its own MongoDB

[Part 3](quickstart-broker.md) put a shared broker between `flight-api` (publisher) and `boarding-api`
(consumer). This part adds a third service on the same events: **`baggage-api`**, a Python service that
re-routes a flight's bags to another carousel when its gate changes, and keeps that state in a
**MongoDB** component of its own.

> The checkable version - real commands, replayed against the live clusters - is
> [`../walkthroughs/part4-baggage-api.yaml`](../walkthroughs/part4-baggage-api.yaml) (run it with
> `tools/walkthrough-runner`).

Cluster names: `<dev-cluster>` and `<prod-cluster>` are the names chosen when the clusters were built
(for example `hangar-dev` and `hangar-prod`), as explained at the top of [part 1](quickstart.md).
Infisical projects are `<app>-<cluster>`.

Do parts 1 to 3 first. This guide assumes `flight-api` publishes to `skyport-broker` on the dev cluster,
and doesn't repeat how to create an app or merge the pipeline PR.

**What has and hasn't been verified.**
- **Verified:** the service. `./test.sh` runs 12 unit tests against `mongomock`, with no broker or
  database.
- **Verified live, in the previous lab** (2026-09-26 to 2026-10-07): `baggage-api` on dev consuming
  `flights.events` (a gate change in `flight-api` moved AC123's bags from carousel 2 to 3 within
  seconds), then moved onto the MongoDB component on dev and on prod staging. The env files in this
  guide are the ones that ran there, with the cluster name made a placeholder.
- **Not yet verified on freshly built clusters.** Nothing here has been replayed on the new clusters.
  The walkthrough's checks are the definition of done.

## 01 — What you're building

```
   flight-api ──publish──▶  skyport-broker (RabbitMQ)  ──deliver──▶ baggage-api ──▶ bag-db (MongoDB)
   (Spring)   flight.#.*    exchange flights.events        queue     (Python)        replica set,
                                                       baggage.flight-events          its own namespace
```

- **The broker attach** is the same component as part 3's, in `attach` mode, as a consumer: queues
  named `baggage.*`, bound to `flights.events`, nothing else.
- **The database is dedicated**, like part 2's PostgreSQL: one `MongoDB` replica set per app
  environment, in `app-baggage-api-<env>`, through the MongoDB Controllers for Kubernetes operator's
  `MongoDBCommunity` resource. Deleting the environment deletes the data.
- The concourse letter of a gate picks the carousel (A=1, B=2, C=3, ...). A `GATE_CHANGED` event moves
  the flight's bags and records the move.

## 02 — Before you start

- **The MongoDB operator and the `MongoDB` XRD on both clusters.** Both cluster repos carry
  `10-crds-operators/mongodb-kubernetes` and list `xrds/mongodb.yaml` +
  `compositions/mongodb/composition.yaml` in their `idp-service-catalog` Application. Check:

  ```bash
  kubectl --context <dev-cluster> get xrd mongodbs.catalog.hangar.io
  kubectl --context <prod-cluster> get xrd mongodbs.catalog.hangar.io
  ```
- **`app-baggage-api-dev` in the broker's `allowedNamespaces`** (part 3, section 03). Without it the
  attach user is refused and the AMQP port is closed to the app.
- **The kernel on the prod cluster's node.** MongoDB 8.0's bundled tcmalloc crashes at startup on Linux
  kernels 6.19 through 7.0.13 (SERVER-121912). The previous prod cluster needed
  `mongoVersion: 7.0.14`; check `uname -r` on the new node (section 07).
- **Leftovers.** If a previous `baggage-api` existed, finish [decommissioning](decommission-app.md)
  first: Infisical projects `baggage-api-<cluster>`, the `secretstore-provisioner` key, the repos
  `baggage-api` and `gitops-baggage-api`, and any local checkout. See the
  [runbook](skyport-runbook.md#before-you-start-leftovers-from-a-previous-run).

## 03 — Create the app

**Tower → Create → PythonApplication.**

| Field | Value |
|---|---|
| Name | `baggage-api` |
| `devCluster` | `<dev-cluster>` |
| `description` | Skyport baggage handling: consumes flights.events from the broker and re-routes bags when a gate changes |
| `pythonVersion` | `3.13` |
| `packageManager` | `pip` |
| `port` | `8080` |
| `visibility` | `private` |

Merge the request PR, then the two onboarding PRs ([part 1, section 03](quickstart.md#03--merge-the-pipeline-onboarding-pr)).

```bash
kubectl --context <dev-cluster> get pythonapplication baggage-api -n app-baggage-api-cicd
```

`SYNCED True`, `READY True`, and `DevClusterReady`/`CicdOnboarded` True in `kubectl describe`.

## 04 — Pull in the code

```bash
git clone https://github.com/jfillman/airframe.git /tmp/airframe   # skip if you still have it
git clone https://github.com/<github-owner>/baggage-api.git && cd baggage-api   # fails if ./baggage-api exists

cp -R /tmp/airframe/examples/skyport/baggage-api/. .
./test.sh                # 12 passing (installs requirements + mongomock first)
```

This overwrites `main.py`, `requirements.txt`, `VERSION` and the scaffold's **`Containerfile`**, and adds
`baggage.py`, `events.py`, the tests and `test.sh`.

**Why the `Containerfile` is replaced.** The scaffold's is `python:<version>-slim` (Debian), which fails
the image-scan gate on unfixed HIGH util-linux/acl CVEs. The example uses `python:3.13-alpine` and then
runs **`pip uninstall -y setuptools pip`** after installing the dependencies: the vendored copies of
`msgpack` and `setuptools` inside pip fail Trivy too (GHSA-6v7p-g79w-8964, CVE-2025-47273), upgrading
doesn't remove them, and nothing needs them at runtime. pymongo's optional C extension doesn't build on
alpine (no compiler); pip falls back to the pure-Python BSON, which is fine at this traffic.

**One container file only.** Make sure the repo has exactly one, named `Containerfile`. A repo that also
has a `Dockerfile` (an older scaffold, or a copy) is ambiguous to read, and a cluster rebuild re-composes
the scaffold's default filename next to an existing file of another name (Airframe
[known gap 6](../admin/known-gaps.md)).

The image version comes from `VERSION` (`0.1.0`), which the Python scaffold creates and Glidepath's build
reads (Glidepath known gap 1, fixed).

| Endpoint | Purpose |
|---|---|
| `GET /api/bags` | Every flight seen: gate, carousel, bag count, re-route count |
| `GET /api/bags/{flight}` | One flight |
| `GET /api/reroutes` | Recent re-routes, newest first |
| `GET /api/events/status` | Broker consumer: `off`, `connecting` or `connected`, and messages `received` |
| `GET /api/whoami`, `/healthz` | Version and pod; liveness |

`main.py` **exits at start if `MONGODB_URI` is unset**: there is no in-memory fallback, so a pod that
crash-loops with `MONGODB_URI is not set` means the component or its env wiring is missing.

## 05 — Ground: the database, the broker attach, and the pipeline

**`glidepath/envs/dev.yaml`** (the file onboarding scaffolded):

```yaml
envName: dev
rollout:
  replicas: 1   # every replica would compete for the same queue; see below
components:
  - type: rabbitmq
    name: bag-mq              # credentials land in Secret bag-mq-user-credentials
    spec:
      mode: attach
      brokerRef: { name: skyport-broker, namespace: app-skyport-broker-dev }
      vhost: flights
      queuePrefix: baggage    # may create, bind and consume queues named baggage.*
      consume: [flights.events]
  - type: mongodb
    name: bag-db              # credentials + connection string land in Secret bag-db-app
    spec: {}                  # defaults: members 1, storageSize 5Gi, mongoVersion 8.0.32
env:
  - { name: RABBITMQ_HOST,     fromComponent: { name: bag-mq, output: host } }
  - { name: RABBITMQ_VHOST,    fromComponent: { name: bag-mq, output: vhost } }
  - { name: RABBITMQ_USER,     fromComponent: { name: bag-mq, output: username } }
  - { name: RABBITMQ_PASSWORD, fromComponent: { name: bag-mq, output: password } }
  - { name: MONGODB_URI,       fromComponent: { name: bag-db, output: uri } }
```

`fromComponent` is the way to reference a component's output (AGENTS.md): the chart resolves
`bag-db`/`uri` to the Secret `bag-db-app`, key `connectionString.standard` (a flat key with a dot in it,
not a nested field), and `airframe-validate` rejects a component or output that doesn't exist. The
previous lab's file wrote the four RabbitMQ entries as hand-written `valueFrom` references to
`bag-mq-connection` / `bag-mq-user-credentials`; they resolve to the same keys, and `airframe-validate`
warns on that form (AF-COMP-003), so this guide uses `fromComponent` throughout.

**One replica, on purpose.** State is in MongoDB now, but every replica declares the same queue and
they compete for its messages, so each would apply only half of the events. One replica is correct until
the consumer is changed, not the storage.

Validate before you push:

```bash
/tmp/airframe/tools/airframe-validate glidepath/envs/dev.yaml
```

**`cicd.yaml`** - replace the starter (it uses the removed `lowerEnvironments` keys):

```yaml
apiVersion: platform/v1
kind: PipelineConfig

build:
  agent: python-3.13
  containerfile: Containerfile
  unitTest:
    enabled: true
    command: ./test.sh

deploy:
  strategy: rollout
  environments:
    - { name: dev, tier: ground }

governance:
  sast: true
  imageScan: true          # the Trivy gate the Containerfile is written for
  policyCheck: true
  sbom: true
  allowedCommitSigners:
    - you@example.com       # the address gitsign signs your commits with

pipelines:
  ci:
    trigger: { source: git, event: push, branch: main }
    steps:
      - stage: build
      - stage: deploy
        env: dev
```

Commit both, push, merge the `.tekton/` resync PR the `cicd.yaml` change opens, then push again (or let
the merge's push run). The deploy stage commits the image to `glidepath/envs/dev.release.yaml`; pull
before your next push.

Check the components:

```bash
kubectl --context <dev-cluster> get mongodbs.catalog.hangar.io,rabbitmqs.catalog.hangar.io -n app-baggage-api-dev
# COMPONENT column: MongoDBReady and RabbitMQAttachReady
tools/airframe-verify mongodb app-baggage-api-dev/bag-db --context <dev-cluster>
tools/airframe-verify rabbitmq app-baggage-api-dev/bag-mq --context <dev-cluster>
```

(Use the full resource names: plain `mongodb` and `rabbitmq` are ambiguous with the operators' own
kinds.) The first start of a replica set takes a few minutes; `MongoDBPending` means the operator's
agents are still converging.

## 06 — See it work

```bash
kubectl --context <dev-cluster> port-forward -n app-flight-api-dev svc/flight-api 8081:8080 &
kubectl --context <dev-cluster> port-forward -n app-baggage-api-dev svc/baggage-api 8083:8080 &

curl -s localhost:8083/api/events/status      # {"mode": "connected", "received": N}
curl -s localhost:8083/api/bags/AC123         # gate, carousel, bags

curl -s -X PUT -H 'Content-Type: application/json' -d '{"gate":"C4"}' localhost:8081/api/flights/AC123/gate

curl -s localhost:8083/api/bags/AC123         # carousel 3 now, reroutes went up
curl -s localhost:8083/api/reroutes           # the move, newest first
```

> **After [part 5](quickstart-skyport-auth.md)** these API calls need a bearer token (`401` without one).
> Mint one with `. docs/walkthroughs/lib/dex.sh; tok="$(dex_token <dev-cluster> app-boarding-api-dev board-oauth)"`
> and add `-H "Authorization: Bearer $tok"`. Probes and `/api/whoami` stay open.

A flight appears in `/api/bags` only after its first event (the first sighting assigns a carousel, it
doesn't re-route). The simulator in `flight-api` changes a flight about every 30 seconds, so the list
fills on its own. Restart the pod: the bags and re-routes are still there, because they live in
`bag-db`.

If `mode` stays `connecting`, the bind is being refused: `flight-api` hasn't declared `flights.events`
yet, or the namespace isn't in the broker's `allowedNamespaces`. The consumer retries every five seconds.

## 07 — Flight: staging on the prod cluster

As in [part 1, section 07](quickstart.md#07--flight-a-governed-environment-on-an-upper-cluster). Only what
differs is here.

**Step 1 - the broker first.** `skyport-broker` needs its staging environment on the prod cluster with
`app-baggage-api-staging` in its `allowedNamespaces` ([part 3, section 08](quickstart-broker.md#08--flight-the-same-on-the-prod-cluster)).

**Step 2 - `cicd.yaml`.** Add the flight env and a release step:

```yaml
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

Merge the `.tekton/` PR it opens.

**Step 3 - Tower → Create → ApplicationEnvironment:** `Name` `baggage-api-<prod-cluster>-staging`,
`Namespace` `app-baggage-api-cicd`, `appName` `baggage-api`, `cluster` `<prod-cluster>`, `env` `staging`,
**`configMapGenerator` off**. (The previous lab's env had it on, and its first sync failed with
`app path does not exist` until `<cluster>/staging/configmap/kustomization.yaml` was added by hand; since
2026-10-19 the composition seeds that file.) Merge the PR.

**Step 4 - the staging values**, in `gitops-baggage-api/<prod-cluster>/staging/values.yaml`, through a PR.
Keep the identity keys Crossplane wrote (`appName`, `appType`, `cluster`, `envName`) and add:

```yaml
rollout:
  replicas: 1
components:
  - type: rabbitmq
    name: bag-mq
    spec:
      mode: attach
      brokerRef: { name: skyport-broker, namespace: app-skyport-broker-staging }
      vhost: flights
      queuePrefix: baggage
      consume: [flights.events]
  - type: mongodb
    name: bag-db
    spec:
      mongoVersion: 7.0.14   # only if the node's kernel is 6.19 through 7.0.13 (SERVER-121912)
env:
  # the same five entries as dev
```

Check the kernel first and drop `mongoVersion` if it is outside that range:

```bash
kubectl --context <prod-cluster> get nodes -o jsonpath='{.items[*].status.nodeInfo.kernelVersion}'
```

**Step 5 - release.** Push to `main`; the `release` step opens a PR on `gitops-baggage-api` that writes
`<prod-cluster>/staging/release.yaml`. Merge it by fast-forwarding the signed commit, never with
GitHub's button ([part 1, section 07](quickstart.md#step-4--release-an-image)): the `provenance` gate
fails on an unsigned merge commit, and `image-promotion` then fails with it (exactly what happened to two
of `baggage-api`'s four earlier release records).

```bash
kubectl --context <prod-cluster> get mongodbs.catalog.hangar.io -n app-baggage-api-staging
kubectl --context <prod-cluster> get rollout baggage-api -n app-baggage-api-staging
```

## Cheat sheet

- **MongoDB is a component** (`type: mongodb`), dedicated per environment. Secret `<name>-app`:
  `username`, `password`, `connectionString.standard`, `connectionString.standardSrv`. Service
  `<name>-svc` on 27017.
- **Reference it with `fromComponent: {name: bag-db, output: uri}`**, never a hand-written Secret name.
- **`kubectl get mongodbs.catalog.hangar.io`**, not `mongodb`.
- **The `COMPONENT` column** shows `MongoDBReady` / `MongoDBPending` / `MongoDBFailed` / `MongoDBProvisioning`.
- **One consumer replica** until the consumer changes: replicas compete for one queue.
- **Python images: alpine, then `pip uninstall -y setuptools pip`**, or the image-scan gate fails.
- **`mongoVersion: 7.0.x` on kernels 6.19 to 7.0.13.**
- **`configMapGenerator` off** on the ApplicationEnvironment unless you add the folder yourself.
- **Deleting the environment deletes the database.**
