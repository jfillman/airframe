# Airframe: user guide

Documentation for **application developers** using this service catalog — not the
people running it. If you're creating a new service, giving it somewhere to run, or
attaching it to a component like Redis, start here.

The one-sentence version: you fill out a form in Tower (or commit a manifest by hand
if you'd rather), Git holds that request as the source of truth, and Crossplane
reconciles it against real infrastructure continuously. You never call a provider
API, run `kubectl apply`, or touch a Helm chart directly.

## Contents

| Doc | Read this when... |
|---|---|
| [quickstart.md](quickstart.md) | You're creating a new service and want it running, with an environment on each tier, in the next twenty minutes. |
| [quickstart-flight-api.md](quickstart-flight-api.md) | You want a service that owns a database: a Spring Boot app with PostgreSQL, credentials read from the component's Secret, and a call from part 1's gate board. |
| [quickstart-broker.md](quickstart-broker.md) | You want services to talk through a shared message broker: provisioning RabbitMQ as an `InfraService`, then attaching a publisher and a consumer with least-privilege access. |

For the platform architecture underneath this guide — every XRD's inputs/outputs,
the composition graph, the plumbing — see [../admin/architecture.md](../admin/architecture.md).

## The two environment tiers, in one line each

- **Ground** — a disposable environment on the dev cluster, declared in your own
  repo's `platform/envs/*.yaml`, no PR, no review.
- **Flight** — a governed environment on a real upper cluster, created as an
  `ApplicationEnvironment` XR, promoted through a reviewed pull request.

See [quickstart.md](quickstart.md#01--ground--flight) for the full comparison.

## Illustrated version

This guide also exists as a fully illustrated, interactive walkthrough with worked
diagrams — same content, richer format:
**[Airframe Quickstart](https://claude.ai/artifact/WDPmWSD9BMBGurFzqATDWG)**
