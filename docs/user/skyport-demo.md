# Skyport — the demo system

Skyport is one small, believable airport system split across five services. Its job
is to exercise **every Airframe stack and every component** in one place, so each
feature has a real caller and a visible effect instead of a toy curl.

The code lives in [`examples/skyport/`](https://github.com/jfillman/airframe/tree/main/examples/skyport)
in the `airframe` repo. Why here and not `hangar`: the demos are consumers of
Airframe's XRDs and versioned alongside them, while `hangar` is the docs umbrella.
Each service directory is what you copy into the source repo Airframe scaffolds for
you (see the [quickstart](quickstart.md), section 03).

> **Status.** `boarding-api` (Phase 0) and `flight-api` (Phase 1) exist. Everything else is a
> plan. The components the later phases depend on — RabbitMQ, MongoDB, OAuth server — are
> **unbuilt** in Airframe today; each phase below lists what has to be built first. Postgres
> is built: a dedicated CloudNativePG cluster per app environment.

## The five services

| Service | Airframe stack | Components | What it does |
|---|---|---|---|
| **boarding-api** | `NodeJSApplication` | Redis · RabbitMQ (consumer) | The passenger-facing **gate board**: flight/gate lookups, boarding-pass scans, and the canary visualizer. Caches lookups in Redis. |
| **flight-api** | `SpringBootApplication` | Postgres · RabbitMQ (producer) · OAuth (resource server) | System of record for flights and gates. A scheduled simulator delays flights and changes gates, recording an event each time (published to the broker from Phase 2). |
| **baggage-api** | `PythonApplication` | RabbitMQ (consumer) · MongoDB | Tracks each bag's journey as a document. Consumes flight events to re-route bags when a gate changes. |
| **skyport-auth** | `InfraService` | `oauth-server` | The OIDC provider. Issues the tokens `flight-api` and `baggage-api` validate. |
| **skyport-broker** | `InfraService` | `rabbitmq` | The shared message broker `flight-api`, `baggage-api` and `boarding-api` all attach to. |

`GoApplication` is deliberately left out; the other four Bootstrap stacks
(`NodeJS`, `SpringBoot`, `Python`, `InfraService`) are all used, and `InfraService`
twice — it's the stack for things several services share.

An `InfraService` is an empty GitOps deploy repo with no source, so the two shared
pieces are components hosted there rather than code.

## How they work together

```
                 browser
                    │
                    ▼
            ┌───────────────┐   token    ┌───────────────┐
            │  boarding-api │──────────▶ │ skyport-auth  │
            │  (NodeJS)     │            │ (OIDC)        │
            │  Redis cache  │            └───────┬───────┘
            └──┬─────────▲──┘                    │ JWKS
        GET    │         │ gate-changed          ▼
     /flights  │         │ (evict cache)  ┌───────────────┐   flight.*    ┌───────────────┐
               ▼         │                │  flight-api   │──────────────▶│skyport-broker │
                         └────────────────│  (Spring)     │               │ (RabbitMQ)    │
                                          │  Postgres     │               └──────┬────────┘
                                          └───────────────┘                      │ flight.*
                                                                                 ▼
                                                                         ┌───────────────┐
                                                                         │  baggage-api  │
                                                                         │  (Python)     │
                                                                         │  MongoDB      │
                                                                         └───────────────┘
```

A day in the life:

1. **Look up a flight.** The gate board asks `boarding-api`. On a Redis miss it
   calls `flight-api` (with a bearer token from `skyport-auth`), which reads Postgres.
   The answer is cached for three minutes.
2. **Scan a boarding pass.** `boarding-api` increments a per-flight counter in Redis.
   With two replicas this is only correct because Redis is shared — the gate board
   shows which cache mode it's in, and in-memory mode visibly miscounts.
3. **Something changes.** `flight-api`'s simulator moves a flight to another gate
   and publishes `flight.gate-changed`.
4. **Two consumers react.** `boarding-api` evicts the cached entry, so the next
   lookup shows the new gate at once instead of after the TTL. `baggage-api`
   re-routes that flight's bags and updates their documents in MongoDB.

The events are the point of the design: cache invalidation and bag re-routing are
two unrelated consumers of one fact, which is exactly what a queue is for.

## Which component does what

| Component | Used by | Demonstrates |
|---|---|---|
| Redis | boarding-api | Cache-aside with TTL, shared counters across replicas |
| Postgres | flight-api | A relational system of record, schema migration on deploy, credentials read straight from the component's Secret |
| RabbitMQ | flight-api → boarding-api, baggage-api | Fan-out events; a shared broker via `InfraService` |
| MongoDB | baggage-api | Document storage that doesn't fit rows |
| OAuth server | flight-api, baggage-api, boarding-api | Service-to-service tokens; one issuer for the platform |
| SLO / RolloutWatch / SecretStore | all five | The components that already exist, on every service |

## The canary test bench

`boarding-api` is built to make progressive delivery *visible*. The gate board polls
`/api/whoami` twice a second and draws a bar of which **version** answered:

- The header colour is derived from the answering version, so a v1 → v2 flip is
  obvious without reading anything.
- **v2.0.0 adds a "boarding group" line** to the lookup result, so a canary also
  changes behaviour, not just a number.
- Each poll opens a fresh connection (`Connection: close`), so even through
  `kubectl port-forward` — which pins a connection to one pod — the tally reflects
  the pod mix instead of showing 100% of whichever pod you landed on.

The [quickstart](quickstart.md) walks a real canary with it. Blue/green works the
same way: the bar flips from 100% v1 to 100% v2 at promotion instead of ramping.

## Phases

Each phase ends with something you can run. Nothing later than Phase 1 is built.

| Phase | Adds | Must exist first | Status |
|---|---|---|---|
| 0 | `boarding-api` (NodeJS) + Redis + canary UI — [quickstart](quickstart.md) | Redis component, `provider-helm` on the target cluster | **Deployed on the dev cluster with Redis.** The canary and flight environment are the parts not yet walked. |
| 1 | `flight-api` (Spring) + Postgres; boarding-api calls it — [quickstart part 2](quickstart-flight-api.md) | `postgresql` component (built) | **Code written and tested against a real Postgres, and boarding-api verified against it. Not yet deployed through Airframe.** |
| 2 | `skyport-broker` (RabbitMQ), flight events, `baggage-api` (Python), cache eviction | `rabbitmq` component; a decision on shared-vs-dedicated brokers | Planned |
| 3 | MongoDB for `baggage-api` | `mongodb` component | Planned |
| 4 | `skyport-auth` and enforced JWTs | `oauth-server` component; Keycloak-vs-alternative decision | Planned |
| 5 | *(optional)* an nginx edge as a third `InfraService` | `nginx` component; its scope is still undecided | Planned |

The open design questions behind Phases 2–5 — shared vs dedicated tenancy for
Postgres/Mongo/RabbitMQ, what `nginx` covers, `provider-rabbitmq`'s single-maintainer
risk — are in `hangar/docs/service-catalog-design.md`. This plan doesn't settle them.

## Two architectures

`kiac-dev` (ground) is **arm64** and `kind-prod` (flight) is **amd64**. Everything
in Skyport has to run on both:

- **Application images.** The build stage builds `linux/arm64` and `linux/amd64` by
  default (`build.platforms` in `cicd.yaml`); leave it alone. The amd64 leg runs
  under QEMU on the arm64 build node, so it is slow, and a compiler crashing under
  emulation is a known failure mode. Where a build stage is architecture-neutral
  (Java bytecode, pure-JS dependencies) use `FROM --platform=$BUILDPLATFORM` for it.
  `boarding-api` has no native dependencies. `flight-api` and `baggage-api` must
  avoid ones without both wheels or classifiers.
- **Component charts.** Every image a wrapped upstream chart pulls has to be a
  multi-arch index. Checked for Redis (Bitnami `redis:latest`: amd64 and arm64);
  **check each new component before it ships** — this is the easiest thing to get
  wrong.
- **Crossplane Functions and providers.** Any function or provider image this
  catalog publishes must be multi-arch, because Crossplane runs on both clusters.
  `function-rollout-watcher` already is. The platform toolbox image
  (`platform-cicd-toolbox`) is **arm64-only**, which is fine only because pipelines
  run on `kiac-dev`; a pipeline on `kind-prod` would fail with `exec format error`.
