# Airframe quickstart, part 2: a service with a database

[Part 1](quickstart.md) took a NodeJS service from nothing to a canary. This part does the
same for a **Spring Boot** service that owns a **PostgreSQL** database, then connects part 1's
`boarding-api` to it so the gate board shows real data.

We build `flight-api`, the system of record for [Skyport](skyport-demo.md): 24 flights and
their gates in Postgres, a REST API, and a simulator that keeps moving flights around so there
is something to watch.

> An illustrated version of this guide is published at
> [Airframe Database Quickstart](https://claude.ai/artifact/YJDciwsLesxr7p56vbw6Lf).

Do part 1 first. This guide assumes `boarding-api` is running in its dev environment and
doesn't repeat the mechanics of creating an app, merging the pipeline PR, or the ground/flight
split; it links back to the section that explains each.

**What has and hasn't been verified.**
- **Verified:** the service. Its 17 unit tests pass in the platform's own Java build image; its
  migrations and queries pass against a real PostgreSQL (4 integration tests); the container
  image was built with the exact `Containerfile` the platform scaffolds and run against that
  database; and `boarding-api` was run against it end to end.
- **Verified:** the database component, on **both clusters**. A `PostgreSQL` component was
  created, went Ready, kept its data across a restart, scaled to two instances on the dev
  cluster, and tore down cleanly. On `kind-prod` (which enforces NetworkPolicy) it went Ready with
  the app's baseline policy in place, and a control run **without** the component's operator
  policy never became healthy, so that policy is necessary, not decoration. A pod in another
  namespace could not reach the database.
- **Verified by rendering only:** the chart passing `flight-db-app`'s Secret into the container
  (`env` entries with `valueFrom`) and the `allowIngressFrom` rule for `boarding-api`.
- **Verified:** the build. `build.sh` compiles in the exact Java agent image in about 30 seconds, the
  thin image built from it starts, migrates and answers against a real PostgreSQL, and its emulated
  amd64 packaging leg was timed on the cluster's builder at about 30 seconds. (The scaffold's
  in-Containerfile Maven build did finish, but took about 17 minutes under emulation (the amd64 leg alone
  took 11 minutes), which is why this
  guide replaces it.)
- **Verified live by walking it (2026-09-25):** create → pipeline → ground deploy on the dev
  cluster with the database component; `boarding-api` on dev serves from `flight-api`
  (`source: flight-api`, live status from the simulator) and the database accumulated hundreds of
  events; `flight-api` runs on `kind-prod` staging with a two-instance database. Walking it found and
  fixed the slow emulated Java build (section 04) and a liveness probe pointed at the readiness
  endpoint (section 05).
- **Not yet confirmed:** `boarding-api` on `kind-prod` staging still reports its built-in lookup
  (`FLIGHT_API_URL` not set there), so the staging call path in section 07 has not been exercised.

**Needs airframe v0.3.88 or later** on the dev cluster's ApplicationSets (`env:` `valueFrom`).

## 01 — What you're building

```
                       ┌──────────────┐  GET /api/flights/AC123   ┌──────────────────────────┐
  gate board  ───────▶ │ boarding-api │ ────────────────────────▶ │ flight-api (Spring Boot) │
  (browser)            │ (part 1)     │      cached 3 minutes     │ app-flight-api-dev       │
                       │ Redis cache  │                           │            │             │
                       └──────────────┘                           │            ▼             │
                                                                  │  flight-db  (Postgres)   │
                                                                  │  CloudNativePG, 1 pod    │
                                                                  └──────────────────────────┘
```

`flight-api` and its database live in **one namespace**, `app-flight-api-dev`. The database is a
*dedicated* PostgreSQL cluster for this app environment — not a shared one — so deleting the
environment deletes its data, and no other app can reach it.

## 02 — Create the app

**Tower → Create → SpringBootApplication.**

| Field | Value |
|---|---|
| Name | `flight-api` |
| `devCluster` | `kind-dev` |
| `description` | Skyport system of record: flights and gates in Postgres |
| `javaVersion` | `21` |
| `buildTool` | `maven` |
| `groupId` | `io.skyport.flight` |
| `port` | `8080` |
| `visibility` | `private` |

**Use `kind-dev` exactly for `devCluster`**, even though the dev cluster is `kiac-dev` — see
[part 1, section 02](quickstart.md#02--create-the-app) for why.

**Set `groupId` to `io.skyport.flight`.** The scaffold uses it as the app's one Java package, and
the code you'll copy in sits in `io/skyport/flight/`. A different value scaffolds a different
package and the two won't match.

Merge the PR Tower opens, then check the XR:

```
$ kubectl get springbootapplication flight-api -n app-flight-api-cicd
NAME         SYNCED   READY   COMPOSITION                              AGE
flight-api   True     True    springbootapplications.catalog.idp.io    3m
```

The source repo starts with a hello-world `Application.java`, a `pom.xml` (web and actuator
only), an `application.properties`, and a `Containerfile`.

If a previous `flight-api` was decommissioned, finish [decommissioning](decommission-app.md)
first (including its Infisical projects), and move any old local checkout out of the way.

## 03 — Merge the pipeline PR

Same as [part 1, section 03](quickstart.md#03--pipeline-onboarding): Glidepath opens a PR
adding `.tekton/`. **Merge it**, or pushes do nothing.

## 04 — Pull in the code

```bash
git clone https://github.com/jfillman/airframe.git /tmp/airframe   # skip if you still have it
git clone https://github.com/jfillman/flight-api.git && cd flight-api

cp -R /tmp/airframe/examples/skyport/flight-api/. .
git add -A && git commit -m "flight-api: flights and gates in Postgres"
```

This overwrites the scaffold's `pom.xml`, `Application.java`, `application.properties` **and
`Containerfile`**, and adds the other classes, the SQL migrations, the tests, `test.sh`, `build.sh`
and the Maven Wrapper (`mvnw`, `.mvn/`). Keep `cicd.yaml` for now; you change it in section 05.

**Why the `Containerfile` is replaced (unlike part 1).** The scaffold's Java `Containerfile`
compiles the app inside the image build. That build runs for two architectures, and the amd64 leg
runs under QEMU emulation on the arm64 build node, where Maven on a JVM took about 11 minutes,
while the native arm64 leg took about five (the two legs run one after the other, so about 17
minutes in all). Java bytecode is identical on
both architectures, so the fix is to compile **once, natively**, and let only a tiny packaging
step run per architecture: `build.sh` compiles inside the pipeline's Java agent, and the new
`Containerfile` just copies the jar into a JRE image. Measured: the emulated amd64 packaging leg
takes about 30 seconds.

The wrapper matters: the platform builds Java in a plain JDK image with no Maven, so `test.sh`
runs `./mvnw`, which downloads Maven on first use.

Try it before pushing. The unit tests need no database:

```bash
./test.sh                # 17 passing (needs a JDK 21 locally, or run it in a container)
```

Leave `build.platforms` alone, as in part 1: with the thin `Containerfile` the image builds for both
architectures, and the amd64 leg is cheap. (`FROM --platform=$BUILDPLATFORM` in the scaffold's
Containerfile would be the usual answer, but this platform's builder, kaniko, ignores it: the
"build" stage still ran emulated, and `BUILDPLATFORM` was empty. Testing it is how that was found.)

What the service does:

| Endpoint | Purpose |
|---|---|
| `GET /api/flights/{flight}` | Gate, status, scheduled and estimated departure, capacity, boarding group |
| `GET /api/flights` | All 24 flights |
| `GET /api/flights/{flight}/events` | The change log for one flight, newest first |
| `PUT /api/flights/{flight}/gate` / `…/delay` | Move a flight, or delay it |
| `GET /api/whoami` | Version and pod |
| `GET /actuator/health/readiness` | Ready only when the database answers |

## 05 — Ground: the service and its database

The database is not something you create in Tower. It's a **component** — a block in the
environment's values, exactly like Redis in [part 1, section 08](quickstart.md#08--add-a-redis-cache).

**Step 1 — declare the environment.** Create `platform/envs/dev.yaml`:

```yaml
envName: dev
rollout: null            # explicit; the deploy stage fills in the image later

components:
  - type: postgresql
    name: flight-db      # the Secret this creates is named flight-db-app
    spec: { size: small, instances: 1, storageSize: 1Gi }

env:
  # Read straight from the Secret the database component creates - no copying into Infisical.
  - { name: DB_HOST,     valueFrom: { secretKeyRef: { name: flight-db-app, key: host } } }
  - { name: DB_PORT,     valueFrom: { secretKeyRef: { name: flight-db-app, key: port } } }
  - { name: DB_NAME,     valueFrom: { secretKeyRef: { name: flight-db-app, key: dbname } } }
  - { name: DB_USER,     valueFrom: { secretKeyRef: { name: flight-db-app, key: username } } }
  - { name: DB_PASSWORD, valueFrom: { secretKeyRef: { name: flight-db-app, key: password } } }
  - { name: SIMULATOR_INTERVAL_MS, value: "30000" }

networkPolicy:
  allowIngressFrom:      # let boarding-api's namespace reach us (section 06)
    - { namespace: app-boarding-api-dev, ports: [8080] }
```

Two things worth knowing:

- **The database is created before the app runs.** With `rollout: null` there's no workload yet, so
  the first thing this file produces is the `PostgreSQL` XR and its cluster. Within about a
  minute you'll see them:

  ```bash
  kubectl get postgresql -n app-flight-api-dev              # READY True
  kubectl get cluster.postgresql.cnpg.io -n app-flight-api-dev
  ```
- **`database name == role name`** is deliberate: the component's `pg_hba` only lets a role
  connect to the database named after it, so the app can't reach any other database. The
  default is the component name with `-` turned into `_` (`flight_db`), which is what
  `application.properties` defaults to as well.

**Step 2 — let the pipeline deploy to it.** Replace `cicd.yaml`:

```yaml
apiVersion: platform/v1
kind: PipelineConfig

build:
  agent: openjdk-21
  script: ./build.sh            # compiles natively in the Java agent (see section 04)
  containerfile: ./Containerfile  # thin: just copies the jar in
  unitTest:
    enabled: true         # runs ./test.sh

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

Setting `build.script` is what switches the pipeline from "build inside the Containerfile" to
"build in the agent, then package". It is documented in Glidepath's cicd.yaml reference under *Two
build strategies*.

**Step 3 — commit both, merge the `.tekton/` PR** this push opens, then push. As in part 1
the `deploy` stage commits the image straight into `platform/envs/dev.yaml` on `main`, so
`git pull` before your next push.

The first start takes a little longer than a NodeJS app: the JVM starts, then Flyway waits for
the database if it isn't up yet (it retries for about two and a half minutes) and runs the two
migrations.

**Step 4 — add health probes.** Once the deploy stage has written the image, add probes to the
same file (adding them earlier would make `rollout` non-null with no image):

```yaml
rollout:
  image: { … }          # keep what the deploy stage wrote
  resources:
    requests: { cpu: 500m, memory: 512Mi }   # a JVM starts CPU-bound; see below
    limits: { memory: 1Gi }                  # memory only: no CPU limit, or startup is throttled
  readinessProbe:
    httpGet: { path: /actuator/health/readiness, port: 8080 }
    initialDelaySeconds: 30
    periodSeconds: 10
    timeoutSeconds: 5
    failureThreshold: 6
  livenessProbe:
    httpGet: { path: /actuator/health/liveness, port: 8080 }   # NOT /readiness
    initialDelaySeconds: 60
    periodSeconds: 20
    timeoutSeconds: 5
    failureThreshold: 6
```

Readiness is what makes the pod wait for the database: it isn't sent traffic until Postgres
answers.

**The liveness probe must use `/actuator/health/liveness`, not `/readiness`.** Readiness includes
the database, so pointing liveness at it means a brief database or CPU stall makes the pod look
*dead*, and Kubernetes kills and restarts a healthy pod. This was hit for real: both dev pods
restarted 5–6 times (exit 137, `Liveness probe failed` events) until the path was corrected, after
which the same pods started in 24–33 seconds and stayed up.

**Give it a CPU request.** Spring Boot's startup is CPU-bound. Pods without a request are
`BestEffort` and get the lowest possible CPU priority. On an idle node they still started in 24–33
seconds, but while a pipeline build shared the node the same pods had not finished starting after
about 100 seconds, so a probe with a short budget kills them mid-start. (That link is inferred
from those timings; it was not isolated with a controlled test.) `timeoutSeconds: 5` also matters:
the default of 1 second fails whenever the JVM is briefly busy.

**See it.**

```bash
kubectl port-forward -n app-flight-api-dev svc/flight-api 8081:8080
curl -s localhost:8081/api/flights/AC123
curl -s localhost:8081/api/flights/AC123/events
```

The simulator writes an event about every 30 seconds; watch `events` grow.

**Everything, in one selector.** The component labels everything it creates, so one command finds
the app, its database, its Secret and its volume together:

```bash
kubectl get all,pvc,secret,networkpolicy -n app-flight-api-dev -l hangar.io/app=flight-api
```

## 06 — Point boarding-api at it

In your `boarding-api` repo, copy the updated gate board over the version from part 1:

```bash
cd boarding-api
cp /tmp/airframe/examples/skyport/boarding-api/{app.js,index.js,reservations.js} .
cp /tmp/airframe/examples/skyport/boarding-api/public/index.html public/
cp /tmp/airframe/examples/skyport/boarding-api/test/app.test.js test/
npm test                                     # 11 passing
```

Then add one line to its `platform/envs/dev.yaml`:

```yaml
env:
  - { name: REDIS_URL, value: "redis://cache-master:6379" }
  - { name: FLIGHT_API_URL, value: "http://flight-api.app-flight-api-dev.svc.cluster.local:8080" }
```

Commit and push; the pipeline redeploys. With `FLIGHT_API_URL` unset the app falls back to its
built-in stand-in, so it still runs anywhere. Set, it never invents an answer: an unknown flight is
a 404, and flight-api being down is a 502 that is **not** cached.

Open the gate board and look up `AC123`. The **source** row now says *flight-api (Postgres)* and
there's a **status** row (`ON_TIME`, or `DELAYED (+15 min)` once the simulator has touched it). The
first lookup takes tens of milliseconds because it really hit a database; the second is a
cache hit.

**Now see the problem Phase 2 fixes.** Move the flight's gate in flight-api:

```bash
curl -s -X PUT -H 'Content-Type: application/json' -d '{"gate":"B2"}' localhost:8081/api/flights/AC123/gate
```

Look up `AC123` on the gate board again: it still shows the **old gate**, from the cache. It'll
be right after the three-minute TTL. Waiting for a TTL to expire is the wrong way to keep a gate
board accurate — the fix is for flight-api to publish `flight.gate-changed` and for boarding-api to
evict the entry, which is Phase 2 of [Skyport](skyport-demo.md). The `flight_events` table is
already there for that: every gate change is written to it in the same transaction as the change.

## 07 — Flight: the same service on `kind-prod`

The flight environment works exactly as in [part 1, section 07](quickstart.md#07--flight-a-governed-environment-on-an-upper-cluster):
declare it in `cicd.yaml`, create the `ApplicationEnvironment`, configure it, release an image.
Only the parts that differ are here.

`kind-prod` has the CloudNativePG operator and the `PostgreSQL` XRD installed. Note that it runs
Kubernetes 1.37, which CloudNativePG 1.30 lists as *tested but not supported* upstream; the
component was verified there (above), not assumed.

**Step 1 — `cicd.yaml`.** Add the flight env and a `release` stage:

```yaml
deploy:
  lowerEnvironments: [dev]
  upperEnvironments:
    - { name: staging, cluster: kind-prod }

governance:
  allowedCommitSigners:
    - you@example.com

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

Merge the `.tekton/` PR it opens.

**Step 2 — Tower → Create → ApplicationEnvironment**, with `Name` `flight-api-kind-prod-staging`,
`Namespace` `app-flight-api-cicd`, `appName` `flight-api`, `cluster` `kind-prod`, `env` `staging`.
Merge the PR. The flight environment starts as `rollout: null`, so **the database is created
first**, in `app-flight-api-staging`, before any application runs:

```bash
kubectl --context kind-prod get postgresql -n app-flight-api-staging
```

**Step 3 — configure it.** The flight values live in
`gitops-flight-api/kind-prod/staging/values.yaml` and change only through a pull request. Add the
database, its credentials, the probes and the network rule — **edit the file in that PR directly**
rather than through Tower's App Configuration *Environment variables* section (see the note
below):

```yaml
rollout:
  replicas: 2
  ports: [{ name: http, containerPort: 8080 }]
  resources:
    requests: { cpu: 500m, memory: 512Mi }
    limits: { memory: 1Gi }
  readinessProbe:
    httpGet: { path: /actuator/health/readiness, port: 8080 }
    initialDelaySeconds: 30
    timeoutSeconds: 5
    failureThreshold: 6
  livenessProbe:
    httpGet: { path: /actuator/health/liveness, port: 8080 }   # NOT /readiness
    initialDelaySeconds: 60
    timeoutSeconds: 5
    failureThreshold: 6

components:
  - type: postgresql
    name: flight-db
    spec: { size: small, instances: 2, storageSize: 5Gi }    # a primary and a replica

env:
  - { name: DB_HOST,     valueFrom: { secretKeyRef: { name: flight-db-app, key: host } } }
  - { name: DB_PORT,     valueFrom: { secretKeyRef: { name: flight-db-app, key: port } } }
  - { name: DB_NAME,     valueFrom: { secretKeyRef: { name: flight-db-app, key: dbname } } }
  - { name: DB_USER,     valueFrom: { secretKeyRef: { name: flight-db-app, key: username } } }
  - { name: DB_PASSWORD, valueFrom: { secretKeyRef: { name: flight-db-app, key: password } } }
  - { name: SIMULATOR_INTERVAL_MS, value: "60000" }

networkPolicy:
  allowIngressFrom:
    - { namespace: app-boarding-api-staging, ports: [8080] }
```

`instances: 2` gives a real failover pair; on a small single-node cluster `1` is fine too.
The image is not set here: the release pipeline sets it, as in part 1.

> **Tower and `valueFrom`.** Tower's *Environment variables* section is a name/value form, and
> older builds of it saved the whole `env` list back as name/value pairs, which **replaced a
> `valueFrom` entry with an empty value** (the app then started with a blank `DB_HOST`). Builds from
> Backstage commit `366ea8c` on show `valueFrom` rows read-only (`← Secret flight-db-app / host`) and
> keep them when you save; they only go away if you press Remove. If your Tower predates that
> commit, edit this section in the PR directly instead. Either way, read the PR diff before merging.

**Step 4 — release**, as a signed merge, as in part 1. Then in `boarding-api`'s staging values point
it at `http://flight-api.app-flight-api-staging.svc.cluster.local:8080`.

Check it from a machine that can reach `kind-prod`:

```bash
kubectl --context kind-prod get all,pvc,secret,networkpolicy -n app-flight-api-staging -l hangar.io/app=flight-api
kubectl --context kind-prod -n app-flight-api-staging port-forward svc/flight-api 8082:8080
curl -s localhost:8082/api/flights/AC123
```

Deleting this environment deletes its database and both volumes.

## Cheat sheet

- **`devCluster: kind-dev`**, and **`groupId: io.skyport.flight`** — the code you copy in assumes
  that package.
- **A database is a component**, in the environment's `components:` — not a Tower Create form.
- **Read its credentials with `valueFrom.secretKeyRef`** to `<name>-app`; there's nothing to copy
  into Infisical. Keys: `host`, `port`, `dbname`, `username`, `password` (and `uri`, `jdbc-uri`,
  `fqdn-uri`).
- **Database name equals role name** — the component enforces it.
- **Deleting the environment deletes the database.** It's dedicated, and its volume goes with it.
- **Build Java with `build.script`, not in the Containerfile.** The amd64 image leg runs under emulation; a
  Maven build there took ~11 minutes (17 for the whole image), the packaging-only leg ~30 s.
- **Liveness is `/actuator/health/liveness`, never `/readiness`**, and give the pod a CPU request. Symptom of getting it wrong: the pod restarts repeatedly (exit 137, `Liveness probe failed`) though the database is fine.
- **Add probes after the first deploy**, not before: `rollout` must stay `null` until the deploy
  stage has written an image.
- **Cross-namespace traffic needs a rule.** Namespaces deny ingress from other namespaces by
  default; `networkPolicy.allowIngressFrom` opens exactly one.
- **`test.sh` uses `./mvnw`** — the Java build agent has no Maven.
- **One selector for everything:** `-l hangar.io/app=<app>`.
- **`valueFrom` and Tower:** older Tower builds drop `valueFrom` entries when you edit *Environment variables*; builds from Backstage `366ea8c` keep them. Read the PR diff either way.
- **After any component change, expect ~10 minutes of `Ready=False`** on its Release: provider-helm
  (Redis) reports it until its next poll though the pods are fine. The PostgreSQL component
  doesn't use provider-helm and doesn't do this.
