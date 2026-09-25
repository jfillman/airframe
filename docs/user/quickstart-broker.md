# Airframe quickstart, part 3: a shared message broker

[Part 1](quickstart.md) built a NodeJS service with a Redis cache. [Part 2](quickstart-flight-api.md)
built a Spring Boot service with its own PostgreSQL and ended on a problem: move a flight's gate in
`flight-api` and the gate board keeps showing the old one until the three-minute cache expires.

This part fixes it with a **message broker**. You provision `skyport-broker` (RabbitMQ) once, then
attach `flight-api` as a **publisher** and `boarding-api` as a **consumer**: `flight-api` announces
every change, `boarding-api` drops the changed flight from its cache, and the board is right
immediately.

> An illustrated version of this guide is published at
> [Airframe Broker Quickstart](https://claude.ai/artifact/UbLvT5JsB8Kmcbwk8VJ4eX).

Do parts 1 and 2 first. This guide assumes `boarding-api` and `flight-api` are running in their dev
environments and doesn't repeat how to create an app or merge a pipeline PR.

**What has and hasn't been verified.** See [the end of this guide](#what-was-verified) before you rely
on section 08: the ground steps were walked live, the flight (`kind-prod`) steps were not.

## 01 — What you're building

```
   flight-api ──publish──▶ ┌─────────────────────────────────────────┐ ──deliver──▶ boarding-api
   (Spring)    flight.AC123│  skyport-broker  (RabbitMQ, 1 pod)      │ boarding.       (NodeJS)
               .gate_changed│  vhost: flights                        │ flight-events   evicts the
                           │  exchange: flights.events  (topic)      │ queue           cached flight
                           └─────────────────────────────────────────┘
        app-flight-api-dev       app-skyport-broker-dev            app-boarding-api-dev
```

Three namespaces, and this is the first time in the series that apps share something:

- **One broker** lives in its own namespace, `app-skyport-broker-dev`. Unlike a database or a cache,
  it isn't dedicated to an app: the whole point is that several apps talk through it.
- **Each app gets its own broker user**, with permissions generated from a few names. `flight-api`
  can publish to the `flights.events` exchange. `boarding-api` can read from it into queues named
  `boarding.*`. Neither can do anything else. This is enforced by the broker, not by convention.
- **One vhost per domain.** A vhost is a namespace inside the broker; messages don't cross between
  them. Apps that exchange messages must share one, so the vhost is named for the domain
  (`flights`), not for an app.

## 02 — Create the broker

The broker is a **component**, like Redis and PostgreSQL, but a shared one, so it needs somewhere to
live that isn't any app's environment. That's an **`InfraService`**: an empty GitOps deploy repo with
no source code.

**Tower → Create → InfraService.**

| Field | Value |
|---|---|
| Name | `skyport-broker` |
| `devCluster` | `kind-dev` |
| `description` | Skyport shared message broker (RabbitMQ) |
| `visibility` | `private` |

Use `kind-dev` for `devCluster` exactly, as in [part 1](quickstart.md#02--create-the-app).

Tower opens a PR against the tenants repo. **Merge it.** Within a few minutes:

```bash
kubectl get infraservice skyport-broker -n app-skyport-broker-cicd
NAME             SYNCED   READY   COMPOSITION                         AGE
skyport-broker   True     True    infraservices.catalog.idp.io        2m
```

It created one repo, `gitops-infra-skyport-broker`, containing only a `README.md` and a stub
`cicd.yaml`. There is no application to build, so there is no pipeline.

> **If it stays `OutOfSync`** with `InfraService is not permitted in project idp-onboarding`, the dev
> cluster's onboarding project predates `InfraService` support. Add `InfraService` to the
> `namespaceResourceWhitelist` in `02-argocd-apps/xr-requests/appproject.yaml` (gitops-cluster-dev,
> or apron for a new cluster). This was the first thing that broke when this path was walked for
> real: `InfraService` had never been created on a live cluster before.

## 03 — Declare the broker

An environment of any app is a file, `platform/envs/<env>.yaml`, in the repo the app is built from.
For an `InfraService` that repo is `gitops-infra-skyport-broker` itself. Create
`platform/envs/dev.yaml` and push it to `main`:

```yaml
appType: infra
envName: dev
rollout: null            # no workload of our own: the broker is the component below

components:
  - type: rabbitmq
    name: skyport-broker # also the broker's Service name: skyport-broker.app-skyport-broker-dev.svc
    spec:
      mode: broker
      size: small
      instances: 1
      storageSize: 1Gi
      vhosts: [flights]
      # Only these namespaces may attach (get a user) and reach the AMQP port.
      allowedNamespaces: [app-flight-api-dev, app-boarding-api-dev]
```

| Field | Meaning |
|---|---|
| `mode: broker` | This entry runs the broker. (`attach` is what the apps use, below.) |
| `size` | `small` is 100m CPU and 512Mi to 1Gi of memory. `medium` and `large` scale that up. |
| `instances` | `1` is a single node. `3` is a replicated cluster (RabbitMQ needs an odd count). |
| `vhosts` | Created for you. One per domain. |
| `allowedNamespaces` | **The trust boundary.** A namespace not listed here can neither create a user nor reach the broker's port. Adding an app to the broker is a one-line change here. |

The dev cluster picks the file up within a few minutes (it polls the repo), creates the namespace
`app-skyport-broker-dev`, and the component starts. The first start pulls the image and takes about
two minutes:

```bash
kubectl get rabbitmqs.catalog.idp.io -n app-skyport-broker-dev
NAME             SYNCED   READY   COMPOSITION               AGE
skyport-broker   True     True    rabbitmq.catalog.idp.io   2m

kubectl get pods,svc,pvc -n app-skyport-broker-dev -l hangar.io/app=skyport-broker
```

(Use the full name `rabbitmqs.catalog.idp.io`: plain `rabbitmq` is ambiguous with the operator's own
API group.) Its admin credentials are in the Secret `skyport-broker-default-user`; apps never need
them.

## 04 — Wire flight-api (the publisher)

Two changes: the code, and the environment.

**The code.** `flight-api` gains an opt-in publisher. With `EVENTS_ENABLED` unset it publishes
nothing and needs no broker, so the part 2 setup is unchanged. Copy it in:

```bash
git clone https://github.com/jfillman/airframe.git /tmp/airframe   # skip if you still have it
cd flight-api
A=/tmp/airframe/examples/skyport/flight-api
cp $A/pom.xml .
cp $A/src/main/resources/application.properties src/main/resources/
cp $A/src/main/java/io/skyport/flight/{FlightMessage,FlightEventPublisher,NoopFlightEventPublisher,RabbitFlightEventPublisher,FlightService}.java src/main/java/io/skyport/flight/
cp $A/src/test/java/io/skyport/flight/{FlightServiceTest,RabbitFlightEventPublisherTest}.java src/test/java/io/skyport/flight/
./test.sh                # 21 passing
```

What it does, and why it's written this way:

- **It publishes after the database commit**, not during it. A change that rolls back is never
  announced. A change is written to `flight_events` in the same transaction as before; the message
  goes out only once that has committed.
- **A broker outage never fails a flight change.** The publisher logs a warning and carries on;
  losing one notification is better than rejecting a change that was already saved.
- **Each message carries the flight's state after the change** (`gate`, `delayMinutes`), so a
  consumer never has to call back to learn what is true now.
- **The routing key is `flight.<number>.<type>`**, for example `flight.AC123.gate_changed`, so
  consumers can bind to `flight.#` (everything) or `flight.AC123.*` (one flight).
- **It declares the exchange itself.** `flight-api` owns `flights.events`; consumers only bind to it.

**The pom.** The copy of `pom.xml` also moves Spring Boot from 3.3.4 to **3.5.16** and pins Tomcat,
the Postgres driver, the RabbitMQ client and Netty to patched versions. This is not about RabbitMQ:
the pipeline's image scan fails on HIGH and CRITICAL findings, and Boot 3.3.4 (already end-of-life)
now trips it on its own Tomcat, Spring and Jackson. A build of part 2's `flight-api` would fail the
same way today. The `<properties>` in the pom explain each override; drop them as Boot catches up.

**The environment.** Add an `rabbitmq` component in `attach` mode, and hand its connection details
to the app, in `platform/envs/dev.yaml`:

```yaml
components:
  # ... flight-db stays as it is ...
  - type: rabbitmq
    name: flight-mq            # credentials land in Secret flight-mq-user-credentials
    spec:
      mode: attach
      brokerRef: { name: skyport-broker, namespace: app-skyport-broker-dev }
      vhost: flights
      publish: [flights.events]   # may declare and publish to this exchange, nothing else

env:
  # ... the DB_* entries stay as they are ...
  - { name: EVENTS_ENABLED, value: "true" }
  - { name: RABBITMQ_HOST,     valueFrom: { configMapKeyRef: { name: flight-mq-connection, key: host } } }
  - { name: RABBITMQ_VHOST,    valueFrom: { configMapKeyRef: { name: flight-mq-connection, key: vhost } } }
  - { name: RABBITMQ_USER,     valueFrom: { secretKeyRef:    { name: flight-mq-user-credentials, key: username } } }
  - { name: RABBITMQ_PASSWORD, valueFrom: { secretKeyRef:    { name: flight-mq-user-credentials, key: password } } }
```

What an `attach` entry creates, in `flight-api`'s own namespace:

| Object | Holds |
|---|---|
| a broker **user** | with a generated name and password, written to the Secret `<name>-user-credentials` (`username`, `password`) |
| a **permission** | generated from `publish`, `consume` and `queuePrefix` (below) |
| a ConfigMap `<name>-connection` | `host`, `port`, `vhost` |

Nothing is copied through Infisical: the app reads the Secret and the ConfigMap directly with
`valueFrom`, exactly as it reads the database's credentials in part 2.

Commit both, push, and let the pipeline run. `git pull` before your next push: the deploy stage commits
the image into `platform/envs/dev.yaml`.

## 05 — Wire boarding-api (the consumer)

**The code.** `boarding-api` gains `events.js`, a consumer that is off unless `RABBITMQ_HOST` is set:

```bash
cd boarding-api
A=/tmp/airframe/examples/skyport/boarding-api
cp $A/{app.js,index.js,events.js,store.js,package.json,package-lock.json} .
cp $A/test/{app.test.js,events.test.js} test/
npm ci && npm test        # 18 passing
```

What it does:

- **It creates its own queue**, `boarding.flight-events`, binds it to `flights.events` with `flight.#`,
  and on each message deletes `boarding:<flight>` from the Redis cache. The next lookup goes to
  `flight-api` and is correct.
- **It cannot declare the exchange**, because it may only read from it. If `flight-api` hasn't started
  yet, the bind is refused (`NOT_FOUND - no exchange 'flights.events'`) and the consumer **retries every
  five seconds** until the exchange exists. Start order doesn't matter.
- **A malformed message is ignored**, not fatal; an eviction that fails is retried.
- `/api/whoami` gains `events` (`off`, `connecting` or `connected`) and `eventsReceived`, so you can
  see it working.

**The environment.** In `boarding-api`'s `platform/envs/dev.yaml`:

```yaml
components:
  # ... the redis cache stays as it is ...
  - type: rabbitmq
    name: board-mq             # credentials land in Secret board-mq-user-credentials
    spec:
      mode: attach
      brokerRef: { name: skyport-broker, namespace: app-skyport-broker-dev }
      vhost: flights
      queuePrefix: boarding    # may create, bind and consume queues named boarding.*
      consume: [flights.events] # may bind them to this exchange, not publish to it

env:
  # ... REDIS_URL and FLIGHT_API_URL stay as they are ...
  - { name: RABBITMQ_HOST,     valueFrom: { configMapKeyRef: { name: board-mq-connection, key: host } } }
  - { name: RABBITMQ_VHOST,    valueFrom: { configMapKeyRef: { name: board-mq-connection, key: vhost } } }
  - { name: RABBITMQ_USER,     valueFrom: { secretKeyRef:    { name: board-mq-user-credentials, key: username } } }
  - { name: RABBITMQ_PASSWORD, valueFrom: { secretKeyRef:    { name: board-mq-user-credentials, key: password } } }
```

Commit, push, and let the pipeline redeploy.

## 06 — See it work

```bash
kubectl port-forward -n app-flight-api-dev svc/flight-api 8081:8080 &
kubectl port-forward -n app-boarding-api-dev svc/boarding-api 8080:8080 &

curl -s localhost:8080/api/whoami        # "events":"connected"
curl -s localhost:8080/api/boarding/AC123   # note the gate; a second call says "cached":true

curl -s -X PUT -H 'Content-Type: application/json' -d '{"gate":"B2"}' localhost:8081/api/flights/AC123/gate

curl -s localhost:8080/api/boarding/AC123   # gate is B2 at once, "cached":false
curl -s localhost:8080/api/whoami           # "eventsReceived" went up
```

In part 2 that last lookup showed the old gate for up to three minutes. Now the change reaches every
`boarding-api` pod as soon as it is committed, because each pod's consumer receives the event and
evicts the entry. (With two replicas the queue is shared, so one pod handles each event; the cache is
in Redis, so evicting it once clears it for both.)

The simulator changes a flight roughly every 30 seconds too, so `eventsReceived` keeps climbing on its
own.

## 07 — What each app can and can't do

The permissions are generated from the names in each `attach` entry. Nothing is a raw regex you write:

| Field | Gives the app | For |
|---|---|---|
| `queuePrefix: boarding` | create, bind and consume queues | names starting `boarding.` |
| `publish: [flights.events]` | declare and publish | that exchange |
| `consume: [flights.events]` | bind its queues to it | that exchange, read-only |

Tested over real AMQP against the running broker, with the credentials each app really uses:

| Attempt | Result |
|---|---|
| `flight-api` declares `flights.events` and publishes | allowed |
| `boarding-api` declares `boarding.q`, binds it to `flights.events`, receives the message | allowed |
| `boarding-api` publishes to `flights.events` | **refused** |
| `boarding-api` declares a queue named `x.q` (outside its prefix) | **refused** |
| `flight-api` reads `boarding-api`'s queue | **refused** |

A compromised `boarding-api` credential therefore can't forge a flight event, and a bug in
`baggage-api` (Phase 2, next) can't read another app's queue.

**Who may attach is decided by the broker's owner**, in `allowedNamespaces` (section 03). Anyone who
can edit an app's environment file can *request* any permission on the vhost for that app, so the list
of namespaces, not the permission text, is what protects the broker. That's acceptable for this demo;
a shared production broker would also want an admission policy on what an app may ask for.

## 08 — Flight: the same on `kind-prod`

> **Not walked.** Everything in this section is written from how the pieces work and from the
> component being verified on `kind-prod` (below); it was not run end to end. `kind-prod` was also
> short of memory when this was written, and the broker adds about 1Gi. Check `podman` VM headroom
> first.

The flight environment for the broker works as in [part 1, section 07](quickstart.md#07--flight-a-governed-environment-on-an-upper-cluster)
and [part 2, section 07](quickstart-flight-api.md#07--flight-the-same-service-on-kind-prod):

1. Tower → Create → **ApplicationEnvironment**: `Name` `skyport-broker-kind-prod-staging`, `Namespace`
   `app-skyport-broker-cicd`, `appName` `skyport-broker`, `cluster` `kind-prod`, `env` `staging`.
   Merge the PR.
2. In the PR that adds `gitops-infra-skyport-broker/kind-prod/staging/values.yaml`, use the same
   `components:` block as section 03 with `allowedNamespaces: [app-flight-api-staging,
   app-boarding-api-staging]`.
3. In each app's staging values, add its `attach` component and the `env` entries from sections 04 and
   05, pointing `brokerRef` at `app-skyport-broker-staging`.

`kind-prod` has the RabbitMQ operators, cert-manager and the RabbitMQ component installed, and the
component was verified there: broker and attach both reached Ready with the app baseline
NetworkPolicy in place, a pod in an allowed namespace connected on 5672, and a pod in a namespace not
on the list was blocked.

## What was verified

- **Verified live by walking it (2026-09-25), on the dev cluster.** Creating the `InfraService` (which
  found the `idp-onboarding` gap in section 02), declaring the broker in `platform/envs/dev.yaml`,
  both `attach` components going Ready and creating their Secrets, `boarding-api` connecting with its
  real credentials and waiting for the exchange (section 05), and the pipeline builds. Walking it also
  found the image-scan failure in section 04.
- **Verified by test, against real RabbitMQ:** the component's broker and attach modes on both
  clusters, and every allowed and refused action in section 07 (over AMQP, on the dev cluster).
  `flight-api`: 21 unit tests. `boarding-api`: 18.
- **Verified in the component on `kind-prod`** (Calico, which enforces NetworkPolicy): broker and
  attach modes Ready; allowed namespace connects, other namespace blocked.
- **Not walked:** section 08 end to end, and the `kind-prod` staging environments for either app.
- **Verified end to end, live:** with both apps on their final images (`flight-api` 1.1.0 on Spring
  Boot 3.5.16, `boarding-api` 1.1.0), a lookup of `AC123` was a cache hit on gate A1; after
  `PUT …/gate` to B2 the same lookup returned B2 at once with `"cached": false`, and `eventsReceived`
  climbed. The simulator's own changes were arriving too (`eventsReceived` was already 4 before the
  manual change).

**Needs airframe v0.3.89 or later** on the dev cluster's ApplicationSets (the `rabbitmq` component and
its `componentKinds` entry).

## Cheat sheet

- **The broker is an `InfraService` with a `rabbitmq` component (`mode: broker`).** Apps use the same
  component type in `mode: attach`.
- **Use `rabbitmqs.catalog.idp.io`** in `kubectl`, not `rabbitmq`.
- **One vhost per domain** (`flights`), created by `vhosts:`. Apps that exchange messages share one.
- **`allowedNamespaces` is the trust boundary.** Add an app's namespace there before it attaches; an
  unlisted namespace's user is refused.
- **Credentials:** Secret `<name>-user-credentials` (`username`, `password`), ConfigMap
  `<name>-connection` (`host`, `port`, `vhost`). Read them with `valueFrom`; nothing goes through Infisical.
- **Permissions come from `queuePrefix`, `publish` and `consume`**, never hand-written regexes.
- **The broker's Service is `<name>.<namespace>.svc:5672`.**
- **A consumer can't declare the exchange** and retries until the producer has; start order is free.
- **Publish after commit, and never fail the change on a broker error** — the pattern in section 04.
- **The pipeline's image scan gates the build.** If it fails on Tomcat, Spring, Jackson or a driver
  you didn't touch, the base has aged; bump Spring Boot or override the vulnerable version in the pom.
- **RabbitMQ 4.2, not 4.1**, with operator 2.23: the operator's startup probe needs an endpoint 4.1
  doesn't have. The component pins the version, so you don't choose.
- **The broker's PVC isn't labelled `hangar.io/app`**, unlike its pods, Services and Secrets.
- **Deleting the broker's environment deletes its data.** It isn't backed up.
- **The `provenance` gate on release PRs fails for unsigned commits.** It did on `boarding-api`'s own
  earlier release too; see [part 1](quickstart.md) for signing merges.
