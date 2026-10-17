# Skyport demo code

Source for the Skyport demo system. The design, the service map and the build
phases are in [`docs/user/skyport-demo.md`](../../docs/user/skyport-demo.md); the order to
stand it all up on fresh clusters is the [Skyport runbook](../../docs/user/skyport-runbook.md).

Status is as of the previous lab (rebuilt from scratch 2026-10-16). "Prod staging" means the
`staging` environment on the prod (upper) cluster. Nothing has been replayed on the rebuilt
clusters yet; each guide's walkthrough is the check.

| Directory | Stack | Status | Guide |
|---|---|---|---|
| [`boarding-api/`](boarding-api/) | `NodeJSApplication` | Built. Redis component, RabbitMQ consumer, Dex token client for flight-api (part 5). Ran on dev and prod staging (without the token client). | [part 1](../../docs/user/quickstart.md), [part 3](../../docs/user/quickstart-broker.md), [part 5](../../docs/user/quickstart-skyport-auth.md) |
| [`flight-api/`](flight-api/) | `SpringBootApplication` | Built. PostgreSQL component, RabbitMQ publisher. Ran on dev and prod staging. Validates Dex tokens on `/api/flights` (part 5; not yet compiled or run). | [part 2](../../docs/user/quickstart-flight-api.md), [part 3](../../docs/user/quickstart-broker.md) |
| [`baggage-api/`](baggage-api/) | `PythonApplication` | Built. RabbitMQ consumer + MongoDB component (Skyport phase 3). Ran on dev and prod staging. Validates Dex tokens (part 5; tested, not yet run on a cluster). | [part 4](../../docs/user/quickstart-baggage-api.md) |
| [`gate-api/`](gate-api/) | `NodeJSApplication` | Built. Ran on dev and prod staging. First app onboarded through the release-file split (D9/AF-5). | [part 6](../../docs/user/quickstart-gate-api.md) |
| [`checkin-api/`](checkin-api/) | `PythonApplication` | Built. Ran on dev and prod staging. Second app onboarded through the release-file split, through Tower. | [part 7](../../docs/user/quickstart-checkin-api.md) |

`skyport-broker` and `skyport-auth` have no code here: they are `InfraService`s whose only content
is a component (RabbitMQ broker; Dex server). See parts [3](../../docs/user/quickstart-broker.md)
and [5](../../docs/user/quickstart-skyport-auth.md).

Each directory is meant to be copied over the source repo Airframe scaffolds for
that service — not built or deployed from here. The quickstarts show the copy.
