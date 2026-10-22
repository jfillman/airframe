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
| [quickstart-baggage-api.md](quickstart-baggage-api.md) | Part 4: a Python service with its own MongoDB that consumes the broker's events, wired with `fromComponent`. |
| [quickstart-skyport-auth.md](quickstart-skyport-auth.md) | Part 5: a shared Dex OIDC server as an `InfraService` on both clusters, a client per app, and enforced tokens: flight-api and baggage-api refuse calls without one, boarding-api sends one. |
| [quickstart-gate-api.md](quickstart-gate-api.md) | Part 6: the smallest service, from one XR to a canary on the prod cluster, all from the terminal (the recorded "zero to running" run). |
| [quickstart-checkin-api.md](quickstart-checkin-api.md) | Part 7: the same path through Tower: the create form, the Environments and App Configuration tabs, the release. |
| [skyport-runbook.md](skyport-runbook.md) | You are standing up all of Skyport on freshly built clusters: order, prerequisites, leftovers to clean first, and how to replay every check. |

Before you commit an env file, run `tools/airframe-validate glidepath/envs/dev.yaml` from the Airframe repo:
it catches typos the chart would otherwise silently ignore (`rolout:`, `replcas:`) and bad component
values (`size: gigantic`). A newly created app renders no workload until its first image is built, so it is
safe to configure it first. AI agents: start with [`AGENTS.md`](../../AGENTS.md).

For the platform architecture underneath this guide — every XRD's inputs/outputs,
the composition graph, the plumbing — see [../admin/architecture.md](../admin/architecture.md).

## The two environment tiers, in one line each

- **Ground** — a disposable environment on the dev cluster, declared in your own
  repo's `glidepath/envs/*.yaml`, no PR, no review.
- **Flight** — a governed environment on a real upper cluster, created as an
  `ApplicationEnvironment` XR, promoted through a reviewed pull request.

[Quickstart part 1](quickstart.md) walks through both.

## Illustrated version

Each quickstart also exists as an illustrated page, generated from the Markdown by
`tools/build-quickstart-docs`: start at **[Airframe Quickstart, part 1](html/quickstart.html)**.
Edit the Markdown, then rerun the tool; `--check` fails when a page is out of date.

- [Cloud targets](cloud-targets.md): stand up the AWS Lambda, ECS or Azure Container Apps infrastructure a cloud deploy needs, on demand.
