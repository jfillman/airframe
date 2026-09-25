# Airframe quickstart, part 2: a service with a database

[Part 1](quickstart.md) took a NodeJS service from nothing to a canary. This part does the
same for a **Spring Boot** service that owns a **PostgreSQL** database, then connects part 1's
`boarding-api` to it so the gate board shows real data.

We build `flight-api`, the system of record for [Skyport](skyport-demo.md): 24 flights and
their gates in Postgres, a REST API, and a simulator that keeps moving flights around so there
is something to watch.

Do part 1 first. This guide assumes `boarding-api` is running in its dev environment and
doesn't repeat the mechanics of creating an app, merging the pipeline PR, or the ground/flight
split; it links back to the section that explains each.

**What has and hasn't been verified.**
- **Verified:** the service. Its 17 unit tests pass in the platform's own Java build image; its
  migrations and queries pass against a real PostgreSQL (4 integration tests); the container
  image was built with the exact `Containerfile` the platform scaffolds and run against that
  database; and `boarding-api` was run against it end to end.
- **Verified:** the database component. A `PostgreSQL` component was created, went Ready,
  scaled to two instances with data intact, and tore down cleanly on the dev cluster.
- **Verified by rendering only:** the chart passing `flight-db-app`'s Secret into the container
  (`env` entries with `valueFrom`) and the `allowIngressFrom` rule for `boarding-api`.
- **Not verified:** this exact walkthrough — creating the app in Tower, the pipeline, and the
  deploy — has not been walked end to end. Where a step turns out wrong, this guide is corrected.

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

This overwrites the scaffold's `pom.xml`, `Application.java` and `application.properties`,
and adds the other classes, the SQL migrations, the tests, `test.sh` and the Maven Wrapper
(`mvnw`, `.mvn/`). **Keep the scaffolded `Containerfile`.** Keep `cicd.yaml` for now; you change
it in section 05.

The wrapper matters: the platform builds Java in a plain JDK image with no Maven, so `test.sh`
runs `./mvnw`, which downloads Maven on first use.

Try it before pushing. The unit tests need no database:

```bash
./test.sh                # 17 passing (needs a JDK 21 locally, or run it in a container)
```

Nothing in `flight-api` reads a database at build time, so the image builds on both
architectures with no changes (Java bytecode is architecture-neutral). Leave `build.platforms`
alone, as in part 1.

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
  readinessProbe:
    httpGet: { path: /actuator/health/readiness, port: 8080 }
    initialDelaySeconds: 20
    periodSeconds: 10
  livenessProbe:
    httpGet: { path: /actuator/health/liveness, port: 8080 }
    initialDelaySeconds: 60
    periodSeconds: 20
```

Readiness is what makes the pod wait for the database: it isn't sent traffic until Postgres
answers.

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

## Cheat sheet

- **`devCluster: kind-dev`**, and **`groupId: io.skyport.flight`** — the code you copy in assumes
  that package.
- **A database is a component**, in the environment's `components:` — not a Tower Create form.
- **Read its credentials with `valueFrom.secretKeyRef`** to `<name>-app`; there's nothing to copy
  into Infisical. Keys: `host`, `port`, `dbname`, `username`, `password` (and `uri`, `jdbc-uri`,
  `fqdn-uri`).
- **Database name equals role name** — the component enforces it.
- **Deleting the environment deletes the database.** It's dedicated, and its volume goes with it.
- **Add probes after the first deploy**, not before: `rollout` must stay `null` until the deploy
  stage has written an image.
- **Cross-namespace traffic needs a rule.** Namespaces deny ingress from other namespaces by
  default; `networkPolicy.allowIngressFrom` opens exactly one.
- **`test.sh` uses `./mvnw`** — the Java build agent has no Maven.
- **One selector for everything:** `-l hangar.io/app=<app>`.
